"""Authorization management for the interactive device terminal."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_async_session
from core.dependencies import require_role
from core.time_utils import UtcDatetime
from modules.auth.models import TerminalGrant, User, UserRole
from modules.auth.service import AuditService
from modules.device.models import Device

router = APIRouter(prefix="/auth/users/{user_id}/terminal-grants", tags=["终端授权"])


class TerminalPermissionError(PermissionError):
    pass


class GrantInput(BaseModel):
    minutes: int = Field(ge=5, le=1440)
    note: str = Field(default="", max_length=240)


class GrantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    grant_id: str
    user_id: int
    device_id: int
    management_address: str
    ssh_port: int
    issued_by: int
    issued_at: UtcDatetime
    expires_at: UtcDatetime
    revoked_at: UtcDatetime | None
    note: str


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def check_terminal_grant(
    db: AsyncSession, actor: dict, device: Device, *, mode: str, expected: str | None = None,
) -> str | None:
    if mode == "sim" or actor["role"] == "admin":
        return None
    grant = await db.get(TerminalGrant, (actor["user_id"], device.id), populate_existing=True)
    if (
        grant is None or grant.revoked_at is not None or grant.expires_at <= _now()
        or grant.management_address != device.mgmt_ip or grant.ssh_port != device.ssh_port
        or (expected is not None and grant.grant_id != expected)
    ):
        raise TerminalPermissionError("真实终端需管理员授权。可先返回设备页做只读观察。")
    return grant.grant_id


@router.get("", response_model=list[GrantResponse])
async def list_grants(
    user_id: int,
    db: AsyncSession = Depends(get_async_session),
    _actor: dict = Depends(require_role("admin")),
):
    rows = await db.scalars(select(TerminalGrant).where(TerminalGrant.user_id == user_id)
                            .order_by(TerminalGrant.device_id))
    return rows.all()


@router.put("/{device_id}", response_model=GrantResponse)
async def issue_grant(
    user_id: int,
    device_id: int,
    payload: GrantInput,
    db: AsyncSession = Depends(get_async_session),
    actor: dict = Depends(require_role("admin")),
):
    user = await db.get(User, user_id, with_for_update=True)
    device = await db.get(Device, device_id, with_for_update=True)
    if user is None or device is None:
        raise HTTPException(404, "账号或设备不存在")
    if not user.is_active or user.role != UserRole.USER:
        raise HTTPException(409, "只能为启用的学员账号授权")
    grant = await db.get(TerminalGrant, (user_id, device_id), with_for_update=True)
    if grant is None:
        grant = TerminalGrant(user_id=user_id, device_id=device_id)
        db.add(grant)
    now = _now()
    grant.grant_id = uuid4().hex
    grant.management_address = device.mgmt_ip
    grant.ssh_port = device.ssh_port
    grant.issued_by = actor["user_id"]
    grant.issued_at = now
    grant.expires_at = now + timedelta(minutes=payload.minutes)
    grant.revoked_at = None
    grant.note = payload.note.strip()
    try:
        await AuditService.log(db, actor["user_id"], actor["username"], "auth", "terminal_grant_issued",
                               "device", str(device_id), {"learner_id": user_id, "minutes": payload.minutes},
                               commit=False)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "授权记录已变化，请刷新后再试") from exc
    return grant


@router.delete("/{device_id}", status_code=204)
async def revoke_grant(
    user_id: int,
    device_id: int,
    grant_id: str = Query(min_length=32, max_length=32),
    db: AsyncSession = Depends(get_async_session),
    actor: dict = Depends(require_role("admin")),
):
    result = await db.execute(update(TerminalGrant).where(
        TerminalGrant.user_id == user_id, TerminalGrant.device_id == device_id,
        TerminalGrant.grant_id == grant_id, TerminalGrant.revoked_at.is_(None),
    ).values(revoked_at=_now()))
    if result.rowcount != 1:
        raise HTTPException(409, "授权已变化，请刷新后核对")
    await AuditService.log(db, actor["user_id"], actor["username"], "auth", "terminal_grant_revoked",
                           "device", str(device_id), {"learner_id": user_id}, commit=False)
    await db.commit()
