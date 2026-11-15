"""Negative boundaries of the disposable launcher. No service/device I/O."""
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock
from contextlib import nullcontext

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/final_delegation'))
import isolation_boundary as boundary
import lifecycle
import process_owner as owner


@pytest.fixture
def tool(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location('isolated_env_under_test', ROOT / 'scripts/final_delegation/isolated_env.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    return module


@pytest.mark.parametrize('run_name,db_name', [('', 'x.db'), ('.runtime', '.runtime/x.db'),
    ('.runtime/run-a', '.runtime/run-ab/x.db'), ('.runtime/run-a', 'outside/not-created.db'),
    ('.runtime/run-a', '.runtime/sim_workspace.db')])
def test_reject_paths_before_creation(tmp_path, run_name, db_name):
    with pytest.raises(ValueError):
        boundary.validate_paths(tmp_path, tmp_path / run_name, tmp_path / db_name)
    assert not (tmp_path / '.runtime').exists()


def test_valid_new_child_and_hard_link_rejection(tmp_path):
    run = tmp_path / '.runtime/run-a'
    boundary.validate_paths(tmp_path, run, run / 'db.sqlite3')
    run.mkdir(parents=True)
    db = run / 'db.sqlite3'
    db.write_text('sentinel')
    os.link(db, run / 'shared.sqlite3')
    with pytest.raises(ValueError, match='unshared'):
        boundary.validate_paths(tmp_path, run, db)


def test_reject_nested_linked_credentials(tmp_path, monkeypatch):
    run = tmp_path / '.runtime/run-a'
    (run / 'private').mkdir(parents=True)
    creds = run / 'private/credentials.json'
    creds.write_text('{}')
    original = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink', lambda p: p == creds or original(p))
    with pytest.raises(ValueError, match='links'):
        boundary.validate_paths(tmp_path, run, run / 'db.sqlite3')


def test_environment_drops_parent_configuration(monkeypatch, tmp_path):
    project = tmp_path / 'project'
    run = project / '.runtime' / 'isolation-test'
    scripts = project / 'scripts'
    scripts.mkdir(parents=True)
    runner = 'run-offline-tests.py'
    (scripts / runner).write_bytes((ROOT / 'scripts' / runner).read_bytes())
    for key in ('LLM_API_KEY', 'KNOWLEDGE_API_KEY', 'LLM_FALLBACK_API_KEY', 'DEVICE_DEFAULT_PASSWORD',
                'DB_PASSWORD', 'VITE_SECRET', 'HTTP_PROXY', 'PYTHONPATH'):
        monkeypatch.setenv(key, 'poison')
    monkeypatch.setenv('DB_BACKEND', 'mysql')
    monkeypatch.setenv('DEVICE_MODE', 'ssh')
    env = boundary.build_environment(project, run, run / 'isolated.sqlite3', 'temporary-test-value', 'temporary-test-jwt')
    assert 'poison' not in env.values()
    assert env['DB_BACKEND'] == 'sqlite' and env['DEVICE_MODE'] == 'sim'
    assert env['MONITOR_SCHEDULER_ENABLED'] == 'false'
    assert Path(env['KNOWLEDGE_CORPUS_DIR']) == project / 'knowledge/corpus/huawei-ip'
    for key in ('LOG_DIR', 'TEMP', 'TMP', 'KNOWLEDGE_ANYTHINGLLM_STORAGE', 'AGENT_BUDGET_FILE'):
        assert Path(env[key]).is_relative_to(run)


def test_local_knowledge_uploads_and_cached_provider_cannot_cross_instance(tmp_path, monkeypatch):
    from modules.knowledge import local_provider
    original = local_provider.DEFAULT_STORAGE_DIR
    monkeypatch.setattr(local_provider, 'DEFAULT_STORAGE_DIR', original)
    first_run = tmp_path / '.runtime/first'
    second_run = tmp_path / '.runtime/second'
    try:
        boundary.configure_local_knowledge(tmp_path, first_run)
        first = local_provider.get_local_provider(str(tmp_path / 'corpus'), 5, .2, 'same-workspace')
        boundary.configure_local_knowledge(tmp_path, second_run)
        second = local_provider.get_local_provider(str(tmp_path / 'corpus'), 5, .2, 'same-workspace')
        assert first is not second
        assert first.storage_dir == first_run / 'knowledge-storage'
        assert second.storage_dir == second_run / 'knowledge-storage'
        with pytest.raises(ValueError):
            boundary.configure_local_knowledge(tmp_path, tmp_path / 'outside')
        assert local_provider.DEFAULT_STORAGE_DIR == second.storage_dir
    finally:
        local_provider.get_local_provider.cache_clear()


@pytest.mark.parametrize('preflight', [{}, {'status': 'ready'}, {'status': 'draft', 'verification_mode': 'sim'},
                                     {'status': 'ready', 'verification_mode': 'ssh'}])
def test_preflight_not_ready_is_failure(preflight):
    with pytest.raises(RuntimeError):
        boundary.require_ready(preflight)


def test_ready_sim_accepted():
    boundary.require_ready({'status': 'ready', 'verification_mode': 'sim'})


@pytest.mark.parametrize('change', [{'created_ticks': 133999000000000002}, {'created_ticks': None},
                                  {'command': 'another command'}, {'pid': 999}, {'executable': 'foreign.exe'}])
def test_identity_needs_every_exact_field(change):
    record = {'pid': 100, 'created_ticks': 133999000000000001, 'command': 'owned', 'executable': 'python.exe'}
    assert not owner.same_process(record, dict(record, **change))


def test_stop_mismatch_never_opens_termination_handle(monkeypatch):
    record = {'pid': 100, 'created_ticks': 1, 'command': 'owned', 'executable': 'python.exe'}
    monkeypatch.setattr(owner, 'snapshot', lambda pid: dict(record, created_ticks=2))
    k = Mock(side_effect=AssertionError('Must not open terminate handle'))
    monkeypatch.setattr(owner, 'kernel', k)
    assert owner.stop_verified(record) == 'refused_identity_mismatch'
    k.assert_not_called()


def test_pid_reused_between_snapshot_and_handle_not_terminated(monkeypatch):
    record = {'pid': 100, 'created_ticks': 1, 'command': 'owned', 'executable': 'python.exe'}
    monkeypatch.setattr(owner, 'snapshot', lambda pid: record)
    k = Mock()
    monkeypatch.setattr(owner, 'kernel', lambda: k)
    monkeypatch.setattr(owner, 'open_process', lambda *a, **kw: 'handle')
    monkeypatch.setattr(owner, 'handle_identity', lambda *a: {'created_ticks': 2, 'executable': 'python.exe'})
    assert owner.stop_verified(record) == 'refused_identity_mismatch'
    k.TerminateProcess.assert_not_called()
    k.CloseHandle.assert_called_once_with('handle')


def test_parent_exiting_during_metadata_query_is_already_exited(monkeypatch):
    k = Mock()
    k.WaitForSingleObject.side_effect = [258, 0]
    monkeypatch.setattr(owner, 'kernel', lambda: k)
    monkeypatch.setattr(owner, 'open_process', lambda *a, **kw: 'handle')
    monkeypatch.setattr(owner, 'handle_identity', lambda *a: {'created_ticks': 1})
    monkeypatch.setattr(owner, 'powershell_json', lambda *a: None)
    assert owner.snapshot(100) is None
    k.CloseHandle.assert_called_once_with('handle')


def test_termination_failure_is_not_reported_as_stopped(monkeypatch):
    record = {'pid': 100, 'created_ticks': 1, 'command': 'owned', 'executable': 'python.exe'}
    monkeypatch.setattr(owner, 'snapshot', lambda pid: record)
    k = Mock()
    k.WaitForSingleObject.return_value = 258
    k.TerminateProcess.return_value = 0
    monkeypatch.setattr(owner, 'kernel', lambda: k)
    monkeypatch.setattr(owner, 'open_process', lambda *a, **kw: 'handle')
    monkeypatch.setattr(owner, 'handle_identity', lambda *a: record)
    assert owner.stop_verified(record) == 'failed_termination'


def test_healthy_foreign_port_not_adopted(monkeypatch):
    monkeypatch.setattr(owner, 'listener_pids', lambda port: {222222})
    monkeypatch.setattr(owner, 'snapshot', Mock(side_effect=AssertionError('Do not inspect/adopt foreign owner')))
    with pytest.raises(RuntimeError, match='another process'):
        lifecycle.wait_owned_listener(8101, {'pid': 111111})


def test_legacy_receipt_cannot_stop(tool, tmp_path, monkeypatch):
    run = tmp_path / '.runtime/run'
    run.mkdir(parents=True)
    tool.write_json(run / 'instance.json', {'db': str(run / 'isolated.sqlite3'), 'backend_pid': 1})
    stop = Mock(side_effect=AssertionError('Never stop a legacy PID'))
    monkeypatch.setattr(owner, 'stop_verified', stop)
    with pytest.raises(ValueError, match='legacy'):
        lifecycle.stop(tool, SimpleNamespace(run_dir=str(run)))
    stop.assert_not_called()


def test_busy_port_fails_before_directory_or_seed(tool, tmp_path, monkeypatch):
    run = tmp_path / '.runtime/new'
    monkeypatch.setattr(lifecycle, 'available_ports', Mock(side_effect=OSError('occupied')))
    with pytest.raises(OSError):
        lifecycle.init(tool, SimpleNamespace(run_dir=str(run), backend_port=8101, frontend_port=5274, no_frontend=False))
    assert not run.exists()


@pytest.mark.parametrize('ports', [(8101, 8101), (80, None), (8101, 65536), ('8101', None)])
def test_bad_port_rejected(ports):
    with pytest.raises(ValueError):
        lifecycle.validate_ports(*ports)


def test_failed_stop_preserves_failure_status(tool, tmp_path, monkeypatch):
    run = tmp_path / '.runtime/run'
    run.mkdir(parents=True)
    inst = {'processes': [{'kind': 'backend', 'pid': 1}]}
    monkeypatch.setattr(lifecycle, 'validate_instance', lambda *a: None)
    monkeypatch.setattr(owner, 'stop_verified', lambda *a: 'failed_termination')
    assert not lifecycle.stop_all(tool, run, inst)
    assert tool.read_json(run / 'instance.json')['status'] == 'STOP_FAILED'


def test_live_identity_matches_application_fingerprint(tool, tmp_path):
    from core.runtime_identity import runtime_identity
    from core.config import Settings
    run = tmp_path / '.runtime/run'
    settings = Settings(_env_file=None, db_backend='sqlite', db_url=f'sqlite+aiosqlite:///{(run / "isolated.sqlite3").as_posix()}')
    actual = runtime_identity(settings, root=tmp_path)
    expected = lifecycle.expected_identity(tool, run, {'launch_id': 'test'})
    assert actual['database_fingerprint'] == expected['database_fingerprint']
    assert actual['root_fingerprint'] == expected['root_fingerprint']


def test_preflight_failure_cleans_own_processes_and_cannot_be_ready(tool, tmp_path, monkeypatch):
    run = tmp_path / '.runtime/run'
    run.mkdir(parents=True)
    inst = {'backend_port': 18280, 'frontend_port': 18273, 'db': str(run / 'isolated.sqlite3'),
            'environment': {'environment_id': 1}}
    worker = {'pid': 101, 'parent_pid': 100, 'kind': 'backend'}
    spawned = []
    def spawn(*args):
        spawned.append(args[-1])
        tool.write_json(run / f"worker-{inst['launch_id']}.json", worker)
        return Mock(), {'pid': 100}
    monkeypatch.setattr(lifecycle, 'available_ports', lambda *a: nullcontext())
    monkeypatch.setattr(tool, 'env_for', lambda *a: {})
    monkeypatch.setattr(lifecycle, 'spawn', spawn)
    monkeypatch.setattr(owner, 'check_record', lambda *a: None)
    monkeypatch.setattr(owner, 'snapshot', lambda *a: worker)
    monkeypatch.setattr(owner, 'same_process', lambda *a: True)
    monkeypatch.setattr(lifecycle, 'wait_owned_listener', lambda *a: None)
    monkeypatch.setattr(lifecycle, 'token_for', lambda *a: 'local-test-token')
    monkeypatch.setattr(lifecycle, 'verified_identity', lambda *a: {})
    monkeypatch.setattr(tool, 'http_json', lambda *a: {'status': 'draft', 'verification_mode': 'sim'})
    stop = Mock(return_value=True)
    monkeypatch.setattr(lifecycle, 'stop_all', stop)
    with pytest.raises(RuntimeError, match='preflight'):
        lifecycle.launch(tool, run, inst, {'admin_password': 'local-test', 'jwt_secret': 'local-test'})
    assert spawned == ['launcher']
    stop.assert_called_once()
    assert tool.read_json(run / 'instance.json')['status'] == 'START_FAILED_CLEANED'


def test_status_reports_stale_receipt_not_ready(tool, tmp_path, monkeypatch, capsys):
    run = tmp_path / '.runtime/run'
    run.mkdir(parents=True)
    tool.write_json(run / 'instance.json', {'status': 'READY', 'processes': [{'kind': 'backend', 'pid': 10}]})
    monkeypatch.setattr(lifecycle, 'validate_instance', lambda *a: None)
    monkeypatch.setattr(owner, 'snapshot', lambda *a: None)
    assert lifecycle.status(tool, SimpleNamespace(run_dir=str(run))) == 2
    result = json.loads(capsys.readouterr().out)
    assert result['recorded_status'] == 'READY' and result['live_ready'] is False
    assert result['processes'][0]['state'] == 'exited'


def test_unknown_worker_cannot_be_claimed_cleanly_stopped(tool, tmp_path, monkeypatch):
    run = tmp_path / '.runtime/run'
    run.mkdir(parents=True)
    inst = {'processes': [], 'ownership_incomplete': True}
    monkeypatch.setattr(lifecycle, 'validate_instance', lambda *a: None)
    assert not lifecycle.stop_all(tool, run, inst)
    assert inst['status'] == 'STOP_FAILED'
