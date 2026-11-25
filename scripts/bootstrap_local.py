"""Prepare and run the local SQLite workbench on Windows or Linux."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "sim-frontend"
DEMO_DIR = ROOT / ".runtime" / "demo"
DEMO_CREDENTIAL = ("admin", "123456")
VENV_HELP = ("无法准备 Python 虚拟环境。Ubuntu 24.04 请先安装 python3.12-venv，"
             "其他 Debian/Ubuntu 版本请安装与 Python 对应的 venv 软件包，然后重试原命令。")


def demo_secrets() -> dict[str, str]:
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    path = DEMO_DIR / "instance.json"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {"JWT_SECRET_KEY": secrets.token_urlsafe(48),
                "FERNET_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")}
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream)
    return {key: data[key] for key in ("JWT_SECRET_KEY", "FERNET_KEY")}


def prepare_environment(db_path: Path | None = None, *, demo: bool = False) -> dict[str, str]:
    env = {**os.environ, "DB_BACKEND": "sqlite", "DB_URL": "", "DEVICE_MODE": "sim",
           "KNOWLEDGE_PROVIDER": "local", "WORKBENCH_MODE": "minimal", "PYTHONUTF8": "1"}
    env.pop("IP_SIM_DEMO", None)
    if demo:
        db_path = DEMO_DIR / "workbench.sqlite3"
        env.update(demo_secrets())
        env.update(IP_SIM_DEMO="1", ADMIN_USERNAME=DEMO_CREDENTIAL[0], ADMIN_PASSWORD=DEMO_CREDENTIAL[1],
                   API_PREFIX="/api/v1", CORS_ORIGINS="", API_DOCS_ENABLED="false", DEBUG="false",
                   DEPLOY_SIMULATE_ONLY="true", MONITOR_SCHEDULER_ENABLED="false",
                   MINIO_ACCESS_KEY="", MINIO_SECRET_KEY="", MINIO_REQUIRED="false",
                   KNOWLEDGE_CORPUS_DIR=str(ROOT / "knowledge" / "corpus" / "huawei-ip"),
                   KNOWLEDGE_LOCAL_STORAGE=str(DEMO_DIR / "knowledge"), LOG_DIR=str(DEMO_DIR / "logs"),
                   KNOWLEDGE_EDITION_DIR="", KNOWLEDGE_PREVIOUS_EDITION_DIR="", KNOWLEDGE_ORIGINAL_DIR="",
                   LLM_PROVIDER="openai_compatible", LLM_BASE_URL="https://api.deepseek.com",
                   LLM_MODEL="deepseek-flash", LLM_API_KEY="", LLM_VISION_MODEL="",
                   LLM_FALLBACK_MODEL="", LLM_FALLBACK_API_KEY="", LLM_FALLBACK_BASE_URL="")
    if db_path is not None:
        resolved = db_path.expanduser().resolve()
        env["DB_SQLITE_PATH"] = str(resolved)
    return env


def ensure_local_config() -> None:
    path = ROOT / ".env"
    if path.is_file() or (BACKEND / ".env").is_file():
        print("使用现有本地配置；初始化不会重置现有账号。", flush=True)
        return
    values = {
        "JWT_SECRET_KEY": secrets.token_urlsafe(48),
        "FERNET_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"),
        "ADMIN_PASSWORD": "A7a-" + secrets.token_urlsafe(18),
        "DB_PASSWORD": "", "LLM_API_KEY": "", "KNOWLEDGE_API_KEY": "",
        "LLM_BASE_URL": "http://127.0.0.1:1", "DB_BACKEND": "sqlite", "DEVICE_MODE": "sim",
        "KNOWLEDGE_PROVIDER": "local",
    }
    template = (ROOT / ".env.example").read_text(encoding="utf-8-sig")
    for key, value in values.items():
        pattern = rf"(?m)^(?:# )?{re.escape(key)}=.*$"
        template, replaced = re.subn(pattern, f"{key}={value}", template, count=1)
        if not replaced:
            template += f"\n{key}={value}\n"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(template)
    except FileExistsError:
        return
    print("已生成本机根 .env。请在文件中查看 ADMIN_USERNAME 和 ADMIN_PASSWORD。", flush=True)


def _check_port(port: int) -> None:
    with socket.socket() as listener:
        if sys.platform == "win32":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError as exc:
            raise RuntimeError(f"无法监听本机端口 {port}。请确认端口可用，或通过 --port 指定其他端口。") from exc


def _local_directory(path: Path) -> bool:
    return (path.is_dir() and not path.is_symlink() and path.resolve() == path
            and not (getattr(path.lstat(), "st_file_attributes", 0)
                     & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)))


def _pip_available(interpreter: Path) -> bool:
    if not interpreter.is_file():
        return False
    try:
        result = subprocess.run([interpreter, "-I", "-m", "pip", "--version"], capture_output=True)
    except OSError:
        return False
    return result.returncode == 0


def _prepare_venv(interpreter: Path) -> None:
    if _pip_available(interpreter):
        return
    path = interpreter.parent.parent
    if sys.version_info < (3, 11):
        raise RuntimeError("需要 Python 3.11 或以上版本，推荐 Python 3.12。")
    try:
        path.mkdir()
        created = True
    except FileExistsError:
        created = False
        if not _local_directory(path) or not (path / "pyvenv.cfg").is_file():
            raise RuntimeError(f"{path} 已存在且无法识别为 Python 虚拟环境，请先检查该目录。") from None
    try:
        # Running the venv CLI as a child also catches distributions that call
        # sys.exit directly when ensurepip is missing.
        base_python = getattr(sys, "_base_executable", None) or sys.executable
        subprocess.run([base_python, "-I", "-m", "venv", path], check=True)
        if not _pip_available(interpreter):
            raise RuntimeError(VENV_HELP)
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        if created and _local_directory(path):
            shutil.rmtree(path)
        raise RuntimeError(VENV_HELP) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="安装并启动本地模拟工作台")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-start", action="store_true", help="初始化后退出")
    parser.add_argument("--start-only", action="store_true", help="启动已经初始化的实例")
    parser.add_argument("--demo", action="store_true", help="启动仅对本机开放的独立演示环境")
    parser.add_argument("--skip-dependency-install", action="store_true", help="检查并复用已有虚拟环境")
    parser.add_argument("--rebuild-frontend", action="store_true")
    parser.add_argument("--db-path", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or (args.no_start and args.start_only):
        parser.error("请填写有效端口。--no-start 与 --start-only 不能同时使用。")
    if args.demo and args.db_path is not None:
        parser.error("--demo 使用独立演示库，不能同时指定 --db-path。")
    if args.demo and args.start_only and not (DEMO_DIR / "workbench.sqlite3").is_file():
        parser.error("请先运行 --demo 完成演示环境初始化。")

    interpreter = BACKEND / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not args.no_start:
        _check_port(args.port)
    if not args.start_only:
        _prepare_venv(interpreter)
    env = prepare_environment(args.db_path, demo=args.demo)
    if not args.start_only:
        if not args.skip_dependency_install:
            subprocess.run([interpreter, "-m", "pip", "install", "-r", BACKEND / "requirements.lock"],
                           env=env, cwd=BACKEND, check=True)
        subprocess.run([interpreter, "-m", "pip", "check"], env=env, cwd=BACKEND, check=True)
        if args.rebuild_frontend or not (FRONTEND / "dist/index.html").is_file():
            npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
            if not npm:
                raise RuntimeError("缺少预构建前端。请使用含 dist 的交付包，或安装 Node 后构建。")
            subprocess.run([npm, "ci"], cwd=FRONTEND, check=True, env=env)
            subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True, env=env)
        if not args.demo:
            ensure_local_config()
        backup = (args.backup_dir or (DEMO_DIR if args.demo else ROOT / ".runtime") / "backups").resolve()
        subprocess.run([interpreter, "scripts/bootstrap_local.py", "--backup-dir", backup],
                       env=env, cwd=BACKEND, check=True)
        for script in ("seed_sim_devices.py", "seed_training_labs.py"):
            subprocess.run([interpreter, "scripts/" + script], env=env, cwd=BACKEND, check=True)
    if args.no_start:
        print("本地初始化完成。", flush=True)
        return 0
    if not interpreter.is_file() or not (FRONTEND / "dist/index.html").is_file():
        raise RuntimeError("请先运行 scripts/bootstrap_local.py 完成初始化。")
    if Path(sys.prefix).resolve() != interpreter.parent.parent:
        start = [interpreter, __file__, "--start-only", "--port", str(args.port)]
        if args.demo:
            start.append("--demo")
        return subprocess.run(start, env=env, cwd=ROOT).returncode
    os.environ.update(env)
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))
    import uvicorn
    login = "演示账号 admin / 123456" if args.demo else "账号见本机 .env"
    print(f"启动后打开 http://127.0.0.1:{args.port}。{login}，Ctrl+C 停止。", flush=True)
    uvicorn.run("main:app", host="127.0.0.1", port=args.port, proxy_headers=False)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"准备工作台失败（退出码 {exc.returncode}）。请查看上方步骤的具体提示。", file=sys.stderr)
        raise SystemExit(1)
    except (OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
