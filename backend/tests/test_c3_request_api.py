import asyncio
import json
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from modules.ai_text import router
from modules.ai_text.cancel import registry
from modules.ai_text.llm_service import LLMService
from modules.ai_text.request_lifecycle import execute, encode
from modules.ai_text.request_store import RequestStore
from modules.ai_text.schemas import CopilotChatRequest
from tests.test_training.test_v7a_state_and_reports import _admin_token, auth_header


class Provider:
    model = "offline-c3"

    def __init__(self):
        self.calls = 0

    async def chat_completion(self, messages, tools=None):
        self.calls += 1
        return {"content": "", "tool_calls": []}

    async def stream_parts(self, prompt, system=None):
        self.calls += 1
        for text in ("先核对。\n```cli\ninterface GE", "0/0/7\n\n", "shutdown\n", "```\n"):
            yield {"kind": "content", "text": text}


@pytest_asyncio.fixture
async def api_case(client, test_session_factory, monkeypatch):
    provider = Provider()
    retrieval = AsyncMock(return_value=[])
    monkeypatch.setattr(router, "_retrieve", retrieval)
    monkeypatch.setattr(router, "load_protected_interfaces", AsyncMock(return_value=["GigabitEthernet0/0/7"]))
    monkeypatch.setattr(router.SystemService, "build_llm_provider", AsyncMock(return_value=provider))
    monkeypatch.setattr(LLMService, "_log_request", AsyncMock())
    token = await _admin_token(test_session_factory)
    return client, auth_header(token), provider, retrieval


def events(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["/chat", "/chat/stream"])
async def test_replay_between_transports_never_retrieves_or_generates_again(api_case, first):
    client, headers, provider, retrieval = api_case
    body = {"message": "请解释接口", "request_id": uuid.uuid4().hex}
    first_response = await client.post("/api/v1/ai/copilot" + first, json=body, headers=headers)
    assert first_response.status_code == 200, first_response.text
    calls, retrievals = provider.calls, retrieval.await_count
    assert calls > 0 and retrievals == 1
    for path in ("/chat", "/chat/stream"):
        replay = await client.post("/api/v1/ai/copilot" + path, json=body, headers=headers)
        assert replay.status_code == 200, replay.text
        if path == "/chat":
            assert replay.json()["replayed"] and replay.json()["historical"]
            answer = replay.json()["answer"]
        else:
            replay_events = events(replay)
            assert replay_events[0]["replayed"] and replay_events[-1]["type"] == "done"
            answer = "".join(e["text"] for e in replay_events if e["type"] == "token")
        assert "shutdown" not in answer.lower()
        assert provider.calls == calls and retrieval.await_count == retrievals
    conflict = await client.post("/api/v1/ai/copilot/chat", json={**body, "message": "changed"}, headers=headers)
    assert conflict.status_code == 409
    recovery = await client.get(f'/api/v1/ai/copilot/requests/{body["request_id"]}', headers=headers)
    assert recovery.status_code == 200 and recovery.json()["state"] == "completed"
    assert "shutdown" not in recovery.json()["response"]["answer"]
    assert provider.calls == calls


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
async def test_actual_routes_cancel_retrieval_without_restarting_same_id(api_case, test_session_factory, monkeypatch, path):
    client, headers, provider, _ = api_case
    entered, closed = asyncio.Event(), asyncio.Event()

    async def retrieve(*args):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    monkeypatch.setattr(router, "_retrieve", retrieve)
    body = {"message": "test", "request_id": uuid.uuid4().hex}
    task = asyncio.create_task(client.post("/api/v1/ai/copilot" + path, json=body, headers=headers))
    await asyncio.wait_for(entered.wait(), 5)
    cancelled = await client.post(f'/api/v1/ai/copilot/requests/{body["request_id"]}/cancel', headers=headers)
    assert cancelled.json()["cancelled"] is True
    response = await asyncio.wait_for(task, 5)
    assert closed.is_set() and provider.calls == 0
    status = response.json()["status"] if path == "/chat" else events(response)[-1]["status"]
    assert status == "cancelled"
    replay = await client.post("/api/v1/ai/copilot" + path, json=body, headers=headers)
    assert replay.status_code == 200
    assert provider.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('explicit_cancel', [False, True])
async def test_disconnect_finalizes_partial_and_closes_upstream(api_case, test_session_factory, explicit_cancel):
    from core.security import decode_access_token
    _, headers, _, _ = api_case
    payload = decode_access_token(headers["Authorization"][7:])
    actor = {"user_id": int(payload["sub"]), "role": "admin", "token_version": 0}
    data = CopilotChatRequest(message="test", request_id=uuid.uuid4().hex)
    closed = False
    calls = 0

    async def invoke(data, cancel_event):
        nonlocal calls
        calls += 1
        async def generate():
            nonlocal closed
            try:
                yield encode({"type": "token", "text": "partial"})
                await asyncio.Event().wait()
            finally:
                closed = True
        return StreamingResponse(generate())

    response = await execute(data, actor, test_session_factory, invoke, streaming=True)
    iterator = response.body_iterator
    assert "partial" in await anext(iterator)
    if explicit_cancel:
        assert registry.request_cancel(actor['user_id'], data.request_id)
    await iterator.aclose()
    assert closed
    recovered = await RequestStore(test_session_factory).read(data.request_id, actor)
    expected_state = 'cancelled' if explicit_cancel else 'interrupted'
    assert recovered["state"] == expected_state
    assert recovered["response"]["answer"] == "partial"
    replay = await execute(data, actor, test_session_factory, invoke, streaming=True)
    all_events = [event async for event in replay.body_iterator]
    assert calls == 1 and expected_state in all_events[-1]


@pytest.mark.asyncio
async def test_missing_request_store_never_starts_work():
    invoke = AsyncMock()
    data = CopilotChatRequest(message="test", request_id="no-store")
    with pytest.raises(HTTPException) as error:
        await execute(data, {"user_id": 1}, None, invoke, streaming=True)
    assert error.value.status_code == 503
    invoke.assert_not_called()
    assert not registry.request_cancel(1, "no-store")


@pytest.mark.asyncio
async def test_failed_final_save_never_exposes_success_done(api_case, test_session_factory, monkeypatch):
    from core.security import decode_access_token
    _, headers, _, _ = api_case
    actor = {"user_id": int(decode_access_token(headers["Authorization"][7:])["sub"]), "role": "admin", "token_version": 0}
    data = CopilotChatRequest(message="test", request_id=uuid.uuid4().hex)
    calls = 0

    async def invoke(data, event):
        nonlocal calls
        calls += 1
        async def generate():
            yield encode({"type": "token", "text": "answer"})
            yield encode({"type": "done", "status": "ok"})
        return StreamingResponse(generate())

    monkeypatch.setattr(RequestStore, "finish", AsyncMock(side_effect=RuntimeError("storage failure")))
    response = await execute(data, actor, test_session_factory, invoke, streaming=True)
    frames = [json.loads(frame[6:]) async for frame in response.body_iterator]
    assert frames[-1]["status"] == "interrupted"
    assert not any(e.get("type") == "done" and e.get("status") == "ok" for e in frames)
    with pytest.raises(HTTPException) as error:
        await execute(data, actor, test_session_factory, invoke, streaming=True)
    assert error.value.status_code == 409 and calls == 1
