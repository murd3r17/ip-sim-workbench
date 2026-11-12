# -*- coding: utf-8 -*-
"""V7-A A-06 / AF2-02：AI 请求取消登记表与可取消等待。

取消是“本次请求”的语义，不是撤销已经提交到设备的配置。上游模型是否真正停止
计费无法从客户端确认，因此接口只返回 ``upstream=abort_requested``，不宣称已停止。

AF2-02 收紧：
- 外层调用者被取消时，必须取消并等待它自己创建的上游 task，不能只清理 waiter；
- 迭代器的 pump、queue getter、event waiter、上游 ``aclose`` 在正常结束、显式取消、
  上游异常、消费者关闭四条路径都要收尾；
- 同一用户同一 request_id 在途重复登记直接拒绝，避免旧 event 被顶掉后失去取消入口；
- 注销带登记身份，旧请求的 finally 不能删掉后来同 ID 的新登记。
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import suppress
from typing import Any, Awaitable, Callable, TypeVar

_MAX_ENTRIES = 512
T = TypeVar("T")


class RequestCancelled(Exception):
    """本次请求被用户取消（只影响本地请求，不撤销设备动作）。"""


class RequestIdConflict(ValueError):
    """同一用户同一 request_id 已有在途请求。"""


class RequestCapacityExceeded(RuntimeError):
    """在途请求登记达到容量上限；拒绝新请求而不是静默丢弃旧登记。"""


async def _cancel_and_wait(task: asyncio.Future | None) -> None:
    """取消并等待一个任务结束；清理异常不再向调用者抛出。"""
    if task is None:
        return
    if not task.done():
        task.cancel()
    with suppress(BaseException):
        await task


async def run_cancellable(
    awaitable: Awaitable[T],
    event: asyncio.Event | None,
    on_cancel: Callable[[], None] | None = None,
) -> T:
    """等待一个可阻塞操作，同时响应取消事件或外层取消。

    外层 task 被取消时，本函数负责取消并等待内部 task，然后原样抛回
    ``CancelledError``；不会留下仍在运行的上游协程。
    """
    if event is None:
        return await awaitable

    def notify_cancel() -> None:
        if on_cancel is not None:
            try:
                on_cancel()
            except Exception:  # noqa: BLE001
                pass

    if event.is_set():
        notify_cancel()
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()
        raise RequestCancelled
    task = asyncio.ensure_future(awaitable)
    waiter = asyncio.ensure_future(event.wait())
    try:
        done, _ = await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            return task.result()
        # 先释放本请求的登记，再取消上游；这样上游 finally 触发时登记已经消失。
        notify_cancel()
        await _cancel_and_wait(task)
        raise RequestCancelled
    except asyncio.CancelledError:
        notify_cancel()
        await _cancel_and_wait(task)
        raise
    finally:
        await _cancel_and_wait(waiter)
        await _cancel_and_wait(task)


async def iterate_cancellable(agen, event: asyncio.Event | None):
    """带取消的异步迭代器：等待首 token / token 之间都可取消，退出时关闭上游。

    不能用 ``wait_for(agen.__anext__())``：超时会取消 ``__anext__`` 并直接关闭
    异步生成器（实测会把正常回答变成空流）。这里用 pump 任务读取上游，主循环只
    等待队列或取消事件。
    """
    if event is None:
        async for item in agen:
            yield item
        return

    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    async def pump() -> None:
        try:
            async for item in agen:
                await queue.put(("item", item))
                if event.is_set():
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            with suppress(BaseException):
                await queue.put(("error", exc))
        finally:
            with suppress(BaseException):
                await queue.put(("end", None))

    task = asyncio.create_task(pump())
    getter: asyncio.Task | None = None
    waiter: asyncio.Task | None = None
    try:
        while True:
            if event.is_set():
                return
            getter = asyncio.create_task(queue.get())
            waiter = asyncio.create_task(event.wait())
            try:
                done, _ = await asyncio.wait({getter, waiter}, return_when=asyncio.FIRST_COMPLETED)
                if waiter in done and event.is_set():
                    return
                kind, value = getter.result()
            finally:
                await _cancel_and_wait(waiter)
                waiter = None
                if getter is not None and not getter.done():
                    await _cancel_and_wait(getter)
                getter = None
            if kind == "end":
                return
            if kind == "error":
                raise value
            yield value
    finally:
        await _cancel_and_wait(getter)
        await _cancel_and_wait(waiter)
        await _cancel_and_wait(task)
        with suppress(BaseException):
            await agen.aclose()


class CancellationRegistry:
    def __init__(self, max_entries: int = _MAX_ENTRIES) -> None:
        self._events: OrderedDict[tuple[int, str], asyncio.Event] = OrderedDict()
        self._max_entries = max(1, int(max_entries))

    def register(self, user_id: int | None, request_id: str) -> asyncio.Event:
        """登记在途请求；同一用户同 ID 重复登记拒绝，不替换旧 event。"""
        key = (int(user_id or 0), request_id)
        if key in self._events:
            raise RequestIdConflict("同一请求 ID 仍在处理中，请等待完成或先取消后再重试")
        if len(self._events) >= self._max_entries:
            # AF2-02：有界容量用“拒绝新请求”表达，不能静默删掉旧登记让它失去取消入口。
            raise RequestCapacityExceeded("当前在途 AI 请求过多，请稍后重试")
        event = asyncio.Event()
        self._events[key] = event
        self._events.move_to_end(key)
        return event

    def request_cancel(self, user_id: int | None, request_id: str) -> bool:
        event = self._events.get((int(user_id or 0), request_id))
        if event is None:
            return False
        event.copilot_user_cancelled = True
        event.set()
        return True

    def is_cancelled(self, user_id: int | None, request_id: str) -> bool:
        event = self._events.get((int(user_id or 0), request_id))
        return bool(event and event.is_set())

    def unregister(self, user_id: int | None, request_id: str, event: asyncio.Event | None = None) -> bool:
        """注销登记；传入 event 时只删除同一登记，避免旧请求误删新请求。"""
        key = (int(user_id or 0), request_id)
        current = self._events.get(key)
        if current is None:
            return False
        if event is not None and current is not event:
            return False
        self._events.pop(key, None)
        return True

    def clear(self) -> None:
        self._events.clear()


registry = CancellationRegistry()
