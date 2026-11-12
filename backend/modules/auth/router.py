from typing import Any
"""认证模块路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_async_session
from core.dependencies import get_current_user
from modules.auth.service import AuthService
from modules.auth.schemas import UserLogin, UserCreate, TokenResponse, UserResponse, PasswordChange
from core.rate_limiter import rate_limit

router = APIRouter(prefix="/auth", tags=["认证"])


def _is_db_unavailable(exc: Exception) -> bool:
    name = type(exc).__name__
    text = str(exc).lower()
    return name in {"OperationalError", "InterfaceError"} or "can't connect" in text or "mysql" in text


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, db: AsyncSession = Depends(get_async_session), _rate_limit=Depends(rate_limit(max_requests=30, window_seconds=60))) -> Any:
    """登录（限流 30 次/分钟/IP）。

    原来是 10 次/分钟：对真实使用场景太紧 —— 实训教室几十名学生在同一个 NAT 出口后
    各登录一次就会互相 429（同时 e2e 串跑 18 个用例也会撞到，表现为"最后一个用例登录超时"）。
    30 次/分钟仍然足以挡住暴力破解（配合 401 与审计），又不会误伤正常上课。
    """
    try:
        result = await AuthService.login(db, data.username, data.password)
        return result
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        import logging
        logging.getLogger("auth").error("login_error", exc_info=True)
        if _is_db_unavailable(e):
            raise HTTPException(status_code=503, detail="数据库未启动，请先运行 scripts/start-local-windows.ps1") from e
        raise HTTPException(status_code=500, detail="登录失败，请稍后重试") from e


@router.post("/users", response_model=UserResponse)
async def create_user(data: UserCreate, db: AsyncSession = Depends(get_async_session), current_user: dict = Depends(get_current_user)) -> Any:
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    try:
        user = await AuthService.create_user(db, data.username, data.password, data.display_name, data.role)
        return user
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)) -> Any:
    from sqlalchemy import select
    from modules.auth.models import User
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
