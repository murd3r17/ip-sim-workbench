"""负载验证：模拟 16-30 名并发用户访问主要只读接口，输出 P50/P95/P99 与错误率。

对照《详细开发计划V6.0》§16 并发与性能底线：
  - 30 名用户可同时登录和浏览页面；
  - 首页聚合接口 P95 ≤ 2s；普通列表/详情 API P95 ≤ 1s；
  - 慢接口必须有 loading（前端），后端这里只量延迟。

用法（backend 目录下）：
    .venv\\Scripts\\python.exe scripts\\load_probe.py                     # 默认 30 用户 / 120 秒
    .venv\\Scripts\\python.exe scripts\\load_probe.py --users 16 --duration 60
    .venv\\Scripts\\python.exe scripts\\load_probe.py --report .runtime/load_probe.json

退出码：0 = 全部达标；1 = 有接口超过 P95 阈值或有错误率超标。
不打印任何口令。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

# (名称, 方法, 路径, P95 阈值毫秒) —— 阈值为 None 表示不计入达标判定
ENDPOINTS: list[tuple[str, str, str, int | None]] = [
    ("dashboard/summary", "GET", "/api/v1/dashboard/summary", 2000),
    ("devices", "GET", "/api/v1/devices", 1000),
    ("deploy/tasks", "GET", "/api/v1/deploy/tasks", 1000),
    ("training/labs", "GET", "/api/v1/training/labs", 1000),
    ("alarms", "GET", "/api/v1/alarms", 1000),
    ("system/info", "GET", "/api/v1/system/info", 1000),
    ("monitor/stats", "GET", "/api/v1/monitor/stats", 1000),
]

MAX_ERROR_RATE = 0.02  # 2%


def response_error(name, response) -> str | None:
    """A redirect, HTML login page, or JSON error envelope isn't an API sample."""
    if response.status_code != 200:
        return f"HTTP {response.status_code}"
    try:
        body = response.json()
    except ValueError:
        return "invalid_json"
    if name in {"devices", "deploy/tasks", "training/labs", "alarms"}:
        return None if isinstance(body, list) and all(isinstance(row, dict) and "id" in row for row in body) else "invalid_api_shape"
    fields = {
        "dashboard/summary": {"generated_at", "devices", "tasks", "alarms", "services"},
        "system/info": {"app_name", "database_status", "llm_status", "device_count"},
        "monitor/stats": {"totalDevices", "onlineDevices", "activeAlarms", "warningAlarms"},
    }
    return None if isinstance(body, dict) and fields.get(name, {"__unknown__"}) <= body.keys() else "invalid_api_shape"


def read_env() -> dict:
    from core.config import get_settings
    settings = get_settings()
    return {"ADMIN_USERNAME": settings.admin_username, "ADMIN_PASSWORD": settings.admin_password}


def login(target: str, env: dict) -> str:
    username = env.get("ADMIN_USERNAME", "admin")
    password = env.get("ADMIN_PASSWORD", "")
    if not password:
        raise SystemExit("根 .env 未配置 ADMIN_PASSWORD，无法登录（脚本不会硬编码口令）")
    body = json.dumps({"username": username, "password": password}).encode()
    req = urllib.request.Request(
        f"{target}/api/v1/auth/login", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    token = payload.get("access_token")
    if not token:
        raise SystemExit("登录成功但未返回 access_token")
    return token


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(ratio * len(ordered))) - 1))
    return ordered[index]


async def run(target: str, users: int, duration: float, token: str) -> dict:
    import httpx

    limits = httpx.Limits(max_connections=users * 4, max_keepalive_connections=users * 2)
    timeout = httpx.Timeout(60.0, connect=10.0)
    samples: dict[str, list[float]] = {name: [] for name, *_ in ENDPOINTS}
    errors: dict[str, dict[str, int]] = {name: {} for name, *_ in ENDPOINTS}
    attempts = {name: 0 for name, *_ in ENDPOINTS}
    headers = {"Authorization": f"Bearer {token}"}
    deadline = time.perf_counter() + duration
    request_count = 0
    lock = asyncio.Lock()

    async with httpx.AsyncClient(base_url=target, limits=limits, timeout=timeout, headers=headers, trust_env=False) as client:
        async def worker(worker_id: int) -> None:
            nonlocal request_count
            index = worker_id
            while time.perf_counter() < deadline:
                name, method, path, _ = ENDPOINTS[index % len(ENDPOINTS)]
                index += 1
                attempts[name] += 1
                started = time.perf_counter()
                try:
                    resp = await client.request(method, path)
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    async with lock:
                        samples[name].append(elapsed_ms)
                        request_count += 1
                        key = response_error(name, resp)
                        if key:
                            errors[name][key] = errors[name].get(key, 0) + 1
                except Exception as exc:  # noqa: BLE001
                    async with lock:
                        key = type(exc).__name__
                        errors[name][key] = errors[name].get(key, 0) + 1
                        request_count += 1

        await asyncio.gather(*(worker(i) for i in range(users)))
    return {"samples": samples, "errors": errors, "attempts": attempts,
            "request_count": request_count}


def report(result: dict, users: int, duration: float, target: str) -> tuple[dict, bool]:
    rows = []
    ok_all = True
    for name, _, _, threshold in ENDPOINTS:
        values = result["samples"][name]
        errs = result["errors"][name]
        error_count = sum(errs.values())
        # HTTP failures already have a latency sample. Count each attempt once.
        total = result["attempts"][name]
        row = {
            "endpoint": name,
            "requests": total,
            "errors": error_count,
            "error_rate": round(error_count / total, 4) if total else 0.0,
            "p50_ms": round(percentile(values, 0.50), 1),
            "p95_ms": round(percentile(values, 0.95), 1),
            "p99_ms": round(percentile(values, 0.99), 1),
            "max_ms": round(max(values), 1) if values else 0.0,
            "p95_threshold_ms": threshold,
        }
        if values:
            row["mean_ms"] = round(statistics.fmean(values), 1)
        violations = []
        if not total or not values:
            violations.append("没有有效采样，不能判断达标")
        if threshold is not None and values and row["p95_ms"] > threshold:
            violations.append(f"P95 {row['p95_ms']}ms > {threshold}ms")
        if total and error_count / total > MAX_ERROR_RATE:
            violations.append(f"错误率 {row['error_rate']:.1%} > {MAX_ERROR_RATE:.0%}")
        row["violations"] = violations
        if violations:
            ok_all = False
        rows.append(row)

    summary = {
        "target": target,
        "users": users,
        "duration_seconds": duration,
        "total_requests": result["request_count"],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "endpoints": rows,
        "passed": ok_all,
    }
    return summary, ok_all


def main() -> int:
    parser = argparse.ArgumentParser(description="只读接口负载验证（对照设计 §16 性能底线）")
    parser.add_argument("--users", type=int, default=30)
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--target", default="http://127.0.0.1:8000")
    parser.add_argument("--report", default=str(ROOT / ".runtime" / "logs" / "load_probe.json"))
    args = parser.parse_args()

    env = read_env()
    print(f"目标 {args.target} | 并发 {args.users} | 时长 {args.duration:.0f}s")
    token = login(args.target, env)
    print("登录成功，开始压测…")

    result = asyncio.run(run(args.target, args.users, args.duration, token))
    summary, ok = report(result, args.users, args.duration, args.target)

    print()
    print(f"{'接口':<20}{'请求':>7}{'错误':>7}{'P50(ms)':>10}{'P95(ms)':>10}{'P99(ms)':>10}{'阈值':>8}")
    for row in summary["endpoints"]:
        print(
            f"{row['endpoint']:<20}{row['requests']:>7}{row['errors']:>7}"
            f"{row['p50_ms']:>10}{row['p95_ms']:>10}{row['p99_ms']:>10}"
            f"{(row['p95_threshold_ms'] or '-'):>8}"
        )
    print(f"\n总请求 {summary['total_requests']}｜结果：{'达标' if ok else '有超标项'}")
    for row in summary["endpoints"]:
        for violation in row["violations"]:
            print(f"  ! {row['endpoint']}: {violation}")

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告：{report_path}")
    print("范围：一个管理员登录后的并发只读 HTTP 请求；不代表多账户同时登录或 5-10 个真实 WebSSH 会话。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
