"""认证模块服务"""
from datetime import datetime, timezone
import re
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from core.security import hash_password, verify_password, create_access_token
from core.logger import get_logger
from modules.auth.models import User, AuditLog, UserRole

logger = get_logger("audit")


def _validate_password(password: str) -> None:
    """验证密码复杂度（长度上限对齐 bcrypt 的 72 字节限制）。"""
    if len(password) < 8:
        raise ValueError("密码长度不能少于8位")
    if len(password.encode("utf-8")) > 72:
        raise ValueError("密码不能超过 72 字节（bcrypt 限制）")
    if not re.search(r'[A-Z]', password):
        raise ValueError("密码必须包含大写字母")
    if not re.search(r'[a-z]', password):
        raise ValueError("密码必须包含小写字母")
    if not re.search(r'\d', password):
        raise ValueError("密码必须包含数字")


class AuthService:
    @staticmethod
    async def login(db: AsyncSession, username: str, password: str) -> dict:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if not user or not verify_password(password, user.hashed_password):
            raise ValueError("用户名或密码错误")
        if not user.is_active:
            raise ValueError("账号已被禁用")

        user.last_login_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(user)

        token = create_access_token(user.id, user.username, user.role.value, user.token_version)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": user  # 返回User对象，让Pydantic序列化
        }

    @staticmethod
    async def create_user(db: AsyncSession, username: str, password: str, display_name: str = None, role: str = "user", *, actor: dict | None = None) -> User:
        username = username.strip()
        if not username or len(username) > 64:
            raise ValueError("用户名须填写，最多 64 个字符")
        if display_name is not None and len(display_name) > 128:
            raise ValueError("显示名称最多 128 个字符")
        _validate_password(password)

        existing = await db.execute(select(User).where(User.username == username))
        if existing.scalar_one_or_none():
            raise ValueError("用户名已存在")

        user = User(username=username, hashed_password=hash_password(password), display_name=display_name or username, role=UserRole(role))
        db.add(user)
        try:
            if actor:
                await db.flush()
                await AuditService.log(db, actor["user_id"], actor.get("username", ""), "auth",
                                       "account_created", "user", str(user.id),
                                       {"account": username, "role": role}, commit=False)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError("用户名已存在") from exc
        await db.refresh(user)
        return user

    @staticmethod
    async def change_password(db: AsyncSession, user_id: int, old_password: str, new_password: str):
        _validate_password(new_password)

        user = await db.get(User, user_id)
        if not user or not verify_password(old_password, user.hashed_password):
            raise ValueError("旧密码错误")
        changed = await db.execute(update(User).where(
            User.id == user_id, User.hashed_password == user.hashed_password,
        ).values(hashed_password=hash_password(new_password), token_version=User.token_version + 1))
        if changed.rowcount != 1:
            await db.rollback()
            raise ValueError("账户已变更，请重新登录后重试")
        await AuditService.log(db, user.id, user.username, "auth", "account_password_changed", "user",
                               str(user.id), commit=False)
        await db.commit()

    @staticmethod
    async def reset_trainee_password(db: AsyncSession, user_id: int, new_password: str, actor: dict) -> None:
        _validate_password(new_password)
        user = await db.get(User, user_id)
        if user is None:
            raise LookupError("账号不存在")
        if user.role != UserRole.USER:
            raise PermissionError("管理员密码请使用本人改密或部署端恢复")
        result = await db.execute(update(User).where(User.id == user_id, User.role == UserRole.USER).values(
            hashed_password=hash_password(new_password), token_version=User.token_version + 1,
        ))
        if result.rowcount != 1:
            raise ValueError("该账号已有变更，请刷新后重试")
        await AuditService.log(db, actor["user_id"], actor.get("username", ""), "auth",
                               "account_password_reset", "user", str(user_id),
                               {"account": user.username}, commit=False)
        await db.commit()


class AuditService:
    @staticmethod
    async def log(db: AsyncSession, user_id: int, username: str, module: str, action: str, resource_type: str = None, resource_id: str = None, detail: dict = None, ip_address: str = None, result: str = "success", commit: bool = True):
        from core.redaction import redact_payload
        entry = AuditLog(user_id=user_id, username=username, module=module, action=action, resource_type=resource_type, resource_id=resource_id, detail=str(redact_payload(detail)) if detail else None, ip_address=ip_address, result=result)
        db.add(entry)
        if commit:
            await db.commit()
        else:
            await db.flush()
        logger.info("audit_event", user=username, module=module, action=action, resource=resource_type, result=result)
