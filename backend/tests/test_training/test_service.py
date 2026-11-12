"""实训模块服务测试"""
import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from modules.training.service import (
    TrainingService, FAULT_TEMPLATES, DEFAULT_SCORING,
)
from modules.training.models import FaultType

# 确保所有关系模型已注册（SQLAlchemy mapper配置需要）
import modules.device.models  # noqa: F401
import modules.auth.models  # noqa: F401
import modules.deploy.models  # noqa: F401
import modules.monitor.models  # noqa: F401

_analyze_command_quality = TrainingService._analyze_command_quality
_calculate_time_score = TrainingService._calculate_time_score
_find_repeated_commands = TrainingService._find_repeated_commands


@pytest.fixture
def mock_db():
    db = AsyncMock(spec=AsyncSession)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock()
    db.get = AsyncMock()
    db.delete = AsyncMock()
    return db


class TestFaultTemplates:
    def test_has_all_seven_templates(self):
        assert len(FAULT_TEMPLATES) == 7

    def test_each_template_has_required_keys(self):
        for fault_type, template in FAULT_TEMPLATES.items():
            assert "description" in template, f"{fault_type} missing description"
            assert "inject" in template, f"{fault_type} missing inject"
            assert "rollback" in template, f"{fault_type} missing rollback"
            assert "verify" in template, f"{fault_type} missing verify"
            assert isinstance(template["inject"], list)
            assert isinstance(template["rollback"], list)

    def test_interface_shutdown_template(self):
        t = FAULT_TEMPLATES[FaultType.INTERFACE_SHUTDOWN]
        assert "shutdown" in t["inject"][1]
        assert "undo shutdown" in t["rollback"][1]

    def test_ospf_neighbor_down_template(self):
        t = FAULT_TEMPLATES[FaultType.OSPF_NEIGHBOR_DOWN]
        assert any("ospf" in cmd for cmd in t["inject"])
        assert any("ospf" in cmd for cmd in t["rollback"])

    def test_vlan_mismatch_template(self):
        t = FAULT_TEMPLATES[FaultType.VLAN_MISMATCH]
        assert any("vlan" in cmd for cmd in t["inject"])

    def test_acl_block_template(self):
        t = FAULT_TEMPLATES[FaultType.ACL_BLOCK]
        assert any("acl" in cmd for cmd in t["inject"])

    def test_route_blackhole_template(self):
        t = FAULT_TEMPLATES[FaultType.ROUTE_BLACKHOLE]
        assert any("route-static" in cmd for cmd in t["inject"])

    def test_mtu_mismatch_template(self):
        t = FAULT_TEMPLATES[FaultType.MTU_MISMATCH]
        assert any("mtu" in cmd for cmd in t["inject"])

    def test_dns_fault_template(self):
        t = FAULT_TEMPLATES[FaultType.DNS_FAULT]
        assert any("dns" in cmd for cmd in t["inject"])


class TestDefaultScoring:
    def test_weights_sum_to_one(self):
        total = (DEFAULT_SCORING["operation_weight"]
                 + DEFAULT_SCORING["fault_weight"]
                 + DEFAULT_SCORING["time_weight"])
        assert abs(total - 1.0) < 0.01

    def test_operation_weight_is_60_percent(self):
        assert DEFAULT_SCORING["operation_weight"] == 0.60

    def test_fault_weight_is_30_percent(self):
        assert DEFAULT_SCORING["fault_weight"] == 0.30

    def test_time_weight_is_10_percent(self):
        assert DEFAULT_SCORING["time_weight"] == 0.10


class TestCommandQualityAnalysis:
    def test_no_log_returns_50(self):
        assert _analyze_command_quality(None) == 50.0
        assert _analyze_command_quality("") == 50.0

    def test_perfect_log_returns_100(self):
        log = json.dumps({"command": "display version"})
        assert _analyze_command_quality(log) == 100.0

    def test_undo_commands_reduce_score(self):
        log = "\n".join([
            json.dumps({"command": f"undo interface GigabitEthernet0/0/{i}"})
            for i in range(5)
        ])
        score = _analyze_command_quality(log)
        assert score < 100.0
        assert score >= 80.0

    def test_error_commands_reduce_score(self):
        log = "\n".join([
            json.dumps({"command": "test", "error": "invalid command"})
            for _ in range(3)
        ])
        score = _analyze_command_quality(log)
        assert score < 100.0
        assert score >= 70.0

    def test_success_false_also_reduces_score(self):
        log = "\n".join([
            json.dumps({"command": "display foo", "success": False})
            for _ in range(3)
        ])
        score = _analyze_command_quality(log)
        assert score < 100.0
        assert score >= 70.0

    def test_repeated_commands_reduce_score(self):
        log = "\n".join([
            json.dumps({"command": "display version"})
            for _ in range(4)
        ])
        score = _analyze_command_quality(log)
        assert score < 100.0


class TestTimeScoreCalculation:
    def test_no_time_returns_100(self):
        assert _calculate_time_score(None, 3600) == 100.0

    def test_zero_time_limit(self):
        assert _calculate_time_score(100, 0) == 100.0

    def test_within_limit(self):
        score = _calculate_time_score(1800, 3600)
        assert 60.0 <= score <= 100.0

    def test_over_limit(self):
        score = _calculate_time_score(5400, 3600)
        assert score < 60.0

    def test_well_over_limit(self):
        score = _calculate_time_score(7200, 3600)
        assert score == 0.0


class TestRepeatedCommands:
    def test_no_repeats(self):
        cmds = [{"command": "a"}, {"command": "b"}]
        assert _find_repeated_commands(cmds) == 0

    def test_repeats(self):
        cmds = [{"command": "a"}, {"command": "a"}, {"command": "a"}]
        assert _find_repeated_commands(cmds) == 2


class TestCreateLab:
    @pytest.mark.asyncio
    async def test_create_lab_success(self, mock_db):
        lab = await TrainingService.create_lab(
            mock_db, "Test Lab", "Description", 1, 1,
            time_limit_minutes=30, is_sandbox=True,
        )
        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited()
        assert lab.title == "Test Lab"
        assert lab.time_limit_minutes == 30
        assert lab.is_sandbox is True


class TestUpdateLab:
    @pytest.mark.asyncio
    async def test_update_lab_success(self, mock_db):
        mock_lab = MagicMock()
        mock_lab.title = "old"
        mock_db.get.return_value = mock_lab
        result = await TrainingService.update_lab(mock_db, 1, title="new")
        assert result.title == "new"

    @pytest.mark.asyncio
    async def test_update_lab_rejects_protected_fields(self, mock_db):
        mock_lab = MagicMock()
        mock_lab.id = 1
        mock_db.get.return_value = mock_lab
        await TrainingService.update_lab(mock_db, 1, id=999)
        # id is not in _UPDATABLE_LAB_FIELDS, so it should not be set


class TestStartSession:
    @pytest.mark.asyncio
    async def test_start_session_success(self, mock_db):
        mock_lab = MagicMock()
        mock_lab.status = "ready"
        mock_db.get.return_value = mock_lab

        session = await TrainingService.start_session(mock_db, 1, 1)
        mock_db.add.assert_called_once()
        assert session.status == "in_progress"

    @pytest.mark.asyncio
    async def test_start_session_lab_not_found(self, mock_db):
        mock_db.get.return_value = None
        with pytest.raises(ValueError, match="Lab不存在"):
            await TrainingService.start_session(mock_db, 999, 1)


class TestInjectFaults:
    @pytest.mark.asyncio
    async def test_inject_single_fault(self, mock_db):
        mock_db.get.return_value = MagicMock(status="in_progress")
        fault_scenario = [
            {"device_id": 1, "fault_type": "interface_shutdown", "config": {"interface": "GigabitEthernet0/0/1"}}
        ]
        injections = await TrainingService.inject_faults(mock_db, 1, fault_scenario)
        assert len(injections) == 1
        assert injections[0].fault_type == FaultType.INTERFACE_SHUTDOWN

    @pytest.mark.asyncio
    async def test_inject_multiple_faults(self, mock_db):
        mock_db.get.return_value = MagicMock(status="in_progress")
        fault_scenario = [
            {"device_id": 1, "fault_type": "ospf_neighbor_down", "config": {"interface": "GE0/0/1", "process_id": "1", "area_id": "0"}},
            {"device_id": 1, "fault_type": "acl_block", "config": {"acl_number": "2000"}},
        ]
        injections = await TrainingService.inject_faults(mock_db, 1, fault_scenario)
        assert len(injections) == 2

    @pytest.mark.asyncio
    async def test_inject_never_calls_device_adapter(self, mock_db):
        mock_db.get.return_value = MagicMock(status="in_progress")
        with patch("engines.device_adapter.get_device_adapter") as adapter:
            await TrainingService.inject_faults(
                mock_db,
                1,
                [{"device_id": 1, "fault_type": "interface_shutdown", "config": {"interface": "GigabitEthernet0/0/1"}}],
            )
            adapter.assert_not_called()


class TestScoringEngine:
    @pytest.mark.asyncio
    async def test_score_session_not_found(self, mock_db):
        mock_db.get.return_value = None
        with pytest.raises(ValueError, match="会话不存在"):
            await TrainingService.score_session(mock_db, 999)


class TestIdempotencyGuard:
    @pytest.mark.asyncio
    async def test_complete_session_accepts_mysql_naive_started_at(self, mock_db):
        mock_session = MagicMock()
        mock_session.status = "in_progress"
        mock_session.started_at = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=5)
        )
        mock_db.get.return_value = mock_session

        result = await TrainingService.complete_session(mock_db, 1)

        assert result["time_spent_seconds"] >= 5
        assert mock_session.status == "completed"
        assert mock_session.completed_at.tzinfo is not None
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_complete_session_is_idempotent(self, mock_db):
        mock_session = MagicMock()
        mock_session.status = "completed"
        mock_session.time_spent_seconds = 42
        mock_db.get.return_value = mock_session
        assert await TrainingService.complete_session(mock_db, 1) == {"session_id": 1, "time_spent_seconds": 42}
        mock_db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_complete_session_rejects_pending(self, mock_db):
        mock_db.get.return_value = MagicMock(status="pending")
        with pytest.raises(ValueError, match="会话不在进行中"):
            await TrainingService.complete_session(mock_db, 1)


class TestStage7TrainingArtifacts:
    @pytest.mark.asyncio
    async def test_log_operation_appends_command_log(self, mock_db):
        mock_session = MagicMock()
        mock_session.lab_id = 7
        mock_session.status = "in_progress"
        mock_session.command_log = None
        mock_db.get.return_value = mock_session

        log = await TrainingService.log_operation(
            mock_db,
            session_id=1,
            lab_id=7,
            action="execute",
            target_device="R1",
            command="display version",
            result="ok",
            success=True,
            meta={"step": 1},
        )

        assert log.action == "execute"
        assert "display version" in mock_session.command_log

    def test_build_training_hint(self):
        class Lab:
            id = 7
            title = "接口恢复训练"
            objectives = ["恢复链路", "记录步骤"]

        class Session:
            id = 11
            status = "in_progress"

        snapshot = {
            "session": Session(),
            "lab": Lab(),
            "logs": [
                {"command": "display version", "result": "ok", "success": True},
                {"command": "shutdown", "result": "failed", "success": False},
            ],
            "faults": [],
        }
        hint = TrainingService.build_training_hint(snapshot)
        assert hint["goal"] == "接口恢复训练"
        assert hint["next_steps"]
        assert hint["corrections"]

    def test_build_hint_search_query_handles_step_dicts(self):
        class Lab:
            title = "OSPF 单区域基础实验完整版"
            objectives = [
                {"id": 1, "name": "互联与环回地址核对", "goal": "确认三台在同一广播域"},
                {"id": 7, "name": "Silent-Interface 对比", "goal": "对比 silent-interface 现象"},
            ]

        query = TrainingService.build_hint_search_query(
            Lab(),
            [{"command": "display ospf peer", "result": "Full"}],
        )
        assert "OSPF 单区域" in query
        assert "Silent-Interface" in query
        assert "display ospf peer" in query
        assert "{" not in query

    def test_build_training_hint_uses_step_name_not_dict(self):
        class Lab:
            id = 7
            title = "OSPF"
            objectives = [{"id": 1, "name": "互联与环回地址核对", "goal": "确认地址"}]

        class Session:
            id = 11
            status = "in_progress"

        hint = TrainingService.build_training_hint({
            "session": Session(),
            "lab": Lab(),
            "logs": [],
            "faults": [],
        })
        assert hint["next_steps"]
        assert "互联与环回地址核对" in hint["next_steps"][0]
        assert "{" not in hint["next_steps"][0]

    def test_build_recap_report(self):
        class Fault:
            id = 1
            fault_type = FaultType.INTERFACE_SHUTDOWN
            resolved_correctly = False
            device_id = 3

        class Lab:
            id = 7
            title = "接口恢复训练"
            objectives = ["恢复链路"]

        class Session:
            id = 11
            status = "completed"
            score = 82.5
            passed = True
            command_log = json.dumps({"command": "display version"})

        snapshot = {
            "session": Session(),
            "lab": Lab(),
            "logs": [
                {"command": "display version", "result": "ok", "success": True},
                {"command": "shutdown", "result": "failed", "success": False},
            ],
            "faults": [Fault()],
        }
        report = TrainingService.build_recap_report(snapshot)
        assert report["title"].startswith("接口恢复训练")
        assert report["report_text"]
        assert report["faults"][0]["fault_type"] == FaultType.INTERFACE_SHUTDOWN.value
