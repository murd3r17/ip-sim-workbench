"""Saved system settings must reach request payloads and transport timeouts."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.config import Settings
from core import llm_provider as lp
from modules.system.models import SystemConfig
from modules.system.service import SystemService


@pytest.fixture
def configured(monkeypatch):
    settings = Settings(_env_file=None, llm_base_url="https://model.example/v1", llm_model="example-model",
                        llm_max_tokens=16000, llm_temperature=0.4, llm_timeout=99, llm_thinking_enabled=False)
    monkeypatch.setattr(lp, "get_settings", lambda: settings)
    monkeypatch.setattr("modules.system.service.get_settings", lambda: settings)
    monkeypatch.setattr("core.shared_http.get_managed_client", lambda **kwargs: SimpleNamespace(**kwargs))
    return settings


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", ["openai_compatible", "ollama"])
@pytest.mark.parametrize("fallback", [False, True])
async def test_db_parameters_apply_to_primary_and_fallback(configured, mock_db, provider_name, fallback):
    values = {"llm.provider": provider_name, "llm.max_tokens": "4500", "llm.temperature": "0",
              "llm.timeout": "37", "llm.fallback_model": "backup-model" if fallback else ""}
    rows = [SystemConfig(config_key=key, config_value=value) for key, value in values.items()]
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    mock_db.execute.return_value = result
    provider = await SystemService.build_llm_provider(mock_db)
    active = [provider.primary.primary, provider.primary.secondary] if fallback else [provider.primary]
    for current in active:
        payload = current._build_payload("probe", None, None, None, False)
        parameters = payload["options"] if provider_name == "ollama" else payload
        assert parameters["num_predict" if provider_name == "ollama" else "max_tokens"] == 4500
        assert parameters["temperature"] == 0.0
        assert current._client.timeout == 37.0
        overridden = current._build_payload("probe", None, 17, 0.6, False)
        per_request = overridden["options"] if provider_name == "ollama" else overridden
        assert per_request["num_predict" if provider_name == "ollama" else "max_tokens"] == 17
        assert per_request["temperature"] == 0.6


@pytest.mark.parametrize("provider_name", ["openai_compatible", "ollama"])
def test_empty_overrides_keep_environment_defaults(configured, provider_name):
    current = lp.create_llm_provider({"llm_provider": provider_name, "llm_max_tokens": None,
                                      "llm_temperature": "", "llm_timeout": None}).primary
    assert current.default_max_tokens == 16000
    assert current.default_temperature == 0.4
    assert current._client.timeout == 99.0


def test_strict_live_probe_uses_same_effective_parameters(configured):
    from scripts.verify_live_ai import build_primary

    primary = build_primary({"llm_base_url": "https://api.deepseek.com/v1", "llm_model": "deepseek-chat",
                             "llm_api_key": "test-placeholder", "llm_max_tokens": 4500,
                             "llm_temperature": 0, "llm_timeout": 37})
    assert primary.default_max_tokens == 4500
    assert primary.default_temperature == 0
    assert primary._client.timeout == 37.0
