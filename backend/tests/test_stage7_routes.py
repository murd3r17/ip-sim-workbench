"""阶段7路由冒烟测试。"""
import pytest
from unittest.mock import AsyncMock, patch
from core.security import hash_password, create_access_token


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _setup_admin_user(session_factory):
    from modules.auth.models import User, UserRole
    from sqlalchemy import select

    async with session_factory() as db:
        result = await db.execute(select(User).where(User.username == "admin"))
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                username="admin",
                hashed_password=hash_password("admin123"),
                display_name="系统管理员",
                role=UserRole.ADMIN,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        return create_access_token(user.id, user.username, user.role.value)


class TestStage7Routes:
    @pytest.mark.asyncio
    async def test_training_hint_and_report_routes(self, client, test_session_factory):
        token = await _setup_admin_user(test_session_factory)
        topo = await client.post("/api/v1/topologies", json={"name": "阶段7拓扑"}, headers=auth_header(token))
        assert topo.status_code == 200
        topo_id = topo.json()["id"]

        device = await client.post(
            "/api/v1/devices",
            json={
                "hostname": "Stage7R1",
                "mgmt_ip": "10.10.10.10",
                "device_type": "router",
                "topology_id": topo_id,
            },
            headers=auth_header(token),
        )
        assert device.status_code == 200

        lab = await client.post(
            "/api/v1/training/labs",
            json={"title": "阶段7训练", "topology_id": topo_id, "objectives": ["恢复接口"]},
            headers=auth_header(token),
        )
        assert lab.status_code == 200
        lab_id = lab.json()["id"]

        await client.put(f"/api/v1/training/labs/{lab_id}", json={"status": "ready"}, headers=auth_header(token))
        session = await client.post("/api/v1/training/sessions", json={"lab_id": lab_id}, headers=auth_header(token))
        assert session.status_code == 200
        session_id = session.json()["id"]

        fake_ai = AsyncMock()
        fake_ai.coach_training = AsyncMock(return_value={
            "summary": "summary",
            "next_steps": ["step-1"],
            "corrections": ["fix-1"],
            "explanations": ["explain-1"],
            "risk_notes": ["risk-1"],
            "coach_text": "coach",
        })
        fake_ai.generate_report = AsyncMock(return_value={
            "title": "report title",
            "summary": "report summary",
            "key_findings": ["finding"],
            "root_causes": ["cause"],
            "impact_analysis": ["impact"],
            "recommendations": ["recommendation"],
            "report_text": "report text",
        })
        fake_knowledge = AsyncMock()
        fake_knowledge.search = AsyncMock(return_value=[{"text": "snippet", "title": "doc-a"}])
        with patch("modules.training.router._get_ai_service", return_value=fake_ai), patch("modules.training.router._get_knowledge_service", return_value=fake_knowledge):
            hint = await client.get(f"/api/v1/training/sessions/{session_id}/hint", headers=auth_header(token))
            assert hint.status_code == 200
            hint_data = hint.json()
            assert hint_data["session_id"] == session_id
            # AF-03：普通实验没有核验绑定，提示必须安全降级而不是把配置步骤交给模型
            assert hint_data["config_blocked"] is True
            assert hint_data["environment_status"] in ("unverified", "unknown")
            assert any("display ospf peer" in step for step in hint_data["next_steps"])
            assert "system-view" not in hint_data["coach_text"]
            assert fake_ai.coach_training.await_count == 0

            generated = await client.post(
                f"/api/v1/training/sessions/{session_id}/report/generate",
                json={"regenerate": False},
                headers=auth_header(token),
            )
            assert generated.status_code == 200
            envelope = generated.json()
            assert envelope["status"] == "ready"
            report_data = envelope["report"]
            # 读取不再调用模型：同参数再 GET 一次，模型调用数不增加
            calls_after_generate = fake_ai.generate_report.await_count
            stored = await client.get(f"/api/v1/training/sessions/{session_id}/report", headers=auth_header(token))
            assert stored.status_code == 200
            assert fake_ai.generate_report.await_count == calls_after_generate
            assert stored.json()["report"]["version"] == report_data["version"]

            fake_ai.generate_report.side_effect = RuntimeError("offline simulated model failure")
            failed = await client.post(
                f"/api/v1/training/sessions/{session_id}/report/generate",
                json={"regenerate": True},
                headers=auth_header(token),
            )
            assert failed.status_code == 502
            preserved = await client.get(f"/api/v1/training/sessions/{session_id}/report", headers=auth_header(token))
            assert preserved.status_code == 200
            preserved_data = preserved.json()
            assert preserved_data["report"]["version"] == report_data["version"]
            assert preserved_data["report"]["report_text"] == report_data["report_text"]
            assert preserved_data["last_failure"]["version"] == report_data["version"] + 1
        assert report_data["report_text"]
        assert len(report_data["sources"]) == 1
        source = report_data['sources'][0]
        assert source['content'] == 'snippet' and source['filename'] == 'doc-a'
        assert source['prompt_text'] in fake_ai.generate_report.call_args.kwargs['source_text']
        assert stored.json()['report']['sources'] == report_data['sources']
        assert "未验证" in fake_ai.generate_report.call_args.kwargs["source_text"]

    @pytest.mark.asyncio
    async def test_report_generation_survives_knowledge_search_failure(self, client, test_session_factory):
        token = await _setup_admin_user(test_session_factory)
        topo = await client.post("/api/v1/topologies", json={"name": "降级拓扑"}, headers=auth_header(token))
        topo_id = topo.json()["id"]
        lab = await client.post(
            "/api/v1/training/labs",
            json={"title": "降级训练", "topology_id": topo_id, "objectives": ["恢复接口"]},
            headers=auth_header(token),
        )
        lab_id = lab.json()["id"]
        await client.put(f"/api/v1/training/labs/{lab_id}", json={"status": "ready"}, headers=auth_header(token))
        session = await client.post("/api/v1/training/sessions", json={"lab_id": lab_id}, headers=auth_header(token))
        session_id = session.json()["id"]

        fake_knowledge = AsyncMock()
        fake_knowledge.search = AsyncMock(side_effect=RuntimeError("kb down"))
        fake_ai = AsyncMock()
        fake_ai.generate_report = AsyncMock(return_value={"title": "t", "summary": "s", "report_text": "body"})
        with patch("modules.training.router._get_knowledge_service", return_value=fake_knowledge), patch(
            "modules.training.router._get_ai_service", return_value=fake_ai
        ):
            resp = await client.post(
                f"/api/v1/training/sessions/{session_id}/report/generate",
                json={},
                headers=auth_header(token),
            )
        assert resp.status_code == 200
        data = resp.json()
        # 知识库不可用不阻断复盘生成，但必须如实显示“没有引用”
        assert data["report"]["report_text"] == "body"
        assert data["report"]["sources"] == []

    @pytest.mark.asyncio
    async def test_sandbox_fault_uses_real_device_id(self, client, test_session_factory):
        token = await _setup_admin_user(test_session_factory)
        topo = await client.post("/api/v1/topologies", json={"name": "沙箱设备拓扑"}, headers=auth_header(token))
        topo_id = topo.json()["id"]
        device = await client.post(
            "/api/v1/devices",
            json={"hostname": "SandboxR1", "mgmt_ip": "10.20.30.40", "device_type": "router", "topology_id": topo_id},
            headers=auth_header(token),
        )
        device_id = device.json()["id"]
        lab = await client.post(
            "/api/v1/training/labs",
            json={"title": "沙箱设备Lab", "topology_id": topo_id, "is_sandbox": True},
            headers=auth_header(token),
        )
        lab_id = lab.json()["id"]
        await client.put(f"/api/v1/training/labs/{lab_id}", json={"status": "ready"}, headers=auth_header(token))
        started = await client.post(
            "/api/v1/training/sandbox/start",
            json={"lab_id": lab_id, "fault_types": ["interface_shutdown"]},
            headers=auth_header(token),
        )
        assert started.status_code == 200
        session_id = started.json()["id"]
        faults = await client.get(f"/api/v1/training/sessions/{session_id}/faults", headers=auth_header(token))
        assert faults.status_code == 200
        rows = faults.json()
        assert rows
        assert rows[0]["device_id"] == device_id
        # 故障必须挂在真实设备上，而不是拓扑 id（两者是不同表的主键，
        # 此前的 `!= topo_id` 在 id 恰好不等时恒真、清理数据后又会误报）
        devices = await client.get(f"/api/v1/devices?topology_id={topo_id}", headers=auth_header(token))
        assert device_id in {item["id"] for item in devices.json()}

    @pytest.mark.asyncio
    async def test_sandbox_without_devices_returns_400(self, client, test_session_factory):
        token = await _setup_admin_user(test_session_factory)
        topo = await client.post("/api/v1/topologies", json={"name": "空沙箱拓扑"}, headers=auth_header(token))
        topo_id = topo.json()["id"]
        lab = await client.post(
            "/api/v1/training/labs",
            json={"title": "空沙箱Lab", "topology_id": topo_id, "is_sandbox": True},
            headers=auth_header(token),
        )
        lab_id = lab.json()["id"]
        await client.put(f"/api/v1/training/labs/{lab_id}", json={"status": "ready"}, headers=auth_header(token))
        started = await client.post(
            "/api/v1/training/sandbox/start",
            json={"lab_id": lab_id, "fault_types": ["interface_shutdown"]},
            headers=auth_header(token),
        )
        assert started.status_code == 400

    @pytest.mark.asyncio
    async def test_inject_returns_applied_false(self, client, test_session_factory):
        token = await _setup_admin_user(test_session_factory)
        topo = await client.post("/api/v1/topologies", json={"name": "注入拓扑"}, headers=auth_header(token))
        topo_id = topo.json()["id"]
        device = await client.post(
            "/api/v1/devices",
            json={"hostname": "InjectR1", "mgmt_ip": "10.20.30.41", "device_type": "router", "topology_id": topo_id},
            headers=auth_header(token),
        )
        device_id = device.json()["id"]
        lab = await client.post(
            "/api/v1/training/labs",
            json={"title": "注入Lab", "topology_id": topo_id},
            headers=auth_header(token),
        )
        lab_id = lab.json()["id"]
        await client.put(f"/api/v1/training/labs/{lab_id}", json={"status": "ready"}, headers=auth_header(token))
        session = await client.post("/api/v1/training/sessions", json={"lab_id": lab_id}, headers=auth_header(token))
        session_id = session.json()["id"]
        resp = await client.post(
            f"/api/v1/training/sessions/{session_id}/inject",
            json={"fault_scenario": [{"device_id": device_id, "fault_type": "interface_shutdown"}]},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["applied"] is False
        assert body["injected"] == 1

    @pytest.mark.asyncio
    async def test_legacy_ai_stream_route_removed(self, client, test_session_factory):
        """P2-05：该路径从未接任务队列，永久 501 的假接口已删除（不再是 404 之外的承诺）。"""
        token = await _setup_admin_user(test_session_factory)
        resp = await client.get("/api/v1/ai/stream/abc-123", headers=auth_header(token))
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_knowledge_health_route(self, client, test_session_factory):
        token = await _setup_admin_user(test_session_factory)
        fake_knowledge = AsyncMock()
        fake_knowledge.health_check = AsyncMock(return_value={
            "available": True,
            "provider": "anythingllm",
            "workspace_slug": "ip-ops-kb",
        })
        with patch("modules.ai_text.router._get_knowledge_service", return_value=fake_knowledge):
            resp = await client.get("/api/v1/ai/knowledge/health", headers=auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert "available" in data
        assert "provider" in data

    @pytest.mark.asyncio
    async def test_knowledge_search_failure_is_503_not_empty_list(self, client, test_session_factory):
        token = await _setup_admin_user(test_session_factory)
        fake_knowledge = AsyncMock()
        fake_knowledge.search = AsyncMock(side_effect=RuntimeError("kb down"))
        with patch("modules.ai_text.router._get_knowledge_service", return_value=fake_knowledge):
            resp = await client.post(
                "/api/v1/ai/knowledge/search",
                json={"question": "OSPF"},
                headers=auth_header(token),
            )
        assert resp.status_code == 503
        assert resp.json() != []
