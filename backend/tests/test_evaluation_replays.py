"""Exercise fixtures through collection and server evidence read-back, not prose."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from engines.device_lock import DeviceBusyError
from modules.ai_text.agent_tools import execute_tool
from modules.ai_text.tool_result import classify
from modules.ai_text.trusted_context import load_verified_evidence
from modules.auth.models import User, UserRole
from modules.device.models import Device, DeviceType, Topology, TopologyType
from modules.trust.models import EnvironmentProfile
from modules.trust.service import collect_observation

DATA = json.loads((Path(__file__).parent / "fixtures/evaluation/device_scenarios.json").read_text(encoding="utf-8"))


def test_ospf_detail_context_does_not_leak_across_area_or_mix_dr():
    from modules.trust.service import parse_ospf_peer
    output = ("OSPF Process 1 with Router ID 10.0.0.1\n"
              "Router ID: 10.0.0.2 Address: 10.0.12.2\nState: Full\nDR: 10.0.12.1\n"
              "Router ID: 10.0.0.3 Address: 10.0.13.3\nState: Init\n"
              "Router ID: 10.0.0.4 Address: 10.0.14.4\nArea 0.0.0.1\nState: Full\n")
    assert parse_ospf_peer(output) == {"peers": [
        {"neighbor_id": "10.0.0.2", "state": "Full"}, {"neighbor_id": "10.0.0.3", "state": "Init"}]}


async def seed(db, name):
    account = User(username=f"c2-{name}", hashed_password="not-a-login-hash", role=UserRole.ADMIN)
    topology = Topology(name=f"c2-{name}", topology_type=TopologyType.LAB)
    db.add(topology)
    await db.flush()
    device = Device(hostname="R1", mgmt_ip="192.0.2.1", device_type=DeviceType.ROUTER,
                    topology_id=topology.id)
    db.add_all([account, device])
    await db.flush()
    env = EnvironmentProfile(name=f"c2-{name}", version="v1", status="ready",
                             devices=[{"device_id": device.id}], protections=[])
    db.add(env)
    await db.commit()
    return account, device, env


@pytest.mark.asyncio
@pytest.mark.parametrize("case", DATA["scenarios"], ids=lambda c: c["id"])
async def test_collect_exact_command_fixture(case, test_session_factory, monkeypatch):
    adapter = AsyncMock()
    if "exception" in case:
        adapter.run_command.side_effect = TimeoutError("fixture timeout")
    else:
        adapter.run_command.return_value = case["output"]
    monkeypatch.setattr("engines.device_adapter.get_device_adapter", AsyncMock(return_value=adapter))
    monkeypatch.setattr("engines.device_adapter.get_device_mode", lambda: "sim")
    async with test_session_factory() as db:
        user, device, env = await seed(db, case["id"])
        row = await collect_observation(db, user={"user_id": user.id}, device_id=device.id,
                                        action_id=case["action"], environment_id=env.id)
        adapter.run_command.assert_awaited_once_with(case["command"])
        adapter.close.assert_awaited_once()
        assert row.status == case["expected_status"]
        assert row.completeness == case["expected_completeness"]
        facts = row.facts.get(case["fact_key"], [])
        assert len(facts) == case["count"]
        if "reported_peer_counts" in case:
            assert row.facts.get("reported_peer_counts", []) == case["reported_peer_counts"]
        if "state" in case:
            assert facts[0]["state"] == case["state"]
        if "neighbor" in case:
            assert facts[0]["neighbor_id"] == case["neighbor"]
        if "absent_destination" in case:
            assert case["absent_destination"] not in {f["destination"] for f in facts}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", DATA["trust_replays"], ids=lambda c: c["id"])
async def test_server_readback_positive_stale_and_wrong_object(case, test_session_factory, monkeypatch):
    adapter = AsyncMock()
    adapter.run_command.return_value = DATA["scenarios"][0]["output"]
    monkeypatch.setattr("engines.device_adapter.get_device_adapter", AsyncMock(return_value=adapter))
    monkeypatch.setattr("engines.device_adapter.get_device_mode", lambda: "sim")
    async with test_session_factory() as db:
        user, device, env = await seed(db, case["id"])
        actor = {"user_id": user.id, "role": "admin"}
        row = await collect_observation(db, user=actor, device_id=device.id, action_id="interface_brief", environment_id=env.id)
        now = datetime.now(timezone.utc)
        row.collected_at = now - timedelta(seconds=case["age_seconds"])
        await db.commit()
        result = await load_verified_evidence(db, row.id, user=actor, selection=case["selection"], now=now)
        assert result.trusted is case["trusted"]
        if "reason" in case:
            assert case["reason"] in result.meta["reasons"]
        assert json.loads(result.text)["evidence_id"] == row.id


@pytest.mark.asyncio
@pytest.mark.parametrize("case", DATA["tool_replays"], ids=lambda c: c["id"])
async def test_tool_denied_busy_timeout(case, test_session_factory, monkeypatch):
    adapter = AsyncMock()
    errors = {"DeviceBusyError": DeviceBusyError("fixture busy"), "TimeoutError": TimeoutError("fixture timeout")}
    if "exception" in case:
        adapter.run_command.side_effect = errors[case["exception"]]
    factory = AsyncMock(return_value=adapter)
    monkeypatch.setattr("engines.device_adapter.get_device_adapter", factory)
    async with test_session_factory() as db:
        user, device, _ = await seed(db, case["id"])
        user.role = UserRole(case["role"])
        await db.commit()
        args = {"device_id": device.id, "command": "display ospf peer"} if case["tool"] == "run_display_command" else {}
        raw = await execute_tool(db, case["tool"], args, user_id=user.id)
        assert classify(case["tool"], args, raw).status == case["expected_status"]
        if case["id"] == "denied":
            factory.assert_not_awaited()
        else:
            adapter.close.assert_awaited_once()
