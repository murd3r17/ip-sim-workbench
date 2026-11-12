"""structlog日志配置"""
import structlog
import logging
import os
import tempfile
from logging.handlers import RotatingFileHandler
from core.config import get_settings

_configured = False

# 需要独立文件的模块日志：覆盖代码中实际使用的 logger 名。
# 此前硬编码 8 个，device/retry/security/system/training/knowledge/health/error
# 的 INFO/WARNING 因为 root 只挂了 ERROR 级 handler 而被静默丢弃。
MODULE_LOGGERS = (
    "deploy", "ssh", "ai", "monitor", "topology", "scheduler",
    "webssh", "audit", "device", "system",
)
_MODULE_MAX_BYTES = 10 * 1024 * 1024
_ERROR_MAX_BYTES = 50 * 1024 * 1024


def _create_rotating_handler(path: str, max_bytes: int = _MODULE_MAX_BYTES) -> RotatingFileHandler:
    """创建可轮转文件日志处理器，必要时回退到临时目录。"""

    def _make(target: str) -> RotatingFileHandler:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        return RotatingFileHandler(target, maxBytes=max_bytes, backupCount=10, encoding="utf-8")

    try:
        return _make(path)
    except OSError:
        fallback_dir = os.path.join(tempfile.gettempdir(), "ip-sim-workbench-logs")
        os.makedirs(fallback_dir, exist_ok=True)
        return _make(os.path.join(fallback_dir, os.path.basename(path)))


def _shared_processors() -> list:
    """structlog 与 stdlib 共用的 processor 链。"""
    return [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]


def _build_formatter(shared_processors) -> structlog.stdlib.ProcessorFormatter:
    """统一的 JSON 输出格式。

    此前各 handler 用的是 logging.Formatter("%(message)s")，而 structlog 已把事件
    包装成 ProcessorFormatter 的待处理对象 → 落盘是 Python dict repr，既不是 JSON
    也无法被日志系统解析。这里给所有 handler 挂上同一个 ProcessorFormatter。
    """
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
    )


def setup_logging():
    """配置结构化日志"""
    global _configured
    if _configured:
        return

    settings = get_settings()
    log_dir = settings.log_dir

    shared_processors = _shared_processors()

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = _build_formatter(shared_processors)

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.log_level))

    # 全量应用日志：兜底，保证任何 logger 的 INFO/WARNING 都不会被丢弃
    app_handler = _create_rotating_handler(os.path.join(log_dir, "app.log"))
    app_handler.setFormatter(formatter)
    root_logger.addHandler(app_handler)

    # 错误日志（全量 ERROR+）
    error_handler = _create_rotating_handler(os.path.join(log_dir, "error.log"), _ERROR_MAX_BYTES)
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root_logger.addHandler(error_handler)

    # 各模块日志（挂在对应 logger 上，记录同时经 root 写入 app.log）
    for module in MODULE_LOGGERS:
        handler = _create_rotating_handler(os.path.join(log_dir, f"{module}.log"))
        handler.setFormatter(formatter)
        logging.getLogger(module).addHandler(handler)

    if settings.debug:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root_logger.addHandler(console)

    # 全部配置成功后才置位，避免中途异常导致后续调用直接跳过配置
    _configured = True


def get_logger(name: str):
    """获取logger实例"""
    setup_logging()
    return structlog.get_logger(name)
