"""Request-local accounting at the HTTP dispatch boundary, including failover.

The scope is bound only while awaiting provider work, never across a consumer
yield. Shared providers and concurrent requests therefore keep separate meters.
No prompts, credentials or images are retained in the trace.
"""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import time
from copy import deepcopy

_active = ContextVar("llm_request_meter", default=None)


class RequestBudgetExceeded(RuntimeError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), default=str).encode()).hexdigest()


def before_dispatch(provider, payload):
    meter = _active.get()
    return meter.record(provider, payload) if meter else None


def record_usage(index, usage):
    meter = _active.get()
    if meter is not None and index is not None and isinstance(usage, dict):
        clean = {key: value for key, value in usage.items()
                 if key in {"prompt_tokens", "completion_tokens", "total_tokens",
                            "prompt_cache_hit_tokens", "prompt_cache_miss_tokens",
                            "cache_read_input_tokens", "cache_creation_input_tokens"}
                 and type(value) is int and value >= 0}
        details = usage.get("prompt_tokens_details")
        cached = details.get("cached_tokens") if isinstance(details, dict) else None
        if type(cached) is int and cached >= 0:
            clean["cached_prompt_tokens"] = cached
        if clean:
            meter.calls[index]["usage"] = clean


class RequestMeter:
    def __init__(self, limit, identity, charge=None, seconds=180, deadline=None, operation_limit=None):
        self.limit = limit
        self.identity = identity
        self.charge = charge
        self.deadline = deadline if deadline is not None else time.monotonic() + seconds
        self.calls = []
        self.operations = []
        self.kind = "answer"
        self.operation_limit = operation_limit

    @contextmanager
    def bind(self):
        token = _active.set(self)
        try:
            yield
        finally:
            _active.reset(token)

    def remaining(self):
        seconds = self.deadline - time.monotonic()
        if seconds <= 0:
            raise RequestBudgetExceeded("本次请求已达到总时限")
        return seconds

    def record(self, provider, payload):
        self.remaining()
        if self.limit is not None and len(self.calls) >= self.limit:
            raise RequestBudgetExceeded("本次请求已达到模型调用上限")
        if self.charge:
            self.charge(self.kind)
        index = len(self.calls)
        endpoint = getattr(provider, "api_base_url", getattr(provider, "base_url", ""))
        context_id = digest({"identity": self.identity, "payload": payload,
                             "provider": type(provider).__name__, "endpoint": endpoint})
        self.calls.append({"context_id": context_id, "kind": self.kind,
                           "model": payload.get("model", "unknown"), "usage": None})
        return index

    def trace(self):
        usages = [entry["usage"] for entry in self.calls]
        # Partial usage must not be represented as a complete total.
        usage = None
        if usages and all(usage is not None and "total_tokens" in usage for usage in usages):
            # A field is complete only when every actual dispatch returned it.
            common = set.intersection(*(set(item) for item in usages))
            usage = {key: sum(item[key] for item in usages) for key in common}
        return {"model_calls": len(self.calls), "generation_limit": self.limit,
                "contexts": deepcopy(self.calls), "usage": usage,
                "provider_operations": deepcopy(self.operations)}


class MeteredProvider:
    def __init__(self, provider, meter):
        self.provider, self.meter = provider, meter

    def __getattr__(self, name):
        return getattr(self.provider, name)

    def _fixture_dispatch(self, name, args, kwargs):
        # Test/custom providers without the native HTTP hook remain observable.
        # Built-in wrappers inherit the native flag from their primary provider.
        if getattr(self.provider, "metered_dispatch", False) is not True:
            self.meter.record(self.provider, {"method": name, "args": args, "kwargs": kwargs,
                                             "model": getattr(self.provider, "model", "unknown")})

    async def _call(self, name, *args, **kwargs):
        operation, started, first_dispatch = self._start_operation(name)
        try:
            with self.meter.bind():
                self._fixture_dispatch(name, args, kwargs)
                timeout = self.meter.remaining()
                result = await asyncio.wait_for(getattr(self.provider, name)(*args, **kwargs),
                                                timeout=timeout)
            operation["status"] = "completed"
            if self._has_content(result):
                operation["first_content_ms"] = round((time.perf_counter() - started) * 1000, 3)
            return result
        except BaseException as exc:
            self._failed_operation(operation, exc)
            raise
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            operation["provider_await_ms"] = round(elapsed, 3)
            self._finish_operation(operation, started, first_dispatch)

    def _start_operation(self, name):
        self.meter.remaining()
        if self.meter.operation_limit is not None and len(self.meter.operations) >= self.meter.operation_limit:
            raise RequestBudgetExceeded("本次请求已达到生成步骤上限")
        operation = {"method": name, "status": "running", "provider_await_ms": 0.0,
                     "first_content_ms": None, "dispatch_count": 0,
                     "timing_scope": "provider_operation_may_include_failover_not_single_http"}
        self.meter.operations.append(operation)
        return operation, time.perf_counter(), len(self.meter.calls)

    @staticmethod
    def _has_content(part):
        if isinstance(part, str):
            return bool(part)
        if isinstance(part, dict):
            return bool(part.get("text")) if part.get("kind") == "content" else bool(part.get("content"))
        return False

    @staticmethod
    def _failed_operation(operation, exc):
        operation["status"] = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
        operation["error_type"] = type(exc).__name__

    def _finish_operation(self, operation, started, first_dispatch):
        operation["operation_wall_ms"] = round((time.perf_counter() - started) * 1000, 3)
        operation["dispatch_count"] = len(self.meter.calls) - first_dispatch

    async def generate(self, *args, **kwargs):
        return await self._call("generate", *args, **kwargs)

    async def chat_completion(self, *args, **kwargs):
        return await self._call("chat_completion", *args, **kwargs)

    async def _stream(self, name, *args, **kwargs):
        self.meter.remaining()
        operation, started, first_dispatch = self._start_operation(name)
        iterator = getattr(self.provider, name)(*args, **kwargs)
        first = True
        try:
            while True:
                try:
                    with self.meter.bind():
                        if first:
                            self._fixture_dispatch(name, args, kwargs)
                            first = False
                        timeout = self.meter.remaining()
                        awaiting = time.perf_counter()
                        try:
                            part = await asyncio.wait_for(anext(iterator), timeout=timeout)
                        finally:
                            operation["provider_await_ms"] += (time.perf_counter() - awaiting) * 1000
                except StopAsyncIteration:
                    operation["status"] = "completed"
                    break
                if operation["first_content_ms"] is None and self._has_content(part):
                    operation["first_content_ms"] = round((time.perf_counter() - started) * 1000, 3)
                yield part
        except GeneratorExit:
            operation["status"] = "interrupted"
            raise
        except BaseException as exc:
            self._failed_operation(operation, exc)
            raise
        finally:
            try:
                await iterator.aclose()
            finally:
                operation["provider_await_ms"] = round(operation["provider_await_ms"], 3)
                self._finish_operation(operation, started, first_dispatch)

    def stream_parts(self, *args, **kwargs):
        return self._stream("stream_parts", *args, **kwargs)

    def stream(self, *args, **kwargs):
        return self._stream("stream", *args, **kwargs)

    def stream_parts_with_images(self, *args, **kwargs):
        return self._stream("stream_parts_with_images", *args, **kwargs)
