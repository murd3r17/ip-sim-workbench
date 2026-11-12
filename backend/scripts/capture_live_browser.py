"""Capture browser acceptance bindings using explicit process config only."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


async def capture() -> dict:
    # Never fall back to a developer profile when the caller omitted its clone.
    required = {"DB_BACKEND", "DEVICE_MODE", "KNOWLEDGE_PROVIDER", "DEPLOY_SIMULATE_ONLY"}
    required |= {"DB_URL"} if os.environ.get("DB_URL") else {"DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"}
    if any(not os.environ.get(key) for key in required):
        raise ValueError("explicit_clone_process_configuration_required")
    # Empty vision is a meaningful disabled state, but an omitted key could
    # silently turn a real deployed capability into a default in this subprocess.
    if any(not os.environ.get(key) for key in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL")) or "LLM_VISION_MODEL" not in os.environ:
        raise ValueError("explicit_model_process_configuration_required")
    from core.config import Settings
    Settings.model_config["env_file"] = None
    settings = Settings(_env_file=None)
    from scripts.verify_full_stack import capture_run_binding, db_facts, selected_devices
    binding = capture_run_binding(settings)
    facts = await db_facts(settings)
    endpoints = os.environ.get("LIVE_EXPECTED_ENDPOINTS") or os.environ.get("WORKBENCH_EXPECTED_ENDPOINTS", "")
    targets = selected_devices(endpoints, facts["devices"])
    return {"binding": binding, "llm": facts["llm"], "vision": {"model": settings.llm_vision_model.strip()}, "max_ai_log_id": facts["max_ai_log_id"],
            "targets": [{key: row[key] for key in ("id", "hostname", "mgmt_ip", "ssh_port")} for row in targets]}


if __name__ == "__main__":
    try:
        print(json.dumps({"ok": True, **asyncio.run(capture())}, ensure_ascii=True))
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__}))
        raise SystemExit(1)
