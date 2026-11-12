"""启动配置预检测试（A-15）。"""
from types import SimpleNamespace

from core.preflight import check_startup_config


def _settings(**overrides):
    base = dict(
        db_backend="mysql",
        db_url="",
        db_password="secret",
        jwt_secret_key="x" * 48,
        fernet_key="key",
        llm_api_key="sk-test",
        knowledge_provider="anythingllm",
        knowledge_api_key="kb-key",
        device_mode="ssh",
        device_default_username="admin",
        device_default_password="pwd",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _keys(result) -> set[str]:
    return {issue.key for issue in result.issues}


class TestPreflight:
    def test_fully_configured_has_no_issues(self):
        result = check_startup_config(_settings())
        assert result.issues == []
        assert result.summary() == "配置检查通过"

    def test_missing_db_password_is_fatal(self):
        result = check_startup_config(_settings(db_password=""))
        assert "DB_PASSWORD" in _keys(result)
        assert result.fatal

    def test_missing_jwt_is_fatal(self):
        result = check_startup_config(_settings(jwt_secret_key=""))
        assert "JWT_SECRET_KEY" in _keys(result)
        assert result.fatal

    def test_short_jwt_is_warning_only(self):
        result = check_startup_config(_settings(jwt_secret_key="short"))
        assert not result.fatal
        assert "JWT_SECRET_KEY" in _keys(result)

    def test_missing_llm_key_is_warning(self):
        result = check_startup_config(_settings(llm_api_key=""))
        assert not result.fatal
        assert "LLM_API_KEY" in _keys(result)

    def test_anythingllm_without_key_warns(self):
        result = check_startup_config(_settings(knowledge_api_key=""))
        assert "KNOWLEDGE_API_KEY" in _keys(result)

    def test_ssh_mode_without_device_credentials_warns(self):
        result = check_startup_config(_settings(device_default_username="", device_default_password=""))
        assert "DEVICE_DEFAULT_USERNAME/PASSWORD" in _keys(result)

    def test_sqlite_minimal_mode_is_info_not_fatal(self):
        result = check_startup_config(_settings(
            db_backend="sqlite",
            db_password="",
            knowledge_provider="local",
            knowledge_api_key="",
            device_mode="sim",
            device_default_username="",
            device_default_password="",
            llm_api_key="",
        ))
        assert not result.fatal, result.summary()
        keys = _keys(result)
        assert "DB_BACKEND" in keys and "KNOWLEDGE_PROVIDER" in keys and "DEVICE_MODE" in keys
