"""Actual assistant routes must not adopt another trainee's session or mixed lab identity."""
import uuid
import pytest
from sqlalchemy import select
from modules.auth.models import User
from modules.device.models import Topology,TopologyType
from modules.training.models import TrainingLab,TrainingSession
from tests.test_copilot_session_idor import _make_user,auth_header
from tests.test_c3_request_api import api_case,events


@pytest.mark.asyncio
@pytest.mark.parametrize('path',['/chat','/chat/stream'])
@pytest.mark.parametrize('actor',['foreign','mismatch','owner','admin'])
async def test_lab_session_identity_checked_before_model(api_case,test_session_factory,path,actor):
    client,admin_headers,provider,_=api_case
    owner_token=await _make_user(test_session_factory,'c6-lab-owner','user')
    foreign_token=await _make_user(test_session_factory,'c6-lab-foreign','user')
    async with test_session_factory() as db:
        owner=(await db.execute(select(User).where(User.username=='c6-lab-owner'))).scalar_one()
        topology=Topology(name='c6-lab-identity',topology_type=TopologyType.LAB)
        db.add(topology);await db.flush()
        lab=TrainingLab(title='Public lab',topology_id=topology.id,instructor_id=owner.id,
            environment_spec={'requires_binding':False},objectives=[{'name':'只读核对'}])
        db.add(lab);await db.flush()
        session=TrainingSession(lab_id=lab.id,trainee_id=owner.id,status='in_progress',
            content_snapshot={'title':'PRIVATE_SESSION_SNAPSHOT','objectives':[{'name':'只读核对'}]})
        db.add(session);await db.commit()
        lab_id,sid=lab.id,session.id
    headers=admin_headers if actor=='admin' else auth_header(foreign_token if actor=='foreign' else owner_token)
    payload={'message':'这一步先核对什么？','request_id':uuid.uuid4().hex,
        'lab_session_id':sid,'lab_id':lab_id+1000 if actor=='mismatch' else lab_id}
    denied=actor in {'foreign','mismatch'}
    for _ in range(2):
        response=await client.post('/api/v1/ai/copilot'+path,headers=headers,json=payload)
        assert response.status_code==200,response.text
        frames=events(response) if path.endswith('stream') else []
        if denied:
            assert provider.calls==0
            assert 'PRIVATE_SESSION_SNAPSHOT' not in response.text
            assert (frames[-1] if frames else response.json())['status']=='blocked_environment'
        else:
            assert provider.calls==2  # one existing planning call + one answer; replay adds none
