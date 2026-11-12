# -*- coding: utf-8 -*-
"""C-R2 5.3.1：从环境映射读取动态保护项，而不是只认固定几个接口名。"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from .trusted_context import ResolvedDraftTarget

MGMT_HINTS = ("mgmt", "management", "管理", "带外", "oob")
IFACE = re.compile(r"([A-Za-z][A-Za-z0-9\-/\.]*\s*\d+(?:/\d+)*)")


def _target_interface(target: str) -> str:
    text = str(target or "")
    tail = text.split(":")[-1].strip()
    m = IFACE.search(tail) or IFACE.search(text)
    return (m.group(1) if m else tail).strip()


def parse_protections(protections: Any, *, target: ResolvedDraftTarget | None = None) -> list[str]:
    out: list[str] = []
    for item in protections or []:
        if isinstance(item, str):
            out.append(item)
            continue
        if not isinstance(item, dict):
            continue
        if isinstance(target, ResolvedDraftTarget):
            if item.get('device_id') is not None and str(item['device_id']) != str(target.device_id):
                continue
            named_target=str(item.get('target') or '')
            if ':' in named_target:
                owner=named_target.split(':',1)[0].strip()
                # Device-qualified targets apply only to that inventory identity.
                # A colon in an interface's own name is not a device qualifier.
                from .protected_output import NAME
                if owner and not re.fullmatch(NAME,owner,re.I):
                    if owner.lower().replace('-','') != target.hostname.lower().replace('-',''):
                        continue
        iface = _target_interface(item.get("target") or item.get("interface") or "")
        if iface:
            out.append(iface)
    return sorted({x for x in out if x})


async def load_protected_interfaces(
    db: Any, *, target: ResolvedDraftTarget | None = None
) -> list[str]:
    """Resolve protection scope from server inventory, never browser versions.

    Unknown targets conservatively use the union. Multiple profiles for the
    same device retain all their protections until environment binding resolves
    them; a newer unrelated profile cannot silently replace the target policy.
    """
    if db is None:
        return []
    from modules.trust.models import EnvironmentProfile

    stmt = select(EnvironmentProfile).order_by(EnvironmentProfile.id.desc()).limit(1001)
    rows = (await db.execute(stmt)).scalars().all()
    if len(rows)>1000:
        raise RuntimeError('Environment protection scope exceeds the supported bound')
    out: set[str] = set()
    for row in rows:
        if isinstance(target, ResolvedDraftTarget) and not any(
            isinstance(device,dict) and str(device.get('device_id')) == str(target.device_id)
            for device in (row.devices or [])):
            continue
        out.update(parse_protections(row.protections,target=target))
    return sorted(out)
