"""Bound, read-only HTTP load and real WebSSH contention/recovery acceptance.

Uses one administrator login for 30 virtual readers, not 30 distinct accounts.
Only display version is sent to one explicitly selected device. No configuration
or service outage is introduced; dependency fault tests have separate evidence.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import sys
import time
import uuid

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from core.config import get_settings
from core.live_evidence import binding_unchanged, capture_binding
from core.runtime_identity import same_runtime
from scripts.load_probe import run as load_run, report as load_report
from scripts.verify_full_stack import api_url, db_facts, selected_devices
from scripts.verify_live_workflows import check_webssh


def require(value, reason):
    if not value:
        raise ValueError(reason)


async def verify_server(client, base, token, binding, targets, previous=None):
    """Recheck the actual server and endpoint inventory before using a terminal."""
    headers = {'Authorization': 'Bearer ' + token}
    response = await client.get(base + '/system/runtime-identity', headers=headers)
    require(response.status_code == 200, 'runtime_identity_http_failed')
    actual = response.json()
    require(same_runtime(binding, actual), 'runtime_identity_mismatch')
    require(type(actual.get('pid')) is int and actual['pid'] > 0 and bool(actual.get('launch_id')), 'runtime_process_identity_missing')
    if previous is not None:
        require(actual['pid'] == previous['pid'] and actual['launch_id'] == previous['launch_id'], 'runtime_process_changed')
    response = await client.get(base + '/devices', headers=headers)
    require(response.status_code == 200, 'runtime_inventory_http_failed')
    inventory = response.json()
    require(isinstance(inventory, list), 'runtime_inventory_invalid')
    keys = ('id', 'hostname', 'mgmt_ip', 'ssh_port')
    for target in targets:
        matches = [row for row in inventory if row.get('id') == target['id']]
        require(len(matches) == 1 and all(matches[0].get(k) == target[k] for k in keys), 'runtime_targets_mismatch')
    return actual


async def check_contention(base: str, token: str, target: dict) -> dict:
    from websockets.asyncio.client import connect
    address = base.replace('http://', 'ws://', 1).replace('https://', 'wss://', 1)
    address += f"/ws/ssh/{target['id']}"
    options = dict(subprotocols=[token], open_timeout=20, close_timeout=5, proxy=None)
    result = {'device_id': target['id'], 'ok': False, 'first_closed': False, 'second_closed': False}
    async with connect(address, **options) as first:
        ready = await check_webssh(first, target['hostname'])
        require(ready['ok'], 'first_terminal_not_ready')
        async with connect(address, **options) as second:
            output = ''
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    message = json.loads(await asyncio.wait_for(second.recv(), timeout=max(.1, deadline-time.monotonic())))
                    output += str(message.get('message') or message.get('data') or '')
                except Exception:
                    break
                if '设备终端占用' in output:
                    break
            result['busy_reported'] = '设备终端占用' in output
            result['second_session_rejected'] = result['busy_reported'] and f"<{target['hostname']}>" not in output
            require(result['second_session_rejected'], 'concurrent_terminal_not_rejected')
        result['second_closed'] = True
    result['first_closed'] = True
    # Server's channel-close cleanup may take a short time; its normal lock wait
    # permits that cleanup. No repeated connections or blind retries are needed.
    async with connect(address, **options) as recovered:
        result['recovery'] = await check_webssh(recovered, target['hostname'])
    result['recovery_closed'] = True
    result['ok'] = result['recovery']['ok']
    return result


async def verify(args) -> dict:
    import httpx
    settings = get_settings()
    require(settings.device_mode == 'ssh' and settings.db_backend == 'mysql' and settings.knowledge_provider == 'anythingllm', 'full_runtime_required')
    require(args.exclusive_window, 'exclusive_ssh_window_required')
    require(16 <= args.users <= 30 and 30 <= args.duration <= 300, 'bounded_load_required')
    start = capture_binding(settings)
    facts = await db_facts(settings)
    targets = selected_devices(args.expected_endpoints, facts['devices'])
    base = api_url(args.api_url)
    report = {'schema': 1, 'producer': 'verify_live_resilience', 'run_id': uuid.uuid4().hex,
              'scope': 'live_http_load_authentication_and_webssh_lock_recovery', 'ok': False,
              'targets': [{k: row[k] for k in ('id', 'hostname', 'mgmt_ip', 'ssh_port')} for row in targets],
              'llm': facts['llm'], 'steps': []}
    try:
        async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.post(base + '/auth/login', json={
                'username': settings.admin_username, 'password': settings.admin_password})
            require(response.status_code == 200, 'admin_login_failed')
            token = response.json()['access_token']
            identity = await verify_server(client, base, token, start, targets)
            report['runtime_identity'] = identity
            for name, headers in [('anonymous_rejected', {}), ('invalid_token_rejected', {'Authorization': 'Bearer invalid-live-verification-token'})]:
                response = await client.get(base + '/system/runtime-identity', headers=headers)
                report['steps'].append({'name': name, 'ok': response.status_code == 401, 'http_status': response.status_code})
                require(response.status_code == 401, 'authentication_rejection_failed')
            result = await load_run(base.removesuffix('/api/v1'), args.users, args.duration, token)
            summary, passed = load_report(result, args.users, args.duration, base)
            summary['identity_scope'] = 'one_administrator_login_with_concurrent_virtual_readers'
            # Full acceptance is stricter than the diagnostic's 2% error budget.
            no_errors = all(row['errors'] == 0 for row in summary['endpoints'])
            report['load'] = summary
            report['steps'].append({'name': 'concurrent_readers', 'ok': passed and no_errors})
            await verify_server(client, base, token, start, targets, identity)
            report['steps'].append({'name': 'runtime_bound_before_webssh', 'ok': True})
            try:
                report['webssh_contention'] = await check_contention(base, token, targets[0])
                report['steps'].append({'name': 'webssh_contention_recovery', 'ok': report['webssh_contention']['ok']})
            except Exception as exc:
                report['steps'].append({'name': 'webssh_contention_recovery', 'ok': False, 'error_type': type(exc).__name__})
            report['runtime_identity_finish'] = await verify_server(client, base, token, start, targets, identity)
            report['steps'].append({'name': 'server_runtime_unchanged', 'ok': True})
    except Exception as exc:
        report['steps'].append({'name': 'resilience_run_failed', 'ok': False, 'error_type': type(exc).__name__})
    finish = capture_binding(settings)
    report.update(binding={'start': start, 'finish': finish}, started_at=start['captured_at'], finished_at=finish['captured_at'])
    report['steps'].append({'name': 'build_runtime_unchanged', 'ok': binding_unchanged(start, finish)})
    report['ok'] = all(step['ok'] for step in report['steps'])
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-url', required=True)
    parser.add_argument('--expected-endpoints', required=True)
    parser.add_argument('--users', type=int, default=30)
    parser.add_argument('--duration', type=float, default=60)
    parser.add_argument('--exclusive-window', action='store_true')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    logging.disable(logging.CRITICAL)
    try:
        report = asyncio.run(verify(args))
    except Exception as exc:
        report = {'schema': 1, 'producer': 'verify_live_resilience', 'ok': False, 'error_type': type(exc).__name__}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps({'ok': report['ok'], 'report': str(args.report), 'steps': report.get('steps', [])}, ensure_ascii=True))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
