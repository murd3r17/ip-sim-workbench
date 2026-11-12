"""设备终端占用必须回 409 + 可执行建议，而不是 500。

背景（2026-10-05 用户实测）：学员开着某台设备的 WebSSH 会话时，去「配置管理」采集快照，
后端抛 `DeviceBusyError("设备终端占用中，请稍后重试")`。它此前只是普通 Exception，
落到兜底处理器返回 **500「服务器内部错误」**，学员既不知道原因也不知道要断开终端。
"""

import asyncio
import json

import pytest

from core.exceptions import register_exception_handlers
from engines.device_lock import DeviceBusyError, acquire_device_lock


def test_device_busy_error_handler_is_registered():
    from main import app

    assert DeviceBusyError in app.exception_handlers, "DeviceBusyError 必须注册专用处理器（否则 500）"


@pytest.mark.asyncio
async def test_device_busy_error_handler_returns_409_with_actionable_message():
    from main import app

    handler = app.exception_handlers[DeviceBusyError]
    response = await handler(None, DeviceBusyError("设备终端占用中，请稍后重试"))

    assert response.status_code == 409
    body = json.loads(response.body)
    assert body["error"] == "DeviceBusyError"
    # 文案必须告诉用户"怎么办"，而不只是"出错了"
    assert "WebSSH" in body["message"]
    assert "占用" in body["message"]


@pytest.mark.asyncio
async def test_lock_conflict_raises_device_busy_error():
    """锁冲突本身的行为不变：第二个持有者超时抛 DeviceBusyError。"""
    with pytest.raises(DeviceBusyError):
        async with acquire_device_lock("10.255.255.1", 22, timeout=0.1):
            async with acquire_device_lock("10.255.255.1", 22, timeout=0.1):
                pass


def test_register_exception_handlers_is_idempotent_on_fresh_app():
    """注册函数可在任意 app 上重复调用（测试/最小模式都会重建 app）。"""
    from fastapi import FastAPI

    app = FastAPI()
    register_exception_handlers(app)
    assert DeviceBusyError in app.exception_handlers
