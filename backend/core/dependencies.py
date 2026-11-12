"""FastAPI依赖注入"""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from core.security import decode_access_token
from jose import JWTError
from core.database import get_session_factory

# auto_error=False：缺少 Authorization 头时由我们自己抛 401
# （HTTPBearer 默认抛 403，语义不对且与 token 失效无法区分）
security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
):
    """Check the current account in a short session, including for SSE endpoints."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="缺少认证令牌")
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="认证服务暂不可用")
    async with factory() as db:
        return await authenticate_token(credentials.credentials, db)


async def authenticate_token(token: str, db) -> dict:
    """Shared HTTP/WebSocket boundary; never trust a stale role in a signed JWT."""
    from modules.auth.models import User
    try:
        payload = decode_access_token(token)
        user = await db.get(User, int(payload["sub"]), populate_existing=True)
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail="账号不存在或已禁用")
        role = user.role.value
        if payload.get("role") != role or int(payload.get("ver", 0)) != user.token_version:
            raise HTTPException(status_code=401, detail="登录状态已变更，请重新登录")
        return {"user_id": user.id, "username": user.username, "role": role,
                "token_version": user.token_version}
    except (JWTError, KeyError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="无效的认证令牌")


def require_role(*roles: str):
    """角色权限校验工厂"""
    async def _check(current_user: dict = Depends(get_current_user)):
        if current_user["role"] not in roles:
            raise HTTPException(status_code=403, detail=f"需要角色: {list(roles)}")
        return current_user
    return _check
