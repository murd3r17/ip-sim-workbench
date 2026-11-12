"""LLM Provider抽象层"""
import json
import time
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Optional

import httpx

from core.config import get_settings
from core.logger import get_logger
from core.llm_meter import before_dispatch, record_usage

logger = get_logger("ai")


# LLM 健康检查 TTL 缓存：健康接口/系统信息接口每次请求都同步打外部 LLM API
# （如 GET /v1/models，超时 10s），高并发下会排队阻塞事件循环（实测 30 并发 P95≈42s）。
# 60 秒窗口内只真正探测一次，失败也缓存（快速降级而非每次等待超时）。
_LLM_HEALTH_CACHE: dict[str, tuple[float, bool]] = {}
_LLM_HEALTH_TTL_SECONDS = 60.0


def _llm_health_cache_key(provider: "LLMProvider") -> str:
    return "|".join(
        [
            type(provider).__name__,
            str(getattr(provider, "base_url", "")),
            str(getattr(provider, "model", "")),
            str(getattr(provider, "api_key", "") or ""),
        ]
    )


async def cached_llm_health_check(provider: "LLMProvider") -> bool:
    """带 TTL 的 LLM 健康检查；TTL 内重复调用直接命中缓存，不触发外部请求。"""
    key = _llm_health_cache_key(provider)
    now = time.monotonic()
    hit = _LLM_HEALTH_CACHE.get(key)
    if hit is not None and now - hit[0] < _LLM_HEALTH_TTL_SECONDS:
        return hit[1]
    healthy = await provider.health_check()
    _LLM_HEALTH_CACHE[key] = (now, healthy)
    return healthy


class LLMUnavailableError(RuntimeError):
    """No configured model produced an answer; static guidance is not generation."""


class LLMProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        ...

    @abstractmethod
    async def stream(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> AsyncIterator[str]:
        ...

    async def stream_parts(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> AsyncIterator[dict[str, str]]:
        """流式分片：{'kind': 'reasoning'|'content', 'text': '...'}。默认仅 content。"""
        async for chunk in self.stream(prompt, system, max_tokens, temperature):
            if chunk:
                yield {"kind": "content", "text": chunk}

    @abstractmethod
    async def health_check(self) -> bool:
        ...

    @property
    def name(self) -> str:
        return self.__class__.__name__


class OllamaProvider(LLMProvider):
    metered_dispatch = True

    @staticmethod
    def _record_usage(dispatch, result: dict) -> None:
        # Ollama /api/generate reports input/output counts on the final response.
        # Missing counts remain unknown, rather than being filled with zero.
        usage = {}
        for source, target in (("prompt_eval_count", "prompt_tokens"), ("eval_count", "completion_tokens")):
            value = result.get(source)
            if type(value) is int and value >= 0:
                usage[target] = value
        if "prompt_tokens" in usage and "completion_tokens" in usage:
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        record_usage(dispatch, usage)

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        timeout: Optional[float] = None,
    ):
        settings = get_settings()
        self.base_url = base_url or settings.llm_base_url
        self.model = model or settings.llm_model
        self.default_max_tokens = settings.llm_max_tokens if max_tokens is None else max_tokens
        self.default_temperature = settings.llm_temperature if temperature is None else temperature
        # 共享客户端（trust_env=True：需走系统代理；关闭由应用退出时统一处理）
        # 超时读配置（A5：设计 §8 的 timeout 项）
        from core.shared_http import get_managed_client
        self._client = get_managed_client(
            timeout=float(settings.llm_timeout if timeout is None else timeout), trust_env=True, follow_redirects=False
        )

    async def close(self):
        # 客户端为进程级共享，不随单个 provider 关闭
        return None

    def _build_payload(
        self,
        prompt: str,
        system: Optional[str],
        max_tokens: Optional[int],
        temperature: Optional[float],
        stream: bool,
    ) -> dict:
        return {
            "model": self.model,
            "prompt": prompt,
            "system": system or "",
            "stream": stream,
            "options": {
                "num_predict": max_tokens if max_tokens is not None else self.default_max_tokens,
                "temperature": temperature if temperature is not None else self.default_temperature,
            },
        }

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        payload = self._build_payload(prompt, system, max_tokens, temperature, stream=False)
        dispatch = before_dispatch(self, payload)
        resp = await self._client.post(f"{self.base_url}/api/generate", json=payload)
        resp.raise_for_status()
        result = resp.json()
        self._record_usage(dispatch, result)
        return result.get("response", "")

    async def stream(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> AsyncIterator[str]:
        payload = self._build_payload(prompt, system, max_tokens, temperature, stream=True)
        completed = False
        dispatch = before_dispatch(self, payload)
        async with self._client.stream("POST", f"{self.base_url}/api/generate", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    # 代理/网关偶尔插入非 JSON 行；此前会直接终止整条流
                    logger.debug("ollama_stream_skip_non_json", line=line[:120])
                    continue
                token = chunk.get("response", "")
                if token:
                    yield token
                if chunk.get("done", False):
                    self._record_usage(dispatch, chunk)
                    completed = True
                    break
        if not completed:
            raise RuntimeError("Ollama stream ended without completion marker")

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get(f"{self.base_url}/api/tags", timeout=10)
            return resp.status_code == 200
        except Exception as e:
            logger.warning("ollama_health_check_failed", error=str(e))
            return False


class OpenAICompatibleProvider(LLMProvider):
    metered_dispatch = True
    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        timeout: Optional[float] = None,
    ):
        settings = get_settings()
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_base_url = self.base_url if self.base_url.endswith("/v1") else f"{self.base_url}/v1"
        self.model = model or settings.llm_model
        self.api_key = api_key or settings.llm_api_key
        self.default_max_tokens = settings.llm_max_tokens if max_tokens is None else max_tokens
        self.default_temperature = settings.llm_temperature if temperature is None else temperature
        self.thinking_enabled = bool(getattr(settings, "llm_thinking_enabled", True))
        self.reasoning_effort = str(getattr(settings, "llm_reasoning_effort", "high") or "high")
        # 共享客户端（trust_env=True：DeepSeek 需走系统代理；关闭由应用退出时统一处理）
        # 超时读配置（A5：设计 §8 的 timeout 项），健康检查仍用固定的 10s 短超时
        from core.shared_http import get_managed_client
        self._client = get_managed_client(
            timeout=float(settings.llm_timeout if timeout is None else timeout), trust_env=True, follow_redirects=False
        )

    async def close(self):
        # 客户端为进程级共享，不随单个 provider 关闭
        return None

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get(
                f"{self.api_base_url}/models",
                headers=self._build_headers(),
                timeout=10
            )
            return resp.status_code == 200
        except Exception:
            return False

    def _build_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _build_messages(
        self, prompt: str, system: Optional[str]
    ) -> list[dict]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _supports_thinking(self) -> bool:
        model = (self.model or "").lower()
        host = (self.base_url or "").lower()
        return "deepseek" in model or "deepseek" in host

    def _build_payload(
        self,
        prompt: str,
        system: Optional[str],
        max_tokens: Optional[int],
        temperature: Optional[float],
        stream: bool,
    ) -> dict:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._build_messages(prompt, system),
            "max_tokens": max_tokens if max_tokens is not None else self.default_max_tokens,
            "stream": stream,
        }
        use_thinking = self.thinking_enabled and self._supports_thinking()
        if use_thinking:
            # DeepSeek thinking mode: CoT -> reasoning_content, answer -> content
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = self.reasoning_effort
        else:
            payload["temperature"] = (
                temperature if temperature is not None else self.default_temperature
            )
            if self._supports_thinking() and not self.thinking_enabled:
                payload["thinking"] = {"type": "disabled"}
        return payload

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        payload = self._build_payload(prompt, system, max_tokens, temperature, stream=False)
        dispatch = before_dispatch(self, payload)
        resp = await self._client.post(
            f"{self.api_base_url}/chat/completions",
            json=payload,
            headers=self._build_headers(),
        )
        resp.raise_for_status()
        record_usage(dispatch, resp.json().get("usage"))
        message = resp.json()["choices"][0]["message"]
        # Deliberation is never a substitute for a missing final answer.
        # Callers already handle empty generation as failure/local fallback.
        content = message.get("content")
        return content if isinstance(content, str) else ""

    async def chat_completion(
        self,
        messages: list[dict],
        tools: Optional[list] = None,
        tool_choice: str = "auto",
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> dict:
        """单轮对话（非流式），返回完整 message（可能含 tool_calls）。

        供 AI 助手的工具调用循环使用：工具决策轮不启用深度思考以降低延迟，
        最终答案生成仍走 stream_parts（保留 reasoning）。
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens if max_tokens is not None else self.default_max_tokens,
            "stream": False,
            "temperature": temperature if temperature is not None else self.default_temperature,
        }
        # thinking 是 DeepSeek 专有字段；非 DeepSeek 的 OpenAI 兼容端点收到未知字段会 400，
        # 而 FallbackProvider 会吞掉异常返回无 tool_calls 的消息 → 工具循环静默全失效。
        if self._supports_thinking():
            payload["thinking"] = {"type": "disabled"}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        dispatch = before_dispatch(self, payload)
        resp = await self._client.post(
            f"{self.api_base_url}/chat/completions",
            json=payload,
            headers=self._build_headers(),
        )
        resp.raise_for_status()
        record_usage(dispatch, resp.json().get("usage"))
        return resp.json()["choices"][0]["message"]

    def _build_vision_payload(
        self,
        system: Optional[str],
        user_prompt: str,
        images: list[dict],
        max_tokens: Optional[int],
        temperature: Optional[float],
        stream: bool,
        model: Optional[str] = None,
    ) -> dict:
        """构建带图片的 OpenAI 兼容 payload（content 为混合块数组）。"""
        content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
        for img in images:
            mime = img.get("mime") or "image/png"
            url = img.get("url")  # data:image/png;base64,... 或 https://...
            if not url:
                continue
            content.append({"type": "image_url", "image_url": {"url": url, "detail": "high"}})
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})
        return {
            "model": model or self.model,
            "messages": messages,
            "max_tokens": max_tokens if max_tokens is not None else self.default_max_tokens,
            "stream": stream,
            "temperature": temperature if temperature is not None else self.default_temperature,
        }

    async def generate_with_images(
        self,
        prompt: str,
        images: list[dict],
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None,
    ) -> str:
        """带图片的非流式生成（视觉模型）。"""
        payload = self._build_vision_payload(system, prompt, images, max_tokens, temperature, stream=False, model=model)
        dispatch = before_dispatch(self, payload)
        resp = await self._client.post(
            f"{self.api_base_url}/chat/completions",
            json=payload,
            headers=self._build_headers(),
        )
        resp.raise_for_status()
        record_usage(dispatch, resp.json().get("usage"))
        message = resp.json()["choices"][0]["message"]
        content = message.get("content")
        return content if isinstance(content, str) else ""

    async def stream_parts_with_images(
        self,
        prompt: str,
        images: list[dict],
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None,
    ) -> AsyncIterator[dict[str, str]]:
        """带图片的流式生成（视觉模型），产出 reasoning/content 分片。"""
        payload = self._build_vision_payload(system, prompt, images, max_tokens, temperature, stream=True, model=model)
        completed = False
        dispatch = before_dispatch(self, payload)
        async with self._client.stream(
            "POST",
            f"{self.api_base_url}/chat/completions",
            json=payload,
            headers=self._build_headers(),
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str:
                    continue
                if data_str == "[DONE]":
                    completed = True
                    break
                chunk = json.loads(data_str)
                record_usage(dispatch, chunk.get("usage"))
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                completed = completed or choices[0].get("finish_reason") is not None
                reasoning = delta.get("reasoning_content") or ""
                content = delta.get("content") or ""
                if reasoning:
                    yield {"kind": "reasoning", "text": reasoning}
                if content:
                    yield {"kind": "content", "text": content}
        if not completed:
            raise RuntimeError("Vision stream ended without completion marker")

    async def stream_parts(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> AsyncIterator[dict[str, str]]:
        payload = self._build_payload(prompt, system, max_tokens, temperature, stream=True)
        completed = False
        dispatch = before_dispatch(self, payload)
        async with self._client.stream(
            "POST",
            f"{self.api_base_url}/chat/completions",
            json=payload,
            headers=self._build_headers(),
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str:
                    continue
                if data_str == "[DONE]":
                    completed = True
                    break
                chunk = json.loads(data_str)
                record_usage(dispatch, chunk.get("usage"))
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                completed = completed or choices[0].get("finish_reason") is not None
                reasoning = delta.get("reasoning_content") or ""
                content = delta.get("content") or ""
                if reasoning:
                    yield {"kind": "reasoning", "text": reasoning}
                if content:
                    yield {"kind": "content", "text": content}
        if not completed:
            raise RuntimeError("LLM stream ended without completion marker")

    async def stream(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> AsyncIterator[str]:
        # 仅产出最终回答，不把思考过程混进正文
        async for part in self.stream_parts(prompt, system, max_tokens, temperature):
            if part.get("kind") == "content" and part.get("text"):
                yield part["text"]

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get(
                f"{self.api_base_url}/models",
                headers=self._build_headers(),
                timeout=10,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.warning("openai_health_check_failed", error=str(e))
            return False


class FallbackProvider(LLMProvider):
    """模型不可用时显式报错；流式可显示静态提示，但仍以失败结束。"""

    def __init__(self, primary: LLMProvider, fallback_message: Optional[str] = None):
        self.primary = primary
        self.fallback_message = fallback_message or "当前AI服务不可用，请稍后重试。"

    @property
    def metered_dispatch(self):
        return getattr(self.primary, "metered_dispatch", False)

    @property
    def name(self) -> str:
        return self.primary.name

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        try:
            return await self.primary.generate(prompt, system, max_tokens, temperature)
        except Exception as e:
            logger.warning("llm_fallback", error_type=type(e).__name__)
            raise LLMUnavailableError(self.fallback_message) from e

    async def stream(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> AsyncIterator[str]:
        yielded = False
        try:
            async for chunk in self.primary.stream(prompt, system, max_tokens, temperature):
                yielded = yielded or bool(chunk)
                yield chunk
        except Exception as e:
            logger.warning("llm_stream_fallback", error=str(e))
            # 已经产出过真实 token 时不再追加降级文案，否则用户看到半截答案 + 报错句
            if not yielded:
                yield self.fallback_message
            # 静态提示也不代表模型成功；让调用方明确标记失败。
            raise

    async def stream_parts(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> AsyncIterator[dict[str, str]]:
        yielded = False
        try:
            async for part in self.primary.stream_parts(prompt, system, max_tokens, temperature):
                yielded = yielded or bool(part.get("text"))
                yield part
        except Exception as e:
            logger.warning("llm_stream_parts_fallback", error=str(e))
            if not yielded:
                yield {"kind": "content", "text": self.fallback_message}
            raise

    async def chat_completion(
        self,
        messages: list[dict],
        tools: Optional[list] = None,
        tool_choice: str = "auto",
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> dict:
        """单轮工具调用失败必须上抛，不能伪装成无需工具的模型决策。"""
        try:
            return await self.primary.chat_completion(messages, tools, tool_choice, max_tokens, temperature)
        except Exception as e:  # noqa: BLE001
            logger.warning("llm_chat_completion_fallback", error_type=type(e).__name__)
            raise LLMUnavailableError(self.fallback_message) from e

    async def generate_with_images(
        self,
        prompt: str,
        images: list[dict],
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None,
    ) -> str:
        """带图片的生成（视觉模型）；异常时降级为纯文本生成。"""
        try:
            if hasattr(self.primary, "generate_with_images"):
                return await self.primary.generate_with_images(prompt, images, system, max_tokens, temperature, model)
        except Exception as e:  # noqa: BLE001
            logger.warning("llm_generate_with_images_fallback", error=str(e))
            return await self.primary.generate(prompt, system, max_tokens, temperature)
        # 主 provider 不支持视觉时降级为纯文本（此前直接落到函数末尾返回 None，
        # 调用方拿到 None 后再做 `"草稿" not in answer` 会抛 TypeError）。
        logger.info("llm_generate_with_images_unsupported", provider=type(self.primary).__name__)
        return await self.primary.generate(prompt, system, max_tokens, temperature)

    async def stream_parts_with_images(
        self,
        prompt: str,
        images: list[dict],
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None,
    ) -> AsyncIterator[dict[str, str]]:
        """视觉流仅在尚未输出时降级；已有内容后的异常必须交给调用方。"""
        yielded = False
        try:
            if hasattr(self.primary, "stream_parts_with_images"):
                async for part in self.primary.stream_parts_with_images(prompt, images, system, max_tokens, temperature, model):
                    yielded = yielded or bool(part.get("text"))
                    yield part
                return
        except Exception as e:  # noqa: BLE001
            logger.warning("llm_stream_parts_with_images_fallback", error=str(e))
            if yielded:
                raise
        async for part in self.stream_parts(prompt, system, max_tokens, temperature):
            yield part

    async def health_check(self) -> bool:
        return await self.primary.health_check()


def _normalize_provider_name(provider_name: str) -> str:
    return provider_name.strip().lower().replace("-", "_")


class FailoverProvider(LLMProvider):
    """主模型不可用时自动切换备用模型（A5：设计 §8 的 fallback 项）。

    只对核心文本能力（generate/stream/stream_parts）做故障切换；视觉能力与其它未覆写的方法
    通过 `__getattr__` 直接委托主 provider（备用模型通常不具备视觉能力）。主备都失败时异常
    继续外抛，由外层 `FallbackProvider` 给出静态降级文案。
    """

    def __init__(self, primary: LLMProvider, secondary: LLMProvider):
        self.primary = primary
        self.secondary = secondary

    @property
    def name(self) -> str:
        return f"{self.primary.name}->{self.secondary.name}"

    def __getattr__(self, item: str):
        # 防止 __init__ 之前/属性缺失时无限递归
        if item in {"primary", "secondary"}:
            raise AttributeError(item)
        return getattr(self.primary, item)

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        try:
            return await self.primary.generate(prompt, system, max_tokens, temperature)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "llm_failover_generate",
                primary=self.primary.name, fallback=self.secondary.name, error=str(exc),
            )
            return await self.secondary.generate(prompt, system, max_tokens, temperature)

    async def stream(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> AsyncIterator[str]:
        yielded = False
        try:
            async for chunk in self.primary.stream(prompt, system, max_tokens, temperature):
                yielded = yielded or bool(chunk)
                yield chunk
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "llm_failover_stream",
                primary=self.primary.name, fallback=self.secondary.name,
                yielded=yielded, error=str(exc),
            )
            # 不切备用，也不能把部分答案伪装成正常完成。
            if yielded:
                raise
        async for chunk in self.secondary.stream(prompt, system, max_tokens, temperature):
            yield chunk

    async def stream_parts(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> AsyncIterator[dict[str, str]]:
        yielded = False
        try:
            async for part in self.primary.stream_parts(prompt, system, max_tokens, temperature):
                yielded = yielded or bool(part.get("text"))
                yield part
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "llm_failover_stream_parts",
                primary=self.primary.name, fallback=self.secondary.name,
                yielded=yielded, error=str(exc),
            )
            if yielded:
                raise
        async for part in self.secondary.stream_parts(prompt, system, max_tokens, temperature):
            yield part

    async def health_check(self) -> bool:
        if await self.primary.health_check():
            return True
        return await self.secondary.health_check()


def _build_single_provider(
    provider_name: str, base_url: str, model: str, api_key: str, *,
    max_tokens: Optional[int] = None, temperature: Optional[float] = None, timeout: Optional[float] = None,
) -> LLMProvider:
    parameters = {"max_tokens": max_tokens, "temperature": temperature, "timeout": timeout}
    if provider_name in {"ollama", "local", "internal"}:
        return OllamaProvider(base_url=base_url, model=model, **parameters)
    if provider_name in {"openai_compatible", "openai"}:
        return OpenAICompatibleProvider(base_url=base_url, model=model, api_key=api_key, **parameters)
    raise ValueError(f"不支持的LLM Provider: {provider_name}")


def _resolve_override(overrides: dict[str, Any] | None, key: str, default: Any) -> Any:
    if not overrides:
        return default
    value = overrides.get(key, default)
    if value is None:
        return default
    if isinstance(value, str) and value.strip() == "":
        return default
    return value


def create_llm_provider(overrides: Optional[dict[str, Any]] = None) -> LLMProvider:
    settings = get_settings()
    provider_name = _normalize_provider_name(
        str(_resolve_override(overrides, "llm_provider", settings.llm_provider))
    )
    base_url = _resolve_override(overrides, "llm_base_url", settings.llm_base_url)
    model = _resolve_override(overrides, "llm_model", settings.llm_model)
    api_key = _resolve_override(overrides, "llm_api_key", settings.llm_api_key)

    parameters = {
        "max_tokens": int(_resolve_override(overrides, "llm_max_tokens", settings.llm_max_tokens)),
        "temperature": float(_resolve_override(overrides, "llm_temperature", settings.llm_temperature)),
        "timeout": float(_resolve_override(overrides, "llm_timeout", settings.llm_timeout)),
    }
    primary = _build_single_provider(provider_name, base_url, model, api_key, **parameters)

    # A5：配了备用模型就套一层故障切换（未配则维持原行为）
    fallback_model = str(
        _resolve_override(overrides, "llm_fallback_model", getattr(settings, "llm_fallback_model", "")) or ""
    ).strip()
    provider: LLMProvider = primary
    if fallback_model:
        fallback_base = str(
            _resolve_override(overrides, "llm_fallback_base_url", getattr(settings, "llm_fallback_base_url", ""))
            or base_url
        )
        fallback_key = str(
            _resolve_override(overrides, "llm_fallback_api_key", getattr(settings, "llm_fallback_api_key", ""))
            or api_key
        )
        try:
            secondary = _build_single_provider(provider_name, fallback_base, fallback_model, fallback_key, **parameters)
        except ValueError as exc:  # 备用 provider 名不合法：忽略备用，不阻塞主链路
            logger.warning("llm_fallback_build_failed", error=str(exc))
        else:
            provider = FailoverProvider(primary, secondary)
    return FallbackProvider(provider)
