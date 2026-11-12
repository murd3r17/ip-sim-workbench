"""httpx 客户端池：按配置去重复用，避免每请求新建客户端导致连接/句柄泄漏。

背景：LLM/Knowledge provider 每请求构造一次（llm_provider、ragflow.py 等），
若每个实例都新建 httpx.AsyncClient 且从不关闭，长期运行连接只增不减。
本池按 (timeout, trust_env, follow_redirects) 去重，相同配置复用同一客户端；
进程关闭时由 main.py lifespan 统一 close_all_clients()。

注意 trust_env 语义不可混用：
  - LLM 提供方（DeepSeek 等）需 trust_env=True 走系统代理（本机梯子）
  - 知识库提供方（RAGFlow 127.0.0.1:9380 等）需 trust_env=False 绕过代理劫持
"""
import threading

import httpx

_POOL: dict[tuple, httpx.AsyncClient] = {}
_LOCK = threading.Lock()


def get_managed_client(*, timeout: float, trust_env: bool, follow_redirects: bool = True) -> httpx.AsyncClient:
    """获取（必要时创建）符合给定配置的共享客户端。

    timeout 拆成 connect/read/write/pool 四段：此前单一 float 也作用在"从池里
    取连接"上，池排队最坏会等满整个 timeout。
    """
    key = (timeout, trust_env, follow_redirects)
    with _LOCK:
        client = _POOL.get(key)
        if client is None:
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(timeout, connect=min(timeout, 10.0), pool=10.0),
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
                trust_env=trust_env,
                follow_redirects=follow_redirects,
            )
            _POOL[key] = client
        return client


async def close_all_clients() -> None:
    """关闭全部共享客户端（应用退出时调用）。"""
    global _POOL
    with _LOCK:
        clients = list(_POOL.values())
        _POOL = {}
    for client in clients:
        try:
            await client.aclose()
        except Exception:
            pass
