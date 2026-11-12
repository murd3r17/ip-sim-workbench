"""LLDP snapshot coverage. Adjacencies do not certify a complete physical network."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone

from .lldp_parser import parse_lldp_neighbor_brief, is_interface_name, normalize_interface_name

VERSION = 'lldp-brief-d05.1'
MAX_AGE_SECONDS = 300


def analyze_lldp_output(output: str) -> dict:
    result = {'state': 'unsupported', 'complete': False, 'neighbors': [], 'message': ''}
    if not isinstance(output, str) or not output.strip():
        return result | {'message': '未取得LLDP回显，不能视为空邻居。'}
    if len(output) > 500_000 or re.search(r'-+\s*more\s*-+|output\s+truncated|press\s+.*continue', output, re.I):
        return result | {'state': 'truncated', 'message': 'LLDP回显可能截断或分页，未完成解析。'}
    if re.search(r'(^|\n)\s*(?:error:|%\s*error)|unrecognized command|unknown command|incomplete command|lldp.*(?:not enabled|disabled)', output, re.I):
        return result | {'message': '设备未提供受支持的LLDP表格，请核对协议启用与命令支持。'}
    lines = output.splitlines()
    header = next((i for i, line in enumerate(lines) if re.search(
        r'Local\s+Intf\s+Neighbor\s+Dev\s+Neighbor\s+Intf', line, re.I)), None)
    if header is None:
        return result | {'message': 'LLDP表头未识别，不能将未知格式视为空邻居。'}
    parsed = parse_lldp_neighbor_brief(output)
    result['neighbors'] = parsed
    invalid = []
    for line in lines[header + 1:]:
        text = line.strip()
        if (not text or re.fullmatch(r'[-=\s]+', text) or re.fullmatch(r'<[^>]+>|\[[^\]]+\]', text)
                or re.match(r'Total\s+Neighbors?\s*[:=]', text, re.I)
                or re.match(r'Info:\s*The max number of neighbors is\s+\d+', text, re.I)):
            continue
        cells = text.split()
        if len(cells) < 3 or not is_interface_name(cells[0]) or not is_interface_name(cells[2]):
            invalid.append(text)
    counts = [int(n) for n in re.findall(r'Total\s+Neighbors?\s*[:=]\s*(\d+)', output, re.I)]
    if invalid or (counts and (len(set(counts)) != 1 or counts[0] != len(parsed))):
        return result | {'message': '部分LLDP行或邻居数量未能完整解析，请查看设备回显核对。'}
    if not parsed and counts != [0]:
        return result | {'state': 'empty_unconfirmed', 'message': '仅有LLDP表头且无明确零邻居计数，邻居状态无法确认。'}
    return result | {'state': 'parsed' if parsed else 'empty', 'complete': True,
                     'message': '已解析指定LLDP表格；不代表业务可达或完整物理网络。'}


def build_coverage(samples: list[dict], *, baseline_count: int, manual_count: int, mode: str) -> dict:
    known = {s['hostname'] for s in samples}
    links, ports, unmanaged = defaultdict(set), defaultdict(set), []
    for sample in samples:
        for neighbor in sample.get('neighbors', []):
            item = {'hostname': sample['hostname'], **neighbor}
            ports[(sample['hostname'], neighbor['local_interface'])].add(neighbor['neighbor_device'])
            if neighbor['neighbor_device'] not in known:
                unmanaged.append(item)
                continue
            endpoints = tuple(sorted((f"{sample['hostname']}:{normalize_interface_name(neighbor['local_interface'])}",
                                      f"{neighbor['neighbor_device']}:{normalize_interface_name(neighbor['remote_interface'])}")))
            links[endpoints].add(sample['hostname'])
    return {
        'version': VERSION, 'mode': mode, 'scope': 'inventory_lldp_adjacencies',
        'expected_devices': len(samples), 'parsed_devices': sum(s.get('complete') is True for s in samples),
        'baseline_count': baseline_count, 'manual_count': manual_count, 'devices': samples,
        'unmanaged_neighbors': unmanaged,
        'multi_neighbor_ports': [{'hostname': host, 'local_interface': port, 'neighbors': sorted(neighbors)}
                                 for (host, port), neighbors in ports.items() if len(neighbors) > 1],
        'bidirectional_links': sum(len(sources) == 2 for sources in links.values()),
        'one_sided_links': sum(len(sources) != 2 for sources in links.values()),
        'network_completeness': 'not_evaluated', 'business_reachability': 'not_evaluated',
    }


def evidence_fresh(coverage: dict | None, now: datetime | None = None) -> bool:
    if not isinstance(coverage, dict) or coverage.get('version') != VERSION or not coverage.get('devices'):
        return False
    now = now or datetime.now(timezone.utc)
    try:
        ages = [(now - datetime.fromisoformat(s['observed_at'].replace('Z', '+00:00'))).total_seconds()
                for s in coverage['devices']]
        return all(-60 <= age <= MAX_AGE_SECONDS for age in ages)
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def unpack_diff(raw: str) -> tuple[dict, dict | None]:
    import json
    data = json.loads(raw)
    return {'missing': data.get('missing', []), 'unexpected': data.get('unexpected', [])}, data.get('_coverage')
