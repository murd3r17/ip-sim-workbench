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
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from .models import CopilotRequest


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
        identity, auth_scope = digest(payload), scope(actor)
        async with self.factory() as db:
            db.add(CopilotRequest(user_id=uid, request_id=rid, input_hash=identity,
                authorization_scope=auth_scope, owner_token=owner, status="running",
                http_status=200, created_at=now(), updated_at=now()))
            try:
                await db.commit()
                return Reservation(uid, rid, owner)
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
                return Reservation(uid, rid, "", row.response, row.http_status)

    async def finish(self, lease, response, *, status="completed", http_status=200):
        if lease.replay:
            raise ValueError("A replay cannot finalize a reservation")
        # Bound stored results; retain the reservation even if a provider sends
        # excessive output. No cache eviction may re-enable side effects.
        if len(json.dumps(response, ensure_ascii=False).encode()) > 2_000_000:
            response = {"answer": "回答过长，未能保存完整结果；请缩小问题范围后重新提问。",
                        "status": "failed", "request_id": lease.request_id}
            status = "failed"
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
        async with self.factory() as db:
            row = await db.get(CopilotRequest, (actor["user_id"], request_id))
            if row is None:
                raise HTTPException(404, detail="请求记录不存在")
            if row.authorization_scope != scope(actor):
                raise HTTPException(403, detail="权限已变化，不能读取原请求结果")
            return {"request_id": request_id, "state": row.status,
                    "created_at": row.created_at.isoformat() + "Z",
                    "updated_at": row.updated_at.isoformat() + "Z",
                    "response": row.response, "http_status": row.http_status,
                    "replayed": True, "historical": True}
