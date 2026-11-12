from datetime import datetime, timedelta, timezone

import pytest

from modules.device.runtime_evidence import analyze_lldp_output, build_coverage, evidence_fresh

HEADER = 'Local Intf Neighbor Dev Neighbor Intf Exptime(s)\n'


@pytest.mark.parametrize('output', ['', 'Error: Unrecognized command', HEADER,
                                   HEADER + 'GE0/0/1 R2 ether2 90',
                                   HEADER + 'GE0/0/1 R2 GE0/0/2 90\n---- More ----',
                                   'LLDP is not enabled'])
def test_empty_unknown_truncated_and_unsupported_never_become_complete(output):
    assert analyze_lldp_output(output)['complete'] is False


def test_supported_rows_and_explicit_empty_are_distinct():
    parsed = analyze_lldp_output(HEADER + 'GE0/0/1 R2 GE0/0/2 90\n<R1>')
    assert parsed['complete'] and len(parsed['neighbors']) == 1
    empty = analyze_lldp_output(HEADER + 'Total Neighbors : 0')
    assert empty['complete'] and empty['state'] == 'empty' and empty['neighbors'] == []
    assert not analyze_lldp_output(HEADER + 'GE0/0/1 R2 GE0/0/2 90\nTotal Neighbors : 2')['complete']


def sample(host, neighbors, *, age=0, complete=True):
    return {'device_id': int(host[-1]), 'hostname': host, 'state': 'parsed' if complete else 'unsupported',
            'complete': complete, 'observed_at': (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat(),
            'neighbors': neighbors, 'ssh_ok': True}


def neighbor(host, local='GE0/0/1', remote='GE0/0/1'):
    return {'neighbor_device': host, 'local_interface': local, 'remote_interface': remote}


def test_coverage_keeps_unmanaged_shared_ports_and_one_sided_evidence():
    samples = [sample('R1', [neighbor('R2'), neighbor('R3'), neighbor('OUTSIDE', local='GE0/0/3')]),
               sample('R2', [neighbor('R1')]), sample('R3', [])]
    coverage = build_coverage(samples, baseline_count=0, manual_count=1, mode='sim')
    assert coverage['baseline_count'] == 0 and coverage['manual_count'] == 1
    assert coverage['parsed_devices'] == 3 and coverage['expected_devices'] == 3
    assert coverage['unmanaged_neighbors'][0]['neighbor_device'] == 'OUTSIDE'
    assert coverage['multi_neighbor_ports'][0]['local_interface'] == 'GE0/0/1'
    assert coverage['bidirectional_links'] == 1 and coverage['one_sided_links'] == 1
    assert coverage['network_completeness'] == 'not_evaluated'
    assert coverage['business_reachability'] == 'not_evaluated'


def test_observation_freshness_is_separate_from_baseline_and_unknown_history():
    fresh = build_coverage([sample('R1', [])], baseline_count=0, manual_count=0, mode='sim')
    assert evidence_fresh(fresh)
    assert not evidence_fresh(None)
    old = build_coverage([sample('R1', [], age=301)], baseline_count=0, manual_count=0, mode='sim')
    assert not evidence_fresh(old)
    assert not evidence_fresh({**fresh, 'devices': [{**fresh['devices'][0], 'observed_at': 'unknown'}]})


@pytest.mark.asyncio
async def test_real_collector_contract_no_baseline_and_stale_promotion_guard(client, test_session_factory, monkeypatch):
    import json
    from modules.auth.models import User, UserRole
    from modules.device.models import Device, DeviceType, Topology, TopologyRuntimeCheck
    from modules.device.service import TopologyService
    from modules.device.baseline_service import TopologyBaselineService
    class Adapter:
        name = 'sim'
        def __init__(self, host): self.host = host
        async def run_command(self, command):
            assert command == 'display lldp neighbor brief'
            return HEADER + ('GE0/0/1 R2 GE0/0/1 90' if self.host == 'R1' else 'GE0/0/1 R1 GE0/0/1 90')
        async def close(self): pass
    async def adapter(device, **kwargs): return Adapter(device.hostname)
    monkeypatch.setattr('engines.device_adapter.get_device_adapter', adapter)
    monkeypatch.setattr('engines.device_adapter.get_device_mode', lambda: 'sim')
    async with test_session_factory() as db:
        topology = Topology(name='D05 no baseline')
        user = User(username='d05-test-admin', hashed_password='x', role=UserRole.ADMIN)
        db.add_all([topology, user]); await db.flush()
        db.add_all([Device(hostname=f'R{i}', device_type=DeviceType.ROUTER, mgmt_ip=f'192.0.2.{i}', topology_id=topology.id) for i in (1, 2)])
        await db.commit()
        result = await TopologyService.discover_via_lldp(db, topology.id)
        assert result['status'] == 'no_baseline' and result['coverage']['bidirectional_links'] == 1
        assert result['coverage']['baseline_count'] == 0 and not result['evidence_stale']
        latest = await TopologyService.get_latest_runtime_check(db, topology.id)
        assert latest['coverage'] == result['coverage'] and latest['discovered'] == 1
        from core.security import create_access_token
        normal = User(username='d05-normal-reader', hashed_password='x', role=UserRole.USER)
        db.add(normal); await db.commit(); await db.refresh(normal)
        headers = {'Authorization': 'Bearer ' + create_access_token(normal.id, normal.username, 'user')}
        assert (await client.post(f'/api/v1/topologies/{topology.id}/discover', headers=headers)).status_code == 403
        read = await client.get(f'/api/v1/topologies/{topology.id}/runtime-checks/latest', headers=headers)
        assert read.status_code == 200 and read.json()['coverage']['version'] == 'lldp-brief-d05.1'
        row = await db.get(TopologyRuntimeCheck, result['check_id'])
        raw = json.loads(row.diff_json)
        monkeypatch.setattr('engines.device_adapter.get_device_mode', lambda: 'ssh')
        assert (await TopologyService.get_latest_runtime_check(db, topology.id))['mode_changed']
        with pytest.raises(ValueError, match='模式'):
            await TopologyBaselineService.confirm_runtime_baseline(db, topology.id, row.id, user.id)
        monkeypatch.setattr('engines.device_adapter.get_device_mode', lambda: 'sim')
        for sample_row in raw['_coverage']['devices']:
            sample_row['observed_at'] = (datetime.now(timezone.utc) - timedelta(seconds=301)).isoformat()
        row.diff_json = json.dumps(raw); await db.commit()
        latest = await TopologyService.get_latest_runtime_check(db, topology.id)
        assert latest['evidence_stale'] and not latest['is_stale']
        with pytest.raises(ValueError, match='过期'):
            await TopologyBaselineService.confirm_runtime_baseline(db, topology.id, row.id, user.id)
        # Existing fingerprint alone cannot upgrade old, unproven parse coverage.
        row.diff_json = json.dumps({'missing': [], 'unexpected': []}); await db.commit()
        with pytest.raises(ValueError, match='缺少完整解析覆盖'):
            await TopologyBaselineService.confirm_runtime_baseline(db, topology.id, row.id, user.id)


@pytest.mark.asyncio
async def test_topology_tool_labels_stored_source_and_unknown_coverage(client, test_session_factory):
    from modules.ai_text.agent_tools import _query_topology
    from modules.device.models import Topology
    async with test_session_factory() as db:
        db.add(Topology(name='D05 tool no observations')); await db.commit()
        text = await _query_topology(db)
        assert '基线关系=0条' in text and '发现覆盖未知' in text
        assert '本次读取不采集设备' in text and '不证明完整物理网络' in text
