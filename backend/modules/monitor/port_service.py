"""Port-policy storage and latest saved monitoring evidence, without device IO."""
from __future__ import annotations
import json
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from modules.auth.service import AuditService
from modules.device.models import Device
from modules.monitor.models import MonitorJob, Alarm, AlarmStatus
from modules.system.models import SystemConfig
from modules.monitor.ports import VERSION, PortPolicyWrite, load_policy, policy_payload, sample_fresh
from core.time_utils import iso_utc


async def get_port_state(db, device_id: int) -> dict:
    device = await db.get(Device, device_id)
    if device is None:
        raise HTTPException(404, '设备不存在')
    policy = await load_policy(db, device_id)
    from engines.device_adapter import get_device_mode
    mode = get_device_mode()
    jobs = list((await db.execute(select(MonitorJob).where(MonitorJob.topology_id == device.topology_id)
                                .order_by(MonitorJob.id.desc()).limit(50))).scalars().all())
    snapshot = None; attempt = None
    for job in jobs:
        try:
            summary = json.loads(job.summary_json) if job.summary_json else {}
            if not isinstance(summary, dict) or not isinstance(summary.get('devices', []), list):
                raise ValueError('unsupported summary')
        except (ValueError, TypeError):
            attempt = {'job_id': job.id, 'status': 'unknown', 'reason': '历史任务明细格式无效，未回退为旧成功状态'}
            break
        if not summary and getattr(job.status, 'value', job.status) in ('running', 'pending', 'failed'):
            attempt = {'job_id': job.id, 'status': getattr(job.status, 'value', job.status),
                       'reason': job.error_message or '当前任务尚无可用端口结果', 'time': iso_utc(job.created_at)}
            break
        item = next((p for p in summary.get('devices', []) if isinstance(p, dict) and p.get('device_id') == device_id), None)
        if item is not None:
            snapshot = item.get('port_observation')
            if (not isinstance(snapshot, dict) or snapshot.get('version') != VERSION
                    or not isinstance(snapshot.get('ports'), list)
                    or not all(isinstance(p, dict) for p in snapshot.get('ports', []))
                    or not isinstance(snapshot.get('missing_expected_ports'), list)
                    or not isinstance(snapshot.get('complete'), bool)
                    or not isinstance(snapshot.get('observed_at'), str)
                    or not isinstance(snapshot.get('policy_revision'), str)):
                snapshot = None
            attempt = {'job_id': job.id, 'status': item.get('status'),
                       'reason': item.get('reason') or ('任务未保存受支持的端口明细' if not snapshot else ''),
                       'time': iso_utc(job.created_at)}
            break
    fresh = sample_fresh(snapshot, mode, policy['revision'])
    return {'device_id': device.id, 'hostname': device.hostname, 'policy': policy,
            'observation': snapshot, 'latest_attempt': attempt, 'fresh': fresh,
            'policy_changed': bool(snapshot and snapshot.get('policy_revision') != policy['revision']),
            'mode_changed': bool(snapshot and snapshot.get('mode') != mode),
            'scope': 'saved_monitoring_only', 'max_age_seconds': 300}


async def save_port_policy(db, device_id: int, body: PortPolicyWrite, actor: dict) -> dict:
    if await db.get(Device, device_id) is None:
        raise HTTPException(404, '设备不存在')
    key = f'monitor.port_expectations.{device_id}'
    row = (await db.execute(select(SystemConfig).where(SystemConfig.config_key == key).with_for_update())).scalars().first()
    current = await load_policy(db, device_id)
    if current['revision'] != body.base_revision:
        raise HTTPException(409, '端口期望已由其他操作更新，请重新加载后核对；当前编辑尚未保存')
    policy = policy_payload(device_id, [p.model_dump() for p in body.ports])
    if row is None:
        row = SystemConfig(config_key=key)
        db.add(row)
    row.config_value = json.dumps({'version': VERSION, 'device_id': device_id, 'ports': policy['ports']}, ensure_ascii=False)
    row.description = '本地端口用途与预期状态，不向设备写配置'
    row.updated_by = str(actor.get('username') or actor['user_id'])
    try:
        await AuditService.log(db, actor['user_id'], str(actor.get('username') or actor['user_id']),
                               'monitor', 'port_expectations_updated', 'device', str(device_id),
                               {'from_revision': current['revision'], 'to_revision': policy['revision'],
                                'ports': len(policy['ports']), 'device_effect': 'none'}, commit=False)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, '端口期望并发更新，请重新加载后核对')
    return policy


async def evaluate_port_alarms(db, device, snapshot: dict) -> list:
    """Resolve only supported complete evidence, never legacy aggregate-count alarms."""
    conditions = [('interface_expected_down', snapshot['expected_down'], 'major',
                   '预期启用接口未Up；核对物理、协议与管理状态，不据此断言业务中断'),
                  ('interface_review', snapshot['review_count'] or int(not snapshot['complete']), 'warning',
                   '端口用途/预期或观察覆盖待核对；不按down总数升级为业务严重故障')]
    emitted = []
    for kind, count, severity, detail in conditions:
        existing = (await db.execute(select(Alarm).where(Alarm.device_id == device.id, Alarm.alarm_type == kind,
                           Alarm.status.in_([AlarmStatus.FIRED, AlarmStatus.ACKNOWLEDGED])))).scalars().all()
        if not count:
            # An incomplete parse cannot prove recovery of expected ports.
            if snapshot['complete'] and not snapshot['missing_expected_ports']:
                from datetime import datetime, timezone
                for alarm in existing:
                    if kind == 'interface_expected_down' and f"期望版本={snapshot['policy_revision']}" not in (alarm.message or ''):
                        continue  # a changed expectation does not demonstrate device recovery
                    alarm.status = AlarmStatus.RESOLVED
                    alarm.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
            continue
        names = [p['name'] for p in snapshot['ports'] if p['assessment'] == ('expected_down' if kind == 'interface_expected_down' else 'review_down')]
        message = f"{device.hostname} {detail}；数量={count}；接口={','.join(names[:8]) or '查看端口观察'}；采样={snapshot['observed_at']}；期望版本={snapshot['policy_revision']}"
        alarm = existing[0] if existing else Alarm(device_id=device.id, alarm_type=kind, status=AlarmStatus.FIRED)
        alarm.severity=severity; alarm.metric_value=count; alarm.threshold=1; alarm.message=message
        if not existing:
            db.add(alarm)
        emitted.append(alarm)
    return emitted
