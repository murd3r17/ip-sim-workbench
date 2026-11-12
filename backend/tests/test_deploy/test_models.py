"""配置下发模型测试"""
import pytest
from modules.deploy.models import DeployStatus, ChangeLevel, DeviceWriteLock


class TestDeployStatus:
    def test_enum_values(self):
        assert DeployStatus.PENDING.value == "pending"
        assert DeployStatus.DEPLOYING.value == "deploying"
        assert DeployStatus.VERIFYING.value == "verifying"
        assert DeployStatus.SUCCESS.value == "success"
        assert DeployStatus.FAILED.value == "failed"
        assert DeployStatus.ROLLED_BACK.value == "rolled_back"
        assert DeployStatus.CANCELLED.value == "cancelled"

    def test_enum_count(self):
        assert len(DeployStatus) == 9

    def test_no_dead_validating_status(self):
        """P2-06：VALIDATING 从未被赋值，V6.0 也没有独立的校验阶段。"""
        assert not hasattr(DeployStatus, "VALIDATING")

    def test_deploy_task_has_no_dead_retry_count(self):
        """P2-06：重试引擎已删除（P2-03），retry_count 没有写入点。"""
        from modules.deploy.models import DeployTask

        assert "retry_count" not in DeployTask.__table__.columns
        assert "config_watermark" in DeployTask.__table__.columns

    def test_confirmation_status_values(self):
        assert DeployStatus.AWAITING_CONFIRMATION.value == "awaiting_confirmation"
        assert DeployStatus.CONFIRMED.value == "confirmed"

    def test_device_write_lock_columns(self):
        """A2：写锁记录对齐设计 §15.3（操作类型 + 过期时间）。

        释放原因**有意不落表**：释放走"删行"语义，删掉的行无法携带原因，原因记在审计
        （`device_write_lock_released` 的 result 字段）—— 见 DeviceWriteLock 文档串。
        """
        names = set(DeviceWriteLock.__table__.columns.keys())
        assert names == {"device_id", "task_id", "lock_type", "expire_at", "created_at", "owner_type", "owner_id", "owner_token", "state", "last_seen_at", "release_state", "release_error", "owner_instance_id"}
        assert DeviceWriteLock.__table__.columns["lock_type"].nullable is False
        assert DeviceWriteLock.__table__.columns["expire_at"].nullable is True


class TestChangeLevel:
    def test_enum_values(self):
        assert ChangeLevel.EMERGENCY.value == "emergency"
        assert ChangeLevel.DAILY.value == "daily"
        assert ChangeLevel.HIGH_RISK.value == "high_risk"

    def test_enum_count(self):
        assert len(ChangeLevel) == 3
