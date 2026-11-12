import uuid
import asyncio
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import update

from modules.ai_text.models import CopilotRequest
from modules.ai_text.request_store import RequestStore
from modules.ai_text.schemas import CopilotChatRequest
from tests.test_training.test_v7a_state_and_reports import _admin_token


@pytest_asyncio.fixture
async def store_case(client, test_session_factory):
    from modules.auth.models import User
    from sqlalchemy import select
    await _admin_token(test_session_factory, username="admin")
    async with test_session_factory() as db:
        user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
        actor = {"user_id": user.id, "role": "admin"}
    return RequestStore(test_session_factory), actor, CopilotChatRequest(message="test", request_id=uuid.uuid4().hex)


@pytest.mark.asyncio
async def test_completed_identity_survives_store_restart_and_cannot_be_reused(store_case, test_session_factory):
    store, actor, data = store_case
    lease = await store.claim(data, actor)
    await store.finish(lease, {"answer": "saved", "status": "ok"})
    restarted = RequestStore(test_session_factory)
    replay = await restarted.claim(data, actor)
    assert replay.replay and replay.response["answer"] == "saved"
    with pytest.raises(HTTPException) as error:
        await restarted.claim(data.model_copy(update={"message": "other"}), actor)
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_inflight_restart_does_not_make_old_id_executable(store_case, test_session_factory):
    store, actor, data = store_case
    await store.claim(data, actor)
    restarted = RequestStore(test_session_factory)
    with pytest.raises(HTTPException) as error:
        await restarted.claim(data, actor)
    assert error.value.detail["code"] == "request_in_progress"
    result = await restarted.read(data.request_id, actor)
    assert result["state"] == "running" and result["response"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["failed", "cancelled", "interrupted"])
async def test_unsuccessful_ids_are_also_terminal(store_case, state):
    store, actor, data = store_case
    lease = await store.claim(data, actor)
    await store.finish(lease, {"answer": "partial", "status": state}, status=state)
    assert (await store.claim(data, actor)).response["status"] == state
    with pytest.raises(RuntimeError):
        await store.finish(lease, {"answer": "late resurrected"})
    assert (await store.read(data.request_id, actor))["response"]["answer"] == "partial"


@pytest.mark.asyncio
async def test_request_results_are_user_and_permission_scoped(store_case):
    store, actor, data = store_case
    lease = await store.claim(data, actor)
    await store.finish(lease, {"answer": "private"})
    with pytest.raises(HTTPException) as error:
        await store.read(data.request_id, {**actor, "user_id": actor["user_id"] + 10000})
    assert error.value.status_code == 404
    with pytest.raises(HTTPException) as error:
        await store.read(data.request_id, {**actor, "role": "user"})
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_old_owner_cannot_finalize_new_owner(store_case):
    store, actor, data = store_case
    lease = await store.claim(data, actor)
    async with store.factory() as db:
        await db.execute(update(CopilotRequest).where(CopilotRequest.request_id == data.request_id)
                         .values(owner_token="different"))
        await db.commit()
    with pytest.raises(RuntimeError):
        await store.finish(lease, {"answer": "wrong owner"})


@pytest.mark.asyncio
async def test_output_bound_keeps_tombstone(store_case):
    store, actor, data = store_case
    lease = await store.claim(data, actor)
    await store.finish(lease, {"answer": "x" * 2_000_001})
    result = await store.claim(data, actor)
    assert result.replay and result.response["status"] == "failed"


@pytest.mark.asyncio
async def test_concurrent_claims_on_independent_database_connections_have_one_owner(tmp_path):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from modules.auth.models import User
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'claims.db').as_posix()}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(User.__table__.create)
            await conn.run_sync(CopilotRequest.__table__.create)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db:
            db.add(User(id=1, username="only", hashed_password="offline"))
            await db.commit()
        data = CopilotChatRequest(message="test", request_id="concurrent")
        actor = {"user_id": 1, "role": "user"}
        results = await asyncio.gather(*(RequestStore(factory).claim(data, actor) for _ in range(5)), return_exceptions=True)
        owners = [r for r in results if not isinstance(r, Exception)]
        assert len(owners) == 1
        assert all(isinstance(r, HTTPException) and r.status_code == 409 for r in results if isinstance(r, Exception))
        await RequestStore(factory).finish(owners[0], {"answer": "one result"})
        assert (await RequestStore(factory).claim(data, actor)).replay
    finally:
        await engine.dispose()
