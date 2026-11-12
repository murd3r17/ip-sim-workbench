"""M1 R10: mock-only streaming completion, failure and failover contracts."""
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.llm_provider import FallbackProvider, FailoverProvider, LLMProvider, OpenAICompatibleProvider, OllamaProvider
from modules.ai_text.llm_service import LLMService


class ScriptedProvider(LLMProvider):
    def __init__(self, parts=(), failure=True):
        self.parts = parts
        self.failure = failure
        self.calls = 0

    async def generate(self, *args, **kwargs):
        return "unused"

    async def health_check(self):
        return True

    async def stream(self, *args, **kwargs):
        async for part in self.stream_parts(*args, **kwargs):
            yield part["text"]

    async def stream_parts(self, *args, **kwargs):
        self.calls += 1
        for part in self.parts:
            yield part
        if self.failure:
            raise RuntimeError("mock connection lost")

    async def stream_parts_with_images(self, *args, **kwargs):
        async for part in self.stream_parts():
            yield part


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["stream", "stream_parts", "stream_parts_with_images"])
async def test_fallback_preserves_failure_after_partial_output(method):
    primary = ScriptedProvider([{"kind": "content", "text": "partial"}])
    provider = FallbackProvider(primary)
    output = []
    with pytest.raises(RuntimeError, match="connection lost"):
        async for part in getattr(provider, method)("prompt", **({"images": []} if "images" in method else {})):
            output.append(part)
    assert len(output) == 1
    assert primary.calls == 1  # vision must not append a text fallback answer


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["stream", "stream_parts"])
async def test_failover_preserves_failure_after_partial_output(method):
    primary = ScriptedProvider([{"kind": "content", "text": "partial"}])
    secondary = ScriptedProvider([{"kind": "content", "text": "backup"}], failure=False)
    output = []
    with pytest.raises(RuntimeError, match="connection lost"):
        async for part in getattr(FailoverProvider(primary, secondary), method)("prompt"):
            output.append(part)
    assert len(output) == 1
    assert secondary.calls == 0


@pytest.mark.asyncio
async def test_fallback_before_output_is_not_a_successful_stream():
    provider = FallbackProvider(ScriptedProvider(), fallback_message="unavailable")
    output = []
    with pytest.raises(RuntimeError):
        async for part in provider.stream_parts("prompt"):
            output.append(part)
    assert output == [{"kind": "content", "text": "unavailable"}]


@pytest.mark.asyncio
async def test_copilot_partial_failure_ends_failed_and_does_not_generate_draft(monkeypatch):
    monkeypatch.setattr("modules.ai_text.agent_tools.available_tool_defs", lambda actor, allowed=None: [])
    service = LLMService(provider=FallbackProvider(ScriptedProvider([{"kind": "content", "text": "partial"}])))
    service.generate_and_validate = AsyncMock()
    events = [event async for event in service.copilot_chat_stream("hi", want_draft=True)]
    assert events[0] == {"type": "token", "text": "partial"}
    assert [event["type"] for event in events[-2:]] == ["error", "done"]
    assert events[-1]["status"] == "failed"
    service.generate_and_validate.assert_not_called()


@pytest.mark.asyncio
async def test_copilot_successful_secondary_finishes_ok(monkeypatch):
    monkeypatch.setattr("modules.ai_text.agent_tools.available_tool_defs", lambda actor, allowed=None: [])
    service = LLMService(provider=FallbackProvider(FailoverProvider(
        ScriptedProvider(), ScriptedProvider([{"kind": "content", "text": "backup"}], failure=False),
    )))
    events = [event async for event in service.copilot_chat_stream("hi")]
    assert events[0] == {"type": "token", "text": "backup"}
    assert events[-1]["status"] == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("parts", [[], [{"kind": "reasoning", "text": "still thinking"}]])
async def test_copilot_empty_answer_is_failed_even_when_provider_completed(monkeypatch, parts):
    monkeypatch.setattr("modules.ai_text.agent_tools.available_tool_defs", lambda actor, allowed=None: [])
    service = LLMService(provider=ScriptedProvider(parts, failure=False))
    events = [event async for event in service.copilot_chat_stream("hi")]
    assert [event["type"] for event in events[-2:]] == ["error", "done"]
    assert events[-1]["status"] == "failed"


@pytest.mark.asyncio
async def test_copilot_static_fallback_ends_failed(monkeypatch):
    monkeypatch.setattr("modules.ai_text.agent_tools.available_tool_defs", lambda actor, allowed=None: [])
    service = LLMService(provider=FallbackProvider(ScriptedProvider(), fallback_message="unavailable"))
    events = [event async for event in service.copilot_chat_stream("hi")]
    assert events[0] == {"type": "token", "text": "unavailable"}
    assert events[-1]["status"] == "failed"


@pytest.mark.asyncio
async def test_router_generator_exception_sends_error_then_failed_done(client, test_session_factory, monkeypatch):
    from modules.ai_text import router
    from tests.test_training.test_v7a_state_and_reports import _admin_token, auth_header
    import uuid

    async def failing_stream(self, **kwargs):
        raise RuntimeError("mock generator failure")
        yield  # pragma: no cover

    monkeypatch.setattr(router, "_retrieve", AsyncMock(return_value=[]))
    monkeypatch.setattr(router.SystemService, "build_llm_provider", AsyncMock(return_value=ScriptedProvider()))
    monkeypatch.setattr(LLMService, "copilot_chat_stream", failing_stream)
    token = await _admin_token(test_session_factory)
    request_id = uuid.uuid4().hex
    response = await client.post('/api/v1/ai/copilot/chat/stream', headers=auth_header(token),
                                 json={'message': 'hi', 'request_id': request_id})
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert [event["type"] for event in events[-2:]] == ["error", "done"]
    assert events[-1]["status"] == "failed"
    result = await client.get('/api/v1/ai/copilot/requests/' + request_id, headers=auth_header(token))
    assert result.json()['state'] == 'failed'


@pytest.mark.asyncio
async def test_failover_can_retry_after_only_empty_chunks():
    primary = ScriptedProvider([{"kind": "content", "text": ""}])
    secondary = ScriptedProvider([{"kind": "content", "text": "backup"}], failure=False)
    events = [part async for part in FailoverProvider(primary, secondary).stream_parts("hi")]
    assert events[-1]["text"] == "backup"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_kind", ["text", "vision", "ollama"])
@pytest.mark.parametrize("complete", [False, "done", "finish_reason"])
async def test_provider_requires_protocol_completion_marker(provider_kind, complete):
    async def lines():
        if provider_kind == "ollama":
            yield '{"response":"partial","done":false}'
            if complete:
                yield '{"done":true}'
        else:
            yield 'data:{"choices":[{"delta":{"content":"partial"}}]}'
            if complete == "done":
                yield 'data:[DONE]'
            elif complete == "finish_reason":
                yield 'data:{"choices":[{"delta":{},"finish_reason":"stop"}]}'

    @asynccontextmanager
    async def stream(*args, **kwargs):
        yield SimpleNamespace(raise_for_status=lambda: None, aiter_lines=lines)

    provider = OllamaProvider() if provider_kind == "ollama" else OpenAICompatibleProvider()
    await provider._client.aclose()
    provider._client = SimpleNamespace(stream=stream)
    iterator = (provider.stream_parts_with_images("p", []) if provider_kind == "vision"
                else provider.stream_parts("p"))
    output = []
    if complete:
        output = [part async for part in iterator]
    else:
        with pytest.raises(RuntimeError):
            async for part in iterator:
                output.append(part)
    assert output == [{"kind": "content", "text": "partial"}]
