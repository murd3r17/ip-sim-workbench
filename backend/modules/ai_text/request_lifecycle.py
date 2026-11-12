"""Transport adapters for a single durable request/result contract."""
import asyncio
import json
import uuid
import time
from contextlib import suppress

import anyio
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from core.logger import get_logger
from core.request_metrics import RequestMetrics
from .cancel import (registry, RequestCancelled, RequestCapacityExceeded,
                     RequestIdConflict, run_cancellable)
from .request_store import RequestStore

logger = get_logger("copilot_requests")


def deadline_seconds(data):
    from core.config import get_settings
    from .budget_policy import limits_for, select_tier
    tier = select_tier(data.message, want_draft=data.want_draft)
    # Existing provider timeout times the fixed tier, plus setup/retrieval.
    # This is one total deadline, never renewed by another phase or fallback.
    return min(600, max(30, get_settings().llm_timeout * limits_for(tier).max_generations + 30))


def encode(event):
    return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"


def result_events(result, request_id, *, replayed=True):
    yield {"type": "meta", "request_id": request_id, "sources": result.get("sources", []),
           "provider": result.get("provider", ""), "status": result.get("status", "failed"),
           "knowledge_status": result.get("knowledge_status", "unknown"),
           "draft_refused_reason": result.get("draft_refused_reason", ""),
           "draft_target": result.get("draft_target"),
           "replayed": replayed, "historical": replayed}
    if result.get("answer"):
        yield {"type": "token", "request_id": request_id, "text": result["answer"]}
    if result.get("draft_commands"):
        yield {"type": "draft", "request_id": request_id,
               "draft_commands": result["draft_commands"],
               "draft_explanation": result.get("draft_explanation", "")}
    if result.get("error_message"):
        yield {"type": "error", "request_id": request_id, "message": result["error_message"]}
    yield {"type": "done", "request_id": request_id, "status": result.get("status", "failed"),
           "cancelled": result.get("status") == "cancelled", "assist_only": True,
           "trace": result.get("trace", {}), "replayed": replayed}


class Accumulator:
    def __init__(self, request_id):
        self.result = {"answer": "", "sources": [], "draft_commands": [],
                       "request_id": request_id, "status": "interrupted", "assist_only": True}
        self.size = 0

    def add(self, event):
        self.size += len(json.dumps(event, ensure_ascii=False).encode())
        if self.size > 2_000_000:
            raise RuntimeError("Assistant response exceeds recovery limit")
        kind = event.get("type")
        if kind == "meta":
            for key in ("sources", "provider", "knowledge_status", "draft_refused_reason", "draft_target", "tier", "skill"):
                if key in event:
                    self.result[key] = event[key]
        elif kind == "token":
            self.result["answer"] += event.get("text", "")
        elif kind in {"policy", "draft"}:
            if kind == 'policy' and 'replace_answer' in event:
                self.result['answer'] = event['replace_answer']
                self.result['draft_commands'] = []
                self.result['draft_explanation'] = ''
            for key in ("draft_refused_reason", "draft_commands", "draft_explanation", "draft_target"):
                if key in event:
                    self.result[key] = event[key]
        elif kind == "error":
            self.result["error_message"] = event.get("message", "生成失败")
        elif kind == "done":
            self.result["status"] = event.get("status", "ok")
            self.result["trace"] = event.get("trace", {})
            if event.get("cancelled"):
                self.result["status"] = "cancelled"


def terminal_state(result):
    status = result.get("status")
    if status in {"cancelled", "interrupted"}:
        return status
    return "failed" if status in {"failed", "unavailable"} else "completed"


async def execute(data, actor, factory, invoke, *, streaming):
    """Reserve before any retrieval/tool/provider work; persist before done."""
    rid = (data.request_id or "").strip() or f"req-{uuid.uuid4().hex}"
    data = data.model_copy(update={"request_id": rid})
    uid = actor["user_id"]
    try:
        cancel_event = registry.register(uid, rid)
    except RequestIdConflict as exc:
        raise HTTPException(409, detail={"code": "request_in_progress", "message": str(exc)}) from exc
    except RequestCapacityExceeded as exc:
        raise HTTPException(429, detail=str(exc)) from exc
    lease = None
    finalized = False
    handed_off = False
    store = None
    metrics = RequestMetrics()
    cancel_event.copilot_deadline = time.monotonic() + deadline_seconds(data)

    async def within_deadline(awaitable):
        return await asyncio.wait_for(awaitable, max(0, cancel_event.copilot_deadline - time.monotonic()))

    def current_trace(result=None):
        capture = getattr(cancel_event, "copilot_trace", None)
        if callable(capture):
            return capture()
        meter = getattr(cancel_event, "copilot_meter", None)
        return meter.trace() if meter else (result or {}).get("trace", {"model_calls": 0})

    def timed_out(result=None):
        return {**(result or {}), "answer": (result or {}).get("answer", ""),
                "request_id": rid, "status": "failed", "error_message": "本次请求已达到总时限，回答未完成；未自动重新生成。",
                "trace": {**current_trace(result), "deadline_exceeded": True}}

    def release():
        registry.unregister(uid, rid, event=cancel_event)

    async def finish(result, http_status=200):
        nonlocal finalized
        metrics.finish()
        result["trace"] = {**current_trace(result), **result.get("trace", {}),
                           "timings": metrics.snapshot()}
        await store.finish(lease, result, status=terminal_state(result), http_status=http_status)
        finalized = True

    async def interrupted(result=None):
        if lease and not lease.replay and not finalized:
            # Starlette cancels the streaming task on disconnect. Shield the
            # bounded final write; never leave provider work running for it.
            with anyio.move_on_after(5, shield=True):
                try:
                    status = "cancelled" if getattr(cancel_event, "copilot_user_cancelled", False) else "interrupted"
                    await finish({**(result or {}), "request_id": rid, "status": status,
                                  "trace": current_trace(result)})
                except Exception as exc:
                    logger.warning("request_recovery_write_failed", error=type(exc).__name__)
                    # Durable reservation remains; it still forbids reexecution.

    try:
        store = RequestStore(factory)
        try:
            lease = await store.claim(data, actor)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(503, detail={"code": "request_store_unavailable",
                "message": "请求记录暂不可用，本次未启动模型或工具。"}) from exc
        if lease.replay:
            result = {**(lease.response or {}), "request_id": rid, "replayed": True, "historical": True}
            if lease.http_status >= 400:
                raise HTTPException(lease.http_status, detail=result.get("detail", "原请求失败；重新提问会创建新请求。"))
            if streaming:
                async def replay():
                    for event in result_events(result, rid):
                        yield encode(event)
                return StreamingResponse(replay(), media_type="text/event-stream",
                                         headers={"Cache-Control": "no-store"})
            return result

        if not streaming:
            try:
                with metrics.bind():
                    response = await within_deadline(run_cancellable(invoke(data, cancel_event), cancel_event))
                result = response.model_dump(mode="json") if hasattr(response, "model_dump") else response
                result["request_id"] = rid
                if result.get("answer"):
                    metrics.note_content()
            except RequestCancelled:
                result = {"answer": "本次请求已取消。", "status": "cancelled", "request_id": rid}
            except TimeoutError:
                cancel_event.set()
                result = timed_out()
            await finish(result)
            return result

        try:
            with metrics.bind():
                response = await within_deadline(invoke(data, cancel_event))
        except TimeoutError:
            cancel_event.set()
            result = timed_out()
            await finish(result)
            async def timeout_events():
                for event in result_events(result, rid, replayed=False):
                    yield encode(event)
            return StreamingResponse(timeout_events(), media_type="text/event-stream")
        if not isinstance(response, StreamingResponse):
            await interrupted()
            return response
        accumulator = Accumulator(rid)

        async def persist_stream():
            try:
                while True:
                    try:
                        with metrics.bind():
                            raw = await within_deadline(anext(response.body_iterator))
                    except StopAsyncIteration:
                        break
                    # The inner transport emits exactly one JSON event per frame.
                    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                    for line in text.splitlines():
                        if not line.startswith("data: "):
                            continue
                        event = json.loads(line[6:])
                        event["request_id"] = rid
                        metrics.note_event(event)
                        if event.get("type") == "done":
                            metrics.finish()
                            event["trace"] = {**current_trace(), **event.get("trace", {}),
                                              "timings": metrics.snapshot()}
                        accumulator.add(event)
                        if event.get("type") == "done":
                            await finish(accumulator.result)
                        yield encode(event)
                        if finalized:
                            return
                if not finalized:
                    await finish(accumulator.result)
                    yield encode({"type": "error", "request_id": rid, "message": "连接结束但未收到完成确认；已保存可恢复内容。"})
                    yield encode({"type": "done", "request_id": rid, "status": "interrupted"})
            except asyncio.CancelledError:
                cancel_event.set()
                raise
            except TimeoutError:
                cancel_event.set()
                result = timed_out(accumulator.result)
                await finish(result)
                yield encode({"type": "error", "request_id": rid, "message": result["error_message"]})
                yield encode({"type": "done", "request_id": rid, "status": "failed", "trace": result["trace"]})
            except Exception as exc:
                cancel_event.set()
                logger.warning("request_stream_failed", error=type(exc).__name__)
                yield encode({"type": "error", "request_id": rid, "message": "回答未完成或结果保存失败，请先查询原请求结果。"})
                yield encode({"type": "done", "request_id": rid, "status": "interrupted"})
            finally:
                # Close upstream before recording interruption.
                try:
                    with anyio.move_on_after(5, shield=True):
                        with suppress(Exception):
                            await response.body_iterator.aclose()
                    await interrupted(accumulator.result)
                finally:
                    release()

        handed_off = True
        return StreamingResponse(persist_stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
    except HTTPException as exc:
        if lease and not lease.replay and not finalized:
            await finish({"answer": "", "request_id": rid, "status": "failed", "detail": exc.detail}, exc.status_code)
        raise
    finally:
        if not handed_off:
            await interrupted()
            release()
