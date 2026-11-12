"""交付前的服务健康探测：端口 + HTTP 端点 + 关键依赖可用性。

不打印任何密钥。输出为逐项 OK/FAIL 与退出码（0=全绿）。
"""
from __future__ import annotations

import json
import socket
import sys
import urllib.error
import urllib.request

PORTS = [
    (11434, "Ollama（本地嵌入模型）"),
    (3001, "AnythingLLM（知识库）"),
    (13307, "MySQL（工作台数据库）"),
    (9002, "MinIO（对象存储）"),
    (8000, "后端 API + SPA"),
    (5173, "前端 Vite 开发服务器"),
]

HTTP_CHECKS = [
    ("GET", "http://127.0.0.1:11434/api/tags", "Ollama API 可访问"),
    ("GET", "http://127.0.0.1:8000/api/v1/health", "后端健康检查"),
    ("GET", "http://127.0.0.1:8000/docs", "后端 Swagger 文档"),
    ("GET", "http://127.0.0.1:8000/", "后端托管的 SPA 首页"),
    ("GET", "http://127.0.0.1:5173/", "前端首页"),
]


def tcp(port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except Exception:
        return False


def http_get(url: str, timeout: float = 15.0, limit: int = 4096) -> tuple[int | None, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read(limit).decode("utf-8", "ignore")
            return resp.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception as exc:
        return None, type(exc).__name__


def main() -> int:
    failures: list[str] = []

    print("== 端口 ==")
    for port, label in PORTS:
        ok = tcp(port)
        print(f"  [{'OK ' if ok else 'FAIL'}] {port:<6} {label}")
        if not ok:
            failures.append(f"端口 {port} 未监听（{label}）")

    print("\n== HTTP ==")
    for method, url, label in HTTP_CHECKS:
        status, body = http_get(url)
        ok = status == 200
        extra = ""
        if url.endswith("/api/v1/health") and body:
            try:
                data = json.loads(body)
                extra = f" status={data.get('status') or data.get('database_status')}"
            except Exception:
                extra = ""
        if url.endswith(":8000/") and body:
            extra = " 含 <div id=" if "<div id=" in body else " 未见 SPA 容器"
            ok = ok and "<div id=" in body
        print(f"  [{'OK ' if ok else 'FAIL'}] {label} -> HTTP {status}{extra}")
        if not ok:
            failures.append(f"{label} 失败（HTTP {status}）")

    print("\n== AnythingLLM 工作区 ==")
    status, body = http_get("http://127.0.0.1:3001/api/v1/workspaces", 20.0)
    reachable = status in (200, 401, 403)
    print(f"  [{'OK ' if reachable else 'FAIL'}] AnythingLLM API 可达（HTTP {status}，401 属正常：需要 API Key）")
    if not reachable:
        failures.append("AnythingLLM API 不可达")

    print()
    if failures:
        print(f"共 {len(failures)} 项未通过：")
        for item in failures:
            print("  -", item)
        return 1
    print("全部服务健康：6 端口 + 5 HTTP 端点均正常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
