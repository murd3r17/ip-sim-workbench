import httpx
import pytest

from core.llm_provider import OpenAICompatibleProvider


def test_openai_compatible_provider_normalizes_v1_base_url():
    provider = OpenAICompatibleProvider(base_url="http://llm.example/v1", model="demo", api_key="test")

    assert provider.api_base_url == "http://llm.example/v1"


def test_openai_compatible_provider_adds_missing_v1_base_url():
    provider = OpenAICompatibleProvider(base_url="http://llm.example", model="demo", api_key="test")

    assert provider.api_base_url == "http://llm.example/v1"


@pytest.mark.asyncio
@pytest.mark.parametrize("vision", [False, True])
@pytest.mark.parametrize("content", [None, "", "用户可见的正式回答", [{"text": "invalid shape"}]])
async def test_nonstream_answer_never_substitutes_private_deliberation(content, vision):
    """A reasoning-only completion is an empty answer, including image requests."""
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": content, "reasoning_content": "PRIVATE-DELIBERATION"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
        })

    provider = OpenAICompatibleProvider(base_url="https://model.invalid", model="offline", api_key="fixture")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider._client = client
        if vision:
            answer = await provider.generate_with_images("describe", images=[{"url": "data:image/png;base64,AA=="}])
        else:
            answer = await provider.generate("describe")
    assert answer == (content if isinstance(content, str) else "")
    assert "PRIVATE-DELIBERATION" not in answer
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('vision', [False, True])
async def test_stream_retries_connection_setup_once(vision):
    requests = []

    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ConnectError('controlled TLS handshake failure', request=request)
        return httpx.Response(200, content=(b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
                                             b'data: [DONE]\n\n'))

    provider = OpenAICompatibleProvider(base_url='https://model.invalid', model='offline', api_key='fixture')
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider._client = client
        output = provider.stream_parts_with_images('describe', images=[{'url': 'data:image/png;base64,AA=='}]) if vision else provider.stream_parts('describe')
        assert [part async for part in output] == [{'kind': 'content', 'text': 'ok'}]
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_stream_does_not_retry_a_model_http_error():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(503, json={'error': 'temporary model failure'})

    provider = OpenAICompatibleProvider(base_url='https://model.invalid', model='offline', api_key='fixture')
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider._client = client
        with pytest.raises(httpx.HTTPStatusError):
            assert [part async for part in provider.stream_parts('describe')]
    assert len(requests) == 1
