import asyncio
import json
import uuid

import pytest
from fastapi.responses import StreamingResponse

from modules.ai_text import request_lifecycle
from modules.ai_text.request_store import RequestStore
from modules.ai_text.schemas import CopilotChatRequest


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_preparation_timeout_is_durable_and_does_not_repeat(test_session_factory, monkeypatch, streaming):
    from tests.test_training.test_v7a_state_and_reports import _admin_token
    from core.security import decode_access_token
    token = await _admin_token(test_session_factory)
    # Use the same authenticated identity structure as the actual dependency.
    claims = decode_access_token(token)
    actor = {"user_id": int(claims["sub"]), "role": "admin", "token_version": 0}
    monkeypatch.setattr(request_lifecycle, "deadline_seconds", lambda data: .03)
    calls = 0
    closed = asyncio.Event()
    async def slow(data, cancel):
        nonlocal calls
        calls += 1
        try:
            await asyncio.sleep(5)
        finally:
            closed.set()
    data = CopilotChatRequest(message="q", request_id=uuid.uuid4().hex)
    response = await request_lifecycle.execute(data, actor, test_session_factory, slow, streaming=streaming)
    if streaming:
        events = [json.loads(raw[6:]) async for raw in response.body_iterator]
        assert events[-1]["status"] == "failed"
    else:
        assert response["status"] == "failed"
    assert closed.is_set() and calls == 1
    replay = await request_lifecycle.execute(data, actor, test_session_factory, slow, streaming=False)
    assert replay["replayed"] and replay["trace"]["deadline_exceeded"] and calls == 1


@pytest.mark.asyncio
async def test_setup_and_stream_share_one_deadline(test_session_factory, monkeypatch):
    # The request store has no User foreign key; this identity is isolated to this fixture DB.
    actor = {"user_id": 1, "role": "user"}
    monkeypatch.setattr(request_lifecycle, "deadline_seconds", lambda data: .12)
    closed = asyncio.Event()
    async def invoke(data, cancel):
        await asyncio.sleep(.06)
        async def stream():
            try:
                yield request_lifecycle.encode({"type": "token", "text": "部分回答"})
                await asyncio.sleep(.08)
                yield request_lifecycle.encode({"type": "done", "status": "ok"})
            finally:
                closed.set()
        return StreamingResponse(stream())
    data = CopilotChatRequest(message="q", request_id=uuid.uuid4().hex)
    response = await request_lifecycle.execute(data, actor, test_session_factory, invoke, streaming=True)
    events = [json.loads(raw[6:]) async for raw in response.body_iterator]
    assert closed.is_set() and events[-1]["status"] == "failed"
    stored = await RequestStore(test_session_factory).read(data.request_id, actor)
    assert stored["response"]["answer"] == "部分回答"
    assert stored["state"] == "failed" and stored["response"]["trace"]["deadline_exceeded"]
