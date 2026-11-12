from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_v60_defaults_to_anythingllm() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "KNOWLEDGE_PROVIDER=anythingllm" in env_example
    assert "KNOWLEDGE_BASE_URL=http://127.0.0.1:3001" in env_example
    assert "KNOWLEDGE_WORKSPACE_SLUG=ip-ops-kb" in env_example
    assert "KNOWLEDGE_API_KEY=" in env_example
    from core.config import Settings
    assert Settings.model_fields["knowledge_provider"].default == "anythingllm"
    assert Settings.model_fields["db_port"].default == 13307
