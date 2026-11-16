"""Atomically reserve login attempts across workers using the application database."""

from hashlib import sha256
import hmac
from ipaddress import ip_address
import time
from unicodedata import normalize

from fastapi import HTTPException, Request
from sqlalchemy import case, delete, or_, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.config import get_settings
from modules.auth.models import LoginAttemptWindow


def _source(request: Request) -> str:
    # Uvicorn resolves the client only for explicitly trusted proxy peers.
    # Never read forwarding headers directly in a request handler.
    try:
        address = ip_address(request.client.host if request.client else "")
        return str(getattr(address, "ipv4_mapped", None) or address)
    except ValueError:
        return "unknown"


def _keys(request: Request, username: str) -> dict[str, int]:
    settings = get_settings()
    name = normalize("NFKC", username.strip()).casefold()
    source = _source(request)
    secret = settings.jwt_secret_key.encode()
    return {
        hmac.new(secret, label.encode(), sha256).hexdigest(): limit
        for label, limit in (
            (f"login:account:{name}", settings.login_account_limit),
            (f"login:account-source:{source}:{name}", settings.login_account_ip_limit),
            (f"login:source:{source}", settings.login_ip_limit),
        )
    }


async def reserve_login_attempt(db, request: Request, username: str) -> dict[str, int]:
    now = int(time.time())
    expires = now + get_settings().login_window_seconds
    table = LoginAttemptWindow.__table__
    reserved = {}
    dialect = db.get_bind().dialect.name
    try:
        for key, limit in sorted(_keys(request, username).items()):
            values = dict(bucket=key, attempts=0, expires_at=expires)
            if dialect == "sqlite":
                insert = sqlite_insert(table).values(values).on_conflict_do_nothing(index_elements=[table.c.bucket])
            else:
                insert = mysql_insert(table).values(values).on_duplicate_key_update(bucket=table.c.bucket)
            await db.execute(insert)
            result = await db.execute(update(table).where(
                table.c.bucket == key, or_(table.c.expires_at <= now, table.c.attempts < limit),
            ).values(attempts=case((table.c.expires_at <= now, 1), else_=table.c.attempts + 1),
                     expires_at=case((table.c.expires_at <= now, expires), else_=table.c.expires_at)))
            current_end = await db.scalar(select(table.c.expires_at).where(table.c.bucket == key))
            if result.rowcount != 1:
                raise HTTPException(429, "登录尝试过多，请稍后重试。",
                                    headers={"Retry-After": str(max(1, current_end - now))})
            reserved[key] = current_end
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return reserved


async def release_successful_attempt(db, reserved: dict[str, int]) -> None:
    table = LoginAttemptWindow.__table__
    for key, expires_at in sorted(reserved.items()):
        await db.execute(update(table).where(
            table.c.bucket == key, table.c.expires_at == expires_at, table.c.attempts > 0,
        ).values(attempts=table.c.attempts - 1))
    await db.commit()


async def prune_login_windows(db) -> None:
    # Separate from the reservation transaction so cleanup does not extend
    # the lifetime of the hot account and classroom IP locks.
    now = int(time.time())
    rows = list(await db.scalars(select(LoginAttemptWindow.bucket)
                                .where(LoginAttemptWindow.expires_at <= now)
                                .order_by(LoginAttemptWindow.expires_at).limit(128)))
    if rows:
        await db.execute(delete(LoginAttemptWindow).where(
            LoginAttemptWindow.bucket.in_(rows), LoginAttemptWindow.expires_at <= now,
        ))
    await db.commit()
