"""Path/config boundaries for disposable V7 development instances.

No application import or disk mutation happens before validate_paths succeeds.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import os
from pathlib import Path
import sys


def validate_paths(root: Path, run_dir: Path, db: Path) -> None:
    root = root.resolve()
    runtime = root / '.runtime'
    # Do not let resolve() hide a symlink/junction leading to another instance.
    for raw in (runtime, run_dir, db):
        absolute = Path(os.path.abspath(raw))
        for item in (absolute, *absolute.parents):
            if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
                raise ValueError('Isolation paths cannot traverse links or junctions')
    run_dir, db = run_dir.resolve(), db.resolve()
    if run_dir == runtime or not run_dir.is_relative_to(runtime):
        raise ValueError('run-dir must be a strict child of this repository .runtime')
    if db == run_dir or not db.is_relative_to(run_dir):
        raise ValueError('Database must be inside this exact run-dir, even before it exists')
    for live in (runtime / 'sim_workspace.db', root / 'data/workbench.db'):
        if db == live.resolve():
            raise ValueError('Refusing the existing workspace database')
    if db.exists() and (not db.is_file() or db.stat().st_nlink > 1):
        raise ValueError('Database must be a regular, unshared file')
    if run_dir.exists():
        for folder, dirs, files in os.walk(run_dir, followlinks=False):
            for name in dirs + files:
                item = Path(folder) / name
                if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
                    raise ValueError('Instance files cannot traverse links or junctions')
                if item.is_file() and item.stat().st_nlink > 1:
                    raise ValueError('Instance files cannot share hard links')


def build_environment(root: Path, run_dir: Path, db: Path, admin_password: str, jwt: str) -> dict:
    validate_paths(root, run_dir, db)
    spec = importlib.util.spec_from_file_location('isolated_test_environment', root / 'scripts/run-offline-tests.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    env = runner.isolated_environment(run_dir, 'sim')
    # Reuse the tested OS-variable allowlist. No inherited provider/device keys.
    env.update({
        'DB_URL': f'sqlite+aiosqlite:///{db.resolve().as_posix()}',
        'DB_AUTO_CREATE': 'true', 'ADMIN_USERNAME': 'admin',
        'ADMIN_PASSWORD': admin_password, 'JWT_SECRET_KEY': jwt,
        'FERNET_KEY': base64.urlsafe_b64encode(hashlib.sha256(jwt.encode()).digest()).decode(),
        'FINAL_DELEGATION_RUN': str(run_dir.resolve()), 'PYTHONIOENCODING': 'utf-8',
        'KNOWLEDGE_CORPUS_DIR': str(root / 'knowledge/corpus/huawei-ip'),
    })
    return env


def configure_child(root: Path, env: dict) -> None:
    """Must run before importing any application/seed module in this process."""
    os.environ.clear()
    os.environ.update(env)
    sys.path.insert(0, str(root / 'backend'))
    import dotenv
    dotenv.load_dotenv = lambda *args, **kwargs: False
    from core.config import Settings, get_settings
    Settings.model_config['env_file'] = None
    get_settings.cache_clear()
    configure_local_knowledge(root, Path(env['FINAL_DELEGATION_RUN']))


def configure_local_knowledge(root: Path, run_dir: Path) -> None:
    """Worker-only upload scope; never change a running application's provider.

    Called after replacing the child environment, before constructing a local
    provider. Keep repo textbook reads separate from each instance's uploads.
    """
    validate_paths(root, run_dir, run_dir / 'isolated.sqlite3')
    from modules.knowledge import local_provider
    local_provider.DEFAULT_STORAGE_DIR = run_dir.resolve() / 'knowledge-storage'
    local_provider.get_local_provider.cache_clear()


def require_ready(preflight: dict) -> None:
    if preflight.get('status') != 'ready' or preflight.get('verification_mode') != 'sim':
        raise RuntimeError('Isolated environment preflight did not reach ready/sim; no extra observations collected')
