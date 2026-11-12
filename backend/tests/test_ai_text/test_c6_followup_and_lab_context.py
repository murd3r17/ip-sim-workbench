import uuid
from unittest.mock import AsyncMock
import pytest
from modules.ai_text import router
from modules.ai_text.skills import select_skill
from modules.device.models import Topology,TopologyType
from modules.training.models import TrainingLab,TrainingSession
from tests.test_c3_request_api import api_case,events


@pytest.mark.parametrize('question',['重新回答。','这两个结论能互相证明吗？','把没查到的也列出来。',
                                     '切到环境映射页后，刚才说的还作数吗？'])
def test_operational_recap_does_not_retrieve_unrelated_textbooks(question):
    choice=select_skill(question,history=[{'role':'user','content':'只读查看R2的接口摘要'}])
    assert choice.id=='live_evidence' and not choice.tools and not choice.needs_knowledge


def test_explicit_new_question_overrides_history_recap():
    choice=select_skill('OSPF的原理是什么？',history=[{'role':'user','content':'查看R2接口摘要'}])
    assert choice.id=='knowledge_answer'


@pytest.mark.asyncio
@pytest.mark.parametrize('path',['/chat','/chat/stream'])
async def test_verified_session_steps_replace_client_and_current_lab_content(api_case,test_session_factory,monkeypatch,path):
    client,headers,provider,retrieval=api_case
    async with test_session_factory() as db:
        topology=Topology(name='c6-session-step-source',topology_type=TopologyType.LAB)
        db.add(topology);await db.flush()
        lab=TrainingLab(title='Current lab',topology_id=topology.id,instructor_id=1,
            objectives=[{'name':'CHANGED_CURRENT_LAB'}],environment_spec={'requires_binding':False})
        db.add(lab);await db.flush()
        session=TrainingSession(lab_id=lab.id,trainee_id=1,status='in_progress',content_snapshot={
            'title':'Session snapshot','objectives':[{'name':'VERIFIED_FIRST_STEP','goal':'先只读核对接口'}]})
        db.add(session);await db.commit();lab_id,sid=lab.id,session.id
    captured=[]
    async def stream(prompt,system=None):
        provider.calls+=1;captured.append((prompt,system))
        yield {'kind':'content','text':'先只读核对接口。'}
    monkeypatch.setattr(provider,'stream_parts',stream)
    response=await client.post('/api/v1/ai/copilot'+path,headers=headers,json={
        'message':'实训里第一步做什么？','request_id':uuid.uuid4().hex,'lab_id':lab_id,'lab_session_id':sid,
        'lab_steps':[{'name':'FORGED_CLIENT_STEP'}]})
    assert response.status_code==200,response.text
    if path.endswith('stream'):
        assert events(response)[0]['skill']['id']=='lab_coach'
    assert captured and 'VERIFIED_FIRST_STEP' in captured[-1][0]
    assert 'FORGED_CLIENT_STEP' not in captured[-1][0] and 'CHANGED_CURRENT_LAB' not in captured[-1][0]
    assert provider.calls==1
    retrieval.assert_not_awaited()
