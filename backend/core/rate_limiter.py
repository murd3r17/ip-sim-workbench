"""简单内存速率限制器"""
import time
from collections import defaultdict
from fastapi import Request, HTTPException


class InMemoryRateLimiter:
    """基于IP的滑动窗口速率限制器"""

    def __init__(self):
        self._requests: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str, max_requests: int, window_seconds: int) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        self._requests[key] = [t for t in self._requests[key] if t > cutoff]
        if not self._requests[key]:
            del self._requests[key]
        if len(self._requests.get(key, [])) >= max_requests:
            return False
        self._requests.setdefault(key, []).append(now)
        return True

    def reset(self, key: str) -> None:
        self._requests.pop(key, None)


_limiter = InMemoryRateLimiter()


def _rate_key_path(request: Request) -> str:
    """限流分桶用"路由模板"而不是具体路径。

    此前用 request.url.path，`/deploy/tasks/1/execute` 与 `/deploy/tasks/2/execute`
    各自一个桶，遍历 id 即可绕过 30/分 的限制。
    """
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    return template or request.url.path


def rate_limit(max_requests: int = 10, window_seconds: int = 60):
    """速率限制依赖工厂"""
    async def _check(request: Request):
        client_ip = request.client.host if request.client else "unknown"
        key = f"{client_ip}:{_rate_key_path(request)}"
        if not _limiter.check(key, max_requests, window_seconds):
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后重试")
    return _check
