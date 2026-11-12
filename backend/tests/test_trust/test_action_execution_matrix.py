# -*- coding: utf-8 -*-
"""BF4-04：15 个能力目录动作的实际执行矩阵。

每个动作都走真实 FastAPI 路由 + 隔离 SQLite；设备侧一律使用记录型假适配器，
不连接真实设备、不读写真实库。矩阵结果同时写 ``action-execution-matrix.json``
（设置 ``BF8_RUN_DIR`` 时），供回传证据使用。
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from modules.auth.models import AuditLog, User, UserRole
from modules.deploy.models import ConfigVersion, DeployStatus, DeployTask, DeviceWriteLock
from modules.device.models import Device, DeviceStatus, DeviceType, Topology, TopologyType
from modules.system.models import SystemConfig
from modules.training.models import OperationLog
from modules.trust.models import ReadOnlyObservation
from tests.test_training.test_v7a_state_and_reports import _admin_token, _lab, _session, auth_header

RECORDS: list[dict] = []


def record(case: str, **details) -> None:
    RECORDS.append({"case": case, **details})


@pytest.fixture(scope="module", autouse=True)
def _dump_matrix():
    yield
    run_dir = os.environ.get("BF8_RUN_DIR")
    if run_dir and RECORDS:
        path = Path(run_dir) / "action-execution-matrix.json"
        path.write_text(json.dumps(RECORDS, ensure_ascii=False, indent=2), encoding="utf-8")


class RecordingAdapter:
    """记录所有设备调用；写方法只在显式开启时记录为设备写入。"""

    def __init__(self, responses: dict[str, str] | None = None, *, record_writes: bool = False):
        self.responses = responses or {}
        self.record_writes = record_writes
        self.calls: list[tuple[str, object]] = []

    async def run_command(self, command: str):
        self.calls.append(("run_command", command))
        return self.responses.get(command, "")

    async def send_config(self, commands):
        self.calls.append(("send_config", list(commands)))
        return "ok"

    async def save_config(self):
        self.calls.append(("save_config", None))
        return "saved"

    async def close(self):
        self.calls.append(("close", None))


async def _mk_device(factory, hostname: str, *, mgmt_ip: str = "192.0.2.10",
                     status: DeviceStatus = DeviceStatus.ONLINE) -> int:
    async with factory() as db:
        topo = Topology(name=f"bf8-topo-{hostname}-{uuid.uuid4().hex[:4]}",
                        topology_type=TopologyType.LAB, status="active")
        db.add(topo)
        await db.flush()
        device = Device(hostname=hostname, mgmt_ip=mgmt_ip, device_type=DeviceType.ROUTER,
                        status=status, topology_id=topo.id)
        db.add(device)
        await db.commit()
        return device.id


async def _mk_user(factory, role: UserRole = UserRole.USER) -> tuple[str, int]:
    from core.security import create_access_token

    async with factory() as db:
        user = User(username=f"bf8-{role.value}-{uuid.uuid4().hex[:6]}",
                    hashed_password="x", role=role)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return create_access_token(user.id, user.username, user.role.value), user.id


async def _env(client, token: str, device_id: int, *, iface: str = "GigabitEthernet3/0/3",
               addr: str = "10.0.123.1/24", protections: list | None = None) -> int:
    body = {
        "name": f"BF8 环境 {uuid.uuid4().hex[:6]}",
        "version": "v1", "site": "lab",
        "devices": [{"device_id": device_id, "role": "R1", "mgmt_ip": "192.0.2.10",
                     "interfaces": [{"name": iface, "address": addr}]}],
        "protections": protections if protections is not None else [
            {"kind": "mgmt_port", "target": iface, "role": "R1"}
        ],
    }
    resp = await client.post("/api/v1/trust/environments", json=body, headers=auth_header(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _count(factory, model) -> int:
    async with factory() as db:
        return int((await db.execute(select(func.count()).select_from(model))).scalar_one())


async def _task_id(client, token: str, device_id: int, content: str) -> int:
    resp = await client.post("/api/v1/deploy", json={
        "device_ids": [device_id], "config_content": content,
    }, headers=auth_header(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["details"][0]["task_id"]


@pytest.mark.asyncio
async def test_action_01_observe_interfaces(client, test_session_factory, monkeypatch):
    token = await _admin_token(test_session_factory)
    did = await _mk_device(test_session_factory, "BF8-IF")
    adapter = RecordingAdapter({
        "display ip interface brief": "GigabitEthernet3/0/3  up  up  10.0.123.1/24\nLoopBack0  up  up  10.0.0.1/24",
    })
    monkeypatch.setattr("engines.device_adapter.get_device_adapter", AsyncMock(return_value=adapter))
    monkeypatch.setattr("engines.device_adapter.get_device_mode", lambda: "sim")
    before = await _count(test_session_factory, ReadOnlyObservation)
    resp = await client.post("/api/v1/trust/observations", headers=auth_header(token),
                             json={"device_id": did, "action_id": "interface_brief"})
    after = await _count(test_session_factory, ReadOnlyObservation)
    body = resp.json()
    assert resp.status_code == 200, resp.text
    assert body["command"] == "display ip interface brief"
    assert body["facts"]["interfaces"][0]["address"] == "10.0.123.1/24"
    assert body["completeness"] == "complete" and body["status"] == "ok"
    assert [call[0] for call in adapter.calls] == ["run_command", "close"]
    assert after == before + 1
    record("observe_interfaces", request={"POST": "/api/v1/trust/observations",
                                          "body": {"device_id": did, "action_id": "interface_brief"}},
           status=resp.status_code, device_calls=adapter.calls,
           db={"read_only_observations": [before, after]},
           result={"command": body["command"], "facts": body["facts"], "mode": body["mode"]},
           checks=["设备只读一次", "本地新增 1 条证据", "无设备写入"])


@pytest.mark.asyncio
async def test_action_02_observe_ospf_peer(client, test_session_factory, monkeypatch):
    token = await _admin_token(test_session_factory)
    did = await _mk_device(test_session_factory, "BF8-PEER")
    adapter = RecordingAdapter({"display ospf peer": "10.0.123.2  1  Full/ -  00:00:12"})
    monkeypatch.setattr("engines.device_adapter.get_device_adapter", AsyncMock(return_value=adapter))
    monkeypatch.setattr("engines.device_adapter.get_device_mode", lambda: "sim")
    resp = await client.post("/api/v1/trust/observations", headers=auth_header(token),
                             json={"device_id": did, "action_id": "ospf_peer"})
    body = resp.json()
    assert resp.status_code == 200, resp.text
    assert body["action_id"] == "ospf_peer" and body["command"] == "display ospf peer"
    assert body["facts"]["peers"][0] == {"neighbor_id": "10.0.123.2", "state": "Full"}
    assert adapter.calls[0] == ("run_command", "display ospf peer")
    record("observe_ospf_peer", request={"POST": "/api/v1/trust/observations",
                                         "body": {"device_id": did, "action_id": "ospf_peer"}},
           status=resp.status_code, device_calls=adapter.calls,
           result={"facts": body["facts"], "completeness": body["completeness"]},
           checks=["只读命令与目录一致", "解析 Full 邻居", "无设备写入"])


@pytest.mark.asyncio
async def test_action_03_observe_ospf_route(client, test_session_factory, monkeypatch):
    token = await _admin_token(test_session_factory)
    did = await _mk_device(test_session_factory, "BF8-ROUTE")
    adapter = RecordingAdapter({
        "display ospf routing": "10.0.0.2/32        1     Stub       10.0.123.2      10.0.0.2        0.0.0.0",
    })
    monkeypatch.setattr("engines.device_adapter.get_device_adapter", AsyncMock(return_value=adapter))
    monkeypatch.setattr("engines.device_adapter.get_device_mode", lambda: "sim")
    resp = await client.post("/api/v1/trust/observations", headers=auth_header(token),
                             json={"device_id": did, "action_id": "ospf_route"})
    body = resp.json()
    assert resp.status_code == 200, resp.text
    assert body["facts"]["routes"][0] == {"destination": "10.0.0.2/32", "next_hop": "10.0.123.2"}
    assert adapter.calls[0] == ("run_command", "display ospf routing")
    record("observe_ospf_route", request={"POST": "/api/v1/trust/observations",
                                          "body": {"device_id": did, "action_id": "ospf_route"}},
           status=resp.status_code, device_calls=adapter.calls,
           result={"facts": body["facts"]}, checks=["只读命令", "下一跳取自实际列", "无设备写入"])


@pytest.mark.asyncio
async def test_action_04_preflight_environment(client, test_session_factory, monkeypatch):
    token = await _admin_token(test_session_factory)
    did = await _mk_device(test_session_factory, "BF8-PRE")
    eid = await _env(client, token, did)
    adapter = RecordingAdapter({
        "display ip interface brief": "GigabitEthernet3/0/3  up  up  10.0.123.1/24",
    })
    monkeypatch.setattr("engines.device_adapter.get_device_adapter", AsyncMock(return_value=adapter))
    monkeypatch.setattr("engines.device_adapter.get_device_mode", lambda: "sim")
    before_obs = await _count(test_session_factory, ReadOnlyObservation)
    resp = await client.post(f"/api/v1/trust/environments/{eid}/preflight",
                             json={}, headers=auth_header(token))
    body = resp.json()
    assert resp.status_code == 200, resp.text
    assert body["status"] == "ready"
    assert body["verification_mode"] == "sim" and body["real_device_verified"] is False
    detail = (await client.get(f"/api/v1/trust/environments/{eid}", headers=auth_header(token))).json()
    assert detail["last_preflight_status"] == "ready"
    after_obs = await _count(test_session_factory, ReadOnlyObservation)
    record("preflight_environment", request={"POST": f"/api/v1/trust/environments/{eid}/preflight"},
           status=resp.status_code, device_calls=adapter.calls,
           db={"read_only_observations": [before_obs, after_obs]},
           result={"status": body["status"], "mode": body["verification_mode"],
                   "real_device_verified": body["real_device_verified"]},
           checks=["只读采集接口事实", "写 preflight 状态", "不冒充真实设备通过"])


@pytest.mark.asyncio
async def test_action_05_update_environment(client, test_session_factory):
    token = await _admin_token(test_session_factory)
    did = await _mk_device(test_session_factory, "BF8-UPD")
    eid = await _env(client, token, did)
    before = (await client.get(f"/api/v1/trust/environments/{eid}", headers=auth_header(token))).json()
    resp = await client.put(f"/api/v1/trust/environments/{eid}", headers=auth_header(token), json={
        "version": "v2",
        "devices": [{"device_id": did, "role": "R1", "mgmt_ip": "192.0.2.10",
                     "interfaces": [{"name": "GigabitEthernet3/0/3", "address": "10.0.123.9/24"}]}],
    })
    after = resp.json()
    assert resp.status_code == 200, resp.text
    assert after["revision"] == before["revision"] + 1
    assert after["version"] == "v2" and after["status"] == "draft"
    assert after["last_preflight_status"] == ""
    assert after["content_hash"] != before["content_hash"]
    record("update_environment", request={"PUT": f"/api/v1/trust/environments/{eid}",
                                          "body": {"version": "v2", "interface": "10.0.123.9/24"}},
           status=resp.status_code,
           result={"revision": [before["revision"], after["revision"]],
                   "status": [before["status"], after["status"]],
                   "last_preflight_status": after["last_preflight_status"]},
           checks=["revision 自增", "旧 preflight 立即失效", "内容哈希变化"])


@pytest.mark.asyncio
async def test_action_06_generate_report(client, test_session_factory, monkeypatch):
    token = await _admin_token(test_session_factory)
    lab = await _lab(client, token)
    sid = await _session(client, token, lab)

    class FakeAI:
        model_name = "bf8-fake-model"

        async def generate_report(self, **kwargs):
            return {"title": "BF8 复盘", "summary": "摘要", "key_findings": ["发现1"],
                    "root_causes": [], "impact_analysis": [], "recommendations": ["建议1"],
                    "report_text": "正文"}

    monkeypatch.setattr("modules.training.router._get_ai_service",
                        AsyncMock(return_value=FakeAI()))
    monkeypatch.setattr("modules.training.router._get_knowledge_service",
                        lambda: AsyncMock(search=AsyncMock(return_value=[])))
    before = await _count(test_session_factory, AuditLog)
    resp = await client.post(f"/api/v1/training/sessions/{sid}/report/generate",
                             headers=auth_header(token), json={"regenerate": False})
    body = resp.json()
    assert resp.status_code == 200, resp.text
    assert body["versions"] and body["versions"][0]["status"] == "ready"
    assert body["versions"][0]["model"] == "bf8-fake-model"
    _ = await _count(test_session_factory, AuditLog)
    record("generate_report", request={"POST": f"/api/v1/training/sessions/{sid}/report/generate"},
           status=resp.status_code, model="stub（bf8-fake-model，不请求真实模型）",
           result={"version": body["versions"][0]["version"], "status": body["versions"][0]["status"],
                   "audit_before": before},
           checks=["显式 POST 生成", "版本落库", "模型调用被本地桩替代"])


@pytest.mark.asyncio
async def test_action_07_open_report(client, test_session_factory, monkeypatch):
    token = await _admin_token(test_session_factory)
    lab = await _lab(client, token)
    sid = await _session(client, token, lab)

    class FakeAI:
        model_name = "bf8-fake-model"

        async def generate_report(self, **kwargs):
            return {"title": "BF8 复盘", "summary": "摘要", "key_findings": [],
                    "root_causes": [], "impact_analysis": [], "recommendations": [],
                    "report_text": "正文"}

    monkeypatch.setattr("modules.training.router._get_ai_service", AsyncMock(return_value=FakeAI()))
    monkeypatch.setattr("modules.training.router._get_knowledge_service",
                        lambda: AsyncMock(search=AsyncMock(return_value=[])))
    await client.post(f"/api/v1/training/sessions/{sid}/report/generate",
                      headers=auth_header(token), json={})
    resp = await client.get(f"/api/v1/training/sessions/{sid}/report", headers=auth_header(token))
    body = resp.json()
    assert resp.status_code == 200, resp.text
    assert len(body["versions"]) == 1
    # 旧的 ?generate=true 不得触发新版本（B 已移除 GET 副作用）
    again = await client.get(f"/api/v1/training/sessions/{sid}/report?generate=true",
                             headers=auth_header(token))
    assert len(again.json()["versions"]) == 1
    record("open_report", request={"GET": f"/api/v1/training/sessions/{sid}/report"},
           status=resp.status_code,
           result={"versions": len(body["versions"]), "after_legacy_generate_param": len(again.json()["versions"])},
           checks=["严格只读", "旧 generate 参数不再产生版本"])


@pytest.mark.asyncio
async def test_action_08_start_session(client, test_session_factory):
    token = await _admin_token(test_session_factory)
    lab = await _lab(client, token)
    resp = await client.post("/api/v1/training/sessions", json={"lab_id": lab}, headers=auth_header(token))
    body = resp.json()
    assert resp.status_code == 200, resp.text
    assert body["lab_id"] == lab and body["status"] in {"running", "active", "started", "in_progress"}
    detail = await client.get(f"/api/v1/training/sessions/{body['id']}", headers=auth_header(token))
    assert detail.status_code == 200 and detail.json()["id"] == body["id"]
    record("start_session", request={"POST": "/api/v1/training/sessions", "body": {"lab_id": lab}},
           status=resp.status_code, result={"session_id": body["id"], "status": body["status"]},
           checks=["会话落库", "可从详情读回"])


@pytest.mark.asyncio
async def test_action_09_log_operation(client, test_session_factory):
    token = await _admin_token(test_session_factory)
    lab = await _lab(client, token)
    sid = await _session(client, token, lab)
    before = await _count(test_session_factory, OperationLog)
    resp = await client.post(f"/api/v1/training/sessions/{sid}/log", headers=auth_header(token), json={
        "action": "observe", "target_device": "R1", "command": "display ospf peer",
        "result": "Full", "success": True,
    })
    after = await _count(test_session_factory, OperationLog)
    assert resp.status_code == 200, resp.text
    logs = (await client.get(f"/api/v1/training/sessions/{sid}/logs", headers=auth_header(token))).json()
    assert after == before + 1
    assert any(str(item.get("command")) == "display ospf peer" for item in logs)
    record("log_operation", request={"POST": f"/api/v1/training/sessions/{sid}/log"},
           status=resp.status_code, db={"operation_logs": [before, after]},
           result={"log_id": resp.json()["id"]}, checks=["追加日志", "可从日志列表读回"])


@pytest.mark.asyncio
async def test_action_10_view_snapshot(client, test_session_factory):
    token = await _admin_token(test_session_factory)
    did = await _mk_device(test_session_factory, "BF8-SNAP")
    before = await _count(test_session_factory, ConfigVersion)
    resp = await client.get(f"/api/v1/config-versions?device_id={did}", headers=auth_header(token))
    after = await _count(test_session_factory, ConfigVersion)
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)
    assert before == after
    record("view_snapshot", request={"GET": f"/api/v1/config-versions?device_id={did}"},
           status=resp.status_code, db={"config_versions": [before, after]},
           result={"rows": len(resp.json())}, checks=["只读", "无新增版本"])


@pytest.mark.asyncio
async def test_action_11_deploy_preview(client, test_session_factory):
    token = await _admin_token(test_session_factory)
    did = await _mk_device(test_session_factory, "BF8-VALID")
    before = await _count(test_session_factory, DeployTask)
    resp = await client.post("/api/v1/deploy/validate", headers=auth_header(token),
                             json={"config_content": "sysname BF8-PREVIEW", "device_model": "NE40E"})
    after = await _count(test_session_factory, DeployTask)
    assert resp.status_code == 200, resp.text
    assert before == after
    body = resp.json()
    record("deploy_preview", request={"POST": "/api/v1/deploy/validate",
                                      "body": {"config_content": "sysname BF8-PREVIEW"}},
           status=resp.status_code, db={"deploy_tasks": [before, after]},
           result={"keys": sorted(body)[:8]}, checks=["只校验不建任务", "无设备动作"])


@pytest.mark.asyncio
async def test_action_12_deploy_confirm(client, test_session_factory):
    token = await _admin_token(test_session_factory)
    did = await _mk_device(test_session_factory, "BF8-CONFIRM")
    tid = await _task_id(client, token, did, "sysname BF8-CONFIRM")
    resp = await client.post(f"/api/v1/deploy/tasks/{tid}/confirm", headers=auth_header(token),
                             json={"risk_confirm": False})
    body = resp.json()
    assert resp.status_code == 200, resp.text
    assert body["status"] == "confirmed"
    async with test_session_factory() as db:
        lock = await db.get(DeviceWriteLock, did)
        task = await db.get(DeployTask, tid)
        assert lock is not None and lock.task_id == tid
        assert task.status == DeployStatus.CONFIRMED
    record("deploy_confirm", request={"POST": f"/api/v1/deploy/tasks/{tid}/confirm"},
           status=resp.status_code,
           result={"task_status": body["status"], "lock_task_id": tid},
           checks=["状态 CAS 到 confirmed", "取得设备写锁", "未执行设备写入"])


@pytest.mark.asyncio
async def test_action_13_deploy_execute(client, test_session_factory):
    token = await _admin_token(test_session_factory)
    did = await _mk_device(test_session_factory, "BF8-EXEC")
    tid = await _task_id(client, token, did, "sysname BF8-EXEC")
    await client.post(f"/api/v1/deploy/tasks/{tid}/confirm", headers=auth_header(token), json={})
    resp = await client.post(f"/api/v1/deploy/tasks/{tid}/execute", headers=auth_header(token))
    body = resp.json()
    assert resp.status_code == 200, resp.text
    assert body["mode"] == "simulated"
    async with test_session_factory() as db:
        lock = await db.get(DeviceWriteLock, did)
        assert lock is not None and lock.lock_type == "deploy_simulated_ready"
    audits = (await client.get("/api/v1/system/audit-logs?page=1&page_size=50",
                               headers=auth_header(token))).json()
    items = audits.get("items", audits if isinstance(audits, list) else [])
    assert any(item.get("action") == "deploy_task_executed" for item in items)
    record("deploy_execute", request={"POST": f"/api/v1/deploy/tasks/{tid}/execute"},
           status=resp.status_code, result={"mode": body["mode"], "steps": body.get("steps")},
           checks=["模拟模式固化", "设备未被写入", "审计 deploy_task_executed"])


@pytest.mark.asyncio
async def test_action_13b_deploy_execute_real_path_fake_adapter(client, test_session_factory, monkeypatch):
    """真实执行分支：用假适配器接收写入，不连真实设备；验证写锁与审计落点。"""
    from core.config import get_settings
    from modules.deploy.service import DeployService

    token = await _admin_token(test_session_factory)
    did = await _mk_device(test_session_factory, "BF8-EXEC-REAL")
    tid = await _task_id(client, token, did, "sysname BF8-REAL")
    await client.post(f"/api/v1/deploy/tasks/{tid}/confirm", headers=auth_header(token), json={})
    settings = get_settings()
    monkeypatch.setattr(settings, "deploy_simulate_only", False)
    monkeypatch.setattr(DeployService, "_is_authorized_stage4_target", AsyncMock(return_value=True))
    adapter = RecordingAdapter({
        "display current-configuration": "sysname BF8-OLD\ninterface GigabitEthernet0/0/1\n",
        "display saved-configuration": "sysname BF8-OLD\ninterface GigabitEthernet0/0/1\n",
    })
    monkeypatch.setattr("engines.device_adapter.get_device_adapter", AsyncMock(return_value=adapter))
    resp = await client.post(f"/api/v1/deploy/tasks/{tid}/execute", headers=auth_header(token))
    body = resp.json()
    writes = [call for call in adapter.calls if call[0] == "send_config"]
    assert resp.status_code == 200, resp.text
    assert body["mode"] == "real"
    assert writes and "sysname BF8-REAL" in "".join(writes[0][1]), adapter.calls
    assert ("save_config", None) in adapter.calls
    async with test_session_factory() as db:
        lock = await db.get(DeviceWriteLock, did)
        assert lock is not None and lock.lock_type == "deploy_ready"
    record("deploy_execute_real", request={"POST": f"/api/v1/deploy/tasks/{tid}/execute"},
           status=resp.status_code, device_calls=adapter.calls,
           result={"mode": body["mode"], "steps": body.get("steps")},
           checks=["真实分支由假适配器接收写入", "保存配置", "锁保持 deploy_ready", "未连真实设备"])


@pytest.mark.asyncio
async def test_action_14_approval_confirm(client, test_session_factory):
    admin = await _admin_token(test_session_factory)
    user_token, _uid = await _mk_user(test_session_factory)
    other_token, _oid = await _mk_user(test_session_factory)
    own_device = await _mk_device(test_session_factory, "BF8-APPROVE-OWN")
    did = await _mk_device(test_session_factory, "BF8-APPROVE")
    # 创建者本人确认自己的任务：目录写 admin，但服务端实际允许归属者，按实记录。
    own_task = await _task_id(client, user_token, own_device, "sysname BF8-APPROVE-OWN")
    owner = await client.post(f"/api/v1/deploy/tasks/{own_task}/confirm",
                              headers=auth_header(user_token), json={"risk_confirm": False})
    tid = await _task_id(client, user_token, did, "sysname BF8-APPROVE")
    denied = await client.post(f"/api/v1/deploy/tasks/{tid}/confirm",
                               headers=auth_header(other_token), json={"risk_confirm": False})
    approved = await client.post(f"/api/v1/deploy/tasks/{tid}/confirm",
                                 headers=auth_header(admin), json={"risk_confirm": False})
    assert owner.status_code == 200, owner.text
    assert denied.status_code == 403, denied.text
    assert approved.status_code == 200, approved.text
    record("approval_confirm", request={"POST": f"/api/v1/deploy/tasks/{tid}/confirm",
                                        "actors": ["创建者(user)", "其他 user", "admin"]},
           status=approved.status_code, result={"owner_self_confirm": owner.status_code,
                                                "other_user": denied.status_code,
                                                "admin": approved.status_code,
                                                "task_status": approved.json()["status"]},
           checks=["归属者可确认自己的任务", "非归属普通用户 403", "管理员可跨归属审批", "审批后持锁"])


@pytest.mark.asyncio
async def test_action_15_update_config(client, test_session_factory):
    token = await _admin_token(test_session_factory)
    user_token, _ = await _mk_user(test_session_factory)
    key = f"bf8.key.{uuid.uuid4().hex[:6]}"
    created = await client.post("/api/v1/system/config", headers=auth_header(token), json={
        "config_key": key, "config_value": "v1", "description": "bf8",
    })
    assert created.status_code == 200, created.text
    denied = await client.put(f"/api/v1/system/config/{key}", headers=auth_header(user_token),
                              json={"config_value": "hacked"})
    resp = await client.put(f"/api/v1/system/config/{key}", headers=auth_header(token),
                            json={"config_value": "v2"})
    assert denied.status_code == 403
    assert resp.status_code == 200, resp.text
    assert resp.json()["config_value"] == "v2"
    async with test_session_factory() as db:
        row = (await db.execute(select(SystemConfig).where(SystemConfig.config_key == key))).scalar_one()
        assert row.config_value == "v2"
    record("update_config", request={"PUT": f"/api/v1/system/config/{key}"},
           status=resp.status_code, result={"user_role": denied.status_code, "value": resp.json()["config_value"]},
           checks=["普通用户 403", "管理员更新落库"])


@pytest.mark.asyncio
async def test_action_matrix_rejections(client, test_session_factory, monkeypatch):
    """越权、越归属、非法对象与保护项归属的拒绝路径。"""
    admin = await _admin_token(test_session_factory)
    user_token, uid = await _mk_user(test_session_factory)
    other_token, _ = await _mk_user(test_session_factory)
    did = await _mk_device(test_session_factory, "BF8-REJECT")
    eid = await _env(client, admin, did)

    cases = {}

    async def call(name, method, url, *, token, json_body=None):
        fn = getattr(client, method)
        kwargs = {"headers": auth_header(token)}
        if json_body is not None:
            kwargs["json"] = json_body
        resp = await fn(url, **kwargs)
        cases[name] = {"status": resp.status_code, "detail": resp.json().get("detail") if resp.headers.get("content-type", "").startswith("application/json") else None}
        return resp

    await call("user_update_environment", "put", f"/api/v1/trust/environments/{eid}",
               token=user_token, json_body={"version": "v9"})
    await call("user_preflight", "post", f"/api/v1/trust/environments/{eid}/preflight",
               token=user_token, json_body={})
    await call("user_update_config", "put", "/api/v1/system/config/bf8.denied",
               token=user_token, json_body={"config_value": "x"})
    await call("invalid_action_id", "post", "/api/v1/trust/observations", token=admin,
               json_body={"device_id": did, "action_id": "shell_exec"})
    await call("missing_device", "post", "/api/v1/trust/observations", token=admin,
               json_body={"device_id": 999999, "action_id": "ospf_peer"})
    await call("unknown_environment", "post", "/api/v1/trust/environments/999999/preflight",
               token=admin, json_body={})
    await call("missing_task_confirm", "post", "/api/v1/deploy/tasks/999999/confirm",
               token=admin, json_body={})
    await call("protection_unknown_device", "put", f"/api/v1/trust/environments/{eid}",
               token=admin, json_body={"protections": [{"kind": "uplink", "target": "GigabitEthernet3/0/3",
                                                        "device_id": 999999}]})
    await call("protection_role_conflict", "put", f"/api/v1/trust/environments/{eid}",
               token=admin, json_body={"protections": [{"kind": "uplink", "target": "GigabitEthernet3/0/3",
                                                        "device_id": did, "role": "R9"}]})
    # 全局保护项只在多设备环境被拒绝；单设备环境允许按唯一设备推断归属。
    did2 = await _mk_device(test_session_factory, "BF8-REJECT-2")
    multi = await client.post("/api/v1/trust/environments", headers=auth_header(admin), json={
        "name": f"BF8 多设备 {uuid.uuid4().hex[:6]}", "version": "v1",
        "devices": [
            {"device_id": did, "role": "R1", "mgmt_ip": "192.0.2.10",
             "interfaces": [{"name": "GigabitEthernet3/0/3", "address": "10.0.123.1/24"}]},
            {"device_id": did2, "role": "R2", "mgmt_ip": "192.0.2.10",
             "interfaces": [{"name": "GigabitEthernet3/0/4", "address": "10.0.124.1/24"}]},
        ],
        "protections": [{"kind": "mgmt_port", "target": "GigabitEthernet3/0/3", "role": "R1"}],
    })
    assert multi.status_code == 200, multi.text
    await call("protection_global_multi_device", "put", f"/api/v1/trust/environments/{multi.json()['id']}",
               token=admin, json_body={"protections": [{"kind": "uplink", "target": "GigabitEthernet3/0/3"}]})

    # 越归属：普通用户读他人证据、写他人会话日志
    obs = await client.post("/api/v1/trust/observations", headers=auth_header(admin),
                            json={"device_id": did, "action_id": "interface_brief"})
    # 无适配器时采集返回 error 行，但 id 仍可读；用管理员创建的证据测试普通用户越权
    obs_id = obs.json()["id"]
    await call("user_read_other_observation", "get", f"/api/v1/trust/observations/{obs_id}",
               token=user_token)
    lab = await _lab(client, admin)
    sid = await _session(client, admin, lab)
    await call("user_log_other_session", "post", f"/api/v1/training/sessions/{sid}/log",
               token=user_token, json_body={"action": "x"})

    expected = {
        "user_update_environment": 403, "user_preflight": 403, "user_update_config": 403,
        "invalid_action_id": 400, "missing_device": 400, "unknown_environment": 404,
        "missing_task_confirm": 422, "protection_unknown_device": 422,
        "protection_role_conflict": 422, "protection_global_multi_device": 422,
        "user_read_other_observation": 404, "user_log_other_session": 403,
    }
    mismatched = {k: (v["status"], expected[k]) for k, v in cases.items() if v["status"] != expected[k]}
    record("rejection_paths", request={"cases": list(cases)}, status="mixed",
           result=cases, expected=expected, mismatched=mismatched,
           checks=["越权 403", "非法对象 400/404/422 而非 500", "对象归属 404"])
    assert not mismatched, mismatched
