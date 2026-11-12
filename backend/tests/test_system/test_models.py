"""系统管理模块模型测试"""
import pytest
from datetime import datetime, timezone
from modules.system.models import SystemConfig, BackgroundTask, TaskStatus


class TestSystemConfig:
    def test_create_config(self):
        config = SystemConfig(config_key="test.key", config_value="test_value", description="test desc")
        assert config.config_key == "test.key"
        assert config.config_value == "test_value"
        assert config.description == "test desc"

    def test_config_defaults(self):
        config = SystemConfig(config_key="key1")
        assert config.config_value is None
        assert config.description is None
        assert config.updated_by is None

    def test_config_table_name(self):
        assert SystemConfig.__tablename__ == "system_config"


class TestBackgroundTask:
    def test_create_task(self):
        task = BackgroundTask(task_type="deploy", task_name="测试任务", status=TaskStatus.PENDING, progress=0)
        assert task.task_type == "deploy"
        assert task.task_name == "测试任务"
        assert task.status == TaskStatus.PENDING
        assert task.progress == 0

    def test_task_status_enum(self):
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.SUCCESS == "success"
        assert TaskStatus.FAILED == "failed"
        assert TaskStatus.CANCELLED == "cancelled"

    def test_task_table_name(self):
        assert BackgroundTask.__tablename__ == "background_task"

    def test_task_all_statuses(self):
        for status in TaskStatus:
            task = BackgroundTask(task_type="test", task_name=f"task_{status.value}", status=status)
            assert task.status == status
