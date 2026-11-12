from pathlib import Path
from types import SimpleNamespace

from core.runtime_identity import runtime_identity, same_runtime


def settings(**overrides):
    values = dict(db_url="mysql+aiomysql://operator:example_password@127.0.0.1:13328/live",
                  device_mode="ssh", deploy_simulate_only=True, knowledge_provider="anythingllm")
    values.update(overrides)
    return SimpleNamespace(**values)


def test_runtime_binding_rejects_different_database_root_or_mode():
    expected = runtime_identity(settings(), root=Path("/source"))
    assert same_runtime(expected, runtime_identity(settings(), root=Path("/source")))
    for actual in [runtime_identity(settings(db_url="mysql+aiomysql://operator:example_password@127.0.0.1:13307/live"), root=Path("/source")),
                   runtime_identity(settings(), root=Path("/other")),
                   runtime_identity(settings(device_mode="sim"), root=Path("/source"))]:
        assert not same_runtime(expected, actual)
    assert not same_runtime(expected, {})


def test_identity_omits_secrets_and_password_does_not_change_identity():
    expected = runtime_identity(settings(), root=Path("/source"))
    rotated = runtime_identity(settings(db_url="mysql+aiomysql://operator:rotated_placeholder@127.0.0.1:13328/live"), root=Path("/source"))
    assert same_runtime(expected, rotated)
    assert "example_password" not in str(expected)
    assert "operator" not in str(expected)
