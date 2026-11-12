"""Local, non-secret build/runtime stamps for live acceptance producers.

Capture immediately before and after the actual probe. Never add these stamps
to an older report: a hash binds observations only when captured during its run.
"""
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path


def capture_binding(settings=None, *, root: Path | None = None) -> dict:
    from core.runtime_identity import runtime_identity

    root = (root or Path(__file__).resolve().parents[2]).resolve()
    spec = importlib.util.spec_from_file_location("_live_delivery_fingerprint", root / "scripts/delivery.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("delivery_fingerprint_unavailable")
    delivery = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(delivery)
    return {**runtime_identity(settings, root=root),
            "source_fingerprint": delivery.code_fingerprint(delivery.manifest(root)),
            "captured_at": datetime.now(timezone.utc).isoformat()}


def binding_unchanged(start: dict, finish: dict) -> bool:
    keys = ("schema", "database_fingerprint", "root_fingerprint", "device_mode",
            "deploy_simulate_only", "knowledge_provider", "source_fingerprint")
    return all(key in start and key in finish and start[key] == finish[key] for key in keys)
