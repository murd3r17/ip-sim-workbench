"""Actual ASGI routes, in-memory records; no cloud/device acceptance claim."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from core.security import create_access_token
from modules.auth.models import User, UserRole
from modules.training.models import TrainingLab, TrainingSession, LabStatus
from modules.training.service import TrainingService
from modules.trust.models import EnvironmentProfile, ReadOnlyObservation
from modules.trust.service import environment_hash
from tests.test_training.test_v7a_state_and_reports import _admin_token, _lab, auth_header
from tests.test_trust.test_v7b_trust import _device


async def setup(client, factory, monkeypatch):
    from core.config import get_settings

    monkeypatch.setenv('DEVICE_MODE','sim')
    get_settings.cache_clear()
    token=await _admin_token(factory)
    lab_id=await _lab(client,token)
    device_id=await _device(factory,hostname='D-R1')
    async with factory() as db:
        lab=await db.get(TrainingLab,lab_id)
        lab.content_version='d1'
        lab.environment_spec={'requires_binding':True,'devices':[{'role':'R1'}]}
        lab.objectives=[{'id':1,'name':'邻居','verification':{'version':'d1','kind':'ospf_expectations','components':['neighbors']}}]
        env=EnvironmentProfile(name='D API fixture', version='v1',site='local',status='ready',revision=1,
            devices=[{'role':'R1','device_id':device_id,'interfaces':[], 'expected_neighbors':['2.2.2.2']}],
            expected={},protections=[],source='manual',last_preflight_status='ready',last_preflight_mode='sim')
        env.content_hash=environment_hash(env)
        db.add(env); await db.commit()
        env_id=env.id
    return token,lab_id,device_id,env_id


@pytest.mark.asyncio
async def test_bind_then_start_freezes_content_and_verify_uses_no_client_expectations(client,test_session_factory,monkeypatch):
    token,lab_id,device_id,env_id=await setup(client,test_session_factory,monkeypatch)
    bind=await client.put(f'/api/v1/training/labs/{lab_id}/environment',json={'environment_id':env_id},headers=auth_header(token))
    assert bind.status_code==200 and bind.json()['scope']=='new_sessions_only'
    started=await client.post('/api/v1/training/sessions',json={'lab_id':lab_id},headers=auth_header(token))
    sid=started.json()['id']
    async with test_session_factory() as db:
        s=await db.get(TrainingSession,sid)
        snapshot=deepcopy(s.content_snapshot)
        frozen=deepcopy(s.trust_environment_snapshot['environment'])
        assert snapshot['environment_spec']['trust_environment_id']==env_id
        r=ReadOnlyObservation(device_id=device_id,environment_id=env_id,environment_version='v1',
            environment_snapshot=frozen, action_id='ospf_peer',command='display ospf peer',
            source='server_observed',mode='sim',adapter_mode='sim',parser_version='v7b.4',
            status='ok',completeness='complete',collected_at=datetime.now(timezone.utc),
            facts={'peers':[{'neighbor_id':'2.2.2.2','state':'Full'}]},created_by=s.trainee_id)
        db.add(r); await db.commit(); rid=r.id
        lab=await db.get(TrainingLab,lab_id); lab.objectives=[{'id':1,'name':'CHANGED'}]
        await db.commit()
    url=f'/api/v1/training/sessions/{sid}/steps/1/verify'
    checked=await client.post(url,json={'observation_ids':[rid]},headers=auth_header(token))
    assert checked.status_code==200,checked.text
    assert checked.json()['status']=='satisfied' and checked.json()['skill_passed'] is None
    override=await client.post(url,json={'observation_ids':[rid],'expected_neighbors':[]},headers=auth_header(token))
    assert override.status_code==422
    await client.put(f'/api/v1/training/labs/{lab_id}/environment',json={'environment_id':None},headers=auth_header(token))
    async with test_session_factory() as db:
        s=await db.get(TrainingSession,sid)
        assert s.content_snapshot==snapshot and s.trust_environment_id==env_id
        assert s.score is None and s.passed is None
    await client.post(f'/api/v1/training/sessions/{sid}/complete',headers=auth_header(token))
    assert (await client.post(url,json={'observation_ids':[rid]},headers=auth_header(token))).json()['rejected_reason']=='inactive_session'


@pytest.mark.asyncio
async def test_user_cannot_bind_other_session_or_read_other_observations(client,test_session_factory,monkeypatch):
    token,lab_id,_,env_id=await setup(client,test_session_factory,monkeypatch)
    async with test_session_factory() as db:
        u=User(username='d-unprivileged',hashed_password='unused-test-hash',role=UserRole.USER)
        db.add(u); await db.commit()
        user_token=create_access_token(u.id,u.username,u.role.value)
    assert (await client.put(f'/api/v1/training/labs/{lab_id}/environment',json={'environment_id':env_id},headers=auth_header(user_token))).status_code==403
    s=await client.post('/api/v1/training/sessions',json={'lab_id':lab_id},headers=auth_header(token))
    url=f'/api/v1/training/sessions/{s.json()["id"]}/steps/1/verify'
    assert (await client.post(url,json={'observation_ids':[]},headers=auth_header(user_token))).status_code==403


def test_content_snapshot_is_detached_including_requirements_and_rules():
    lab=SimpleNamespace(content_version='d1',title='original',objectives=[{'id':1}],
                        environment_spec={'devices':[{'role':'R1'}]},scoring_rules={'x':1})
    frozen=TrainingService.content_snapshot(lab)
    lab.environment_spec['devices'].clear(); lab.objectives[0]['id']=2; lab.scoring_rules['x']=3
    assert frozen['objectives'][0]['id']==1 and frozen['environment_spec']['devices']
    assert frozen['scoring_rules']=={'x':1}


@pytest.mark.asyncio
async def test_unverified_session_can_explain_new_controls_without_enabling_model_or_drafts(client,test_session_factory,monkeypatch):
    from modules.ai_text.router import _lab_draft_policy
    from modules.ai_text.schemas import CopilotChatRequest
    token,lab_id,_,_=await setup(client,test_session_factory,monkeypatch)
    started=await client.post('/api/v1/training/sessions',json={'lab_id':lab_id},headers=auth_header(token))
    sid=started.json()['id']
    async with test_session_factory() as db:
        session=await db.get(TrainingSession,sid)
        actor={'user_id':session.trainee_id,'role':'user'}
        request=CopilotChatRequest(message='步骤核对里的核对本步怎么用？',lab_id=lab_id,lab_session_id=sid)
        policy=await _lab_draft_policy(db,request,actor)
        assert policy['allow_model'] is False and policy['allow_draft'] is False
        assert '选择步骤' in policy['safe_text'] and '不调用模型' in policy['safe_text']
        request.want_draft=True
        assert '选择步骤' not in (await _lab_draft_policy(db,request,actor))['safe_text']
        denied=await _lab_draft_policy(db,request,{'user_id':9999,'role':'user'})
        assert '选择步骤' not in denied['safe_text']
