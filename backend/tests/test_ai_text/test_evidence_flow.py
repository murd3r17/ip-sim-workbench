# -*- coding: utf-8 -*-
"""R3-02：真实 evidence_id → 后端回读环境/设备/时间 → 可信 page_data。"""
import json
from datetime import datetime, timezone

import pytest

from core.security import create_access_token
from modules.ai_text import router as ai_router
from modules.auth.models import User, UserRole
from modules.device.models import Device, DeviceStatus, DeviceType, DeviceVendor, Topology, TopologyType
from modules.trust.models import EnvironmentProfile, ReadOnlyObservation


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class _Capture:
    def __init__(self):
        self.page_data = None

    async def copilot_chat_stream(self, **kwargs):
        self.page_data = kwargs.get("page_data")
        yield {"type": "token", "text": "已按服务端证据回答。"}
        yield {"type": "done", "status": "ok", "trace": {"model_calls": 1, "tool_calls": 0}}


@pytest.mark.asyncio
async def test_evidence_id_is_resolved_by_backend(client, test_session_factory, monkeypatch):
    async with test_session_factory() as db:
        user = User(username="r3-evidence", hashed_password="x", role=UserRole.ADMIN)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        topo = Topology(name="r3-topo", topology_type=TopologyType.LAB, status="active")
        db.add(topo)
        await db.flush()
        dev = Device(hostname="R1", mgmt_ip="192.0.2.1", device_type=DeviceType.ROUTER,
                     vendor=DeviceVendor.HUAWEI, status=DeviceStatus.ONLINE, topology_id=topo.id)
        db.add(dev)
        await db.flush()
        env = EnvironmentProfile(name="env", version="v2", status="ready",
                                 devices=[{"device_id": dev.id}], protections=[])
        db.add(env)
        await db.flush()
        obs = ReadOnlyObservation(device_id=dev.id, environment_id=env.id, environment_version="v2",
                                  action_id="a1", command="display ip interface brief",
                                  source="sim", mode="sim", completeness="complete", status="ok",
                                  collected_at=datetime.now(timezone.utc), created_by=user.id)
        db.add(obs)
        await db.commit()
        await db.refresh(obs)
        token = create_access_token(user.id, user.username, "admin")
        obs_id = obs.id

    capture = _Capture()

    async def _fake_service(db, user):
        return capture
    monkeypatch.setattr(ai_router, "_get_service", _fake_service)

    resp = await client.post(
        "/api/v1/ai/copilot/chat",
        json={
            "message": "R1 接口现在是什么状态？",
            "history": [],
            "context": {"route": "/devices", "page_name": "设备", "selection": "R1"},
            "page_data": json.dumps({"evidence_id": obs_id, "text": "客户端旧快照"}),
            "top_k": 5,
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200
    payload = json.loads(capture.page_data)
    assert payload["evidence_id"] == obs_id
    assert payload["device"] == "R1"
    assert payload["source"] == "sim"
    assert payload["environment_version"] == "v2"


@pytest.mark.asyncio
async def test_stale_evidence_falls_back_to_untrusted_text(client, test_session_factory, monkeypatch):
    async with test_session_factory() as db:
        user = User(username="r3-stale", hashed_password="x", role=UserRole.ADMIN)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        token = create_access_token(user.id, user.username, "admin")

    capture = _Capture()

    async def _fake_service(db, user):
        return capture
    monkeypatch.setattr(ai_router, "_get_service", _fake_service)
    resp = await client.post(
        "/api/v1/ai/copilot/chat",
        json={"message": "接口状态？", "history": [], "context": {"selection": "R1"},
              "page_data": json.dumps({"evidence_id": 999999, "text": "客户端旧快照"}), "top_k": 5},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    # 回读失败：结构化包装的 text 作为不可信线索继续传递
    assert "客户端旧快照" in (capture.page_data or "")
