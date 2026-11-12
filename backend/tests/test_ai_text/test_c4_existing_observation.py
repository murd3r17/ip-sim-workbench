import json
import uuid
from unittest.mock import AsyncMock

import pytest

from modules.ai_text import router
from modules.ai_text.skills import select_skill
from modules.ai_text.trusted_context import TrustedPageData
from tests.test_c3_request_api import api_case, events


SNAPSHOT = json.dumps({"evidence_id": 21, "source": "server_observed", "device": "R-2",
    "mode": "sim", "status": "ok", "completeness": "complete", "command": "display ip interface brief",
    "collected_at": "2026-11-05T04:00:00Z", "facts": {"interfaces": [{"name": "GE0/0/1", "state": "up"}]}})


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
@pytest.mark.parametrize("message", [
    "请核对这台设备刚采集的接口证据。",
    "请解释R-2刚采集的接口事实。接口Up是否能证明业务都正常？不要再采集，180字以内。",
    "说明这份接口观察，无需重新读取。",
])
async def test_existing_observation_explanation_uses_one_call_without_retrieval(api_case, monkeypatch, path, message):
    client, headers, provider, retrieval = api_case
    monkeypatch.setattr(router, "_resolve_page_data", AsyncMock(return_value=TrustedPageData(SNAPSHOT, {"trusted": True})))
    result = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
        "message": message, "request_id": uuid.uuid4().hex,
        "context": {"route": "/devices", "selection": "R-2"}, "page_data": '{"evidence_id":21}'})
    assert result.status_code == 200
    trace = result.json()["trace"] if path == '/chat' else events(result)[-1]["trace"]
    assert trace["model_calls"] == provider.calls == 1
    assert trace["tier"] == "direct" and trace["tool_calls"] == 0
    result_meta = result.json() if path == '/chat' else events(result)[0]
    assert result_meta['knowledge_status'] == 'not_requested'
    retrieval.assert_not_awaited()


@pytest.mark.parametrize("message,trusted,short", [
    ("请核对这台设备刚采集的接口证据。", True, True),
    ("请核对这台设备刚采集的接口证据。", False, False),
    ("解释这份观察", True, True),
    ("重新采集接口，解释这次结果", True, False),
    ("请核对刚采集的邻居证据", True, False),
    ("解释 R-3 刚采集的接口证据", True, False),
    ("刚才接口 up 但 R-2 不通，请排查", True, False),
    ("请对比这份观察和 R-3", True, False),
    ("解释这份接口观察，不要再采集。", True, True),
    ("说明本次接口证据，无需重新读取。", True, True),
    ("解释这份接口观察，不要再采集接口，但重新查询邻居。", True, False),
    ("解释这份接口观察，不是不要再采集，请读取最新状态。", True, False),
    ("解释这份接口观察，不要再采集。", False, False),
])
def test_short_path_requires_server_verification_and_matching_question(message, trusted, short):
    choice = select_skill(message, page_data=SNAPSHOT, page_data_trusted=trusted, route='/devices')
    assert (choice.reason == 'verified_observation_explanation') is short
    if short:
        assert choice.id == 'live_evidence' and not choice.tools and not choice.needs_knowledge
