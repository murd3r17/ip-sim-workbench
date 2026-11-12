"""实训模块模型测试"""
import pytest
from modules.training.models import (
    FaultType, LabStatus, TrainingLab, TrainingSession,
    FaultInjection, OperationLog,
)


class TestFaultType:
    def test_has_all_seven_fault_types(self):
        assert len(FaultType) == 7

    def test_fault_type_values(self):
        expected = {
            "interface_shutdown", "ospf_neighbor_down", "vlan_mismatch",
            "acl_block", "route_blackhole", "mtu_mismatch", "dns_fault",
        }
        assert {ft.value for ft in FaultType} == expected

    def test_fault_type_is_str_enum(self):
        for ft in FaultType:
            assert isinstance(ft, str)


class TestLabStatus:
    def test_has_four_statuses(self):
        assert len(LabStatus) == 4

    def test_status_values(self):
        assert LabStatus.DRAFT.value == "draft"
        assert LabStatus.READY.value == "ready"
        assert LabStatus.IN_PROGRESS.value == "in_progress"
        assert LabStatus.COMPLETED.value == "completed"


class TestTrainingLabModel:
    def test_tablename(self):
        assert TrainingLab.__tablename__ == "training_lab"

    def test_has_required_columns(self):
        cols = {c.name for c in TrainingLab.__table__.columns}
        required = {"id", "title", "topology_id", "instructor_id", "status",
                     "objectives", "scoring_rules", "time_limit_minutes", "is_sandbox",
                     "created_at", "updated_at", "description"}
        assert required.issubset(cols)


class TestTrainingSessionModel:
    def test_tablename(self):
        assert TrainingSession.__tablename__ == "training_session"

    def test_has_required_columns(self):
        cols = {c.name for c in TrainingSession.__table__.columns}
        required = {"id", "lab_id", "trainee_id", "started_at", "completed_at",
                     "time_spent_seconds", "score", "score_detail", "passed",
                     "command_log", "status", "created_at"}
        assert required.issubset(cols)


class TestFaultInjectionModel:
    def test_tablename(self):
        assert FaultInjection.__tablename__ == "fault_injection"


class TestOperationLogModel:
    def test_tablename(self):
        assert OperationLog.__tablename__ == "operation_log"

    def test_has_required_columns(self):
        cols = {c.name for c in OperationLog.__table__.columns}
        required = {"id", "session_id", "lab_id", "timestamp", "action",
                     "target_device", "command", "result", "success", "meta"}
        assert required.issubset(cols)
