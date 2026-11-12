"""Request-local observations; unknown usage and replay must remain honest."""
import asyncio
import json
import uuid

import pytest

from core.llm_meter import MeteredProvider, RequestMeter, record_usage
from core.request_metrics import RequestMetrics, measure_stage, note_cache
from modules.ai_text.kb_cache import cached_search, invalidate
from modules.ai_text.request_lifecycle import execute, encode
from modules.ai_text.schemas import CopilotChatRequest
from fastapi.responses import StreamingResponse
from tests.test_c3_request_api import api_case  # noqa: F401


@pytest.mark.asyncio
async def test_concurrent_retrieval_cache_metrics_are_request_owned():
    class Service:
        async def search(self, *args):
            await asyncio.sleep(.002)
            return [{"content": "excerpt"}]
    service = Service()
    invalidate()
    cold, warm, other = RequestMetrics(), RequestMetrics(), RequestMetrics()
    with cold.bind(), measure_stage("retrieval"):
        await cached_search(service, "same", 2)
    async def run(metrics, query):
        with metrics.bind(), measure_stage("retrieval"):
            await cached_search(service, query, 2)
    await asyncio.gather(run(warm, "same"), run(other, "different"))
    assert cold.snapshot()["knowledge_cache"] == {"hits": 0, "misses": 1}
    assert warm.snapshot()["knowledge_cache"] == {"hits": 1, "misses": 0}
    assert other.snapshot()["knowledge_cache"] == {"hits": 0, "misses": 1}
    assert all(m.snapshot()["stages"]["retrieval"]["count"] == 1 for m in (cold, warm, other))
    assert RequestMetrics().snapshot()["knowledge_cache"] is None
    note_cache("hit")  # A caller outside a request cannot contaminate one.
    assert cold.snapshot()["knowledge_cache"]["hits"] == 0
    invalidate()


@pytest.mark.asyncio
async def test_provider_reasoning_is_not_first_content_and_partial_close_is_recorded():
    closed = False
    class Provider:
        async def stream_parts(self, *args):
            nonlocal closed
            try:
                yield {"kind": "reasoning", "text": "private chain"}
                yield {"kind": "content", "text": ""}
                yield {"kind": "content", "text": "answer"}
                await asyncio.Event().wait()
            finally:
                closed = True
    meter = RequestMeter(1, {})
    stream = MeteredProvider(Provider(), meter).stream_parts("secret question")
    await anext(stream)
    assert meter.trace()["provider_operations"][0]["first_content_ms"] is None
    await anext(stream)
    assert meter.trace()["provider_operations"][0]["first_content_ms"] is None
    await anext(stream)
    assert meter.trace()["provider_operations"][0]["first_content_ms"] >= 0
    await stream.aclose()
    operation = meter.trace()["provider_operations"][0]
    assert closed and operation["status"] == "interrupted"
    assert operation["dispatch_count"] == 1 and operation["provider_await_ms"] >= 0
    assert "private chain" not in json.dumps(meter.trace())
    assert "secret question" not in json.dumps(meter.trace())


@pytest.mark.asyncio
async def test_provider_failure_records_type_not_sensitive_exception_and_cache_usage_unknown():
    class Provider:
        async def generate(self, *args):
            raise ValueError("secret upstream body")
    meter = RequestMeter(1, {})
    with pytest.raises(ValueError):
        await MeteredProvider(Provider(), meter).generate("q")
    trace = meter.trace()
    assert trace["provider_operations"][0]["status"] == "failed"
    assert trace["provider_operations"][0]["error_type"] == "ValueError"
    assert trace["usage"] is None
    assert "secret upstream body" not in json.dumps(trace)


def test_actual_cache_token_fields_are_whitelisted_without_fabricated_totals():
    meter = RequestMeter(2, {})
    with meter.bind():
        index = meter.record(object(), {"model": "fixture"})
        record_usage(index, {"prompt_tokens": 12, "total_tokens": 16,
            "completion_tokens": 4, "prompt_cache_hit_tokens": 8,
            "prompt_cache_miss_tokens": 4, "prompt_tokens_details": {"cached_tokens": 8},
            "api_key": "secret", "cache_read_input_tokens": True})
    usage = meter.trace()["usage"]
    assert usage["prompt_cache_hit_tokens"] == 8 and usage["cached_prompt_tokens"] == 8
    assert "cache_read_input_tokens" not in usage
    assert "api_key" not in json.dumps(meter.trace())
    with meter.bind():
        meter.record(object(), {"model": "unknown-usage"})
    assert meter.trace()["usage"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_real_retrieval_failure_reports_measured_stage_and_actual_provider(api_case, monkeypatch, streaming):
    from modules.ai_text import router
    from core.config import get_settings
    client, headers, _, _ = api_case
    class Unavailable:
        async def search(self, *args):
            raise RuntimeError("secret retrieval backend detail")
    # Restore the production helper, not the fixture's mocked retrieval.
    monkeypatch.setattr(router, "_retrieve", _actual_retrieve)
    monkeypatch.setattr(router, "_get_knowledge_service", lambda: Unavailable())
    monkeypatch.setattr(get_settings(), "knowledge_provider", "local")
    response = await client.post("/api/v1/ai/copilot/chat" + ("/stream" if streaming else ""),
        json={"message": "解释 BGP 路径属性", "request_id": uuid.uuid4().hex}, headers=headers)
    assert response.status_code == 200
    if streaming:
        frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        result = frames[-1]
        assert frames[0]["knowledge_status"] == "degraded"
    else:
        result = response.json()
        assert result["knowledge_status"] == "degraded"
    timing = result["trace"]["timings"]
    assert timing["stages"]["retrieval"]["count"] == 1
    assert timing["observations"][0]["status"] == "failed"
    assert timing["knowledge_cache"] == {"hits": 0, "misses": 1}
    assert "secret retrieval backend detail" not in json.dumps(result)


# Capture before api_case replaces the route helper.
from modules.ai_text.router import _retrieve as _actual_retrieve


@pytest.mark.asyncio
async def test_sse_safe_content_timing_is_persisted_and_replayed_unchanged(api_case, test_session_factory):
    from core.security import decode_access_token
    _, headers, _, _ = api_case
    actor = {"user_id": int(decode_access_token(headers["Authorization"][7:])["sub"]),
             "role": "admin", "token_version": 0}
    calls = 0
    async def invoke(data, cancel_event):
        nonlocal calls
        calls += 1
        async def generate():
            with measure_stage("retrieval"):
                note_cache("miss")
                await asyncio.sleep(.002)
            yield encode({"type": "progress", "message": "working"})
            yield encode({"type": "reasoning", "text": "not answer"})
            yield encode({"type": "token", "text": ""})
            await asyncio.sleep(.002)
            yield encode({"type": "token", "text": "answer"})
            yield encode({"type": "done", "status": "ok", "trace": {"model_calls": 0}})
        return StreamingResponse(generate())
    data = CopilotChatRequest(message="fixture", request_id=uuid.uuid4().hex)
    response = await execute(data, actor, test_session_factory, invoke, streaming=True)
    # Binding must not escape to the HTTP consumer across generator yields.
    iterator = response.body_iterator
    await anext(iterator)
    with measure_stage("tool"):
        note_cache("hit")
    frames = [json.loads(frame[6:]) async for frame in iterator]
    timing = frames[-1]["trace"]["timings"]
    assert timing["first_safe_content_ms"] >= 0
    assert timing["first_progress_ms"] <= timing["first_safe_content_ms"]
    assert timing["first_evidence_event_ms"] is None
    assert timing["request_elapsed_ms"] >= timing["first_safe_content_ms"]
    assert timing["stages"]["retrieval"]["count"] == 1
    assert timing["stages"]["tool"]["count"] == 0
    assert timing["knowledge_cache"] == {"hits": 0, "misses": 1}
    for streaming in (False, True):
        replay = await execute(data, actor, test_session_factory, invoke, streaming=streaming)
        result = ([json.loads(frame[6:]) async for frame in replay.body_iterator][-1]
                  if streaming else replay)
        assert result["trace"]["timings"] == timing
    assert calls == 1


@pytest.mark.asyncio
async def test_cancelled_stage_retains_elapsed_and_never_records_exception_body():
    metrics = RequestMetrics()
    entered = asyncio.Event()
    async def work():
        with metrics.bind(), measure_stage("retrieval"):
            entered.set()
            await asyncio.Event().wait()
    task = asyncio.create_task(work())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    metrics.finish()
    snapshot = metrics.snapshot()
    assert snapshot["observations"][0]["status"] == "cancelled"
    assert snapshot["stages"]["retrieval"]["elapsed_ms"] >= 0
    assert snapshot["first_safe_content_ms"] is None
    assert snapshot == metrics.snapshot()
