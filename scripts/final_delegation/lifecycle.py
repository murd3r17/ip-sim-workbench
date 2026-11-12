"""Lifecycle of disposable instances; imported without loading application config."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import time

from isolation_boundary import validate_paths, require_ready
import process_owner as owner


def validate_instance(tool, run_dir, inst):
    validate_paths(tool.ROOT, run_dir, Path(inst['db']))
    if (inst.get('schema') != 2 or inst.get('run_dir') != str(run_dir)
            or inst.get('db') != str(run_dir / 'isolated.sqlite3')
            or inst.get('device_mode') != 'sim'
            or not re.fullmatch('[a-f0-9]{32}', inst.get('launch_id', ''))):
        raise ValueError('Unbound or legacy instance receipt; do not adopt its processes')
    validate_ports(inst['backend_port'], inst.get('frontend_port'))
    for record in inst.get('processes', []):
        owner.check_record(record, inst['launch_id'], run_dir, Path(tool.__file__).resolve())


def validate_ports(backend, frontend):
    ports = [backend] + ([frontend] if frontend is not None else [])
    if any(type(p) is not int or not 1024 <= p <= 65535 for p in ports) or len(set(ports)) != len(ports):
        raise ValueError('Distinct local development ports in 1024..65535 required')


@contextmanager
def available_ports(backend, frontend):
    validate_ports(backend, frontend)
    sockets = []
    try:
        for port in [backend] + ([frontend] if frontend is not None else []):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sockets.append(sock)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(('127.0.0.1', port))
            sock.listen(1)
        yield
    finally:
        for sock in sockets:
            sock.close()


@contextmanager
def locked(run_dir):
    # No PID-based stale-lock stealing. An interrupted operation stays explicit.
    lock = run_dir / 'operation.lock'
    with lock.open('x', encoding='utf-8') as file:
        file.write(str(os.getpid()))
    try:
        yield
    finally:
        lock.unlink()


def paths(tool, raw):
    run_dir = Path(raw).absolute()
    validate_paths(tool.ROOT, run_dir, run_dir / 'isolated.sqlite3')
    return run_dir.resolve()


def checkpoint(tool, run_dir, inst):
    inst['updated_at'] = tool.now()
    tool.write_json(run_dir / 'instance.json', inst)


def spawn(tool, run_dir, inst, env, kind):
    if kind == 'launcher':
        command = tool.worker_command(run_dir, 'serve') + ['--launch-id', inst['launch_id']]
        cwd = tool.BACKEND
    else:
        command = [str(tool.NODE), str(tool.VITE), '--host', '127.0.0.1', '--port',
                   str(inst['frontend_port']), '--strictPort', '--mode', f"isolated-{inst['launch_id']}"]
        cwd = tool.ROOT / 'sim-frontend'
        env = dict(env, VITE_API_TARGET=f"http://127.0.0.1:{inst['backend_port']}",
                   VITE_WS_TARGET=f"ws://127.0.0.1:{inst['backend_port']}")
    with (run_dir / 'logs' / f'{kind}.log').open('a', encoding='utf-8') as out:
        proc = subprocess.Popen(command, cwd=cwd, env=env, stdout=out, stderr=subprocess.STDOUT,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        record = owner.snapshot(proc.pid)
    except Exception:
        # Popen holds the exact Windows process handle, unlike a later PID lookup.
        proc.terminate()
        proc.wait(timeout=5)
        raise
    if record is None:
        raise RuntimeError(f'{kind} exited before ownership could be recorded')
    record['kind'] = kind
    owner.check_record(record, inst['launch_id'], run_dir, Path(tool.__file__).resolve())
    inst['processes'].append(record)
    checkpoint(tool, run_dir, inst)
    return proc, record


def wait_owned_listener(port, record, proc=None):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError('Owned service exited before listening')
        pids = owner.listener_pids(port)
        if pids:
            if pids != {record['pid']} or not owner.same_process(record, owner.snapshot(record['pid'])):
                raise RuntimeError('Port belongs to another process; refusing adoption')
            return
        time.sleep(.3)
    raise RuntimeError('Owned service did not listen before the deadline')


def expected_identity(tool, run_dir, inst):
    db = {'driver': 'sqlite+aiosqlite', 'host': None, 'port': None,
          'name': (run_dir / 'isolated.sqlite3').as_posix(), 'user': None}
    return {'launch_id': inst['launch_id'], 'device_mode': 'sim',
            'root_fingerprint': hashlib.sha256(os.path.normcase(str(tool.ROOT.resolve())).encode()).hexdigest(),
            'deploy_simulate_only': True, 'knowledge_provider': 'local',
            'database_fingerprint': hashlib.sha256(json.dumps(db, sort_keys=True).encode()).hexdigest()}


def verified_identity(tool, run_dir, inst, token):
    identity = tool.http_json(f"http://127.0.0.1:{inst['backend_port']}/api/v1/system/runtime-identity", token=token)
    expected = expected_identity(tool, run_dir, inst)
    worker = next(p for p in inst['processes'] if p['kind'] == 'backend')
    if any(identity.get(k) != v for k, v in expected.items()) or identity.get('pid') != worker['pid']:
        raise RuntimeError('Backend runtime identity mismatch')
    return identity


def token_for(tool, inst, creds):
    worker = next(p for p in inst['processes'] if p['kind'] == 'backend')
    if (owner.listener_pids(inst['backend_port']) != {worker['pid']}
            or not owner.same_process(worker, owner.snapshot(worker['pid']))):
        raise RuntimeError('Cannot authenticate to an unowned backend')
    return tool.http_json(f"http://127.0.0.1:{inst['backend_port']}/api/v1/auth/login", 'POST',
                          {'username': creds['admin'], 'password': creds['admin_password']})['access_token']


def stop_all(tool, run_dir, inst):
    validate_instance(tool, run_dir, inst)
    results = []
    # Worker first, launcher last. Never discover/kill an arbitrary descendant tree.
    for kind in ('frontend', 'backend', 'launcher'):
        for record in inst['processes']:
            if record['kind'] == kind:
                try:
                    status = owner.stop_verified(record)
                except Exception as exc:
                    status = f'failed_{type(exc).__name__}'
                results.append({'pid': record['pid'], 'kind': kind, 'status': status})
    ok = all(r['status'] in ('stopped', 'already_exited') for r in results) and not inst.get('ownership_incomplete')
    inst.update(status='STOPPED' if ok else 'STOP_FAILED', stop_results=results)
    checkpoint(tool, run_dir, inst)
    return ok


def launch(tool, run_dir, inst, creds):
    with available_ports(inst['backend_port'], inst.get('frontend_port')):
        pass
    inst.update(launch_id=secrets.token_hex(16), status='STARTING', processes=[], started_at=tool.now())
    checkpoint(tool, run_dir, inst)
    env = tool.env_for(run_dir, Path(inst['db']), inst['backend_port'], creds['admin_password'], creds['jwt_secret'])
    try:
        inst['ownership_incomplete'] = True
        proc, launcher = spawn(tool, run_dir, inst, env, 'launcher')
        receipt = run_dir / f"worker-{inst['launch_id']}.json"
        deadline = time.monotonic() + 40
        while not receipt.exists() and time.monotonic() < deadline and proc.poll() is None:
            time.sleep(.2)
        worker = tool.read_json(receipt)
        owner.check_record(worker, inst['launch_id'], run_dir, Path(tool.__file__).resolve())
        if (worker['pid'] != launcher['pid'] and worker['parent_pid'] != launcher['pid']) or not owner.same_process(worker, owner.snapshot(worker['pid'])):
            raise RuntimeError('Backend worker is not the launched child')
        inst['processes'].append(worker)
        inst['ownership_incomplete'] = False
        checkpoint(tool, run_dir, inst)
        wait_owned_listener(inst['backend_port'], worker, proc)
        token = token_for(tool, inst, creds)
        inst['runtime_identity'] = verified_identity(tool, run_dir, inst, token)
        preflight = tool.http_json(f"http://127.0.0.1:{inst['backend_port']}/api/v1/trust/environments/{inst['environment']['environment_id']}/preflight", 'POST', {}, token)
        tool.write_json(run_dir / 'preflight.json', preflight)
        require_ready(preflight)
        inst['preflight'] = {k: preflight.get(k) for k in ('status', 'verification_mode')}
        if inst.get('frontend_port'):
            front, front_record = spawn(tool, run_dir, inst, env, 'frontend')
            wait_owned_listener(inst['frontend_port'], front_record, front)
            # Verify proxy reaches exactly the backend already identified above.
            identity = tool.http_json(f"http://127.0.0.1:{inst['frontend_port']}/api/v1/system/runtime-identity", token=token)
            if identity != inst['runtime_identity']:
                raise RuntimeError('Frontend proxy points to another runtime')
        inst.update(status='READY', source_hash=tool.source_fingerprint())
        checkpoint(tool, run_dir, inst)
        return 0
    except BaseException as exc:
        inst['failure'] = type(exc).__name__ + ': ' + str(exc)[:240]
        cleaned = stop_all(tool, run_dir, inst) and not inst.get('ownership_incomplete')
        inst['status'] = 'START_FAILED_CLEANED' if cleaned else 'START_FAILED_CLEANUP_REQUIRED'
        checkpoint(tool, run_dir, inst)
        raise


def init(tool, args):
    run_dir = paths(tool, args.run_dir)
    front = None if args.no_frontend else args.frontend_port
    # Validate both ports and path before creating directories or seeding anything.
    with available_ports(args.backend_port, front):
        if run_dir.exists():
            raise ValueError('init requires a new run directory; use start to restart')
        run_dir.mkdir(parents=True)
    with locked(run_dir):
        for name in ('logs', 'private', 'temp', 'knowledge-storage'):
            (run_dir / name).mkdir()
        creds = {'admin': 'admin', 'admin_password': secrets.token_urlsafe(18),
                 'jwt_secret': secrets.token_urlsafe(32), 'normal': 'demo-user'}
        creds['normal_password'] = creds['admin_password'][:20] + 'U1'
        tool.write_json(run_dir / 'private/credentials.json', creds)
        inst = {'schema': 2, 'run_dir': str(run_dir), 'db': str(run_dir / 'isolated.sqlite3'),
                'launch_id': secrets.token_hex(16), 'device_mode': 'sim', 'processes': [],
                'backend_port': args.backend_port, 'frontend_port': front,
                'created_at': tool.now(), 'status': 'INITIALIZING'}
        checkpoint(tool, run_dir, inst)
        env = tool.env_for(run_dir, Path(inst['db']), args.backend_port, creds['admin_password'], creds['jwt_secret'])
        for script in ('bootstrap_local.py', 'seed_sim_devices.py', 'seed_training_labs.py', 'identity'):
            rc, out = tool.run(tool.worker_command(run_dir, script), env, tool.BACKEND)
            # Seed output can include deployment information; retain it locally, not stdout.
            (run_dir / 'logs' / f'{script}.log').write_text(out, encoding='utf-8')
            if rc:
                inst.update(status='INIT_FAILED', failed_step=script)
                checkpoint(tool, run_dir, inst)
                raise RuntimeError(f'Isolated seed failed: {script}; see instance logs')
        inst['environment'] = tool.read_json(run_dir / 'seed-identity.json')
        checkpoint(tool, run_dir, inst)
        return launch(tool, run_dir, inst, creds)


def start(tool, args):
    run_dir = paths(tool, args.run_dir)
    with locked(run_dir):
        inst = tool.read_json(run_dir / 'instance.json')
        validate_instance(tool, run_dir, inst)
        if inst['status'] not in ('STOPPED', 'START_FAILED_CLEANED'):
            raise ValueError('Instance is not cleanly stopped; inspect status/stop first')
        if not inst.get('environment', {}).get('environment_id'):
            raise ValueError('Instance initialization is incomplete; use a fresh run directory')
        # Even a stale STOPPED receipt must not hide a surviving process.
        if any(owner.snapshot(p['pid']) is not None for p in inst['processes']):
            raise RuntimeError('Recorded PID is still present; restart refused')
        return launch(tool, run_dir, inst, tool.read_json(run_dir / 'private/credentials.json'))


def stop(tool, args):
    run_dir = paths(tool, args.run_dir)
    with locked(run_dir):
        inst = tool.read_json(run_dir / 'instance.json')
        return 0 if stop_all(tool, run_dir, inst) else 2


def status(tool, args):
    run_dir = paths(tool, args.run_dir)
    inst = tool.read_json(run_dir / 'instance.json')
    validate_instance(tool, run_dir, inst)
    checks = []
    for record in inst['processes']:
        actual = owner.snapshot(record['pid'])
        checks.append({'kind': record['kind'], 'pid': record['pid'],
                       'state': 'owned_running' if owner.same_process(record, actual) else 'exited' if actual is None else 'identity_mismatch'})
    result = {'recorded_status': inst['status'], 'processes': checks, 'live_ready': False}
    if inst['status'] == 'READY' and checks and all(c['state'] == 'owned_running' for c in checks):
        try:
            creds = tool.read_json(run_dir / 'private/credentials.json')
            token = token_for(tool, inst, creds)
            verified_identity(tool, run_dir, inst, token)
            if inst.get('frontend_port'):
                front = next(p for p in inst['processes'] if p['kind'] == 'frontend')
                if owner.listener_pids(inst['frontend_port']) != {front['pid']}:
                    raise RuntimeError('Frontend listener mismatch')
            result['live_ready'] = True
        except Exception as exc:
            result['check_error'] = type(exc).__name__
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['live_ready'] or (inst['status'] == 'STOPPED' and all(c['state'] == 'exited' for c in checks)) else 2
