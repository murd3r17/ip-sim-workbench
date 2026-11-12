import asyncio
import json

import httpx
import pytest

from core.llm_meter import MeteredProvider, RequestMeter, RequestBudgetExceeded
from core.llm_provider import OpenAICompatibleProvider, FailoverProvider


def provider(name, handler):
    item = OpenAICompatibleProvider(base_url="http://fixture.invalid/v1", model=name, api_key="fixture")
    item._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return item


@pytest.mark.asyncio
async def test_actual_http_failover_is_charged_and_third_dispatch_is_blocked():
    sent = []
    def reply(request):
        data = json.loads(request.content)
        sent.append(data)
        if data["model"] == "first":
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"message": {"content": "answer"}}],
                                         "usage": {"total_tokens": 19}})
    first, second = provider("first", reply), provider("second", reply)
    meter = RequestMeter(2, {"user_id": 1, "role": "user"})
    wrapped = MeteredProvider(FailoverProvider(first, second), meter)
    try:
        assert await wrapped.generate("question") == "answer"
        assert len(sent) == meter.trace()["model_calls"] == 2
        operation = meter.trace()["provider_operations"][0]
        assert operation["dispatch_count"] == 2 and operation["status"] == "completed"
        assert operation["provider_await_ms"] >= 0
        assert meter.calls[0]["usage"] is None and meter.calls[1]["usage"]["total_tokens"] == 19
        assert meter.trace()["usage"] is None
        with pytest.raises(RequestBudgetExceeded):
            await wrapped.generate("question")
        assert len(sent) == 2
    finally:
        await first._client.aclose()
        await second._client.aclose()


@pytest.mark.asyncio
async def test_context_identity_covers_permissions_exact_prompt_and_model_settings():
    def reply(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "answer"}}]})
    inner = provider("model", reply)
    identities = []
    try:
        for role, prompt, temperature in [("user", "R1", .2), ("user", "R1", .2),
                                         ("admin", "R1", .2), ("user", "R2", .2), ("user", "R1", .3)]:
            meter = RequestMeter(1, {"user_id": 1, "role": role})
            await MeteredProvider(inner, meter).generate(prompt, temperature=temperature)
            identities.append(meter.calls[0]["context_id"])
        assert identities[0] == identities[1]
        assert len(set(identities)) == 4
    finally:
        await inner._client.aclose()


@pytest.mark.asyncio
async def test_shared_provider_concurrent_requests_have_independent_budgets():
    async def reply(request):
        await asyncio.sleep(.01)
        return httpx.Response(200, json={"choices": [{"message": {"content": "answer"}}]})
    inner = provider("model", reply)
    meters = [RequestMeter(1, {"user_id": i}) for i in range(3)]
    try:
        await asyncio.gather(*(MeteredProvider(inner, m).generate("q") for m in meters))
        assert [m.trace()["model_calls"] for m in meters] == [1, 1, 1]
        assert len({m.calls[0]["context_id"] for m in meters}) == 3
    finally:
        await inner._client.aclose()


@pytest.mark.asyncio
async def test_deadline_does_not_reset_and_slow_stream_closes():
    closed = asyncio.Event()
    class Slow:
        async def stream_parts(self, *args, **kwargs):
            try:
                yield {"kind": "content", "text": "partial"}
                await asyncio.sleep(5)
            finally:
                closed.set()
    meter = RequestMeter(1, {}, seconds=.05)
    with pytest.raises(TimeoutError):
        _ = [p async for p in MeteredProvider(Slow(), meter).stream_parts("q")]
    assert closed.is_set() and meter.trace()["model_calls"] == 1
    with pytest.raises(RequestBudgetExceeded):
        meter.record(Slow(), {})


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_expired_deadline_never_constructs_provider_work(stream):
    # Native providers charge only at dispatch. Deadline checking must happen
    # before constructing an awaitable, including one never subsequently awaited.
    constructed = []
    class Native:
        metered_dispatch = True
        def generate(self, *args, **kwargs):
            constructed.append('generate')
            async def work():
                return 'must not run'
            return work()
        def stream_parts(self, *args, **kwargs):
            constructed.append('stream')
            async def parts():
                yield {'kind':'content','text':'must not run'}
            return parts()
    meter = RequestMeter(1, {}, deadline=0)
    wrapped = MeteredProvider(Native(), meter)
    with pytest.raises(RequestBudgetExceeded):
        if stream:
            _ = [part async for part in wrapped.stream_parts('q')]
        else:
            await wrapped.generate('q')
    assert constructed == []
    assert meter.trace()['model_calls'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("counts,expected", [
    ({"prompt_eval_count": 11, "eval_count": 18}, {"prompt_tokens": 11, "completion_tokens": 18, "total_tokens": 29}),
    ({"prompt_eval_count": 11}, {"prompt_tokens": 11}),
    ({"prompt_eval_count": True, "eval_count": -1}, None),
])
async def test_ollama_native_counts_preserve_unknown_and_reject_invalid_values(stream, counts, expected):
    from core.llm_provider import OllamaProvider
    result = {"response": "answer", "done": True, **counts}
    def reply(request):
        if stream:
            return httpx.Response(200, text=json.dumps(result) + "\n")
        return httpx.Response(200, json=result)
    inner = OllamaProvider(base_url="http://fixture.invalid", model="fixture")
    inner._client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
    meter = RequestMeter(1, {})
    wrapped = MeteredProvider(inner, meter)
    try:
        answer = "".join([part async for part in wrapped.stream("q")]) if stream else await wrapped.generate("q")
        assert answer == "answer"
        assert meter.calls[0]["usage"] == expected
        assert meter.trace()["usage"] == (expected if expected and "total_tokens" in expected else None)
    finally:
        await inner._client.aclose()
