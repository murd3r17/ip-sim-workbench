"""Provider failure must not become a successfully generated business result."""
from unittest.mock import AsyncMock

import pytest

from core.llm_provider import FallbackProvider
from modules.ai_text.llm_service import LLMService


def unavailable_service():
    primary = AsyncMock()
    primary.name = "fixture"
    primary.generate.side_effect = RuntimeError("fixture dependency unavailable")
    async def _stream(*args, **kwargs):
        raise RuntimeError("fixture dependency unavailable")
        yield  # pragma: no cover
    primary.stream_parts = _stream
    return LLMService(provider=FallbackProvider(primary))


@pytest.mark.asyncio
async def test_copilot_reports_degraded_without_building_a_draft():
    service = unavailable_service()
    service._maybe_build_draft = AsyncMock(return_value=("should not be generated", [], ""))
    result = await service.copilot_chat("generate a draft", want_draft=True)
    assert result["status"] == "degraded"
    assert result["draft_commands"] == []
    service._maybe_build_draft.assert_not_awaited()


@pytest.mark.asyncio
async def test_success_is_not_classified_by_matching_answer_text():
    primary = AsyncMock()
    primary.name = "fixture"
    primary.generate.return_value = "当前AI服务不可用，请稍后重试。"
    result = await LLMService(provider=FallbackProvider(primary)).copilot_chat("quote a message")
    assert result["status"] == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("method,args", [
    ("generate_cli_commands", ("create config", "NE40E")),
    ("generate_and_validate", ("create config", "NE40E")),
    ("review_config", ("sysname R1",)),
    ("generate_report", ("report", "source")),
    ("generate_config_plan", ("create config", [{"device_id": 1, "hostname": "R1"}])),
    ("coach_training", ("goal", "scenario")),
    ("ask_knowledge", ("question",)),
])
async def test_unavailable_provider_never_manufactures_structured_success(method, args):
    # RuntimeError is the public superclass; the implementation adds a distinct
    # provider exception so callers do not guess availability from answer text.
    with pytest.raises(RuntimeError, match="当前AI服务不可用"):
        await getattr(unavailable_service(), method)(*args)


@pytest.mark.asyncio
@pytest.mark.parametrize("path,payload,expected_status", [
    ("/generate-cli", {"natural_language": "config"}, 500),
    ("/generate-and-validate", {"natural_language": "config"}, 500),
    ("/review-config", {"config_text": "sysname R1"}, 500),
    ("/report", {"title": "report", "source_text": "source"}, 500),
    ("/config-plans", {"natural_language": "config", "devices": [{"device_id": 1, "hostname": "R1"}]}, 500),
    ("/coach", {"goal": "goal", "scenario": "scenario"}, 500),
    # This case exercises provider failure, not the earlier environment gate.
    # Drafts without a verified target/environment correctly stop before it.
    ("/copilot/chat", {"message": "hello", "want_draft": False}, 200),
])
async def test_existing_http_contract_reports_failure(monkeypatch, client, test_session_factory, path, payload, expected_status):
    from httpx import ASGITransport, AsyncClient
    from main import app
    from types import SimpleNamespace
    from modules.ai_text import router
    from tests.test_training.test_v7a_state_and_reports import _admin_token, auth_header

    token = await _admin_token(test_session_factory)
    monkeypatch.setattr("core.database.get_session_factory", lambda: test_session_factory)
    get_service = AsyncMock(return_value=unavailable_service())
    monkeypatch.setattr(router, "_get_service", get_service)
    monkeypatch.setattr(router, "_get_knowledge_service", lambda: SimpleNamespace(
        ask=AsyncMock(return_value={"sources": [], "status": "degraded", "provider": "fixture"}),
        search=AsyncMock(return_value=[])))
    # Keep the real app and fixture's isolated dependencies; inspect its HTTP 500
    # contract instead of re-raising the handled provider exception in the test.
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as http:
        response = await http.post("/api/v1/ai" + path, json=payload, headers=auth_header(token))
    assert response.status_code == expected_status, response.text
    if expected_status == 200:
        assert response.json()["status"] in ("degraded", "failed")
        assert response.json()["draft_commands"] == []
        get_service.assert_awaited_once()
