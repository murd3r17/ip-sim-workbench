"""Observation reuse must match user, device, time and optional environment."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from modules.ai_text.router import _resolve_page_data
from modules.ai_text.schemas import CopilotChatRequest
from modules.ai_text.trusted_context import load_verified_evidence
from modules.trust.models import ReadOnlyObservation
from tests.test_evaluation_replays import seed


@pytest.mark.asyncio
@pytest.mark.parametrize("case,reason", [
    ("unbound", None), ("bound", None), ("partial", None),
    ("wrong_owner", "not_found_or_forbidden"), ("no_owner", "not_found_or_forbidden"),
    ("wrong_id", "device_mismatch"), ("wrong_name", "device_mismatch"),
    ("future", "future_timestamp"), ("stale", "stale"), ("error", "collection_error"),
    ("version", "environment_version_drift"), ("revision", "environment_revision_drift"),
    ("hash", "environment_content_drift"), ("not_ready", "environment_not_ready"),
    ("missing_membership", "device_not_in_environment"),
])
async def test_server_observation_scope(client, test_session_factory, case, reason):
    # client owns per-case cleanup of the shared test database, including the
    # environment records this test creates. Never leak them to later tests.
    async with test_session_factory() as db:
        user, device, env = await seed(db, "c5-" + case)
        env.content_hash = "current-hash"
        now = datetime.now(timezone.utc)
        row = ReadOnlyObservation(device_id=device.id, action_id="interface_brief",
            command="display ip interface brief", source="server_observed", mode="sim",
            adapter_mode="sim", completeness="complete", status="ok", created_by=user.id,
            collected_at=now, facts={"interfaces": [{"name": "GE0/0/1", "state": "up"}]},
            environment_id=None if case == "unbound" else env.id,
            environment_version=None if case == "unbound" else env.version,
            environment_snapshot=None if case == "unbound" else {"revision": env.revision, "content_hash": env.content_hash})
        selection = f"device | R1 | 192.0.2.1 | id={device.id}"
        actor = {"user_id": user.id, "role": "user"}
        if case == "wrong_owner": actor["user_id"] += 1000
        if case == "no_owner": row.created_by = None
        if case == "wrong_id": selection = f"device | R1 | 192.0.2.1 | id={device.id + 1}"
        if case == "wrong_name": selection = f"device | R10 | 192.0.2.1 | id={device.id}"
        if case == "future": row.collected_at = now + timedelta(hours=1)
        if case == "stale": row.collected_at = now - timedelta(hours=2)
        if case == "error": row.status = "error"  # even if parser retained partial facts
        if case == "partial": row.completeness = "partial"; row.status = "partial"
        if case == "version": env.version = "changed"
        if case == "revision": env.revision += 1
        if case == "hash": env.content_hash = "changed"
        if case == "not_ready": env.status = "draft"
        if case == "missing_membership": env.devices = []
        db.add(row)
        await db.commit()
        result = await load_verified_evidence(db, row.id, user=actor, selection=selection, now=now)
        if reason == "not_found_or_forbidden":
            assert result is None
        elif reason:
            assert not result.trusted and reason in result.meta["reasons"]
        else:
            assert result.trusted
            payload = json.loads(result.text)
            assert payload["device_id"] == device.id and payload["evidence_id"] == row.id
            assert payload["environment_binding"] == ("unbound" if case == "unbound" else "verified")
            assert payload["completeness"] == row.completeness
        # Router must retain the real rejection reason instead of replacing it
        # with 'unparsed' from the harmless browser snapshot wrapper.
        if case in {"wrong_id", "version", "unbound"}:
            resolved = await _resolve_page_data(db, CopilotChatRequest(message="核对接口证据",
                context={"selection": selection, "route": "/devices"},
                page_data=json.dumps({"evidence_id": row.id, "text": "browser snapshot"})), actor)
            assert resolved.trusted is (reason is None)
            if reason: assert reason in resolved.meta["reasons"]
