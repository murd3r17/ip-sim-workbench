# -*- coding: utf-8 -*-
"""CF-02 / C-R2：页面数据的服务端可信化。

R2 反例要求：
- 客户端缺 source、或自称 sim，都不是服务端证据；
- 对象必须精确匹配（R2 ≠ R20）；
- 生产默认必须用服务器当前时间判断过期（不能依赖调用方传 now）；
- 后端已验证的正向证据必须可用。

因此默认 **不信任** 客户端 JSON；只有 `load_verified_evidence()` 从
`read_only_observation` 回读、核过归属/设备/新鲜度/环境版本后，才标记 trusted。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

SERVER_SOURCES = {"server_observed", "real", "sim", "snapshot"}
CLIENT_REAL_CLAIMS = {"real", "server_observed", "device", "live"}
TRUSTED_CLIENT_SOURCES = {"sim", "simulation", "snapshot"}
DEVICE_LABEL_PATTERN = r"(?<![A-Za-z0-9_-])[RS]-?\d+(?![A-Za-z0-9_-])"


@dataclass
class TrustedPageData:
    text: str | None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def trusted(self) -> bool:
        return bool(self.meta.get("trusted"))


def validation_note(page: Any) -> str:
    """Only server-created validation results become explanatory constraints."""
    if not isinstance(page, TrustedPageData) or page.trusted:
        return ''
    labels = {
        'stale': '证据已过期，不能当作当前状态，需重新采集',
        'future_timestamp': '采集时间在未来，不能当作有效当前观察',
        'missing_timestamp': '缺少可核验采集时间',
        'mode_unknown': '采集模式缺失或未知，不能判断真机或模拟',
        'environment_version_drift': '环境版本已变化，旧版本观察不能证明新映射',
        'environment_revision_drift': '环境修订已变化，旧观察不能证明当前映射',
        'environment_content_drift': '环境内容已变化，旧观察不能证明当前映射',
        'environment_not_ready': '环境尚未完成有效预检',
        'environment_missing': '原绑定环境不存在',
        'device_not_in_environment': '设备不在当前环境映射中',
        'device_mismatch': '观察与当前目标对象不一致，不能拼接为该对象事实',
        'evidence_not_found_or_forbidden': '观察不存在或当前身份无权读取，不得据此解释私人内容',
        'collection_error': '原采集失败，没有有效完整观察',
        'client_supplied_unverified': '仅客户端提供的线索，未经服务端观察核验',
    }
    reasons = list(dict.fromkeys(labels[reason] for reason in page.meta.get('reasons',[])
                                if isinstance(reason,str) and reason in labels))
    lineage = ('当前身份可见的服务端原记录，仅可按原设备、原时间与原版本解释；'
               if page.meta.get('record_origin') == 'server_observation_record' else '')
    return ('服务端页面观察核验：' + lineage + '；'.join(reasons) + '。') if reasons else ''


@dataclass
class ResolvedTaskTargets:
    """Server inventory identities only; never evidence of connectivity or health."""

    resolved: list[dict[str, Any]]
    unresolved: list[str]
    ambiguous: list[str]
    read_at: str

    def as_context(self) -> dict[str, Any]:
        return {
            "resolved": self.resolved, "unresolved": self.unresolved,
            "ambiguous": self.ambiguous, "read_at": self.read_at,
            "source": "database_snapshot",
            "scope": "identity_only; management_address_not_traffic_destination",
        }


@dataclass(frozen=True)
class ResolvedDraftTarget:
    device_id: int
    hostname: str
    alarm_id: int | None = None
    device_model: str = ""

    def as_meta(self) -> dict:
        return {'device_id': self.device_id, 'hostname': self.hostname,
                **({'alarm_id': self.alarm_id} if self.alarm_id is not None else {})}


async def resolve_draft_target(db: Any, message: str, selection: str, actor: dict) -> ResolvedDraftTarget | None:
    """Bind one draft to inventory identity, never to incidental UI selection.

    Explicit known names win; missing/multiple names stay unbound. A selected
    device/alarm is a fallback only for an explicit 'this/current' reference.
    This supplies a form default, not observation, approval or write authority.
    """
    if db is None or not actor.get('user_id'):
        return None
    from sqlalchemy import select
    from modules.auth.models import User
    from modules.device.models import Device
    account = await db.get(User, actor['user_id'], populate_existing=True)
    if (account is None or not account.is_active or account.role.value != actor.get('role')
            or account.token_version != actor.get('token_version', 0)):
        return None
    rows = (await db.execute(select(Device.id, Device.hostname, Device.model).limit(1001))).all()
    if len(rows) > 1000:
        return None
    # Negated/multiple target wording needs an explicit choice; do not interpret
    # the first recognizable name as the target of a configuration draft.
    found, aliases = {}, set()
    models={device_id:model or '' for device_id,_,model in rows}
    for device_id, hostname, _ in rows:
        names = [hostname]
        if re.fullmatch(r'[RS]-?\d+', hostname, re.I):
            normalized = hostname.upper().replace('-', '')
            names += [normalized, normalized[0] + '-' + normalized[1:]]
        if any(re.search(r'(?:不是|不要给|不要改|别给|不对|排除)\s*(?:设备)?\s*' + re.escape(name) + r'(?![A-Za-z0-9_-])', message, re.I) for name in names):
            return None
        if any(re.search(r'(?<![A-Za-z0-9_-])' + re.escape(name) + r'(?![A-Za-z0-9_-])', message, re.I) for name in names):
            found[device_id] = hostname
            aliases.update(name.upper().replace('-', '') for name in names)
    named_tokens = re.findall(DEVICE_LABEL_PATTERN + r'|(?<![A-Za-z0-9_-])(?:REAL-R\d+|CE\d+|NE\d+)(?![A-Za-z0-9_-])', message, re.I)
    if found or named_tokens:
        if len(found) == 1 and all(name.upper().replace('-', '') in aliases for name in named_tokens):
            device_id, hostname = next(iter(found.items()))
            return ResolvedDraftTarget(device_id, hostname, device_model=models[device_id])
        return None
    if not re.search(r'这台设备|当前(?:选中)?设备|选中的设备|该设备|这个告警|当前(?:选中)?告警', message):
        return None
    selected = re.search(r'^\s*(device|alarm)\s*\|.*\|\s*id=(\d+)(?:\s|$)', selection or '')
    if not selected:
        return None
    kind, selected_id = selected[1], int(selected[2])
    alarm_id = None
    if kind == 'alarm':
        from modules.monitor.models import Alarm
        alarm = await db.get(Alarm, selected_id)
        if alarm is None:
            return None
        alarm_id, selected_id = alarm.id, alarm.device_id
    hostname = {device_id:name for device_id,name,_ in rows}.get(selected_id)
    return ResolvedDraftTarget(selected_id, hostname, alarm_id, models[selected_id]) if hostname else None


async def resolve_task_targets(db: Any, message: str, actor: dict) -> ResolvedTaskTargets | None:
    """Resolve bounded R/S names, including Chinese-adjacent names, without guessing IDs.

    A hyphen variant is accepted only when inventory has one matching identity.
    Other naming schemes retain the existing inventory-tool path.
    """
    names = list(dict.fromkeys(
        name.upper().replace("-", "") for name in
        re.findall(DEVICE_LABEL_PATTERN, message, re.I)
    ))[:4]
    if db is None or not names or not actor.get("user_id"):
        return None
    from sqlalchemy import func, select
    from modules.auth.models import User
    from modules.device.models import Device

    account = await db.get(User, actor["user_id"], populate_existing=True)
    if (account is None or not account.is_active or
            actor.get("role") != account.role.value or
            actor.get("token_version", 0) != account.token_version):
        return None
    aliases = [alias.lower() for name in names for alias in (name, name[0] + "-" + name[1:])]
    rows = (await db.execute(select(Device).where(func.lower(Device.hostname).in_(aliases)))).scalars().all()
    resolved, unresolved, ambiguous = [], [], []
    for name in names:
        matches = [row for row in rows if row.hostname.upper().replace("-", "") == name]
        if len(matches) > 1:
            ambiguous.append(name)
        elif not matches:
            unresolved.append(name)
        else:
            row = matches[0]
            resolved.append({"device_id": row.id, "hostname": row.hostname,
                             "management_address": row.mgmt_ip, "topology_id": row.topology_id})
    return ResolvedTaskTargets(resolved, unresolved, ambiguous, datetime.now(timezone.utc).isoformat())


def _parse(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _object_key(selection: str | None) -> str:
    """选中文本可能带 IP/详情；取首个对象标识，仍做全等比较（R2≠R20）。"""
    text = (selection or "").strip()
    if "|" in text:
        parts = [x.strip() for x in text.split("|")]
        if len(parts) >= 2 and parts[1]:
            return parts[1].lower()
    for sep in (" ", "\t", "（", "("):
        if sep in text:
            text = text.split(sep, 1)[0]
    return text.strip().lower()


def _within(collected_at: Any, now: datetime, max_age_minutes: int) -> tuple[bool, bool, bool]:
    if not isinstance(collected_at, str) or not collected_at:
        return False, False, False
    try:
        ts = datetime.fromisoformat(collected_at.replace("Z", "+00:00"))
    except ValueError:
        return False, False, False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age = now - ts.astimezone(timezone.utc)
    future = age < -timedelta(seconds=5)
    return True, not future and age <= timedelta(minutes=max_age_minutes), future


def sanitize(
    raw: str | None,
    *,
    selection: str | None = None,
    now: datetime | None = None,
    max_age_minutes: int = 60,
    server_verified: bool = False,
) -> TrustedPageData:
    """客户端数据默认不可信；server_verified 仅供后端回读路径使用。"""
    now = now or datetime.now(timezone.utc)
    data = _parse(raw)
    if data is None:
        return TrustedPageData(raw, {"trusted": False, "reasons": ["unparsed"]})

    meta: dict[str, Any] = {"trusted": False, "reasons": []}
    source = str(data.get("source") or "").strip().lower()
    device = str(data.get("device") or "").strip()

    if not server_verified:
        # 浏览器自报的 source 一律只是线索；sim 也不例外。
        if source in TRUSTED_CLIENT_SOURCES or source in CLIENT_REAL_CLAIMS or not source:
            meta["reasons"].append("client_supplied_unverified")
        else:
            meta["reasons"].append("unknown_source")
        if not device:
            meta["reasons"].append("missing_device")
        elif selection and device.lower() != _object_key(selection):
            meta["reasons"].append("device_mismatch")
        return TrustedPageData(json.dumps(data, ensure_ascii=False), meta)

    if source not in SERVER_SOURCES:
        meta["reasons"].append("unknown_source")
        return TrustedPageData(json.dumps(data, ensure_ascii=False), meta)

    if not device:
        meta["reasons"].append("missing_device")
    if selection and (not device or device.strip().lower() != _object_key(selection)):
        meta["reasons"].append("device_mismatch")

    has_ts, fresh, future = _within(data.get("collected_at"), now, max_age_minutes)
    if not has_ts:
        meta["reasons"].append("missing_timestamp")
    elif future:
        meta["reasons"].append("future_timestamp")
    elif not fresh:
        meta["reasons"].append("stale")

    if data.get("completeness") == "error" or data.get("status") in {"error", "unsupported"}:
        meta["reasons"].append("collection_error")

    meta["trusted"] = not meta["reasons"]
    meta["evidence_id"] = data.get("evidence_id")
    meta["source"] = source
    meta["device"] = device
    meta["collected_at"] = data.get("collected_at")
    meta["environment_version"] = data.get("environment_version")
    meta["environment_id"] = data.get("environment_id")
    meta["environment_revision"] = data.get("environment_revision")
    meta["device_id"] = data.get("device_id")
    meta["mode"] = data.get("mode")
    return TrustedPageData(json.dumps(data, ensure_ascii=False), meta)


async def load_verified_evidence(
    db: Any,
    evidence_id: int,
    *,
    user: dict | None = None,
    selection: str | None = None,
    now: datetime | None = None,
    max_age_minutes: int = 60,
) -> TrustedPageData | None:
    """回读当前身份可见的原记录；失效记录仅供历史解释，绝不授予当前事实/草稿权限。"""
    if db is None or not evidence_id:
        return None
    from modules.device.models import Device
    from modules.trust.models import ReadOnlyObservation

    row = await db.get(ReadOnlyObservation, int(evidence_id))
    if row is None:
        return None
    user_id = int((user or {}).get("user_id") or 0)
    role = (user or {}).get("role") or "user"
    if not user_id or role not in {"admin", "user"}:
        return None
    if role != "admin" and (not row.created_by or int(row.created_by) != user_id):
        return None
    # Ownership is checked before exposing any payload, even for stale or
    # mismatched records. Browser copies never substitute for a stored record.
    reasons = []
    if str(row.mode or "") not in {"real", "sim"}:
        reasons.append("mode_unknown")
    device = await db.get(Device, row.device_id)
    hostname = getattr(device, "hostname", "") if device else ""
    selected_id = re.search(r"(?:^|\|)\s*id=(\d+)\s*(?:\||$)", selection or "")
    if selected_id and int(selected_id.group(1)) != row.device_id:
        reasons.append("device_mismatch")
    from modules.trust.models import EnvironmentProfile
    from modules.trust.service import environment_hash
    from core.time_utils import iso_utc
    env = await db.get(EnvironmentProfile, row.environment_id) if row.environment_id else None
    if env is None and row.environment_id is not None:
        reasons.append("environment_missing")
    if env is not None and str(env.version) != str(row.environment_version):
        reasons.append("environment_version_drift")
    snapshot = row.environment_snapshot or {}
    if env is not None and snapshot.get("revision") is not None and snapshot["revision"] != env.revision:
        reasons.append("environment_revision_drift")
    if env is not None and snapshot.get("content_hash") and snapshot["content_hash"] != (env.content_hash or environment_hash(env)):
        reasons.append("environment_content_drift")
    if env is not None and str(env.status or "") != "ready":
        reasons.append("environment_not_ready")
    env_devices = getattr(env, "devices", None) or []
    if env is not None and not any(int((d or {}).get("device_id", -1)) == int(row.device_id) for d in env_devices if isinstance(d, dict)):
        reasons.append("device_not_in_environment")
    environment_invalid = any(reason.startswith('environment_') or reason == 'device_not_in_environment'
                              for reason in reasons)
    payload = {
        "evidence_id": row.id,
        "source": row.source,
        "device": hostname,
        "device_id": row.device_id,
        "mode": row.mode,
        "environment_binding": "historical_invalid" if environment_invalid else "verified" if env is not None else "unbound",
        "environment_id": row.environment_id,
        "scope": "单次设备只读观察；环境映射指工作台设备/接口/保护项与实验预期的绑定，不是NAT地址转换。未绑定或失效记录不能证明当前环境符合预期或允许变更；不能给旧观察补绑或改写版本，应在目标环境下重新预检/采集再比对。",
        "environment_version": row.environment_version,
        "environment_revision": snapshot.get("revision"),
        "collected_at": iso_utc(row.collected_at) or "",
        "completeness": row.completeness,
        "status": row.status,
        "command": row.command,
        "facts": row.facts,
        "raw_excerpt": row.raw_excerpt,
    }
    page = sanitize(
        json.dumps(payload, ensure_ascii=False),
        selection=selection,
        now=now,
        max_age_minutes=max_age_minutes,
        server_verified=True,
    )
    page.meta['record_origin'] = 'server_observation_record'
    page.meta['reasons'] = list(dict.fromkeys(reasons + page.meta['reasons']))
    page.meta['trusted'] = not page.meta['reasons']
    return page
