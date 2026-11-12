"""Probe stamps describe the same live run; tests replace all network activity."""
from types import SimpleNamespace

import pytest

from scripts import verify_live_readonly, verify_live_workflows


@pytest.mark.asyncio
@pytest.mark.parametrize("probe", [verify_live_readonly, verify_live_workflows])
@pytest.mark.parametrize("changed", [False, True])
async def test_run_binds_observations_before_and_after_probe(monkeypatch, probe, changed):
    from core import config
    from core.live_evidence import binding_unchanged

    order = []
    initial = {"schema": 1, "database_fingerprint": "database", "root_fingerprint": "root",
               "device_mode": "ssh", "deploy_simulate_only": False, "knowledge_provider": "local",
               "source_fingerprint": "before", "captured_at": "2026-10-11T00:00:00+00:00"}

    def capture(settings):
        order.append("capture")
        return {**initial, "source_fingerprint": "after" if changed and len(order) > 1 else "before"}

    async def actual_run(args, settings):
        order.append("probe_and_close")
        return {"ok": True}

    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(probe, "capture_binding", capture)
    monkeypatch.setattr(probe, "_run", actual_run)
    result = await probe.run(SimpleNamespace())
    assert order == ["capture", "probe_and_close", "capture"]
    assert result["ok"] is (not changed)
    assert result["started_at"] == result["binding"]["start"]["captured_at"]
    assert result["finished_at"] == result["binding"]["finish"]["captured_at"]
    assert binding_unchanged(**result["binding"]) is (not changed)
    if changed:
        assert result["reason"] == "runtime_or_source_changed_during_probe"


@pytest.mark.asyncio
async def test_workflow_reports_terminal_closure_and_monitor_counts(monkeypatch):
    import httpx
    import websockets.asyncio.client
    from core import database, runtime_identity
    from scripts.verify_live_readonly import ExpectedTarget
    from tests.test_live_workflow_probe import job

    targets = [ExpectedTarget(i, f"R{i}", "192.0.2.1", 2000 + i) for i in (7, 8, 9)]
    closed = []
    monkeypatch.setattr(database, "resolve_database_url", lambda _: "mysql+aiomysql://u:p@127.0.0.1:13328/db")
    monkeypatch.setattr(runtime_identity, "runtime_identity", lambda _: {"schema": 1})
    monkeypatch.setattr(runtime_identity, "same_runtime", lambda *_: True)
    monkeypatch.setenv("LIVE_VERIFY_TOKEN", "fixture-only")

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, method, url):
            if "/devices?" in url:
                value = [{"id": t.device_id, "hostname": t.hostname, "mgmt_ip": t.host,
                          "ssh_port": t.port, "status": "online"} for t in targets]
            elif "/monitor/tasks?" in url:
                value = [job()["task"]]
            elif "/monitor/" in url:
                value = job()
            else:
                value = {"schema": 1}
            return SimpleNamespace(status_code=200, json=lambda: value)

    class SocketContext:
        def __init__(self, url, **kwargs):
            self.device_id = int(url.rsplit("/", 1)[1])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            closed.append(self.device_id)

    async def check(socket, hostname):
        assert socket.device_id not in closed
        return {"ok": True}

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    monkeypatch.setattr(websockets.asyncio.client, "connect", SocketContext)
    monkeypatch.setattr(verify_live_workflows, "check_webssh", check)
    args = SimpleNamespace(exclusive_window=True, expect_db_port=13328, allow_clone_evidence_writes=True,
                           base_url="http://127.0.0.1:18080/api/v1", topology_id=3, expect=targets)
    result = await verify_live_workflows._run(args, SimpleNamespace(device_mode="ssh"))
    assert result["ok"] and closed == [7, 8, 9]
    assert [t["id"] for t in result["targets"]] == [7, 8, 9]
    assert all(step["closed"] for step in result["steps"] if step["name"] == "webssh")
    for step in result["steps"]:
        if step["name"] != "webssh":
            assert [step[key] for key in ("expected", "attempted", "success", "failed", "skipped")] == [3, 3, 3, 0, 0]
            assert step["device_ids"] == [7, 8, 9]
