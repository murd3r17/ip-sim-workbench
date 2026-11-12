"""AlarmService告警评估测试"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from modules.monitor.service import AlarmService, THRESHOLDS
from modules.monitor.models import AlarmStatus


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.fixture
def mock_device():
    device = MagicMock()
    device.id = 1
    device.hostname = "Router01"
    return device


@pytest.fixture(autouse=True)
def _default_thresholds(monkeypatch):
    """这组用例只验证阈值判定逻辑；阈值来源固定为默认值（B3 起阈值可被系统配置覆盖）。"""
    async def _load(_db):
        return {name: dict(cfg) for name, cfg in THRESHOLDS.items()}
    monkeypatch.setattr("modules.monitor.service.load_thresholds", _load)


class TestThresholdValues:
    def test_cpu_thresholds_defined(self):
        assert "cpu_usage" in THRESHOLDS
        assert THRESHOLDS["cpu_usage"]["warning"] == 70
        assert THRESHOLDS["cpu_usage"]["critical"] == 95

    def test_memory_thresholds_defined(self):
        assert "memory_usage" in THRESHOLDS
        assert THRESHOLDS["memory_usage"]["warning"] == 75
        assert THRESHOLDS["memory_usage"]["critical"] == 97


def _make_no_alarm_result():
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    return result


def _make_empty_scalars_result():
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    return result


class TestAlarmServiceEvaluate:
    @pytest.mark.asyncio
    @patch("modules.monitor.service.select")
    async def test_returns_none_below_warning(self, mock_select, mock_db, mock_device):
        mock_db.execute.return_value = _make_empty_scalars_result()
        result = await AlarmService.evaluate_and_alarm(mock_db, mock_device, "cpu_usage", 50.0)
        assert result is None

    @pytest.mark.asyncio
    @patch("modules.monitor.service.Alarm")
    @patch("modules.monitor.service.select")
    async def test_fires_warning_alarm(self, mock_select, MockAlarm, mock_db, mock_device):
        mock_db.execute.return_value = _make_no_alarm_result()
        mock_instance = MagicMock()
        MockAlarm.return_value = mock_instance

        alarm = await AlarmService.evaluate_and_alarm(mock_db, mock_device, "cpu_usage", 75.0)
        assert alarm is mock_instance
        MockAlarm.assert_called_once_with(
            device_id=1, alarm_type="cpu_usage_high", severity="warning",
            message="Router01 cpu_usage = 75.0，触发warning阈值",
            metric_value=75.0, threshold=70, status=AlarmStatus.FIRED
        )

    @pytest.mark.asyncio
    @patch("modules.monitor.service.Alarm")
    @patch("modules.monitor.service.select")
    async def test_fires_critical_alarm(self, mock_select, MockAlarm, mock_db, mock_device):
        mock_db.execute.return_value = _make_no_alarm_result()
        mock_instance = MagicMock()
        MockAlarm.return_value = mock_instance

        alarm = await AlarmService.evaluate_and_alarm(mock_db, mock_device, "cpu_usage", 96.0)
        assert alarm is mock_instance
        MockAlarm.assert_called_once_with(
            device_id=1, alarm_type="cpu_usage_high", severity="critical",
            message="Router01 cpu_usage = 96.0，触发critical阈值",
            metric_value=96.0, threshold=95, status=AlarmStatus.FIRED
        )

    @pytest.mark.asyncio
    @patch("modules.monitor.service.select")
    async def test_updates_existing_alarm(self, mock_select, mock_db, mock_device):
        existing = MagicMock()
        existing.severity = "warning"
        existing.metric_value = 75.0
        existing.message = "old"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        alarm = await AlarmService.evaluate_and_alarm(mock_db, mock_device, "cpu_usage", 91.0)
        assert alarm is existing
        assert existing.severity == "major"
        assert existing.metric_value == 91.0

    @pytest.mark.asyncio
    @patch("modules.monitor.service.select")
    async def test_auto_resolve_below_threshold(self, mock_select, mock_db, mock_device):
        mock_db.execute.return_value = _make_empty_scalars_result()

        result = await AlarmService.evaluate_and_alarm(mock_db, mock_device, "cpu_usage", 30.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_unknown_metric_type_returns_none(self, mock_db, mock_device):
        result = await AlarmService.evaluate_and_alarm(mock_db, mock_device, "unknown_metric", 100.0)
        assert result is None


class TestAcknowledgeAlarm:
    @pytest.mark.asyncio
    async def test_acknowledge_fired_alarm(self, mock_db):
        alarm = MagicMock()
        alarm.status = AlarmStatus.FIRED
        mock_db.get = AsyncMock(return_value=alarm)

        result = await AlarmService.acknowledge_alarm(mock_db, 1, 1)
        assert result.status == AlarmStatus.ACKNOWLEDGED
        assert result.acknowledged_at is not None

    @pytest.mark.asyncio
    async def test_acknowledge_nonexistent_raises(self, mock_db):
        mock_db.get = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="告警不存在"):
            await AlarmService.acknowledge_alarm(mock_db, 999, 1)

    @pytest.mark.asyncio
    async def test_acknowledge_already_acknowledged_raises(self, mock_db):
        alarm = MagicMock()
        alarm.status = AlarmStatus.ACKNOWLEDGED
        mock_db.get = AsyncMock(return_value=alarm)
        with pytest.raises(ValueError, match="当前状态不允许确认"):
            await AlarmService.acknowledge_alarm(mock_db, 1, 1)


class TestCloseAlarm:
    @pytest.mark.asyncio
    async def test_close_resolved_alarm(self, mock_db):
        alarm = MagicMock()
        alarm.status = AlarmStatus.RESOLVED
        mock_db.get = AsyncMock(return_value=alarm)

        result = await AlarmService.close_alarm(mock_db, 1, 1)
        assert result.status == AlarmStatus.CLOSED
        assert result.closed_at is not None

    @pytest.mark.asyncio
    async def test_close_fired_alarm_raises(self, mock_db):
        alarm = MagicMock()
        alarm.status = AlarmStatus.FIRED
        mock_db.get = AsyncMock(return_value=alarm)
        with pytest.raises(ValueError, match="当前状态不允许关闭"):
            await AlarmService.close_alarm(mock_db, 1, 1)
