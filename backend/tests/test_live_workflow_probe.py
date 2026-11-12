"""Contract tests only; no server, database or network device is contacted."""
import copy
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from scripts import verify_live_workflows as probe


def job():
    now = datetime.now(timezone.utc).isoformat()
    devices = [{"device_id": i, "status": "success", "collected_at": now,
                "metrics": [{"metric_type": kind, "value": 1} for kind in
                            ("cpu_usage", "memory_usage", "interface_up", "interface_down")]} for i in (7, 8, 9)]
    summary = {"expected": 3, "attempted": 3, "success": 3, "failed": 0, "skipped": 0,
               "errors": [], "devices": devices}
    return {"task": {"id": 55, "status": "success", "topology_id": 3, "started_at": now,
                     "finished_at": now, "device_count": 3, "success_count": 3, "failure_count": 0},
            "summary": summary,
            "report": {"job_id": 55, "topology_id": 3, "evidence_scope": "current_job",
                       "devices": devices, "summary": {"metric_points": 12}}}


def test_current_complete_three_device_monitor_evidence():
    result = probe.validate_monitor_result(job(), {7, 8, 9}, 3, inspection=True)
    assert result["ok"] and result["device_count"] == 3 and result["metric_points"] == 12


def test_mysql_datetime_second_precision_preserves_last_sample():
    result = job()
    sampled = datetime.fromisoformat(result["task"]["finished_at"])
    result["task"]["started_at"] = sampled.replace(microsecond=0).isoformat()
    result["task"]["finished_at"] = sampled.replace(microsecond=0).isoformat()
    assert probe.validate_monitor_result(result, {7, 8, 9}, 3, inspection=True)["ok"]


@pytest.mark.parametrize("mutation", ["failed", "skipped", "missing_device", "missing_metric", "historic", "wrong_job"])
def test_monitor_never_accepts_partial_or_historic_evidence(mutation):
    result = copy.deepcopy(job())
    if mutation in ("failed", "skipped"):
        result["summary"][mutation] = 1
    elif mutation == "missing_device":
        result["summary"]["devices"].pop()
    elif mutation == "missing_metric":
        result["summary"]["devices"][0]["metrics"].pop()
    elif mutation == "historic":
        result["summary"]["devices"][0]["collected_at"] = "2000-01-01T00:00:00Z"
    else:
        result["report"]["job_id"] = 99
    with pytest.raises(probe.ProbeRefused):
        probe.validate_monitor_result(result, {7, 8, 9}, 3, inspection=True)


@pytest.mark.asyncio
async def test_webssh_reads_real_version_only_and_waits_for_own_prompt():
    events = [
        {"type": "output", "data": "<R1>"}, {"type": "connected"},
        {"type": "output", "data": "screen-length 0 temporary\r\n<R1>"},
        {"type": "output", "data": "display version\r\nHuawei VRP software, Version 8.241\r\n<R1>"},
    ]
    sent = []

    class Socket:
        async def recv(self):
            return json.dumps(events.pop(0))

        async def send(self, message):
            sent.append(json.loads(message)["data"])

    result = await probe.check_webssh(Socket(), "R1")
    assert result["ok"]
    assert sent == ["screen-length 0 temporary\r", "display version\r"]


@pytest.mark.asyncio
@pytest.mark.parametrize("event", [{"type": "error", "message": "arbitrary secret"},
                                  {"type": "connected", "mode": "sim"},
                                  {"type": "output", "data": "security risks in the configuration file [y/n]"}])
async def test_terminal_errors_simulation_and_mutation_prompt_are_rejected(event):
    class Socket:
        async def recv(self):
            return json.dumps(event)

        async def send(self, message):
            pytest.fail("must not send commands to unsafe shell")

    with pytest.raises(probe.ProbeRefused):
        await probe.check_webssh(Socket(), "R1")


@pytest.mark.parametrize("url", ["http://remote.example/api/v1", "https://127.0.0.1@remote.example/api/v1",
                                "http://127.0.0.1/api/v1?token=x"])
def test_only_uncredentialed_local_api_urls(url):
    with pytest.raises(probe.ProbeRefused):
        probe.validate_api_url(url)


@pytest.mark.asyncio
async def test_runtime_mismatch_stops_before_any_business_write(monkeypatch):
    import httpx
    from core import config, database, runtime_identity

    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(device_mode="ssh"))
    monkeypatch.setattr(probe, "capture_binding", lambda settings: {"schema": 1})
    monkeypatch.setattr(database, "resolve_database_url", lambda settings: "mysql+aiomysql://u:p@127.0.0.1:13328/db")
    monkeypatch.setattr(runtime_identity, "runtime_identity", lambda settings: {"schema": 1})
    monkeypatch.setattr(runtime_identity, "same_runtime", lambda expected, actual: False)
    monkeypatch.setenv("LIVE_VERIFY_TOKEN", "in-memory-fixture")
    called = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, method, url):
            called.append((method, url))
            return SimpleNamespace(status_code=200, json=lambda: {"schema": 1})

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    args = SimpleNamespace(exclusive_window=True, expect_db_port=13328, allow_clone_evidence_writes=True,
                           base_url="http://127.0.0.1:18080/api/v1")
    with pytest.raises(probe.ProbeRefused, match="server_runtime_identity_mismatch"):
        await probe.run(args)
    assert called == [("GET", "http://127.0.0.1:18080/api/v1/system/runtime-identity")]
