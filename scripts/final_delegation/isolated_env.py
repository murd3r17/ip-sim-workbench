#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L2：可复用的三设备隔离开发环境（只允许 sim，不接真机/现用库）。

用法：
  python scripts/final_delegation/isolated_env.py init --run-dir .runtime/v7/final-delegation/dev-a
  python scripts/final_delegation/isolated_env.py status --run-dir ...
  python scripts/final_delegation/isolated_env.py stop --run-dir ...
  python scripts/final_delegation/isolated_env.py start --run-dir ...   # 重启已初始化实例

约束：默认只绑定 127.0.0.1；拒绝 DEVICE_MODE!=sim；数据库只允许在本实例目录中；进程归属以完整创建时间与启动身份核验；
不读取/修改根 .env；临时口令只写 run-dir/private/credentials.json（不打印）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import subprocess
import sys
import urllib.request
import runpy
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolation_boundary import build_environment, configure_child, validate_paths
import lifecycle
import process_owner

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
PY = BACKEND / ".venv" / "Scripts" / "python.exe"
NODE = Path(r"C:\Program Files\nodejs\node.exe")
VITE = ROOT / "sim-frontend" / "node_modules" / "vite" / "bin" / "vite.js"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_isolated(run_dir: Path, db: Path) -> None:
    validate_paths(ROOT, run_dir, db)


def env_for(run_dir: Path, db: Path, backend_port: int, admin_password: str, jwt: str) -> dict:
    return build_environment(ROOT, run_dir, db, admin_password, jwt)


def run(cmd: list[str], env: dict, cwd: Path, timeout: int = 180) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


async def seed_identity_and_env(db_path: Path, run_dir: Path, admin_password: str) -> dict:
    ensure_isolated(run_dir, db_path)
    if os.environ.get('FINAL_DELEGATION_RUN') != str(run_dir.resolve()):
        raise RuntimeError('Seed must run inside the configured isolated worker')
    sys.path.insert(0, str(BACKEND))
    from sqlalchemy import select
    from core.database import init_db, close_db, get_session_factory
    from core.security import hash_password
    from modules.auth.models import User, UserRole
    from modules.device.models import Device
    from modules.trust.models import EnvironmentProfile

    await init_db()
    factory = get_session_factory()
    created = {}
    async with factory() as db:
        admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one_or_none()
        normal = (await db.execute(select(User).where(User.username == "demo-user"))).scalar_one_or_none()
        if normal is None:
            normal = User(username="demo-user", hashed_password=hash_password(admin_password[:20] + "U1"),
                          display_name="隔离普通用户", role=UserRole.USER, is_active=True)
            db.add(normal)
            await db.flush()
        devices = (await db.execute(select(Device).where(Device.hostname.in_(["R-1", "R-2", "R-3"])))).scalars().all()
        if len(devices) < 3:
            raise RuntimeError("seed_sim_devices 未提供 R-1/R-2/R-3")
        if admin is not None:
            env = (await db.execute(select(EnvironmentProfile).where(EnvironmentProfile.name == "隔离三设备"))).scalar_one_or_none()
            if env is None:
                env = EnvironmentProfile(
                    name="隔离三设备", version="v1", status="draft", source="manual",
                    devices=[{"device_id": d.id, "role": d.hostname, "mgmt_ip": d.mgmt_ip,
                              "interfaces": [{"name": "GigabitEthernet0/0/0", "address": "10.0.123.1/24"}]}
                             for d in devices],
                    protections=[{"kind": "mgmt_port", "target": "GigabitEthernet0/0/0", "device_id": d.id,
                                   "role": d.hostname, "note": "隔离管理口，禁止写"} for d in devices],
                    created_by=admin.id,
                )
                db.add(env)
                await db.flush()
            created = {"environment_id": env.id, "device_ids": {d.hostname: d.id for d in devices},
                       "normal_user_id": normal.id if normal else None,
                       "admin_id": admin.id}
        await db.commit()
    await close_db()
    return created


def http_json(url: str, method="GET", body=None, token=None, timeout=20):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def source_fingerprint() -> str:
    import hashlib
    h = hashlib.sha256()
    files = {BACKEND / 'main.py', ROOT / 'sim-frontend/vite.config.ts'}
    for directory in ('backend/core', 'backend/modules', 'backend/engines', 'backend/scripts',
                      'scripts/final_delegation', 'sim-frontend/src'):
        files.update(p for p in (ROOT / directory).rglob('*')
                     if p.is_file() and p.suffix in ('.py', '.ts', '.vue', '.css'))
    for p in sorted(files):
        h.update(p.relative_to(ROOT).as_posix().encode())
        h.update(b'\0'); h.update(p.read_bytes()); h.update(b'\0')
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("init", "start", "status", "stop", "_worker"):
        p = sub.add_parser(name)
        p.add_argument("--run-dir", required=True)
        if name == "init":
            p.add_argument("--backend-port", type=int, default=8101)
            p.add_argument("--frontend-port", type=int, default=5274)
            p.add_argument("--no-frontend", action="store_true")
        if name == '_worker':
            p.add_argument('--script', required=True, choices=['bootstrap_local.py', 'seed_sim_devices.py', 'seed_training_labs.py', 'identity', 'serve'])
            p.add_argument('--launch-id')
    args = ap.parse_args()
    if args.cmd == '_worker':
        return cmd_worker(args)
    result = getattr(lifecycle, args.cmd)(sys.modules[__name__], args)
    if args.cmd != 'status':
        print(json.dumps({'action': args.cmd, 'exit_code': result, 'run_dir': str(Path(args.run_dir).resolve())}))
    return result


def worker_command(run_dir: Path, script: str) -> list[str]:
    return [str(PY), '-B', str(Path(__file__).resolve()), '_worker', '--run-dir', str(run_dir), '--script', script]


def cmd_worker(args) -> int:
    run_dir = Path(args.run_dir).absolute()
    db = run_dir / 'isolated.sqlite3'
    ensure_isolated(run_dir, db)
    run_dir, db = run_dir.resolve(), db.resolve()
    creds = read_json(run_dir / 'private/credentials.json')
    env = env_for(run_dir, db, 0, creds['admin_password'], creds['jwt_secret'])
    if args.script == 'serve':
        inst = read_json(run_dir / 'instance.json')
        lifecycle.validate_instance(sys.modules[__name__], run_dir, inst)
        if args.launch_id != inst['launch_id'] or inst['status'] != 'STARTING':
            raise RuntimeError('Worker launch binding mismatch')
        env['WORKBENCH_LAUNCH_ID'] = args.launch_id
        record = process_owner.snapshot(os.getpid())
        record['kind'] = 'backend'
        write_json(run_dir / f'worker-{args.launch_id}.json', record)
    configure_child(ROOT, env)
    from core.config import get_settings
    settings = get_settings()
    from modules.knowledge.service import KnowledgeService
    knowledge = KnowledgeService.from_settings().provider
    checks = {
        'sqlite': settings.db_backend == 'sqlite',
        'database_owned': settings.db_url == env['DB_URL'],
        'sim_only': settings.device_mode == 'sim' and settings.deploy_simulate_only,
        'scheduler_off': not settings.monitor_scheduler_enabled,
        'knowledge_local': settings.knowledge_provider == 'local',
        'knowledge_textbook_root': knowledge.corpus_dir == (ROOT / 'knowledge/corpus/huawei-ip').resolve(),
        'knowledge_uploads_owned': knowledge.storage_dir == run_dir / 'knowledge-storage',
        'provider_keys_empty': not any((settings.llm_api_key, settings.knowledge_api_key,
                                        settings.llm_fallback_api_key, settings.device_default_password)),
        'log_dir_owned': Path(settings.log_dir).resolve() == run_dir / 'logs',
    }
    write_json(run_dir / f'config-{args.script}.json', checks)
    if not all(checks.values()):
        raise RuntimeError('Effective child configuration violated isolation checks')
    if args.script == 'serve':
        import uvicorn
        uvicorn.run('main:app', host='127.0.0.1', port=inst['backend_port'], reload=False)
    elif args.script == 'identity':
        write_json(run_dir / 'seed-identity.json', asyncio.run(seed_identity_and_env(db, run_dir, creds['admin_password'])))
    else:
        sys.argv = [args.script]
        runpy.run_path(str(BACKEND / 'scripts' / args.script), run_name='__main__')
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    raise SystemExit(main())
