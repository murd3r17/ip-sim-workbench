from unittest.mock import AsyncMock
import pytest
from modules.ai_text.skills import select_skill
from modules.ai_text.llm_service import LLMService


@pytest.mark.parametrize('question',[
    '给R13已有的LoopBack0添加描述 V7-DEV-NOTE。只生成草稿，不执行也不保存；不修改IP、路由、账号或接口启停。',
    '给R99已有的LoopBack0添加描述 V7-DEV-NOTE。找不到设备不要沿用选择。',
    '给R13的LoopBack77添加描述 V7-PROTECTED-NOTE。此接口已列为保护项。',
])
def test_simple_interface_description_draft_does_not_retrieve_unrelated_protocol_books(question):
    choice=select_skill(question,want_draft=True)
    assert choice.id=='config_draft' and not choice.needs_knowledge


@pytest.mark.parametrize('question',[
    '给R13的LoopBack0添加描述，并配置OSPF区域0',
    '依据教材给接口添加描述并说明原理',
    '配置一个VLAN100接口地址',
    '给接口配置IP地址，然后添加描述',
])
def test_complex_or_explicit_reference_drafts_keep_retrieval(question):
    assert select_skill(question,want_draft=True).needs_knowledge


@pytest.mark.asyncio
@pytest.mark.parametrize('narrative',[
    '只生成描述草稿，未执行。',
    '草稿未执行。\n```text\ninterface LoopBack0\ndescription wrong-preview\n```\n请核对。',
    '```cli\ninterface LoopBack0\ndescription wrong-preview',
])
async def test_displayed_configuration_equals_fill_payload_without_read_checks(monkeypatch,narrative):
    class Provider:
        model='controlled-draft-contract'
        async def stream_parts(self,prompt,system=None):
            for character in narrative:
                yield {'kind':'content','text':character}
    service=LLMService(db=None,user_id=1,provider=Provider(),actor={'user_id':1,'role':'user'})
    monkeypatch.setattr(service,'_log_request',AsyncMock())
    monkeypatch.setattr(service,'generate_and_validate',AsyncMock(return_value={
        'commands':['display interface LoopBack0','# target comment','interface LoopBack0','description test-only','quit'],
        'explanation':'描述草稿未执行'}))
    stream=[event async for event in service.copilot_chat_stream('给R13的LoopBack0添加描述 test-only',
        want_draft=True,ui_context={'skill_id':'config_draft'},allowed_tools=[])]
    draft=next(event['draft_commands'] for event in stream if event['type']=='draft')
    assert draft==['interface LoopBack0','description test-only','quit']
    answer=''.join(event.get('text','') for event in stream if event['type']=='token')
    assert '```cli\n'+'\n'.join(draft)+'\n```' in answer
    assert answer.count('description test-only')==1
    assert 'wrong-preview' not in answer


@pytest.mark.parametrize('size',[1,7,4096])
def test_narrative_fences_cannot_escape_through_fragmentation(size):
    from modules.ai_text.configuration_narrative import ConfigurationNarrativeGuard
    text='说明 `LoopBack0`，未执行。\n~~~cli\ninterface LoopBack0\ndescription wrong-preview\n~~~\n继续核对。'
    guard=ConfigurationNarrativeGuard()
    visible=''.join(guard.feed(text[i:i+size]) for i in range(0,len(text),size))+guard.flush()
    assert visible=='说明 `LoopBack0`，未执行。\n继续核对。'
    assert guard.suppressed
