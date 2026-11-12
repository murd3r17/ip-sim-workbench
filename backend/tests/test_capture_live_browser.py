"""The browser identity helper cannot silently load the developer's .env."""
import importlib.util
import json
from pathlib import Path
import uuid

import pytest


def helper():
    path = Path(__file__).resolve().parents[1] / "scripts/capture_live_browser.py"
    spec = importlib.util.spec_from_file_location("browser_capture_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_missing_explicit_clone_config_stops_before_settings_or_database(monkeypatch):
    import os
    import core.config
    monkeypatch.setattr(os, "environ", {})
    monkeypatch.setattr(core.config, "get_settings", lambda: pytest.fail("must not read developer profile"))
    with pytest.raises(ValueError, match="explicit_clone"):
        await helper().capture()


@pytest.mark.asyncio
async def test_clone_with_missing_model_config_does_not_guess_defaults(monkeypatch):
    import os
    import scripts.verify_full_stack as verifier
    monkeypatch.setattr(os, "environ", {"DB_BACKEND": "mysql", "DEVICE_MODE": "ssh",
        "KNOWLEDGE_PROVIDER": "anythingllm", "DEPLOY_SIMULATE_ONLY": "false", "DB_URL": "mysql+aiomysql://fixture.invalid/db"})
    monkeypatch.setattr(verifier, "db_facts", lambda _: pytest.fail("incomplete binding must not read DB"))
    with pytest.raises(ValueError, match="explicit_model"):
        await helper().capture()


@pytest.mark.asyncio
async def test_capture_returns_only_binding_effective_model_and_explicit_three_targets(monkeypatch):
    import os
    import scripts.verify_full_stack as verifier
    secret = uuid.uuid4().hex
    config = {"DB_BACKEND": "mysql", "DEVICE_MODE": "ssh", "KNOWLEDGE_PROVIDER": "anythingllm", "DEPLOY_SIMULATE_ONLY": "false",
              "DB_HOST": "db.example.invalid", "DB_PORT": "3306", "DB_NAME": "isolated", "DB_USER": "fixture", "DB_PASSWORD": secret,
              "LLM_PROVIDER": "openai_compatible", "LLM_BASE_URL": "https://api.deepseek.com/v1", "LLM_MODEL": "text-fixture", "LLM_VISION_MODEL": "vision-fixture",
              "WORKBENCH_EXPECTED_ENDPOINTS": "192.0.2.1:22,192.0.2.2:22,192.0.2.3:22"}
    monkeypatch.setattr(os, "environ", config)
    monkeypatch.setattr(verifier, "capture_run_binding", lambda settings: {"database_fingerprint": "bound", "source_fingerprint": "source"})
    async def facts(settings):
        assert settings.db_password == secret and settings.db_name == "isolated"
        assert settings.llm_model == "text-fixture" and settings.llm_vision_model == "vision-fixture"
        return {"devices": [{"id": n, "hostname": "node-" + str(n), "mgmt_ip": "192.0.2." + str(n), "ssh_port": 22} for n in range(1, 5)],
                "llm": {"provider": "openai_compatible", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"}, "max_ai_log_id": 5}
    monkeypatch.setattr(verifier, "db_facts", facts)
    result = await helper().capture()
    assert len(result["targets"]) == 3 and result["max_ai_log_id"] == 5
    assert result["vision"]["model"] == "vision-fixture"
    assert secret not in json.dumps(result)
