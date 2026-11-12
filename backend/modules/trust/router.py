# -*- coding: utf-8 -*-
"""V7-B 可信基础 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_async_session
from core.dependencies import get_current_user
from modules.trust import service
from modules.trust.models import EnvironmentProfile, ReadOnlyObservation
from modules.trust.schemas import (
    EnvironmentCreate, EnvironmentResponse, EnvironmentUpdate, ObservationCreate,
    ObservationResponse, OspfRuleRequest, PreflightRequest, PreflightResponse, RuleResponse,
)

router = APIRouter(prefix="/trust", tags=["trust"])


def _require_admin(user: dict) -> None:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可修改环境映射")


@router.get("/environments", response_model=list[EnvironmentResponse])
async def list_environments(db: AsyncSession = Depends(get_async_session), user: dict = Depends(get_current_user)):
    rows = (await db.execute(select(EnvironmentProfile).order_by(EnvironmentProfile.id.desc()))).scalars().all()
    return [service.serialize_environment(row) for row in rows]


def _validate_protection_ownership(devices: list, protections: list) -> None:
    device_ids = {int(d.get("device_id")) for d in devices if isinstance(d, dict) and d.get("device_id") is not None}
    roles = {str(d.get("role")): int(d["device_id"]) for d in devices if isinstance(d, dict) and d.get("role") and d.get("device_id") is not None}
    for item in protections or []:
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail="保护项必须是对象")
        pid = item.get("device_id")
        role = item.get("role")
        if pid is not None and int(pid) not in device_ids:
            raise HTTPException(status_code=422, detail=f"保护项归属设备 {pid} 不在环境设备中")
        if role and str(role) not in roles:
            raise HTTPException(status_code=422, detail=f"保护项角色 {role} 不在环境设备中")
        if pid is not None and role and int(pid) != roles.get(str(role)):
            raise HTTPException(status_code=422, detail="保护项 device_id 与 role 冲突")
        if pid is None and not role and len(device_ids) > 1:
            raise HTTPException(status_code=422, detail="多设备环境的保护项必须指定 device_id 或 role，不能全局猜测")


@router.post("/environments", response_model=EnvironmentResponse)
async def create_environment(
    data: EnvironmentCreate,
    db: AsyncSession = Depends(get_async_session),
    user: dict = Depends(get_current_user),
):
    _require_admin(user)
    row = EnvironmentProfile(
        name=data.name, version=data.version, site=data.site, status="draft",
        devices=[item.model_dump() for item in data.devices], protections=data.protections,
        expected={"neighbors": data.expected_neighbors, "routes": data.expected_routes},
        source="manual", created_by=user.get("user_id"), revision=1,
    )
    _validate_protection_ownership(row.devices or [], row.protections or [])
    row.content_hash = service.environment_hash(row)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return service.serialize_environment(row)


@router.put("/environments/{environment_id}", response_model=EnvironmentResponse)
async def update_environment(
    environment_id: int,
    data: EnvironmentUpdate,
    db: AsyncSession = Depends(get_async_session),
    user: dict = Depends(get_current_user),
):
    _require_admin(user)
    row = await db.get(EnvironmentProfile, environment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="环境不存在")
    payload = data.model_dump(exclude_unset=True)
    # BF4-02：先核对保护项归属，避免保存后才在 preflight 发现。
    _validate_protection_ownership(payload.get("devices", row.devices or []), payload.get("protections", row.protections or []))
    # 管理员不能手填 ready；映射一改，旧 preflight 立即失效，必须重新用事实核验。
    payload.pop("status", None)
    expected_keys = {"expected_neighbors", "expected_routes"}
    expected = dict(row.expected or {})
    old_hash = row.content_hash or service.environment_hash(row)
    content_changed = False
    for key, value in payload.items():
        if key == "devices" and value is not None:
            value = [item if isinstance(item, dict) else item.model_dump() for item in value]
            setattr(row, "devices", value)
            content_changed = True
        elif key == "protections" and value is not None:
            setattr(row, "protections", value)
            content_changed = True
        elif key in expected_keys:
            expected["neighbors" if key == "expected_neighbors" else "routes"] = value or []
            content_changed = True
        else:
            if key in {"version", "site", "name"}:
                content_changed = True
            setattr(row, key, value)
    row.expected = expected
    new_hash = service.environment_hash(row)
    if content_changed or new_hash != old_hash:
        row.revision = int(row.revision or 1) + 1
        row.status = "draft"
        row.last_preflight_status = None
        row.last_preflight_at = None
        row.content_hash = new_hash
    await db.commit()
    await db.refresh(row)
    return service.serialize_environment(row)


@router.get("/environments/{environment_id}", response_model=EnvironmentResponse)
async def get_environment(environment_id: int, db: AsyncSession = Depends(get_async_session), user: dict = Depends(get_current_user)):
    row = await db.get(EnvironmentProfile, environment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="环境不存在")
    return service.serialize_environment(row)


@router.post("/environments/{environment_id}/preflight", response_model=PreflightResponse)
async def preflight(
    environment_id: int,
    data: PreflightRequest | None = None,
    db: AsyncSession = Depends(get_async_session),
    user: dict = Depends(get_current_user),
):
    # BF4-04：preflight 会改写环境状态并写入证据，属管理员动作；此前只校验登录，
    # 与动作目录 roles=["admin"] 不一致，普通用户可直接触发。
    _require_admin(user)
    row = await db.get(EnvironmentProfile, environment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="环境不存在")
    return await service.preflight_environment(db, row, user_id=user.get("user_id"))


@router.post("/observations", response_model=ObservationResponse)
async def create_observation(
    data: ObservationCreate,
    db: AsyncSession = Depends(get_async_session),
    user: dict = Depends(get_current_user),
):
    try:
        row = await service.collect_observation(
            db, user=user, device_id=data.device_id, action_id=data.action_id,
            environment_id=data.environment_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return service.serialize_observation(row)


@router.get("/observations", response_model=list[ObservationResponse])
async def list_observations(
    device_id: int | None = None,
    environment_id: int | None = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_async_session),
    user: dict = Depends(get_current_user),
):
    stmt = select(ReadOnlyObservation)
    if user.get("role") != "admin":
        stmt = stmt.where(ReadOnlyObservation.created_by == user.get("user_id"))
    if device_id is not None:
        stmt = stmt.where(ReadOnlyObservation.device_id == device_id)
    if environment_id is not None:
        stmt = stmt.where(ReadOnlyObservation.environment_id == environment_id)
    rows = (await db.execute(stmt.order_by(ReadOnlyObservation.id.desc()).limit(min(max(limit, 1), 100)))).scalars().all()
    return [service.serialize_observation(row) for row in rows]


@router.get("/observations/{observation_id}", response_model=ObservationResponse)
async def get_observation(observation_id: int, db: AsyncSession = Depends(get_async_session), user: dict = Depends(get_current_user)):
    row = await db.get(ReadOnlyObservation, observation_id)
    if row is None or (user.get("role") != "admin" and row.created_by != user.get("user_id")):
        raise HTTPException(status_code=404, detail="证据不存在或无权读取")
    return service.serialize_observation(row)


@router.post("/rules/ospf/evaluate", response_model=RuleResponse)
async def evaluate_ospf(
    data: OspfRuleRequest,
    db: AsyncSession = Depends(get_async_session),
    user: dict = Depends(get_current_user),
):
    if user.get("role") != "admin":
        # 非管理员只能使用自己采集的证据。
        ids = list(data.observation_ids) if data.observation_ids else ([data.observation_id] if data.observation_id else [])
        if ids:
            rows = (await db.execute(select(ReadOnlyObservation).where(ReadOnlyObservation.id.in_(ids)))).scalars().all()
            if any(row.created_by != user.get("user_id") for row in rows):
                raise HTTPException(status_code=403, detail="不能使用他人的观察证据")
    return await service.evaluate_ospf_rules(db, data, user=user)


@router.get("/locks")
async def list_locks(db: AsyncSession = Depends(get_async_session), user: dict = Depends(get_current_user)):
    return await service.list_locks(db, user=user)


@router.post("/locks/{device_id}/recover")
async def recover_lock(device_id: int, db: AsyncSession = Depends(get_async_session), user: dict = Depends(get_current_user)):
    _require_admin(user)
    result = await service.recover_terminal_lock(db, device_id, user)
    if not result.get("released") and result.get("reason") != "no_lock":
        raise HTTPException(status_code=409, detail=result.get("reason", "不能恢复"))
    return result


@router.get("/pages")
async def page_catalog(user: dict = Depends(get_current_user)):
    role = user.get("role") or "user"
    return [
        {**item, "roles": item.get("roles", ["admin", "user"]), "executable": role in item.get("roles", ["admin", "user"])}
        for item in service.PAGE_CATALOG
        if role in item.get("roles", ["admin", "user"])
    ]


@router.get("/actions")
async def action_catalog(user: dict = Depends(get_current_user)):
    role = user.get("role") or "user"
    return [item for item in service.ACTION_CATALOG if role in item["roles"]]
