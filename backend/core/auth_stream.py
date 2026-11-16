"""Recheck access while a response still carries authenticated data."""

import asyncio
from contextlib import suppress
import time

from anyio import CancelScope

from core.browser_session import authenticate_browser_session
from core.database import get_session_factory
from modules.auth.models import User

LEASE_INTERVAL = 5.0


async def _still_authorized(actor: dict) -> bool:
    factory = get_session_factory()
    if factory is None:
        return False
    try:
        # ASGI cancels the stream when the peer disconnects. Close the short
        # session fully before that cancellation can interrupt the driver.
        with CancelScope(shield=True):
            async with factory() as db:
                if digest := actor.get("_browser_digest"):
                    await authenticate_browser_session(digest, db)
                    return True
                expiration = actor.get("_bearer_expires")
                if expiration is not None and expiration <= time.time():
                    return False
                user = await db.get(User, actor["user_id"])
                return (user is not None and user.is_active and user.token_version == actor["token_version"]
                        and user.role.value == actor["role"])
    except Exception:
        return False


async def require_live_session(source, actor):
    pending = None
    next_check = 0.0
    loop = asyncio.get_running_loop()
    try:
        while True:
            if loop.time() >= next_check:
                if not await _still_authorized(actor):
                    yield 'data: {"type":"auth_expired"}\n\n'
                    return
                next_check = loop.time() + LEASE_INTERVAL
            if pending is None:
                pending = asyncio.ensure_future(anext(source))
            done, _ = await asyncio.wait({pending}, timeout=max(0, next_check - loop.time()))
            if done and loop.time() < next_check:
                value = pending.result()
                pending = None
                yield value
    except StopAsyncIteration:
        return
    finally:
        with CancelScope(shield=True):
            if pending is not None:
                if not pending.done():
                    pending.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await pending
            if close := getattr(source, "aclose", None):
                await close()
