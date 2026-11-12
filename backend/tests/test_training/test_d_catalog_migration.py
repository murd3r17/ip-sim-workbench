"""Managed D upgrade/rollback under real in-memory SQL transactions."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from modules.training.catalog_migration import upgrade, restore, digest, FIELDS
from modules.training.lab_content import lab_seed_payloads
from modules.training.models import TrainingLab, TrainingSession
from tests.test_training.test_v7a_state_and_reports import _admin_token, _lab, auth_header


async def seeded(client,factory):
    token=await _admin_token(factory)
    lid=await _lab(client,token)
    legacy=lab_seed_payloads()[0]
    async with factory() as db:
        lab=await db.get(TrainingLab,lid)
        for key in FIELDS: setattr(lab,key,deepcopy(legacy.get(key)))
        await db.commit()
    return token,lid,legacy


@pytest.mark.asyncio
async def test_dry_run_apply_idempotence_restore_and_session_snapshot(client,test_session_factory,tmp_path):
    token,lid,legacy=await seeded(client,test_session_factory)
    response=await client.post('/api/v1/training/sessions',json={'lab_id':lid},headers=auth_header(token))
    sid=response.json()['id']
    async with test_session_factory() as db:
        original=deepcopy((await db.get(TrainingSession,sid)).content_snapshot)
        plan=await upgrade(db)
        assert [r['id'] for r in plan['updated']]==[lid]
        assert digest(await db.get(TrainingLab,lid))==digest(legacy)
    backup=tmp_path/'d.json'
    async with test_session_factory() as db:
        result=await upgrade(db,dry_run=False,backup_path=backup)
        assert result['updated'][0]['id']==lid
    async with test_session_factory() as db:
        assert (await upgrade(db))['already_current']==[lid]
        assert (await db.get(TrainingSession,sid)).content_snapshot==original
        assert (await restore(db,backup))['restored']==[lid]
        assert (await restore(db,backup,dry_run=False))['restored']==[lid]
    async with test_session_factory() as db:
        assert digest(await db.get(TrainingLab,lid))==digest(legacy)
    assert set(json.loads(backup.read_text(encoding='utf-8'))['rows'][0]['before'])==set(FIELDS)


@pytest.mark.asyncio
@pytest.mark.parametrize('changed',['description','environment_spec','content_version','duplicate'])
async def test_modified_or_duplicate_system_titles_are_not_overwritten(client,test_session_factory,tmp_path,changed):
    _,lid,legacy=await seeded(client,test_session_factory)
    async with test_session_factory() as db:
        lab=await db.get(TrainingLab,lid)
        if changed=='duplicate':
            db.add(TrainingLab(**{key:deepcopy(getattr(lab,key)) for key in FIELDS},
                               topology_id=lab.topology_id,instructor_id=lab.instructor_id,status=lab.status))
        else: setattr(lab,changed,{'owner_note':'keep'} if changed=='environment_spec' else 'USER_EDIT')
        await db.commit()
        result=await upgrade(db,dry_run=False,backup_path=tmp_path/'skipped.json')
        assert not result['updated'] and result['skipped']


@pytest.mark.asyncio
async def test_injected_failure_rolls_back_and_restore_preserves_later_user_edit(client,test_session_factory,tmp_path):
    _,lid,legacy=await seeded(client,test_session_factory)
    async with test_session_factory() as db:
        with pytest.raises(RuntimeError): await upgrade(db,dry_run=False,backup_path=tmp_path/'failed.json',fail_after=1)
    async with test_session_factory() as db:
        assert digest(await db.get(TrainingLab,lid))==digest(legacy)
        await upgrade(db,dry_run=False,backup_path=tmp_path/'success.json')
    async with test_session_factory() as db:
        lab=await db.get(TrainingLab,lid); lab.description='USER AFTER UPGRADE'; await db.commit()
        result=await restore(db,tmp_path/'success.json',dry_run=False)
        assert not result['restored'] and result['skipped'][0]['id']==lid


@pytest.mark.asyncio
async def test_apply_requires_backup_and_never_overwrites_old_backup(client,test_session_factory,tmp_path):
    await seeded(client,test_session_factory)
    async with test_session_factory() as db:
        with pytest.raises(ValueError): await upgrade(db,dry_run=False)
    existing=tmp_path/'keep.json'; existing.write_text('KEEP')
    async with test_session_factory() as db:
        with pytest.raises(FileExistsError): await upgrade(db,dry_run=False,backup_path=existing)
    assert existing.read_text()=='KEEP'
