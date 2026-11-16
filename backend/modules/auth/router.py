from typing import Any
"""认证模块路由"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_async_session
from core.dependencies import get_current_user, require_role
from core.browser_session import (
    LOGIN_HEADER, create_browser_session, require_browser_origin, revoke_browser_session, session_info,
)
from modules.auth.models import User
from modules.auth.service import AuthService
from modules.auth.schemas import (
    BrowserSessionResponse, UserLogin, UserCreate, TokenResponse, UserResponse, PasswordChange, TraineePasswordReset,
)
from modules.auth.login_limits import prune_login_windows, release_successful_attempt, reserve_login_attempt

router = APIRouter(prefix="/auth", tags=["认证"])


def _is_db_unavailable(exc: Exception) -> bool:
    name = type(exc).__name__
    text = str(exc).lower()
    return name in {"OperationalError", "InterfaceError"} or "can't connect" in text or "mysql" in text


async def _login(data, request, db, authenticate):
    try:
        await prune_login_windows(db)
        reserved = await reserve_login_attempt(db, request, data.username)
        result = await authenticate()
        await release_successful_attempt(db, reserved)
        return result
    except ValueError as e:
        raise HTTPException(status_code=401, detail="用户名或密码错误") from e
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger("auth").error("login_error %s", type(e).__name__)
        if _is_db_unavailable(e):
            raise HTTPException(status_code=503, detail="登录服务暂不可用。请管理员检查工作台数据库。") from e
        raise HTTPException(status_code=500, detail="登录失败，请稍后重试") from e


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, request: Request, response: Response, db: AsyncSession = Depends(get_async_session)) -> Any:
    """Token endpoint for command-line and other non-browser clients."""
    if "origin" in request.headers or "sec-fetch-site" in request.headers:
        raise HTTPException(403, "请从工作台登录页登录")
    response.headers["Cache-Control"] = "no-store"
    return await _login(data, request, db, lambda: AuthService.login(db, data.username, data.password))


@router.post("/session", response_model=BrowserSessionResponse)
async def browser_login(data: UserLogin, request: Request, response: Response,
                        db: AsyncSession = Depends(get_async_session)) -> Any:
    target = require_browser_origin(request)
    if request.headers.get(LOGIN_HEADER) != "1":
        raise HTTPException(403, "无法验证登录请求，请刷新登录页后重试。")

    async def authenticate():
        user = await AuthService.authenticate_password(db, data.username, data.password)
        return await create_browser_session(db, user, response, request, target)

    return await _login(data, request, db, authenticate)


@router.get("/session", response_model=BrowserSessionResponse)
async def browser_identity(response: Response, actor: dict = Depends(get_current_user),
                           db: AsyncSession = Depends(get_async_session)) -> Any:
    if not actor.get("_browser_digest"):
        raise HTTPException(401, "请从工作台登录页登录")
    user = await db.get(User, actor["user_id"])
    if user is None:
        raise HTTPException(401, "登录已失效")
    response.headers["Cache-Control"] = "no-store"
    return session_info(user, actor["_browser_digest"], actor["_browser_session_id"])


@router.delete("/session", status_code=204)
async def browser_logout(request: Request, response: Response, actor: dict = Depends(get_current_user),
                         db: AsyncSession = Depends(get_async_session)) -> None:
    if not actor.get("_browser_digest"):
        raise HTTPException(401, "请从工作台登录页登录")
    await revoke_browser_session(db, response, actor, request)


@router.post("/users", response_model=UserResponse)
async def create_user(data: UserCreate, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    try:
        user = await AuthService.create_user(db, data.username, data.password, data.display_name, data.role, actor=current_user)
        return user
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    q: str = Query("", max_length=128),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(require_role("admin")),
) -> Any:
    query = select(User).order_by(User.username).offset(offset).limit(50)
    if q.strip():
        query = query.where(User.username.contains(q.strip(), autoescape=True) | User.display_name.contains(q.strip(), autoescape=True))
    return (await db.execute(query)).scalars().all()


@router.put("/users/{user_id}/password", response_model=None)
async def reset_trainee_password(
    user_id: int,
    data: TraineePasswordReset,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(require_role("admin")),
) -> dict:
    try:
        await AuthService.reset_trainee_password(db, user_id, data.new_password.get_secret_value(), current_user)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"message": "密码已重置，原登录将失效"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)) -> Any:
    result = await db.execute(select(User).where(User.id == current_user["user_id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


@router.put("/password", response_model=None)
async def change_password(data: PasswordChange, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    try:
        await AuthService.change_password(db, current_user["user_id"], data.old_password, data.new_password)
        return {"message": "密码修改成功"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
