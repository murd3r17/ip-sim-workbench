"""Persistent idempotency, separate from in-process cancellation.

Never expire a reservation into permission to execute again. A crashed owner
may leave a running row: it means outcome unconfirmed, not permission to retry.
Only an explicit new request ID starts another model/tool run.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import uuid

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from .models import CopilotConversation, CopilotRequest

_PRIVATE_CONTEXT = '_workbench_conversation'


def _public_response(response):
    if not isinstance(response, dict):
        return None
    public = {key: value for key, value in response.items() if key != _PRIVATE_CONTEXT}
    return public or None


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def scope(actor):
    return digest({"user_id": actor["user_id"], "role": actor.get("role"),
                   "token_version": actor.get("token_version")})


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class Reservation:
    user_id: int
    request_id: str
    owner: str
    response: dict | None = None
    http_status: int = 200
    conversation_id: str | None = None
    subjects: tuple[str, ...] = ()
    conversation_position: int | None = None

    @property
    def replay(self):
        return not self.owner


class RequestStore:
    def __init__(self, factory):
        if factory is None:
            raise HTTPException(503, detail={"code": "request_store_unavailable",
                "message": "请求记录暂不可用，本次未启动模型或工具。"})
        self.factory = factory

    async def claim(self, data, actor):
        uid, rid = actor["user_id"], data.request_id
        owner = uuid.uuid4().hex
        payload = data.model_dump(mode="json", exclude={"request_id"})
        if isinstance(payload.get('context'), dict) and payload['context'].get('knowledge_source') is None:
            # Omitting a newly introduced optional field must retain existing retry hashes.
            payload['context'].pop('knowledge_source', None)
        identity, auth_scope = digest(payload), scope(actor)
        async with self.factory() as db:
            conversation_id = None
            position = None
            subjects = ()
            selected = data.conversation_id
            if selected:
                conversation = (await db.execute(select(CopilotConversation.id).where(
                    CopilotConversation.id == selected, CopilotConversation.user_id == uid,
                ).with_for_update())).scalar_one_or_none()
                if conversation is not None:
                    from modules.knowledge.query_focus import protocol_names
                    field = CopilotRequest.response[_PRIVATE_CONTEXT]
                    latest = await db.scalar(select(func.max(field['position'].as_integer())).where(
                        CopilotRequest.user_id == uid, field['id'].as_string() == conversation,
                    ))
                    conversation_id = conversation
                    position = (latest or 0) + 1
                    subjects = tuple(sorted(protocol_names(data.message)))
            db.add(CopilotRequest(user_id=uid, request_id=rid, input_hash=identity,
                authorization_scope=auth_scope, owner_token=owner, status="running",
                response={_PRIVATE_CONTEXT: {'id': conversation_id, 'position': position}} if conversation_id else None,
                http_status=200, created_at=now(), updated_at=now()))
            try:
                await db.commit()
                return Reservation(uid, rid, owner, conversation_id=conversation_id, subjects=subjects, conversation_position=position)
            except IntegrityError:
                await db.rollback()
                row = await db.get(CopilotRequest, (uid, rid))
                if row is None:
                    raise  # e.g. missing user FK, never treat as duplicate
                if row.input_hash != identity or row.authorization_scope != auth_scope:
                    raise HTTPException(409, detail={"code": "request_input_conflict",
                        "message": "此请求编号已用于其他输入或权限，请使用新请求编号。"})
                if row.status == "running":
                    raise HTTPException(409, detail={"code": "request_in_progress",
                        "message": "此请求已提交，结果尚未确认；不会重复执行，请先查询原请求结果。"})
                return Reservation(uid, rid, "", _public_response(row.response), row.http_status)

    async def finish(self, lease, response, *, status="completed", http_status=200):
        if lease.replay:
            raise ValueError("A replay cannot finalize a reservation")
        # Bound stored results; retain the reservation even if a provider sends
        # excessive output. No cache eviction may re-enable side effects.
        if len(json.dumps(response, ensure_ascii=False).encode()) > 2_000_000:
            response = {"answer": "回答过长，未能保存完整结果；请缩小问题范围后重新提问。",
                        "status": "failed", "request_id": lease.request_id}
            status = "failed"
        if lease.conversation_id:
            sources = []
            if status == 'completed' and response.get('status') == 'ok' and response.get('generation_status') == 'generated':
                from .knowledge_continuation import cited_locators
                sources = cited_locators(response)
            response = {**response, _PRIVATE_CONTEXT: {'id': lease.conversation_id, 'sources': sources,
                                                       'subjects': lease.subjects, 'position': lease.conversation_position}}
        async with self.factory() as db:
            result = await db.execute(update(CopilotRequest).where(
                CopilotRequest.user_id == lease.user_id,
                CopilotRequest.request_id == lease.request_id,
                CopilotRequest.owner_token == lease.owner,
                CopilotRequest.status == "running",
            ).values(response=response, status=status, http_status=http_status, updated_at=now()))
            if result.rowcount != 1:
                raise RuntimeError("Request finalization ownership lost")
            await db.commit()

    async def read(self, request_id, actor):
        from .context_bundle import sanitize_historical_references
        async with self.factory() as db:
            row = await db.get(CopilotRequest, (actor["user_id"], request_id))
            if row is None:
                raise HTTPException(404, detail="请求记录不存在")
            if row.authorization_scope != scope(actor):
                raise HTTPException(403, detail="权限已变化，不能读取原请求结果")
            return {"request_id": request_id, "state": row.status,
                    "created_at": row.created_at.isoformat() + "Z",
                    "updated_at": row.updated_at.isoformat() + "Z",
                    "response": sanitize_historical_references(_public_response(row.response)), "http_status": row.http_status,
                    "replayed": True, "historical": True}


async def prior_source_context(db, data, actor) -> tuple[str, dict] | None:
    """Select only the immediately prior durable request for the same owned conversation."""
    if db is None or not data.conversation_id or not data.request_id:
        return None
    owner = actor['user_id']
    conversation = await db.get(CopilotConversation, data.conversation_id)
    if conversation is None or conversation.user_id != owner:
        return None
    field = CopilotRequest.response[_PRIVATE_CONTEXT]
    private_context = field.label('private_context')
    position = field['position'].as_integer().label('position')
    result = await db.execute(select(CopilotRequest.request_id, CopilotRequest.status, position,
        CopilotRequest.authorization_scope, private_context)
        .where(CopilotRequest.user_id == owner, field['id'].as_string() == conversation.id, position.is_not(None))
        .order_by(position.desc(), CopilotRequest.request_id.desc()).limit(3))
    rows = result.all()
    if len(rows) < 2:
        return None
    current, previous = rows[:2]
    # Databases without row locks may assign a position concurrently. Equal
    # positions cannot prove which request is later, so never inherit from them.
    if (current.request_id != data.request_id or current.status != 'running' or current.position <= previous.position
            or (len(rows) > 2 and previous.position == rows[2].position)
            or previous.status != 'completed' or previous.authorization_scope != scope(actor)
            or current.authorization_scope != scope(actor) or not isinstance(previous.private_context, dict)):
        return None
    return previous.request_id, previous.private_context
