from typing import Any
"""WebSSH路由"""
import asyncio
import anyio
import json
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.security.utils import get_authorization_scheme_param
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from core.config import get_settings
from core.database import get_async_session, get_session_factory
from core.browser_session import authenticate_browser_session, cookie_name, credential_digest, require_browser_origin
from core.dependencies import authenticate_token, get_current_user
from engines import device_adapter
from modules.auth.terminal_grants import TerminalPermissionError, check_terminal_grant
from modules.webssh.proxy import SSHProxySession
from modules.webssh.session_logger import TerminalSessionLogger
from modules.device.service import DeviceService
from modules.trust.service import CURRENT_INSTANCE_ID, ensure_service_instance

# 确保所有模型已导入
from modules.auth.models import User, AuditLog
from modules.device.models import Device, Topology, TopologyLink
from modules.deploy.models import DeployTask, ConfigTemplate, ConfigVersion, DeviceWriteLock
from modules.monitor.models import MetricRecord, Alarm
from modules.training.models import TrainingLab, TrainingSession, FaultInjection

router = APIRouter(tags=["WebSSH终端"])

# 每用户并发终端会话数（防止 1 用户开 N 路 SSH）
_ACTIVE_WS_SESSIONS: dict[int, int] = {}


def _acquire_ws_slot(user_id: int) -> bool:
    limit = get_settings().webssh_max_sessions_per_user
    if _ACTIVE_WS_SESSIONS.get(user_id, 0) >= limit:
        return False
    _ACTIVE_WS_SESSIONS[user_id] = _ACTIVE_WS_SESSIONS.get(user_id, 0) + 1
    return True


RELEASE_TASKS: set[asyncio.Task] = set()
HEARTBEAT_TASKS: set[asyncio.Task] = set()
# 生产续租间隔 10s；测试可只缩短计时，不改变续租/停止判定逻辑。
TERMINAL_HEARTBEAT_INTERVAL = 10.0


def _track_release(task: asyncio.Task) -> None:
    RELEASE_TASKS.add(task)
    task.add_done_callback(lambda t: RELEASE_TASKS.discard(t))


def _track_heartbeat(task: asyncio.Task) -> None:
    HEARTBEAT_TASKS.add(task)
    task.add_done_callback(lambda t: HEARTBEAT_TASKS.discard(t))


def _release_ws_slot(user_id: int) -> None:
    remaining = _ACTIVE_WS_SESSIONS.get(user_id, 0) - 1
    if remaining > 0:
        _ACTIVE_WS_SESSIONS[user_id] = remaining
    else:
        _ACTIVE_WS_SESSIONS.pop(user_id, None)


async def _reject(websocket: WebSocket, code: int, reason: str) -> None:
    """Send a readable close reason after the request passes Origin checks."""
    try:
        await websocket.accept()
    except Exception:  # 已 accept 或客户端已断开
        pass
    try:
        await websocket.close(code=code, reason=reason)
    except Exception:
        pass


@router.get("/webssh/access/{device_id}")
async def terminal_access(device_id: int, actor: dict = Depends(get_current_user),
                          db=Depends(get_async_session)) -> dict:
    device = await db.get(Device, device_id)
    if device is None:
        raise HTTPException(404, "设备不存在")
    mode = device_adapter.get_device_mode()
    try:
        await check_terminal_grant(db, actor, device, mode=mode)
    except TerminalPermissionError as exc:
        return {"allowed": False, "mode": mode, "reason": str(exc)}
    return {"allowed": True, "mode": mode}


@router.websocket("/ws/ssh/{device_id}")
async def webssh_websocket(websocket: WebSocket, device_id: int) -> Any:
    digest = credential_digest(websocket.cookies.get(cookie_name()))
    scheme, token = get_authorization_scheme_param(websocket.headers.get("authorization"))
    browser = "origin" in websocket.headers or digest is not None
    if browser:
        try:
            require_browser_origin(websocket)
        except HTTPException:
            await websocket.close(code=1008)
            return
    if "token" in websocket.query_params or websocket.headers.get("sec-websocket-protocol"):
        await _reject(websocket, 4001, "终端登录方式已更新，请刷新工作台")
        return
    if not digest and (browser or scheme.lower() != "bearer" or not token):
        await _reject(websocket, 4001, "请登录工作台后再打开终端")
        return
    session_factory = get_session_factory()
    if session_factory is None:
        await _reject(websocket, 4005, "数据库未初始化")
        return

    async def authenticate(db):
        if browser:
            return await authenticate_browser_session(digest, db)
        return await authenticate_token(token, db)

    try:
        async with session_factory() as db:
            actor = await authenticate(db)
        user_id = actor["user_id"]
    except Exception:
        await _reject(websocket, 4001, "登录已失效，请重新登录")
        return

    if not _acquire_ws_slot(user_id):
        await _reject(websocket, 4006, "并发终端会话数已达上限")
        return
    lock_acquired = False
    terminal_token = uuid.uuid4().hex
    heartbeat_stop = None
    heartbeat_task = None
    try:
        await websocket.accept()

        # 获取设备信息
        async with session_factory() as db:
            try:
                device = await DeviceService.get_device(db, device_id)
            except ValueError:
                await websocket.send_text(json.dumps({"type": "error", "message": "设备不存在"}))
                await websocket.close(code=4004, reason="设备不存在")
                return

            mode = device_adapter.get_device_mode()
            try:
                grant = await check_terminal_grant(db, actor, device, mode=mode)
            except TerminalPermissionError as exc:
                await websocket.send_text(json.dumps({"type": "error", "message": str(exc)}))
                await websocket.close(code=4003, reason="缺少真实终端授权")
                return

            if await db.get(DeviceWriteLock, device_id):
                reason = "设备已被部署或其它终端占用，不能新开可写终端"
                await websocket.send_text(json.dumps({"type": "error", "message": reason}))
                await websocket.close(code=4009, reason=reason)
                return
            # BF-03：终端也是权威写占用者；与部署共用 device_write_lock，而不是第二套内存锁。
            # 插入唯一主键是原子竞争点：两个终端/终端与部署同时抢，仅一个成功。
            try:
                await ensure_service_instance(db)
                db.add(DeviceWriteLock(
                    device_id=device_id, task_id=None, lock_type="terminal",
                    owner_type="terminal", owner_id=user_id, owner_token=terminal_token,
                    owner_instance_id=CURRENT_INSTANCE_ID,
                    state="active", last_seen_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    expire_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=2),
                ))
                await asyncio.wait_for(db.commit(), timeout=5)
                lock_acquired = True
            except IntegrityError:
                await db.rollback()
                reason = "设备已被其它任务/终端占用"
                await websocket.send_text(json.dumps({"type": "error", "message": reason}))
                await websocket.close(code=4009, reason=reason)
                return

            heartbeat_stop = asyncio.Event()
            heartbeat_task = asyncio.create_task(_terminal_heartbeat(session_factory, device_id, terminal_token, heartbeat_stop))
            _track_heartbeat(heartbeat_task)
            credentials = await DeviceService.get_device_credentials(device) if mode == "ssh" else {
                "username": "", "password": "",
            }
            endpoint = (device.mgmt_ip, device.ssh_port)
            session_logger = TerminalSessionLogger(user_id=user_id, device_ip=device.mgmt_ip)
            proxy = SSHProxySession(
                websocket=websocket, device_ip=device.mgmt_ip,
                ssh_port=device.ssh_port, username=credentials["username"],
                password=credentials["password"], session_logger=session_logger,
                device_hostname=device.hostname,
                authorize=lambda: _session_authorized(session_factory, authenticate, device_id, mode, grant, endpoint),
            )
        # The interactive terminal must not hold a database connection for its lifetime.
        await proxy.start()
    finally:
        try:
            if heartbeat_stop is not None:
                heartbeat_stop.set()
            if heartbeat_task is not None:
                # Let an active short DB session finish instead of repeatedly
                # cancelling its driver close under an ASGI cancel scope.
                with anyio.CancelScope(shield=True):
                    _, pending = await asyncio.wait({heartbeat_task}, timeout=1.0)
                if pending and not heartbeat_task.cancelling():
                    heartbeat_task.cancel()
        finally:
            _release_ws_slot(user_id)
            if lock_acquired and session_factory is not None:
                # Failed/incomplete release remains fail-closed and visible in
                # /trust/locks; never clear another owner's token.
                try:
                    task = asyncio.create_task(_release_terminal_lock(session_factory, device_id, user_id, terminal_token))
                    _track_release(task)
                except Exception:
                    pass


async def _terminal_heartbeat(session_factory, device_id: int, terminal_token: str, stop: asyncio.Event) -> None:
    """BF7/BF8：短 DB 故障退避后继续续租；只有锁消失或 token 换代才停止。

    R8 组合：同一 token 可能被 reconcile 暂时标成 unknown（进程身份暂不可确认）。
    心跳本身来自持有该 token 的存活进程，下一次成功续租即证明会话仍在，因此把
    unknown 一并纳入条件并在续租时恢复 active；这不是放行别人的 unknown 锁，
    也不复活 closed/orphaned 等已判决状态。
    """
    failures = 0
    while not stop.is_set():
        try:
            async with session_factory() as db:
                await ensure_service_instance(db)
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                from sqlalchemy import update
                result = await db.execute(update(DeviceWriteLock).where(
                    DeviceWriteLock.device_id == device_id,
                    DeviceWriteLock.owner_type == "terminal",
                    DeviceWriteLock.owner_token == terminal_token,
                    DeviceWriteLock.state.in_(["active", "unknown"]),
                ).values(last_seen_at=now, expire_at=now + timedelta(hours=2), state="active"))
                await db.commit()
                if result.rowcount != 1:
                    break
            failures = 0
            try:
                await asyncio.wait_for(stop.wait(), timeout=TERMINAL_HEARTBEAT_INTERVAL)
                break
            except asyncio.TimeoutError:
                continue
        except Exception:
            failures += 1
            delay = min(30, 2 ** min(failures - 1, 4))
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
                break
            except asyncio.TimeoutError:
                continue


async def _release_terminal_lock(session_factory, device_id: int, user_id: int, terminal_token: str | None = None) -> None:
    from modules.trust.service import mark_terminal_release_failure, clear_terminal_release_failure
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            async with session_factory() as lock_db:
                conditions = [
                    DeviceWriteLock.device_id == device_id,
                    DeviceWriteLock.owner_type == "terminal",
                ]
                if terminal_token:
                    conditions.append(DeviceWriteLock.owner_token == terminal_token)
                else:
                    conditions.append(DeviceWriteLock.owner_id == user_id)
                await lock_db.execute(delete(DeviceWriteLock).where(*conditions))
                await lock_db.commit()
            clear_terminal_release_failure(device_id, terminal_token or "")
            return
        except Exception as exc:
            last_exc = exc
            await asyncio.sleep(0.1 * (attempt + 1))
    # DB 释放失败：内存只作短期提示，持久失败由 list_locks/下一次 DB 可用时落库。
    mark_terminal_release_failure(device_id, terminal_token or "")
    try:
        from core.logger import get_logger
        get_logger("webssh").warning("terminal_lock_release_failed", device_id=device_id,
                                     token_present=bool(terminal_token), error=type(last_exc).__name__)
    except Exception:
        pass


async def shutdown_terminal_tasks(timeout: float = 3.0) -> None:
    tasks = list(HEARTBEAT_TASKS) + list(RELEASE_TASKS)
    for task in tasks:
        if not task.done() and not task.cancelling():
            task.cancel()
    if tasks:
        with anyio.CancelScope(shield=True):
            done, pending = await asyncio.wait(tasks, timeout=max(0.0, timeout))
        HEARTBEAT_TASKS.difference_update(done)
        RELEASE_TASKS.difference_update(done)
        # Keep ownership until actual completion; callbacks remove finished
        # tasks. A deadline is not evidence that cleanup completed.
        if pending:
            from core.logger import get_logger
            get_logger('webssh').warning('terminal_shutdown_cleanup_pending', pending_tasks=len(pending))


async def _session_authorized(
    session_factory, authenticate, device_id: int, mode: str, grant: str | None, endpoint: tuple[str, int],
) -> bool:
    try:
        async with session_factory() as db:
            actor = await authenticate(db)
            if device_adapter.get_device_mode() != mode:
                raise TerminalPermissionError("设备连接方式已变化")
            if mode == "ssh":
                device = await db.get(Device, device_id)
                if device is None or (device.mgmt_ip, device.ssh_port) != endpoint:
                    raise TerminalPermissionError("设备管理地址已变化")
                await check_terminal_grant(db, actor, device, mode=mode, expected=grant)
        return True
    except TerminalPermissionError:
        raise
    except Exception:
        return False
