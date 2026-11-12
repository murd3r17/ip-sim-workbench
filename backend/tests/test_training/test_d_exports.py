"""Version-pinned read/export, detached redaction and ordinary-role isolation."""
import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from fastapi import HTTPException
from modules.training.exports import build_export, select_report
from modules.training.models import TrainingReport, OperationLog, TrainingSession
from tests.test_training.test_v7a_state_and_reports import _admin_token, _lab, _session, auth_header


def report(version, status='ready'):
    return TrainingReport(session_id=1,version=version,status=status,title=f'报告{version}',
        report_text='原报告 password cipher dummy-test-secret',sources=[{
            'content':'协议片段\npassword cipher dummy-source-secret',
            'prompt_sha256':'original-prompt-hash','version':'original-source-version'}],
        input_hash='original-input-hash',input_summary={'content_version':'old-v1'})


def test_select_exact_ready_version_no_silent_latest_fallback():
    rows=[report(1),report(2,'failed'),report(3)]
    assert select_report(rows).version==3
    assert select_report(rows,1).version==1
    assert select_report([],None) is None
    for version,code in [(2,404),(4,404),(0,422)]:
        with pytest.raises(HTTPException) as error:select_report(rows,version)
        assert error.value.status_code==code


def test_partial_historical_mode_snapshot_gets_saved_fact_labels_not_current_settings(monkeypatch):
    from modules.training.mode_facts import session_mode_facts
    monkeypatch.setenv('DEVICE_MODE','ssh')
    facts,source=session_mode_facts(SimpleNamespace(mode_snapshot={'device_mode':'sim'}),SimpleNamespace(is_sandbox=False))
    assert source=='session_snapshot' and facts['device_mode']=='sim'
    assert facts['deploy_mode']=='unknown' and facts['deploy_label']=='下发方式未知'
    assert facts['environment_binding']=='unknown' and facts['summary']


def test_export_preserves_stored_source_and_distinguishes_current_notes_from_old_report():
    row=report(1);original=deepcopy(row.sources)
    session=SimpleNamespace(id=1,lab_id=2,status='completed',started_at=None,completed_at=None,
        content_version=None,content_snapshot=None,mode_snapshot={'device_mode':'sim'})
    lab=SimpleNamespace(title='Current title',objectives=[],content_version=None,environment_spec=None)
    workspace={'revision':7,'notes':'new note\npassword cipher dummy-note-secret','steps':[{'api_key':'dummy-step-secret'}]}
    logs=[{'result':'local-user demo password irreversible-cipher dummy-log-secret'}]
    result=build_export({'session':session,'lab':lab,'logs':logs},workspace,[row],1)
    text=json.dumps(result,ensure_ascii=False)
    for secret in ['dummy-test-secret','dummy-source-secret','dummy-note-secret','dummy-step-secret','dummy-log-secret']:assert secret not in text
    assert result['workspace']['revision']==7 and result['report']['version']==1
    source=result['report']['sources'][0]
    assert source['prompt_sha256']=='original-prompt-hash' and source['export_content_redacted']
    assert source['export_content_sha256']==hashlib.sha256(source['content'].encode()).hexdigest()
    assert row.sources==original and 'dummy-note-secret' in workspace['notes']
    assert 'dummy-log-secret' in logs[0]['result']


@pytest.mark.asyncio
async def test_routes_read_export_only_exact_versions_and_jsonl_redaction(client,test_session_factory):
    token=await _admin_token(test_session_factory);lab_id=await _lab(client,token);sid=await _session(client,token,lab_id)
    async with test_session_factory() as db:
        session=await db.get(TrainingSession,sid)
        session.workspace={'notes':'saved note\npassword cipher export-only-dummy','steps':[],'updated_at':'2026-11-07T00:00:00Z'}
        session.workspace_revision=4
        for version in [1,2,3]:
            row=report(version,'failed' if version==2 else 'ready');row.session_id=sid;db.add(row)
        db.add(OperationLog(session_id=sid,lab_id=lab_id,action='inspect',command='display current-configuration',result='password cipher dummy-jsonl-secret',meta={'api_key':'dummy-jsonl-meta'}))
        await db.commit()
    with patch('modules.training.router._get_ai_service',side_effect=AssertionError('read must not initialize model')),patch('modules.training.router._get_knowledge_service',side_effect=AssertionError('read must not retrieve')):
        url=f'/api/v1/training/sessions/{sid}'
        resp=await client.get(url+'/report?version=1',headers=auth_header(token));assert resp.status_code==200;assert resp.json()['report']['version']==1
        exp=await client.get(url+'/export?version=1',headers=auth_header(token));assert exp.status_code==200
        assert exp.json()['report']['version']==1 and exp.json()['workspace']['revision']==4
        for v in [2,99]:
            assert (await client.get(url+f'/export?version={v}',headers=auth_header(token))).status_code==404
            assert (await client.get(url+f'/report?version={v}',headers=auth_header(token))).status_code==404
        assert (await client.get(url+'/export?version=0',headers=auth_header(token))).status_code==422
        jsonl=await client.get(url+'/logs/jsonl',headers=auth_header(token))
        assert jsonl.status_code==200 and 'dummy-jsonl-secret' not in jsonl.text and 'dummy-jsonl-meta' not in jsonl.text
    async with test_session_factory() as db:
        session=await db.get(TrainingSession,sid);assert 'export-only-dummy' in session.workspace['notes']
    from core.security import create_access_token,hash_password
    from modules.auth.models import User,UserRole
    async with test_session_factory() as db:
        user=User(username='d10-export-outsider',role=UserRole.USER,hashed_password=hash_password('local-test-only'))
        db.add(user);await db.commit();await db.refresh(user);outsider=create_access_token(user.id,user.username,user.role.value)
    assert (await client.get(url+'/export',headers=auth_header(outsider))).status_code==403
    assert (await client.get(url+'/report?version=1',headers=auth_header(outsider))).status_code==403
