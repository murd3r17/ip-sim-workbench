"""核心日志配置测试。"""
from __future__ import annotations

import logging
import tempfile


def test_setup_logging_falls_back_to_temp_dir(monkeypatch):
    from core.config import Settings
    from core import logger as logger_module

    settings = Settings()
    settings.log_dir = "/readonly/logs"
    settings.log_level = "INFO"
    settings.debug = False

    monkeypatch.setattr(logger_module, "get_settings", lambda: settings)
    monkeypatch.setattr(logger_module, "_configured", False)

    real_makedirs = logger_module.os.makedirs

    def fake_makedirs(path, exist_ok=False):
        if path == "/readonly/logs":
            raise OSError("read-only")
        return real_makedirs(path, exist_ok=exist_ok)

    monkeypatch.setattr(logger_module.os, "makedirs", fake_makedirs)

    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    root_logger.handlers.clear()
    try:
        logger_module.setup_logging()
        fallback_dir = tempfile.gettempdir()
        assert any(
            getattr(handler, "baseFilename", "").startswith(fallback_dir)
            for handler in root_logger.handlers
        )
    finally:
        root_logger.handlers.clear()
        root_logger.handlers.extend(original_handlers)
        monkeypatch.setattr(logger_module, "_configured", False)
