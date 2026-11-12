from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select
from modules.deploy.vrp_validator import VRPValidator
from modules.deploy.config_verifier import ConfigVerifier
from modules.deploy.models import ConfigVersion
from modules.device.models import Device, DeviceType, Topology
from modules.auth.models import User, UserRole, AuditLog
from modules.auth.service import AuditService
from core.security import create_access_token


def test_original_error_lines_include_leading_blanks_comments_and_duplicates():
    text='\n# source\nsysname R1\ninterface GigabitEthernet0/0/1\n ip address 999.1.1.1 24\n# separator\n ip address 999.1.1.1 24'
    result=VRPValidator().assess(text,'NE40E')
    assert not result['valid']
    assert {d['line_number'] for d in result['diagnostics']} == {5,7}
    assert all(d['command'].strip().startswith('ip address') for d in result['diagnostics'])


def test_display_case_option_does_not_change_legacy_or_device_verification():
    before='interface GigabitEthernet0/0/1\n description SITE-A'
    after='interface GigabitEthernet0/0/1\n description site-a'
    assert ConfigVerifier.compare(before,after)=={'added':[],'removed':[],'changed':[]}
    assert ConfigVerifier.compare(before,after,preserve_case=True)['changed']==['description SITE-A -> description site-a']
    assert ConfigVerifier.verify_snapshot(before,after) is not None


async def seed(db):
    user=User(username='d07-author-'+str(len((await db.execute(select(User))).scalars().all())),hashed_password='unused-test-hash',role=UserRole.ADMIN)
    topo=Topology(name='D07 isolated');db.add_all([user,topo]);await db.flush()
    devices=[Device(hostname=f'D07-R{i}',mgmt_ip=f'198.18.97.{i}',device_type=DeviceType.ROUTER,topology_id=topo.id) for i in [1,2]]
    db.add_all(devices);await db.flush()
    marker='D07_'+'PRIVATE_SENTINEL'
    versions=[ConfigVersion(device_id=d.id,version_number=1,created_by=user.id,config_snapshot=f'sysname R1\n description {desc}\n local-user lab password cipher {marker}{i}') for i,(d,desc) in enumerate(zip(devices,['SITE-A','site-a']))]
    db.add_all(versions);await db.commit()
    headers={'Authorization':'Bearer '+create_access_token(user.id,user.username,'admin')}
    return user,versions,headers,marker


@pytest.mark.asyncio
async def test_compare_identities_case_and_credential_boundary(client,test_session_factory):
    async with test_session_factory() as db: _,v,headers,marker=await seed(db);a,b=v[0].id,v[1].id
    response=await client.get('/api/v1/config-versions/compare',params={'version1':a,'version2':b},headers=headers)
    assert response.status_code==200 and marker not in response.text
    data=response.json()
    assert not data['same_device'] and data['version1']['device_id']!=data['version2']['device_id']
    assert data['display_diff']['changed']==['description SITE-A -> description site-a']
    assert (await client.get('/api/v1/config-versions/compare',params={'version1':a,'version2':999999},headers=headers)).status_code==404


@pytest.mark.asyncio
async def test_ai_diff_preserves_case_and_never_returns_raw_credentials(client,test_session_factory,monkeypatch):
    import modules.ai_text.router as router
    async with test_session_factory() as db: _,v,headers,marker=await seed(db);a,b=v[0].id,v[1].id
    report=AsyncMock(return_value={'summary':'case changed','report_text':'case changed'})
    service=type('ReportService',(),{})();service.generate_report=report
    monkeypatch.setattr(router,'_get_service',AsyncMock(return_value=service))
    response=await client.post('/api/v1/ai/diff-explanation',headers=headers,json={'version_id_a':a,'version_id_b':b})
    assert response.status_code==200 and marker not in response.text
    assert '- description SITE-A' in report.call_args.kwargs['source_text']
    assert '+ description site-a' in report.call_args.kwargs['source_text']
    assert '同设备=False' in report.call_args.kwargs['context']
    assert marker not in report.call_args.kwargs['source_text']


@pytest.mark.asyncio
async def test_redacted_only_change_does_not_claim_full_identity_or_spend_model(client,test_session_factory,monkeypatch):
    import modules.ai_text.router as router
    async with test_session_factory() as db:
        _,v,headers,marker=await seed(db);a,b=v[0].id,v[1].id
        v[1].config_snapshot=v[1].config_snapshot.replace('description site-a','description SITE-A');await db.commit()
    getter=AsyncMock(side_effect=AssertionError('No model should be used'));monkeypatch.setattr(router,'_get_service',getter)
    response=await client.post('/api/v1/ai/diff-explanation',headers=headers,json={'version_id_a':a,'version_id_b':b})
    assert response.status_code==200 and marker not in response.text
    assert '没有差异' in response.json()['explanation'] and '不能据此判断' in response.json()['explanation']
    getter.assert_not_called()


def test_ai_excerpt_keeps_duplicate_deletion_and_bounds_matcher():
    from modules.deploy.display_diff import display_diff_excerpt
    result=display_diff_excerpt('interface GE0/0/1\n description duplicate\n description duplicate','interface GE0/0/1\n description duplicate')
    assert '- description duplicate' in result['text'] and not result['truncated']
    long='\n'.join(f'description row{i}' for i in range(700))
    result=display_diff_excerpt(long,long+'\ndescription OUTSIDE')
    assert result['truncated'] and result['different'] and len(result['text']) <= 14000


@pytest.mark.asyncio
async def test_audit_masks_new_details_and_serializes_old_without_mutating_history(client,test_session_factory):
    async with test_session_factory() as db:
        user,_,headers,marker=await seed(db)
        await AuditService.log(db,user.id,user.username,'deploy','d07_boundary',detail={'password':marker})
        stored=(await db.execute(select(AuditLog).where(AuditLog.action=='d07_boundary'))).scalars().all()
        assert all(marker not in (row.detail or '') for row in stored)
        old=AuditLog(user_id=user.id,username=user.username,module='deploy',action='d07_legacy',detail=f'password cipher {marker}',result='success')
        db.add(old);await db.commit();old_id=old.id
        response=await client.get('/api/v1/system/audit-logs',headers=headers)
        assert response.status_code==200 and marker not in response.text
        await db.refresh(old)
        assert old.id==old_id and marker in old.detail


@pytest.mark.asyncio
async def test_task_detail_uses_persisted_confirmation_mode_and_recovery(client,test_session_factory):
    from datetime import datetime,timezone
    from modules.deploy.models import DeployTask,DeployStatus
    async with test_session_factory() as db:
        user,versions,headers,_=await seed(db)
        stamp=datetime(2026,11,7,0,0,tzinfo=timezone.utc).replace(tzinfo=None)
        task=DeployTask(device_id=versions[0].device_id,operator_id=user.id,config_content='description reviewed',status=DeployStatus.CONFIRMED,confirmed_by=user.id,confirmed_at=stamp,execution_mode=None,rollback_output='saved rollback output')
        db.add(task);await db.commit();task_id=task.id;uid=user.id
    response=await client.get(f'/api/v1/deploy/tasks/{task_id}',headers=headers)
    assert response.status_code==200
    data=response.json()
    assert data['confirmed_by']==uid and datetime.fromisoformat(data['confirmed_at'].replace('Z','+00:00'))==stamp.replace(tzinfo=timezone.utc)
    assert data['execution_mode'] is None and data['rollback_output']=='saved rollback output'
