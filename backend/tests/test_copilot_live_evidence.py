"""Real AsyncSession evidence persistence; model/device I/O stays fake."""
import asyncio
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import select

from modules.auth.models import AuditLog, User
from modules.ai_text.models import AILog
from modules.ai_text.llm_service import LLMService


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_vision_request_logs_the_model_passed_to_provider(test_session_factory, monkeypatch, streaming):
    class Provider:
        name = "fake-provider"
        model = "text-model"
        async def stream_parts_with_images(self, prompt, images, **kwargs):
            assert kwargs["model"] == "vision-model"
            yield {"kind": "content", "text": "fixture-image-marker"}
    monkeypatch.setattr("modules.ai_text.agent_tools.available_tool_defs", lambda actor, allowed=None: [])
    monkeypatch.setattr(LLMService, "_resolve_vision_model", lambda _: "vision-model")
    async with test_session_factory() as db:
        user = User(username=uuid.uuid4().hex, hashed_password=uuid.uuid4().hex)
        db.add(user)
        await db.commit()
        user_id = user.id
        service = LLMService(db=db, user_id=user_id, provider=Provider())
        image = [{"contentString": "data:image/png;base64,aW1hZ2UtZml4dHVyZQ==", "mime": "image/png"}]
        if streaming:
            events = [event async for event in service.copilot_chat_stream("read attached image", attachments=image)]
            assert events[-1]["status"] == "ok"
        else:
            response = await service.copilot_chat("read attached image", attachments=image)
            assert response["answer"] == "fixture-image-marker"
    async with test_session_factory() as other:
        row = (await other.execute(select(AILog).where(AILog.user_id == user_id))).scalar_one()
        assert row.model_used == "vision-model"


@pytest.mark.asyncio
async def test_existing_tool_audit_survives_short_session_close(test_session_factory, monkeypatch):
    from modules.ai_text.agent_tools import _audit_tool
    from scripts.verify_full_stack import matching_tool_audits
    monkeypatch.setattr("core.database.get_session_factory", lambda: test_session_factory)
    async with test_session_factory() as db:
        user = User(username=uuid.uuid4().hex, hashed_password=uuid.uuid4().hex)
        db.add(user)
        await db.commit()
        user_id = user.id
    service = LLMService(user_id=user_id, provider=SimpleNamespace(name="fake"), use_short_sessions=True)
    async with service._session() as db:
        await _audit_tool(db, user_id, "ai_display_command", {"device_id": 7, "command": "display version"})
    async with test_session_factory() as other:
        row = (await other.execute(select(AuditLog).where(AuditLog.user_id == user_id))).scalar_one()
        assert row.result == "success"  # Commit already exists in AuditService.log.
        raw = {"id": row.id, "user_id": row.user_id, "detail": row.detail, "result": row.result}
        assert matching_tool_audits([raw], 7, user_id) == [row.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_owned_short_session_rolls_back_uncommitted_work_on_failure(test_session_factory, monkeypatch, failure):
    monkeypatch.setattr("core.database.get_session_factory", lambda: test_session_factory)
    name = uuid.uuid4().hex
    service = LLMService(provider=SimpleNamespace(name="fake"), use_short_sessions=True)
    with pytest.raises(failure):
        async with service._session() as db:
            db.add(User(username=name, hashed_password=uuid.uuid4().hex))
            await db.flush()
            raise failure("isolated failure")
    async with test_session_factory() as other:
        assert (await other.execute(select(User).where(User.username == name))).scalar_one_or_none() is None


def test_legacy_audit_parser_never_executes_expressions_or_accepts_unexpected_fields(tmp_path):
    from scripts.verify_full_stack import matching_tool_audits
    row = {"id": 1, "user_id": 2, "result": "success"}
    for value in ["__import__('pathlib').Path('unexpected').write_text('bad')", "[]",
                  "{'device_id': 7, 'command': 'display version', 'unexpected': True}", "{" * 5000]:
        assert matching_tool_audits([{**row, "detail": value}], 7, 2) == []
