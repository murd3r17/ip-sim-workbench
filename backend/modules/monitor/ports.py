"""Versioned local port expectations and evidence; never changes device configuration."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.device.lldp_parser import normalize_interface_name
from modules.system.models import SystemConfig

VERSION = 'ports-d06.1'
MAX_AGE_SECONDS = 300
PURPOSES = ('unknown', 'unused', 'business', 'uplink', 'management')


def interface_key(name: str) -> str:
    return normalize_interface_name(name.strip()).casefold()


class PortExpectation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=64)
    purpose: Literal['unknown', 'unused', 'business', 'uplink', 'management'] = 'unknown'
    expected_enabled: StrictBool | None = None

    @field_validator('name')
    @classmethod
    def valid_name(cls, value):
        value = value.strip()
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9./-]*\d', value):
            raise ValueError('接口名称只接受字母、数字、点、斜线和连字符，且以数字结尾')
        return normalize_interface_name(value)

    @model_validator(mode='after')
    def consistent(self):
        if self.purpose == 'unused' and self.expected_enabled is True:
            raise ValueError('闲置接口不能同时登记为预期启用')
        return self


class PortPolicyWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    base_revision: str = Field(max_length=64)
    ports: list[PortExpectation] = Field(default_factory=list, max_length=256)

    @field_validator('ports')
    @classmethod
    def unique(cls, values):
        keys = [interface_key(p.name) for p in values]
        if len(set(keys)) != len(keys):
            raise ValueError('接口名称重复（完整名称和缩写视为同一接口）')
        return values


def policy_payload(device_id: int, ports: list[dict], *, valid=True) -> dict:
    ports = sorted(ports, key=lambda p: interface_key(p['name']))
    revision = hashlib.sha256(json.dumps({'version': VERSION, 'device_id': device_id, 'ports': ports},
                                        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'version': VERSION, 'device_id': device_id, 'ports': ports, 'revision': revision,
            'valid': valid, 'source': 'local_expectation_only'}


async def load_policy(db: AsyncSession, device_id: int) -> dict:
    row = (await db.execute(select(SystemConfig).where(
        SystemConfig.config_key == f'monitor.port_expectations.{device_id}'))).scalars().first()
    if row is None:
        return policy_payload(device_id, [])
    try:
        data = json.loads(row.config_value or '')
        if data.get('version') != VERSION or data.get('device_id') != device_id:
            raise ValueError('unknown version')
        parsed = PortPolicyWrite(base_revision='', ports=data['ports'])
        return policy_payload(device_id, [p.model_dump() for p in parsed.ports])
    except (ValueError, TypeError, KeyError, AttributeError):
        return policy_payload(device_id, [], valid=False) | {'revision': 'invalid', 'reason': '端口期望格式无效，请管理员修复；未按闲置或正常处理。'}


def parse_ports(output: str) -> dict:
    """Strict PHY/Protocol columns; preserve *down rather than stripping admin state."""
    result = {'version': VERSION, 'complete': False, 'ports': [], 'reason': '未识别受支持的接口表格'}
    if not output or len(output) > 500_000 or re.search(r'-+\s*more\s*-+|truncated|unrecognized command', output, re.I):
        return result
    lines = output.splitlines()
    header = next((i for i, s in enumerate(lines) if re.search(r'Interface\s+PHY\s+Protocol\b', s, re.I)), None)
    if header is None:
        return result
    status = r'(?:\*?down|\^down|up|dormant|off|absent|admindown)(?:\([A-Za-z]+\))*'
    pattern = re.compile(rf'^([A-Za-z][\w./-]*\d)\s+({status})\s+({status})(?:\s|$)', re.I)
    seen = set(); invalid = False
    for line in lines[header + 1:]:
        text = line.strip()
        if not text or re.fullmatch(r'[-=\s]+|<[^>]+>|\[[^\]]+\]', text):
            continue
        match = pattern.match(text)
        if not match:
            invalid = True
            continue
        name, phy, protocol = match.groups(); key = interface_key(name)
        if key in seen:
            invalid = True
            continue
        seen.add(key)
        physical = phy.split('(')[0].lower(); proto = protocol.split('(')[0].lower()
        result['ports'].append({'name': normalize_interface_name(name), 'physical': phy, 'protocol': protocol,
                                'admin_state': 'disabled' if physical in ('*down', 'admindown') else 'unknown',
                                'link_up': physical == proto == 'up'})
    result['complete'] = bool(result['ports']) and not invalid
    result['reason'] = '已解析PHY/Protocol表格；非管理关闭不代表已核实管理配置，Up也不代表业务可达' if result['complete'] else '接口回显为空、部分未知或重复，不能确定全量状态'
    return result


def assess_ports(sample: dict, policy: dict) -> dict:
    mapping = {interface_key(p['name']): p for p in policy['ports']} if policy.get('valid') else {}
    rows = []; observed = set()
    for port in sample.get('ports', []):
        key = interface_key(port['name']); observed.add(key)
        expected = mapping.get(key, {'purpose': 'unknown', 'expected_enabled': None})
        if expected['expected_enabled'] is True:
            state = 'expected_up' if port['link_up'] else 'expected_down'
        elif expected['expected_enabled'] is False or expected['purpose'] == 'unused':
            state = 'unexpected_up' if port['link_up'] else 'expected_inactive'
        else:
            state = 'unknown_up' if port['link_up'] else 'review_down'
        rows.append(port | {'purpose': expected['purpose'], 'expected_enabled': expected['expected_enabled'], 'assessment': state})
    missing = [p['name'] for key,p in mapping.items() if key not in observed]
    return {'version': VERSION, 'complete': sample.get('complete') is True and policy.get('valid') is True,
            'reason': sample.get('reason'), 'policy_revision': policy['revision'], 'ports': rows,
            'missing_expected_ports': missing, 'expected_down': sum(p['assessment'] == 'expected_down' for p in rows),
            'review_count': sum(p['assessment'] in ('review_down','unexpected_up') for p in rows) + len(missing),
            'business_reachability': 'not_evaluated'}


def sample_fresh(snapshot: dict | None, mode: str, revision: str, now: datetime | None = None) -> bool:
    if not isinstance(snapshot, dict) or snapshot.get('version') != VERSION or snapshot.get('mode') != mode or snapshot.get('policy_revision') != revision:
        return False
    try:
        age = ((now or datetime.now(timezone.utc)) - datetime.fromisoformat(snapshot['observed_at'].replace('Z','+00:00'))).total_seconds()
        return -60 <= age <= MAX_AGE_SECONDS
    except (KeyError, ValueError, TypeError, AttributeError):
        return False
