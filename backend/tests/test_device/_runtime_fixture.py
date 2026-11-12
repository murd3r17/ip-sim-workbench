"""Explicit synthetic collector metadata for legacy comparison/version tests.

These tests replace collection, not parsing; parser completeness has separate
raw-output tests. Never use this helper in product code or runtime migrations.
"""
from datetime import datetime, timezone

from engines.device_adapter import get_device_mode
from modules.device.runtime_evidence import build_coverage


def coverage_samples(devices, links=()):
    samples = []
    for device in devices:
        neighbors = []
        for link in links:
            if link['source_device'] == device.hostname:
                neighbors.append({'neighbor_device': link['target_device'],
                                  'local_interface': link['source_interface'], 'remote_interface': link['target_interface']})
            elif link['target_device'] == device.hostname:
                neighbors.append({'neighbor_device': link['source_device'],
                                  'local_interface': link['target_interface'], 'remote_interface': link['source_interface']})
        samples.append({'device_id': device.id, 'hostname': device.hostname, 'ssh_ok': True,
                        'state': 'parsed' if neighbors else 'empty', 'complete': True,
                        'observed_at': datetime.now(timezone.utc).isoformat(), 'neighbors': neighbors})
    return samples


def complete_coverage(devices, links=()):
    return build_coverage(coverage_samples(devices, links), baseline_count=1, manual_count=0, mode=get_device_mode())


def with_coverage(collector):
    async def collect(devices):
        result = await collector(devices)
        return result | {'coverage_samples': coverage_samples(devices, result['observed_links']), 'mode': get_device_mode()}
    return collect
