"""最小运行模式端到端验收：模拟"干净机器克隆后"的真实行为。

用法（在 backend 目录下）：
    .venv\\Scripts\\python.exe scripts\\verify_minimal_mode.py

退出码：0=全部通过；1=有失败项（可接 CI / 计划任务）。
"""
import asyncio
import os
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)


def read_env() -> dict:
    env = {}
    for line in (BACKEND.parent / ".env").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if m:
            env[m.group(1)] = m.group(2).strip()
    return env


async def main() -> int:
    env = read_env()
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, bool(ok), detail))
        print(f"  [{'OK ' if ok else 'FAIL'}] {name} {detail}")

    from core.database import init_db, close_db, resolve_database_url

    db_url = resolve_database_url()
    print("DB url      :", db_url)
    print("DEVICE_MODE :", os.environ.get("DEVICE_MODE") or env.get("DEVICE_MODE"))
    print("KB provider :", os.environ.get("KNOWLEDGE_PROVIDER") or env.get("KNOWLEDGE_PROVIDER"))
    check("使用 SQLite 最小模式", db_url.startswith("sqlite"), db_url)

    await init_db()
    import main as m
    from httpx import AsyncClient, ASGITransport

    async with AsyncClient(transport=ASGITransport(app=m.app), base_url="http://t") as c:
        r = await c.get("/")
        check("SPA 由后端托管", r.status_code == 200 and "<div id=" in r.text, f"HTTP {r.status_code}")

        r = await c.post("/api/v1/auth/login", json={
            "username": env.get("ADMIN_USERNAME", "admin"),
            "password": env.get("ADMIN_PASSWORD", ""),
        })
        check("管理员登录", r.status_code == 200, f"HTTP {r.status_code}")
        if r.status_code != 200:
            await close_db()
            return 1
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await c.get("/api/v1/devices", headers=h)
        device_count = len(r.json()) if r.status_code == 200 else 0
        check("模拟设备已播种", r.status_code == 200 and device_count > 0, f"count={device_count}")

        r = await c.get("/api/v1/training/labs", headers=h)
        lab_count = len(r.json()) if r.status_code == 200 else 0
        check("实训实验已播种", r.status_code == 200 and lab_count >= 4, f"count={lab_count}")

        r = await c.get("/api/v1/ai/knowledge/health", headers=h)
        j = r.json() if r.status_code == 200 else {}
        check(
            "本地知识库可用",
            r.status_code == 200 and bool(j.get("available")) and (j.get("document_count") or 0) > 0,
            f"provider={j.get('provider')} docs={j.get('document_count')}",
        )

        r = await c.post("/api/v1/ai/knowledge/search",
                         json={"question": "OSPF 邻居建立过程", "top_k": 3}, headers=h)
        body = r.json() if r.status_code == 200 else {}
        hits = body if isinstance(body, list) else body.get("sources", [])
        check("知识库检索有命中", r.status_code == 200 and len(hits) > 0,
              f"hits={len(hits)} top={(hits[0].get('filename') if hits else None)}")

        r = await c.get("/api/v1/dashboard/summary", headers=h)
        total = (r.json() or {}).get("devices", {}).get("total") if r.status_code == 200 else None
        check("总览聚合可用", r.status_code == 200 and (total or 0) > 0, f"devices={total}")

    await close_db()

    failed = [name for name, ok, _ in checks if not ok]
    print("")
    print(f"--- {len(checks) - len(failed)}/{len(checks)} passed ---")
    if failed:
        print("FAILED:", ", ".join(failed))
        return 1
    print("最小运行模式验收通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
