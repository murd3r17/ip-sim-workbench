"""统一异常定义与全局异常处理器"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from core.logger import get_logger
from engines.device_lock import DeviceBusyError

logger = get_logger("error")


class AppException(Exception):
    """应用级异常基类"""
    def __init__(self, message: str, status_code: int = 400, detail: dict = None):
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}
        super().__init__(message)


class DeployValidationError(AppException):
    def __init__(self, message: str):
        super().__init__(message, status_code=422)


class DeviceOfflineError(AppException):
    def __init__(self, device_hostname: str):
        super().__init__(f"设备 {device_hostname} 当前离线，无法执行操作", status_code=409)


class DeviceLockError(AppException):
    def __init__(self, device_hostname: str):
        super().__init__(f"设备 {device_hostname} 正在执行其他任务，请稍后重试", status_code=409)


class AuthenticationError(AppException):
    def __init__(self, message: str = "认证失败"):
        super().__init__(message, status_code=401)


class AuthorizationError(AppException):
    """权限不足。

    注意：不要命名为 PermissionError —— 那会遮蔽内置异常
    （内置 PermissionError 是 OSError 子类，还会被 except OSError 误捕）。
    """

    def __init__(self, message: str = "权限不足"):
        super().__init__(message, status_code=403)


def parse_enum(enum_cls, value, field: str):
    """把查询/路径参数转成枚举；非法取值给 422 而不是冒泡成 500。

    此前 `DeviceStatus(status)`、`AlarmStatus(status)` 等直接抛 ValueError，
    落到兜底处理器返回 500，而同类代码里有的地方又是 422，行为不一致。
    """
    try:
        return enum_cls(value)
    except (ValueError, KeyError) as exc:
        allowed = ", ".join(sorted(str(item.value) for item in enum_cls))
        raise AppException(f"{field} 取值非法: {value}（可选: {allowed}）", status_code=422) from exc


def register_exception_handlers(app: FastAPI):
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        return JSONResponse(status_code=exc.status_code, content={
            "error": type(exc).__name__, "message": exc.message, "detail": exc.detail
        })

    @app.exception_handler(DeviceBusyError)
    async def device_busy_handler(request: Request, exc: DeviceBusyError):
        """设备终端被占用 → 409 + 可执行建议。

        此前 DeviceBusyError 只是普通 Exception，落到兜底处理器变成 **500「服务器内部错误」**：
        学员开着 WebSSH 时去采集快照/采集指标/执行下发，只会看到"服务器内部错误"，
        既不知道原因也不知道该断开终端（2026-10-05 用户实测踩到：占用 R1 终端后
        `POST /config-versions/capture` 直接 500）。
        """
        logger.warning(
            "device_busy",
            path=str(getattr(request, "url", "")),
            method=getattr(request, "method", ""),
            detail=str(exc),
        )
        return JSONResponse(status_code=409, content={
            "error": "DeviceBusyError",
            "message": (
                "设备终端被占用：同一台设备同一时刻只允许一个操作方。"
                "请先关闭该设备的 WebSSH 会话（或等上一条命令/采集结束）后重试。"
            ),
            "detail": str(exc),
        })

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errors = []
        for err in exc.errors():
            loc = " → ".join(str(l) for l in err.get("loc", []))
            errors.append({"field": loc, "message": err.get("msg", "参数错误")})
        return JSONResponse(status_code=422, content={
            "error": "ValidationError", "message": "请求参数验证失败", "detail": errors
        })

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.critical("unhandled_exception", path=str(request.url), method=request.method, error=str(exc), exc_info=True)
        return JSONResponse(status_code=500, content={"error": "InternalServerError", "message": "服务器内部错误"})
