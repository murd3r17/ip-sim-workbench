import json
from unittest.mock import AsyncMock
import pytest
from modules.ai_text.llm_service import LLMService


@pytest.mark.asyncio
@pytest.mark.parametrize('interface,command,protected',[
    ('GigabitEthernet0/0/0','shutdown',[]),
    ('LoopBack77','description forbidden-change',['LoopBack77']),
    ('LoopBack0','shutdown',[]),
])
async def test_raw_proposal_is_checked_before_danger_filter_can_leave_empty_shell(monkeypatch,interface,command,protected):
    class Provider:
        async def stream_parts(self,*a,**k):yield {'kind':'content','text':'仅提供草稿，未执行。'}
        async def generate(self,*a,**k):return json.dumps({'commands':['interface '+interface,command,'quit'],'explanation':'未执行','warnings':[]})
    service=LLMService(provider=Provider())
    monkeypatch.setattr(service,'_log_request',AsyncMock())
    events=[event async for event in service.copilot_chat_stream('只生成当前接口变更草稿，不执行。',
        want_draft=True,ui_context={'skill_id':'config_draft'},allowed_tools=[],protected_interfaces=protected)]
    assert not any(event.get('type')=='draft' for event in events)
    assert any(event.get('type')=='policy' and event.get('draft_refused_reason') for event in events)
    visible=''.join(event.get('text','') for event in events if event['type']=='token')
    assert '```cli' not in visible and '可复制到配置下发' not in visible
