"""Non-secret identity binding for local startup and live verification."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from sqlalchemy.engine import make_url


def runtime_identity(settings=None, *, root: Path | None = None) -> dict:
    from core.config import get_settings
    from core.database import resolve_database_url

    settings = settings or get_settings()
    url = make_url(resolve_database_url(settings))
    database = {"driver": url.drivername, "host": url.host, "port": url.port,
                "name": url.database, "user": url.username}
    # Password rotation must not change the identity of the database itself.
    database_hash = hashlib.sha256(json.dumps(database, sort_keys=True).encode()).hexdigest()
    root = (root or Path(__file__).resolve().parents[2]).resolve()
    root_hash = hashlib.sha256(os.path.normcase(str(root)).encode()).hexdigest()
    return {"schema": 1, "database_fingerprint": database_hash, "root_fingerprint": root_hash,
            "device_mode": settings.device_mode, "deploy_simulate_only": settings.deploy_simulate_only,
            "knowledge_provider": settings.knowledge_provider, "pid": os.getpid(),
            "parent_pid": os.getppid(), "launch_id": os.environ.get("WORKBENCH_LAUNCH_ID", "")}


def same_runtime(expected: dict, actual: dict) -> bool:
    keys = ("schema", "database_fingerprint", "root_fingerprint", "device_mode",
            "deploy_simulate_only", "knowledge_provider")
    return all(key in actual and actual[key] == expected[key] for key in keys)
