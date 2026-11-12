"""Authenticated capability is safe and disabled until a vision model is set."""
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from core.dependencies import get_current_user
from modules.ai_text.router import router


@pytest.mark.asyncio
@pytest.mark.parametrize("model,mimes,enabled,allowed", [
    ("", "image/png", False, []),
    ("  ", "image/png", False, []),
    ("receiver-vision", "image/png,image/jpeg,text/html", True, ["image/jpeg", "image/png"]),
    ("receiver-vision", "", False, []),
])
async def test_capability_uses_actual_model_and_mime_configuration(monkeypatch, model, mimes, enabled, allowed):
    config = SimpleNamespace(llm_vision_model=model, llm_vision_mime_whitelist=mimes)
    monkeypatch.setattr("modules.ai_text.router.get_settings", lambda: config)
    monkeypatch.setattr("core.config.get_settings", lambda: config)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 2, "role": "user"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/ai/capabilities")
    assert response.status_code == 200
    assert response.json() == {"vision_enabled": enabled, "image_mime_types": allowed}


@pytest.mark.asyncio
async def test_capability_requires_authentication():
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/ai/capabilities")
    assert response.status_code == 401
