"""评分语义回归（2026-10-05 审计：未注入故障仍白送 30% 权重、中途评分用时白送 100 分）。

规则：
- 没有注入故障 → 故障项不适用，其权重按比例分给"操作"与"用时"，而不是按 100 分计入；
- 会话未结束时评分 → 用"开始到现在"计算用时，而不是 None → 100 分；
- 评分即结束会话（status=completed、time_spent_seconds 冻结）。
"""

import asyncio
from datetime import datetime, timedelta, timezone
import uuid

import pytest

from modules.training.models import FaultInjection, FaultType, TrainingLab, TrainingSession
from modules.training.service import TrainingService


async def _session(db, *, started_minutes_ago: int | None, command_log=None, status: str = "in_progress"):
    from modules.auth.models import User, UserRole
    from modules.device.models import Device, DeviceStatus, DeviceType, DeviceVendor, Topology, TopologyType

    # 每个用例独立命名，避免同一测试库内 username 唯一约束冲突
    suffix = uuid.uuid4().hex[:8]
    instructor = User(username=f"score-instructor-{suffix}", hashed_password="x", role=UserRole.ADMIN)
    db.add(instructor)
    await db.flush()
    topology = Topology(name=f"评分语义拓扑-{suffix}", topology_type=TopologyType.LAB, status="active")
    db.add(topology)
    await db.flush()
    device = Device(
        hostname=f"score-dev-{suffix}", mgmt_ip="198.51.100.240", device_type=DeviceType.ROUTER,
        vendor=DeviceVendor.HUAWEI, status=DeviceStatus.ONLINE, topology_id=topology.id,
    )
    db.add(device)
    await db.flush()
    lab = TrainingLab(
        title=f"评分语义实验-{suffix}", objectives=[], time_limit_minutes=60,
        topology_id=topology.id, instructor_id=instructor.id,
    )
    db.add(lab)
    await db.flush()
    now = datetime.now(timezone.utc)
    session = TrainingSession(
        lab_id=lab.id,
        trainee_id=instructor.id,
        status=status,
        # command_log 是客户端上报 JSON Lines，仅计算复盘参考指标。
        command_log=command_log if command_log is not None else (
            '{"command": "display ip interface brief", "success": true}\n'
            '{"command": "ping -c 1 10.0.123.2", "success": true}'
        ),
        started_at=(now - timedelta(minutes=started_minutes_ago)) if started_minutes_ago is not None else None,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    session.device_id = device.id  # 供故障注入用
    return session


class TestFaultWeightWhenNoFaultInjected:
    @pytest.mark.asyncio
    async def test_no_fault_means_fault_item_not_scored(self, test_session_factory):
        async with test_session_factory() as db:
            session = await _session(db, started_minutes_ago=10)

            result = await TrainingService.score_session(db, session.id)

            detail = result["detail"]
            assert detail["fault_applicable"] is False
            assert detail["fault_score"] is None
            # 权重重新分配：故障项 0，操作+用时合计 1
            assert detail["weights"]["fault"] == 0
            assert abs(detail["weights"]["operation"] + detail["weights"]["time"] - 1.0) < 0.01
            assert "未注入故障" in detail["note"]

    @pytest.mark.asyncio
    async def test_with_faults_fault_weight_is_used(self, test_session_factory):
        async with test_session_factory() as db:
            session = await _session(db, started_minutes_ago=10)
            db.add(FaultInjection(
                session_id=session.id, device_id=session.device_id, fault_type=FaultType.INTERFACE_SHUTDOWN,
                resolved_correctly=True,
            ))
            await db.commit()

            result = await TrainingService.score_session(db, session.id)

            detail = result["detail"]
            assert detail["fault_applicable"] is True
            assert detail["fault_score"] == 100.0
            assert detail["weights"]["fault"] > 0


class TestTimeScoreWhenSessionNotFinished:
    @pytest.mark.asyncio
    async def test_midway_score_uses_elapsed_time_not_free_full_marks(self, test_session_factory):
        """会话未结束（time_spent_seconds 为 None）时，用真实已用时长计算，不能直接给 100。"""
        async with test_session_factory() as db:
            # 限时 60 分钟，已用 55 分钟 → 用时效率应明显低于 100
            session = await _session(db, started_minutes_ago=55)
            assert session.time_spent_seconds is None

            result = await TrainingService.score_session(db, session.id)

            detail = result["detail"]
            assert detail["time_score"] < 100, detail
            refreshed = await db.get(TrainingSession, session.id)
            assert refreshed.time_spent_seconds is not None
            assert refreshed.time_spent_seconds >= 54 * 60


class TestUnverifiedEvidenceAndFinalization:
    @pytest.mark.asyncio
    async def test_client_claims_do_not_prove_skill_completion(self, test_session_factory):
        async with test_session_factory() as db:
            session = await _session(db, started_minutes_ago=1, command_log="")
            log = await TrainingService.log_operation(
                db, session.id, session.lab_id, "command", command="unexecuted claim",
                success=True, meta={"source": "server", "evidence_trust": "verified"},
            )
            result = await TrainingService.score_session(db, session.id)
            assert result["score"] is None
            assert result["passed"] is None
            assert result["detail"]["verification_status"] == "unverified"
            assert log.meta["evidence_trust"] == "client_reported"

    @pytest.mark.asyncio
    async def test_score_is_idempotent_and_keeps_original_completion_time(self, test_session_factory):
        async with test_session_factory() as db:
            session = await _session(db, started_minutes_ago=1)
            first = await TrainingService.score_session(db, session.id)
            completed_at, duration = session.completed_at, session.time_spent_seconds
            lab = await db.get(TrainingLab, session.lab_id)
            lab.scoring_rules = {"pass_threshold": 101}
            await db.commit()
            second = await TrainingService.score_session(db, session.id)
            assert second == first
            assert session.completed_at.replace(tzinfo=None) == completed_at.replace(tzinfo=None)
            assert session.time_spent_seconds == duration

    @pytest.mark.asyncio
    @pytest.mark.parametrize("finish", ["score_session", "complete_session"])
    async def test_completed_session_rejects_all_evidence_mutations(self, test_session_factory, finish):
        async with test_session_factory() as db:
            session = await _session(db, started_minutes_ago=1)
            fault = FaultInjection(
                session_id=session.id, device_id=session.device_id,
                fault_type=FaultType.INTERFACE_SHUTDOWN,
            )
            db.add(fault)
            await db.commit()
            await getattr(TrainingService, finish)(db, session.id)
            for mutation in (
                lambda: TrainingService.log_operation(db, session.id, session.lab_id, "command", command="late"),
                lambda: TrainingService.resolve_fault(db, fault.id, True),
                lambda: TrainingService.inject_faults(db, session.id, [{"device_id": session.device_id, "fault_type": "interface_shutdown"}]),
            ):
                with pytest.raises(ValueError, match="会话不在进行中"):
                    await mutation()

    @pytest.mark.asyncio
    async def test_scoring_after_manual_completion_does_not_reopen_or_invent_result(self, test_session_factory):
        async with test_session_factory() as db:
            session = await _session(db, started_minutes_ago=1)
            await TrainingService.complete_session(db, session.id)
            completed_at = session.completed_at
            result = await TrainingService.score_session(db, session.id)
            assert result["score"] is None
            assert result["passed"] is None
            assert result["detail"]["verification_status"] == "unverified"
            assert session.completed_at.replace(tzinfo=None) == completed_at.replace(tzinfo=None)

    @pytest.mark.asyncio
    async def test_concurrent_score_blocks_late_log_even_on_sqlite(self, test_session_factory, monkeypatch):
        async with test_session_factory() as scoring_db, test_session_factory() as logging_db:
            session = await _session(scoring_db, started_minutes_ago=1)
            at_commit, release_commit = asyncio.Event(), asyncio.Event()
            original_commit = scoring_db.commit

            async def paused_commit():
                at_commit.set()
                await release_commit.wait()
                await original_commit()

            monkeypatch.setattr(scoring_db, "commit", paused_commit)
            scoring = asyncio.create_task(TrainingService.score_session(scoring_db, session.id))
            await asyncio.wait_for(at_commit.wait(), timeout=2)
            late_log = asyncio.create_task(TrainingService.log_operation(
                logging_db, session.id, session.lab_id, "command", command="late concurrent claim",
            ))
            try:
                await asyncio.sleep(0)
                assert not late_log.done(), "会话写锁必须覆盖提交，SQLite不能依赖FOR UPDATE"
            finally:
                release_commit.set()
                await scoring
            with pytest.raises(ValueError, match="会话不在进行中"):
                await late_log

    @pytest.mark.asyncio
    async def test_finalized_log_endpoint_returns_client_error(self, client, test_session_factory):
        from core.dependencies import get_current_user
        from main import app
        async with test_session_factory() as db:
            session = await _session(db, started_minutes_ago=1)
            await TrainingService.complete_session(db, session.id)
            session_id, owner_id = session.id, session.trainee_id
        app.dependency_overrides[get_current_user] = lambda: {"user_id": owner_id, "role": "admin"}
        response = await client.post(f"/api/v1/training/sessions/{session_id}/log", json={"action": "command", "command": "late"})
        assert response.status_code == 400
        assert "会话不在进行中" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_score_completes_session_and_freezes_duration(self, test_session_factory):
        async with test_session_factory() as db:
            session = await _session(db, started_minutes_ago=5)

            await TrainingService.score_session(db, session.id)

            refreshed = await db.get(TrainingSession, session.id)
            assert refreshed.status == "completed"
            assert refreshed.completed_at is not None
            assert refreshed.time_spent_seconds is not None

    @pytest.mark.asyncio
    async def test_existing_legacy_grade_is_preserved_without_claiming_verification(self, test_session_factory):
        async with test_session_factory() as db:
            session = await _session(db, started_minutes_ago=1)
            await TrainingService.complete_session(db, session.id)
            session.score, session.passed = 98.0, True
            await db.commit()
            result = await TrainingService.score_session(db, session.id)
            assert (result["score"], result["passed"]) == (98.0, True)
            assert result["detail"]["verification_status"] == "unverified"
            snapshot = await TrainingService.build_session_snapshot(db, session.id)
            report = TrainingService.build_recap_report(snapshot)
            assert "技能达标: 未验证" in report["report_text"]
            assert "本次训练达到通过标准" not in report["report_text"]
