"""Terminal shutdown must bound cancellation cleanup without losing ownership."""
import asyncio
import time

import pytest

from modules.webssh import router


@pytest.mark.asyncio
async def test_slow_cancel_cleanup_honors_deadline_and_stays_tracked():
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_cleanup():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()

    task = asyncio.create_task(slow_cleanup())
    router._track_heartbeat(task)
    await started.wait()
    try:
        before = time.monotonic()
        await asyncio.wait_for(router.shutdown_terminal_tasks(timeout=0.01), timeout=0.2)
        assert time.monotonic() - before < 0.15
        assert not task.done() and task in router.HEARTBEAT_TASKS
        assert task.cancelling() == 1
        await router.shutdown_terminal_tasks(timeout=0.01)
        assert task.cancelling() == 1, 'Repeated shutdown must not cancel an in-progress close again'
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)
    assert task not in router.HEARTBEAT_TASKS
