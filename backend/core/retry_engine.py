"""通用重试引擎"""
import asyncio
from typing import Callable, Any
from core.logger import get_logger

logger = get_logger("retry")


class RetryEngine:
    """通用重试引擎：最多3次重试 + 指数退避(1s, 2s, 4s)"""

    def __init__(self, max_retries: int = 3, backoff_base: float = 1.0, backoff_factor: float = 2.0, max_backoff: float = 30.0):
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_factor = backoff_factor
        self.max_backoff = max_backoff
        self.attempt_count = 0

    async def execute(self, func: Callable, *args, **kwargs) -> Any:
        self.attempt_count = 0
        last_exception = None

        attempts = max(0, int(self.max_retries)) + 1
        for attempt in range(attempts):
            self.attempt_count = attempt + 1
            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    loop = asyncio.get_running_loop()
                    result = await loop.run_in_executor(None, lambda: func(*args, **kwargs))
                if attempt > 0:
                    logger.info("retry_succeeded", func=func.__name__, attempt=attempt + 1)
                return result
            except Exception as e:
                last_exception = e
                if attempt < attempts - 1:
                    backoff = min(self.backoff_base * (self.backoff_factor ** attempt), self.max_backoff)
                    logger.warning("retry_attempt", func=func.__name__, attempt=attempt + 1, backoff=backoff, error=str(e))
                    await asyncio.sleep(backoff)
                else:
                    logger.error("retry_exhausted", func=func.__name__, total_attempts=self.attempt_count, error=str(e))
        # max_retries<0 时循环不会执行，last_exception 为 None（此前会抛 TypeError）
        if last_exception is None:
            raise ValueError("RetryEngine.max_retries 不能为负数")
        raise last_exception
