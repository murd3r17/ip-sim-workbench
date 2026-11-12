"""系统管理模块服务测试"""
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import Result
from modules.system.service import SystemService
from modules.system.models import SystemConfig, BackgroundTask, TaskStatus


@pytest.fixture
def mock_db():
    db = AsyncMock(spec=AsyncSession)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock()
    db.get = AsyncMock()
    return db


@pytest.fixture
def mock_result():
    result = MagicMock(spec=Result)
    result.scalar_one_or_none = MagicMock(return_value=None)
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    result.scalar = MagicMock(return_value=0)
    return result


class TestSystemServiceGetConfig:
    @pytest.mark.asyncio
    async def test_get_config_found(self, mock_db):
        mock_config = SystemConfig(config_key="test.key", config_value="val")
        mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=mock_config))
        result = await SystemService.get_config(mock_db, "test.key")
        assert result is not None
        assert result.config_key == "test.key"

    @pytest.mark.asyncio
    async def test_get_config_not_found(self, mock_db):
        mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        result = await SystemService.get_config(mock_db, "nonexistent")
        assert result is None


class TestSystemServiceSetConfig:
    @pytest.mark.asyncio
    async def test_set_config_create(self, mock_db):
        mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        result = await SystemService.set_config(mock_db, "new.key", "value", "desc", "admin")
        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited_once()
        mock_db.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_set_config_update(self, mock_db):
        existing = SystemConfig(config_key="existing.key", config_value="old")
        mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=existing))
        result = await SystemService.set_config(mock_db, "existing.key", "new_val", None, "admin")
        assert existing.config_value == "new_val"
        assert existing.updated_by == "admin"
        mock_db.flush.assert_awaited_once()
        mock_db.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_set_config_keep_existing_when_value_none(self, mock_db):
        existing = SystemConfig(config_key="existing.key", config_value="keep-me")
        mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=existing))
        result = await SystemService.set_config(mock_db, "existing.key", None, None, "admin")
        assert existing.config_value == "keep-me"
        assert existing.updated_by == "admin"
        mock_db.flush.assert_awaited_once()
        mock_db.refresh.assert_awaited_once()


class TestSystemServiceDeleteConfig:
    @pytest.mark.asyncio
    async def test_delete_config_found(self, mock_db):
        config = SystemConfig(config_key="to_delete")
        mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=config))
        result = await SystemService.delete_config(mock_db, "to_delete")
        assert result is True
        mock_db.delete.assert_called_once_with(config)

    @pytest.mark.asyncio
    async def test_delete_config_not_found(self, mock_db):
        mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        result = await SystemService.delete_config(mock_db, "nonexistent")
        assert result is False


class TestSystemServiceListConfigs:
    @pytest.mark.asyncio
    async def test_list_configs(self, mock_db):
        configs = [SystemConfig(config_key="k1"), SystemConfig(config_key="k2")]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = configs
        mock_db.execute.return_value = mock_result
        result = await SystemService.list_configs(mock_db)
        assert len(result) == 2


class TestSystemServiceSerialization:
    def test_serialize_config_masks_secret(self):
        config = SystemConfig(config_key="llm.api_key", config_value="secret-value", description="api")
        config.id = 1
        serialized = SystemService.serialize_config(config)
        assert serialized["is_secret"] is True
        assert serialized["config_value"] == "******"

    def test_serialize_config_keeps_non_secret_visible(self):
        config = SystemConfig(config_key="topology.name", config_value="core", description="topology")
        config.id = 2
        serialized = SystemService.serialize_config(config)
        assert serialized["is_secret"] is False
        assert serialized["config_value"] == "core"


class TestSystemServiceSecretDetection:
    def test_is_secret_key_exact(self):
        assert SystemService._is_secret_key("jwt_secret_key") is True
        assert SystemService._is_secret_key("llm.api_key") is True

    def test_is_secret_key_non_secret_suffix(self):
        assert SystemService._is_secret_key("workflow_key") is False


class TestSystemServiceRuntimeLLMConfig:
    @pytest.mark.asyncio
    async def test_get_llm_runtime_config_overrides_settings(self, mock_db):
        from core import config as core_config

        settings = core_config.Settings()
        with patch("modules.system.service.get_settings", return_value=settings):
            rows = [
                SystemConfig(config_key="llm.provider", config_value="openai_compatible"),
                SystemConfig(config_key="llm.base_url", config_value="http://ai.local"),
                SystemConfig(config_key="llm.model", config_value="gpt-4o-mini"),
                SystemConfig(config_key="llm.api_key", config_value="abc123"),
                SystemConfig(config_key="llm.max_tokens", config_value="1024"),
                SystemConfig(config_key="llm.temperature", config_value="0.2"),
            ]
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = rows
            mock_db.execute.return_value = mock_result

            runtime = await SystemService.get_llm_runtime_config(mock_db)

        assert runtime["llm_provider"] == "openai_compatible"
        assert runtime["llm_base_url"] == "http://ai.local"
        assert runtime["llm_model"] == "gpt-4o-mini"
        assert runtime["llm_api_key"] == "abc123"
        assert runtime["llm_max_tokens"] == 1024
        assert runtime["llm_temperature"] == 0.2


class TestSystemServiceAuditLogs:
    @pytest.mark.asyncio
    async def test_get_audit_logs_empty(self, mock_db):
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        query_result = MagicMock()
        query_result.scalars.return_value.all.return_value = []
        mock_db.execute.side_effect = [count_result, query_result]
        result = await SystemService.get_audit_logs(mock_db, page=1, page_size=20)
        assert result["total"] == 0
        assert result["items"] == []
        assert result["page"] == 1

    @pytest.mark.asyncio
    async def test_get_audit_logs_with_module_filter(self, mock_db):
        count_result = MagicMock()
        count_result.scalar.return_value = 5
        query_result = MagicMock()
        query_result.scalars.return_value.all.return_value = []
        mock_db.execute.side_effect = [count_result, query_result]
        result = await SystemService.get_audit_logs(mock_db, module="auth")
        assert result["total"] == 5


class TestSystemServiceBackgroundTasks:
    @pytest.mark.asyncio
    async def test_create_task(self, mock_db):
        mock_db.refresh.side_effect = lambda t: None
        result = await SystemService.create_task(mock_db, "deploy", "测试任务", 1)
        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_task_status(self, mock_db):
        task = BackgroundTask(id=1, task_type="deploy", task_name="t", status=TaskStatus.PENDING)
        mock_db.get.return_value = task
        result = await SystemService.update_task_status(mock_db, 1, TaskStatus.RUNNING, progress=50)
        assert result is not None
        assert result.status == TaskStatus.RUNNING
        assert result.progress == 50

    @pytest.mark.asyncio
    async def test_update_task_not_found(self, mock_db):
        mock_db.get.return_value = None
        result = await SystemService.update_task_status(mock_db, 999, TaskStatus.SUCCESS)
        assert result is None

    @pytest.mark.asyncio
    async def test_list_tasks(self, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result
        result = await SystemService.list_tasks(mock_db)
        assert result == []


class TestSystemServiceLogFiles:
    def test_list_log_files_empty(self):
        result = []
        # Non-existent dir returns empty
        assert result == []

    @pytest.mark.asyncio
    async def test_read_log_file_invalid_name(self):
        with pytest.raises(ValueError, match="非法文件名"):
            await SystemService.read_log_file("logs", "../../etc/passwd")

    @pytest.mark.asyncio
    async def test_read_log_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            await SystemService.read_log_file("logs", "nonexistent.log")
