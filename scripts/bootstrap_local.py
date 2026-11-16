"""Prepare and run the local SQLite workbench on Windows or Linux."""

from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "sim-frontend"


def prepare_environment(db_path: Path | None = None) -> dict[str, str]:
    env = {**os.environ, "DB_BACKEND": "sqlite", "DB_URL": "", "DEVICE_MODE": "sim",
           "KNOWLEDGE_PROVIDER": "local", "WORKBENCH_MODE": "minimal", "PYTHONUTF8": "1"}
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


def main() -> int:
    parser = argparse.ArgumentParser(description="安装并启动本地模拟工作台")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-start", action="store_true", help="初始化后退出")
    parser.add_argument("--start-only", action="store_true", help="启动已经初始化的实例")
    parser.add_argument("--skip-dependency-install", action="store_true", help="检查并复用已有虚拟环境")
    parser.add_argument("--rebuild-frontend", action="store_true")
    parser.add_argument("--db-path", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or (args.no_start and args.start_only):
        parser.error("请填写有效端口。--no-start 与 --start-only 不能同时使用。")

    env = prepare_environment(args.db_path)
    interpreter = BACKEND / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not args.no_start:
        _check_port(args.port)
    if not args.start_only:
        if not interpreter.is_file():
            if sys.version_info < (3, 11):
                raise RuntimeError("需要 Python 3.11 或以上版本，推荐 Python 3.12。")
            try:
                venv.EnvBuilder(with_pip=True).create(interpreter.parent.parent)
            except (OSError, subprocess.CalledProcessError) as exc:
                raise RuntimeError("无法创建虚拟环境。请确认当前 Python 附带 venv 和 ensurepip；"
                                   "Debian/Ubuntu 可安装与 Python 版本对应的 python3-venv 软件包。") from exc
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
        ensure_local_config()
        backup = (args.backup_dir or ROOT / ".runtime/backups").resolve()
        subprocess.run([interpreter, "scripts/bootstrap_local.py", "--backup-dir", backup],
                       env=env, cwd=BACKEND, check=True)
        for script in ("seed_sim_devices.py", "seed_training_labs.py"):
            subprocess.run([interpreter, "scripts/" + script], env=env, cwd=BACKEND, check=True)
    if args.no_start:
        return 0
    if not interpreter.is_file() or not (FRONTEND / "dist/index.html").is_file():
        raise RuntimeError("请先运行 scripts/bootstrap_local.py 完成初始化。")
    print(f"启动后打开 http://127.0.0.1:{args.port}。账号见本机 .env，Ctrl+C 停止。", flush=True)
    if Path(sys.executable) != interpreter:
        return subprocess.run([interpreter, __file__, "--start-only", "--port", str(args.port)],
                              env=env, cwd=ROOT).returncode
    os.environ.update(env)
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))
    import uvicorn
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
