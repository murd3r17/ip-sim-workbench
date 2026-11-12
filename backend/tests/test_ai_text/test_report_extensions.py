"""B5：AI 报告助手扩展（巡检总结 + 配置差异说明）。

LLM 用假 provider 替身，不访问外部服务；同时验证降级路径与脱敏。
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from core.security import create_access_token
from modules.ai_text import router as ai_router
from modules.auth.models import User, UserRole
from modules.deploy.models import ConfigVersion
from modules.device.models import Device, DeviceStatus, DeviceType, DeviceVendor, Topology, TopologyType
from modules.monitor.models import MonitorJob, MonitorJobStatus, MonitorJobType, MonitorTriggerMode
from modules.system.service import SystemService


class _FakeProvider:
    """返回固定 JSON 的假 provider（走 generate_report 的结构化解析）。"""

    name = "fake"

    def __init__(self, payload: dict | None = None, fail: bool = False):
        self.payload = payload or {
            "summary": "巡检整体正常，1 台设备采集失败",
            "key_findings": ["R2 采集超时"],
            "root_causes": ["设备 VTY 占用"],
            "impact_analysis": ["指标缺一段"],
            "recommendations": ["重试采集并检查 VTY"],
            "report_text": "巡检结论：整体正常。",
        }
        self.fail = fail
        self.prompts: list[str] = []

    async def generate(self, prompt, system=None, max_tokens=None, temperature=None):
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("llm down")
        return json.dumps(self.payload, ensure_ascii=False)

    async def health_check(self):
        return not self.fail


async def _admin_token(session_factory) -> str:
    async with session_factory() as db:
        user = User(username="b5-admin", hashed_password="x", role=UserRole.ADMIN)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return create_access_token(user.id, user.username, "admin")


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _seed_job(session_factory) -> int:
    async with session_factory() as db:
        topology = Topology(name="b5-topo", topology_type=TopologyType.LAB, status="active")
        db.add(topology)
        await db.flush()
        device = Device(
            hostname="b5-dev", mgmt_ip="198.51.100.131", device_type=DeviceType.ROUTER,
            vendor=DeviceVendor.HUAWEI, status=DeviceStatus.ONLINE, topology_id=topology.id,
        )
        db.add(device)
        await db.flush()
        job = MonitorJob(
            topology_id=topology.id, job_type=MonitorJobType.INSPECTION,
            trigger_mode=MonitorTriggerMode.MANUAL, status=MonitorJobStatus.SUCCESS,
            device_count=3, success_count=2, failure_count=1,
            report_json=json.dumps({"metric_types": ["cpu_usage"], "alarm_count": 2}, ensure_ascii=False),
            summary_json=json.dumps({"note": "demo"}, ensure_ascii=False),
            started_at=datetime.now(timezone.utc).replace(tzinfo=None),
            finished_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_versions(session_factory) -> tuple[int, int]:
    async with session_factory() as db:
        author = User(username=f"b5-diff-author-{datetime.now().timestamp()}", hashed_password="x", role=UserRole.USER)
        db.add(author)
        await db.flush()
        topology = Topology(name="b5-diff-topo", topology_type=TopologyType.LAB, status="active")
        db.add(topology)
        await db.flush()
        device = Device(
            hostname="b5-diff-dev", mgmt_ip="198.51.100.132", device_type=DeviceType.ROUTER,
            vendor=DeviceVendor.HUAWEI, status=DeviceStatus.ONLINE, topology_id=topology.id,
        )
        db.add(device)
        await db.flush()
        v1 = ConfigVersion(
            device_id=device.id, version_number=1, created_by=author.id,
            config_snapshot="sysname R1\n local-user admin password cipher %SECRET%",
            change_description="baseline",
        )
        v2 = ConfigVersion(
            device_id=device.id, version_number=2, created_by=author.id,
            config_snapshot="sysname R1\n interface GE0/0/1\n  description uplink\n local-user admin password cipher %SECRET%",
            change_description="add uplink",
        )
        db.add_all([v1, v2])
        await db.commit()
        await db.refresh(v1)
        await db.refresh(v2)
        return v1.id, v2.id


class TestInspectionSummary:
    @pytest.mark.asyncio
    async def test_returns_report_and_passes_job_payload(self, client, test_session_factory, monkeypatch):
        token = await _admin_token(test_session_factory)
        job_id = await _seed_job(test_session_factory)
        provider = _FakeProvider()
        monkeypatch.setattr(SystemService, "build_llm_provider", AsyncMock(return_value=provider))

        resp = await client.post(
            "/api/v1/ai/inspection-summary", json={"job_id": job_id}, headers=_auth(token)
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["job_id"] == job_id
        assert body["summary"]
        assert body["recommendations"]
        assert "alarm_count" in provider.prompts[0]  # 报告 JSON 真的进了 prompt

    @pytest.mark.asyncio
    async def test_missing_job_returns_404(self, client, test_session_factory):
        token = await _admin_token(test_session_factory)
        resp = await client.post(
            "/api/v1/ai/inspection-summary", json={"job_id": 999999}, headers=_auth(token)
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_llm_failure_degrades_instead_of_500(self, client, test_session_factory, monkeypatch):
        """LLM 不可用时 generate_report 内部走静态模板，接口仍返回 200。"""
        token = await _admin_token(test_session_factory)
        job_id = await _seed_job(test_session_factory)

        class _FallbackStub:
            name = "stub"

            async def generate(self, prompt, system=None, max_tokens=None, temperature=None):
                return ""

            async def health_check(self):
                return False

        monkeypatch.setattr(SystemService, "build_llm_provider", AsyncMock(return_value=_FallbackStub()))
        resp = await client.post(
            "/api/v1/ai/inspection-summary", json={"job_id": job_id}, headers=_auth(token)
        )
        assert resp.status_code == 200, resp.text
        assert resp.json().get("report_text") is not None


class TestDiffExplanation:
    @pytest.mark.asyncio
    async def test_explains_diff_and_masks_secrets(self, client, test_session_factory, monkeypatch):
        token = await _admin_token(test_session_factory)
        v1, v2 = await _seed_versions(test_session_factory)
        provider = _FakeProvider({"summary": "新增了 uplink 描述", "report_text": "差异说明"})
        monkeypatch.setattr(SystemService, "build_llm_provider", AsyncMock(return_value=provider))

        resp = await client.post(
            "/api/v1/ai/diff-explanation",
            json={"version_id_a": v1, "version_id_b": v2},
            headers=_auth(token),
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["diff"]
        assert body["version_id_a"] == v1 and body["version_id_b"] == v2
        # 敏感行必须脱敏后才进 prompt
        prompt = provider.prompts[0]
        assert "%SECRET%" not in prompt
        assert "uplink" in prompt

    @pytest.mark.asyncio
    async def test_same_version_rejected(self, client, test_session_factory):
        token = await _admin_token(test_session_factory)
        v1, _ = await _seed_versions(test_session_factory)
        resp = await client.post(
            "/api/v1/ai/diff-explanation",
            json={"version_id_a": v1, "version_id_b": v1},
            headers=_auth(token),
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_identical_content_skips_llm(self, client, test_session_factory, monkeypatch):
        token = await _admin_token(test_session_factory)
        v1, _ = await _seed_versions(test_session_factory)
        async with test_session_factory() as db:
            same = ConfigVersion(
                device_id=(await db.get(ConfigVersion, v1)).device_id, version_number=9,
                created_by=(await db.get(ConfigVersion, v1)).created_by,
                config_snapshot="sysname R1\n local-user admin password cipher %SECRET%",
                change_description="same",
            )
            db.add(same)
            await db.commit()
            await db.refresh(same)
            same_id = same.id

        provider = _FakeProvider()
        monkeypatch.setattr(SystemService, "build_llm_provider", AsyncMock(return_value=provider))
        resp = await client.post(
            "/api/v1/ai/diff-explanation",
            json={"version_id_a": v1, "version_id_b": same_id},
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text
        assert "没有差异" in resp.json()["explanation"]
        assert provider.prompts == []
