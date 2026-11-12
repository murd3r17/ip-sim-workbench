import json
import uuid
from unittest.mock import AsyncMock

import pytest

from modules.ai_text import router
from modules.ai_text.schemas import CopilotChatRequest
from modules.ai_text.skills import select_skill
from modules.ai_text.llm_service import LLMService
from modules.dashboard.service import DashboardService
from tests.test_c3_request_api import api_case, events


@pytest.mark.asyncio
async def test_dashboard_context_reads_server_counts_not_client_claims(test_session_factory, monkeypatch):
    # Neither model health nor knowledge health is necessary to explain saved counts.
    probe = AsyncMock(side_effect=AssertionError("no external probes for this task"))
    monkeypatch.setattr("core.llm_provider.cached_llm_health_check", probe)
    monkeypatch.setattr("core.health.get_knowledge_health_cached", probe)
    data = CopilotChatRequest(message="首页这些数字是什么意思？", context={"route": "/dashboard"},
        page_data='{"source":"server_observed","devices":{"total":999999},"secret":"UNTRUSTED_VALUE"}')
    async with test_session_factory() as db:
        expected = await DashboardService.get_summary(db, probe_services=False)
        page = await router._resolve_page_data(db, data, {"user_id": 1, "role": "user"})
    payload = json.loads(page.text)
    assert page.trusted and payload["source"] == "database_snapshot"
    assert payload["devices"] == expected["devices"]
    assert payload["collected_at"] and "UNTRUSTED_VALUE" not in page.text
    assert "items" not in payload["tasks"] and "activity" not in payload
    assert "services" not in payload  # do not imply health was checked
    assert payload["topology"] == expected["topology"]  # no active main topology is null, not zero counts
    assert "active_main_topology_only" in payload["topology_scope"]
    probe.assert_not_called()
    service = LLMService(None, user_id=1, provider=object())
    prompt = service._build_copilot_prompt(data.message, [],
        {"skill_id": "page_help", "page_data_trusted": True}, page_data=page.text)
    assert page.text in prompt
    prompt = service._build_copilot_prompt(data.message, [],
        {"skill_id": "page_help", "page_data_trusted": False}, page_data="UNTRUSTED_VALUE")
    assert "UNTRUSTED_VALUE" not in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
async def test_dashboard_explanation_uses_one_generation_no_retrieval_or_device_tools(api_case, path):
    client, headers, provider, retrieval = api_case
    response = await client.post("/api/v1/ai/copilot" + path, headers=headers, json={
        "message": "首页这些数字是什么意思？", "context": {"route": "/dashboard"},
        "request_id": uuid.uuid4().hex, "page_data": "UNTRUSTED_VALUE"})
    assert response.status_code == 200, response.text
    trace = response.json()["trace"] if path == "/chat" else events(response)[-1]["trace"]
    assert provider.calls == trace["model_calls"] == 1
    assert trace["tier"] == "direct" and trace["tool_calls"] == 0
    assert retrieval.await_count == 0


def test_dashboard_route_does_not_hide_an_actual_device_diagnosis():
    assert select_skill("首页这些数字是什么意思？", route="/dashboard").id == "page_help"
    assert select_skill("R2 的指标异常，访问不了 R3", route="/dashboard").id == "troubleshooting"
    assert select_skill("这些数字是什么意思？", route="/devices").id == "live_evidence"
