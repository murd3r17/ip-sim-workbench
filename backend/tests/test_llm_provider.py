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
