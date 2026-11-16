"""Opaque, origin-bound browser authentication for HTTP and WebSocket."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
from ipaddress import ip_address
import re
import secrets
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import HTTPException, Response
from sqlalchemy import delete, select
from starlette.requests import HTTPConnection

from core.config import get_settings
from modules.auth.models import BrowserSession, User

CSRF_HEADER = "x-workbench-csrf"
SESSION_HEADER = "x-workbench-session"
LOGIN_HEADER = "x-workbench-login"
_COOKIE_PATH = "/api/v1"
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _origin(value: str) -> str:
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        port = url.port
        if url.username or url.password or url.path or url.query or url.fragment:
            return ""
        if url.scheme != "https" and not (url.scheme == "http" and host in _LOOPBACK_HOSTS):
            return ""
        if ":" in host:
            host = str(ip_address(host))
        if not re.fullmatch(r"[a-z0-9.:-]+", host):
            return ""
        authority = f"[{host}]" if ":" in host else host
        if port is not None and port != (443 if url.scheme == "https" else 80):
            authority = f"{authority}:{port}"
        return f"{url.scheme}://{authority}"
    except ValueError:
        return ""


def request_origin(connection: HTTPConnection) -> str:
    scheme = {"ws": "http", "wss": "https"}.get(connection.url.scheme, connection.url.scheme)
    return _origin(f"{scheme}://{connection.url.netloc}")


def browser_origins() -> set[str]:
    return {origin for value in get_settings().cors_origins.split(",") if (origin := _origin(value.strip()))}


def require_browser_origin(connection: HTTPConnection) -> str:
    origin = _origin(connection.headers.get("origin", ""))
    target = request_origin(connection)
    allowed = browser_origins()
    if target:
        allowed.add(target)
    if not origin or origin not in allowed:
        raise HTTPException(403, "无法验证浏览器来源。请使用工作台原地址，远程访问需使用 HTTPS。")
    # A configured dev origin may differ from the local API port. An HTTPS
    # origin must still reach an HTTPS application endpoint via its proxy.
    if not target or (origin.startswith("https:") and not target.startswith("https:")):
        raise HTTPException(403, "无法建立安全的浏览器会话。请检查 HTTPS 反向代理配置。")
    return target


def cookie_name() -> str:
    # Cookie matching has no port component. Isolated instances have
    # distinct keys and must not overwrite one another's cookie on loopback.
    key = get_settings().jwt_secret_key
    return "ip_sim_session_" + sha256(key.encode("utf-8")).hexdigest()[:16]


def credential_digest(credential: str | None) -> str | None:
    if credential and len(credential) == 43 and credential.isascii():
        return sha256(credential.encode("ascii")).hexdigest()
    return None


def _csrf(digest: str) -> str:
    return hmac.new(get_settings().jwt_secret_key.encode("utf-8"),
                    ("browser-csrf:" + digest).encode("ascii"), sha256).hexdigest()


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def authenticate_browser_session(digest: str | None, db) -> dict:
    if digest is None:
        raise HTTPException(401, "请登录工作台")
    # One joined read prevents treating independently refreshed session and
    # user snapshots as an authorized pair.
    row = (await db.execute(select(BrowserSession, User).join(
        User, User.id == BrowserSession.user_id,
    ).where(BrowserSession.credential_digest == digest,
            BrowserSession.expires_at > utc_now(), User.is_active.is_(True),
            User.token_version == BrowserSession.token_version,
            User.role == BrowserSession.role))).first()
    if row is None:
        raise HTTPException(401, "登录已过期，请重新登录")
    session, user = row
    return {"user_id": user.id, "username": user.username, "role": user.role.value,
            "token_version": user.token_version, "_browser_digest": digest,
            "_browser_session_id": session.session_id}


def session_info(user: User, digest: str, session_id: str) -> dict:
    return {"user": user, "session_id": session_id, "csrf_token": _csrf(digest)}


def check_browser_request(connection, actor: dict, *, mutating: bool) -> None:
    client_session = connection.headers.get(SESSION_HEADER)
    if client_session and client_session != actor["_browser_session_id"]:
        raise HTTPException(401, "此标签页的登录已变化，请刷新后继续")
    if mutating:
        require_browser_origin(connection)
        supplied = connection.headers.get(CSRF_HEADER, "")
        if not supplied.isascii() or not hmac.compare_digest(supplied, _csrf(actor["_browser_digest"])):
            raise HTTPException(403, "无法验证此操作。请刷新工作台后重试。")


async def create_browser_session(db, user: User, response: Response, connection: HTTPConnection, target: str) -> dict:
    now = utc_now()
    age = timedelta(minutes=get_settings().jwt_expire_minutes)
    credential = secrets.token_urlsafe(32)
    digest = credential_digest(credential)
    session_id = uuid4().hex
    previous = credential_digest(connection.cookies.get(cookie_name()))
    if previous:
        await db.execute(delete(BrowserSession).where(BrowserSession.credential_digest == previous))
    expired = list(await db.scalars(select(BrowserSession.credential_digest)
                                   .where(BrowserSession.expires_at <= now).limit(128)))
    if expired:
        await db.execute(delete(BrowserSession).where(BrowserSession.credential_digest.in_(expired)))
    db.add(BrowserSession(credential_digest=digest, session_id=session_id, user_id=user.id,
                          token_version=user.token_version, role=user.role.value, expires_at=now + age))
    await db.commit()
    response.set_cookie(cookie_name(), credential, max_age=int(age.total_seconds()), path=_COOKIE_PATH,
                        secure=target.startswith("https:"), httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return session_info(user, digest, session_id)


async def revoke_browser_session(db, response: Response, actor: dict, connection: HTTPConnection) -> None:
    await db.execute(delete(BrowserSession).where(BrowserSession.credential_digest == actor["_browser_digest"]))
    await db.commit()
    response.delete_cookie(cookie_name(), path=_COOKIE_PATH, secure=request_origin(connection).startswith("https:"),
                           httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
