"""D02 scoped step checks. No device execution, LLM, score, or client expectations."""
from __future__ import annotations

from datetime import datetime, timezone
from ipaddress import IPv4Address, IPv4Interface, IPv4Network

from modules.trust.service import SERVER_MAX_AGE_SECONDS, SUPPORTED_PARSERS, _normalize_ifname


def _utc(value):
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _set(values, converter):
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise ValueError('invalid list')
    return {str(converter(v)) for v in values}


def evaluate_frozen_step(session, step_id, ids, rows, current_environment, user, *, now=None):
    """Only compare the session's frozen rule and bound role expectations.

    Satisfied means these scoped facts match, never an overall training grade.
    Historical readback stays available elsewhere; fresh checks require active
    sessions and the same current environment identity.
    """
    now = _utc(now or datetime.now(timezone.utc))
    result = {'session_id': session.id, 'step_id': step_id, 'content_version': session.content_version,
              'status': 'insufficient_evidence', 'reason': '', 'rejected_reason': '',
              'evidence_ids': list(ids), 'roles': [], 'checks': [], 'expected': {}, 'observed': {},
              'checked_at': now.isoformat(), 'verification_mode': 'unknown',
              'evaluation_scope': 'step_facts', 'skill_passed': None, 'score': None,
              'limitations': '仅核对本步指定事实；不证明协议全部配置、业务可达、计时、理解程度或整项技能达标。'}
    def fail(code, reason, status='insufficient_evidence'):
        return {**result, 'status': status, 'reason': reason, 'rejected_reason': code}

    if user.get('role') != 'admin' and session.trainee_id != user.get('user_id'):
        return fail('not_owner', '会话不属于当前用户')
    if session.status != 'in_progress':
        return fail('inactive_session', '该会话已结束，可回看原记录；新核对请新建会话')
    content = session.content_snapshot if isinstance(session.content_snapshot, dict) else {}
    if not session.content_version or content.get('version') != session.content_version:
        return fail('missing_content_version', '缺少一致的会话内容版本，不能用当前课程补作历史规则')
    objectives = content.get('objectives')
    if not isinstance(objectives, list):
        return fail('unknown_step', '会话步骤格式不受支持')
    matches = [s for s in objectives if isinstance(s, dict) and s.get('id') == step_id]
    if len(matches) != 1:
        return fail('unknown_step', '会话快照中没有唯一对应步骤')
    rule = matches[0].get('verification') or {}
    if not isinstance(rule, dict):
        return fail('unsupported_rule', '该步骤的规则格式不受支持')
    if rule.get('version') != session.content_version:
        return fail('missing_rule_version', '该步骤没有与会话一致的核对规则')
    kind = rule.get('kind')
    if kind == 'manual_review':
        return fail('manual_review', '本步需要原始记录、计时或教员复核，当前规则不自动判定', 'manual_review')
    if kind not in {'interface_expectations', 'ospf_expectations', 'route_filter_effect'}:
        return fail('unsupported_rule', '该步骤的规则类型尚不受支持')
    snapshot = session.trust_environment_snapshot or {}
    frozen = snapshot.get('environment') if isinstance(snapshot, dict) else None
    if not isinstance(frozen, dict) or not session.trust_environment_id or not frozen.get('content_hash'):
        return fail('unbound_environment', '该会话没有冻结的环境绑定，请管理员绑定实验后新开会话')
    env = current_environment if isinstance(current_environment, dict) else {}
    if (env.get('id') != session.trust_environment_id or frozen.get('id') != env.get('id')
            or env.get('version') != session.trust_environment_version
            or frozen.get('version') != session.trust_environment_version
            or env.get('content_hash') != frozen['content_hash']
            or env.get('revision') != frozen.get('revision')):
        return fail('environment_changed', '当前环境已变更，原会话预期保留；请重新预检并新开会话')
    if any(e.get('status') != 'ready' or e.get('last_preflight_status') != 'ready' for e in (frozen, env)):
        return fail('environment_not_ready', '环境尚未完成一致的只读预检')
    device_mode = (session.mode_snapshot if isinstance(session.mode_snapshot, dict) else {}).get('device_mode')
    mode = {'sim': 'sim', 'ssh': 'real'}.get(device_mode, 'unknown')
    if mode == 'unknown' or any(e.get('last_preflight_mode') != mode for e in (frozen, env)):
        return fail('mode_mismatch', '会话设备方式与环境预检方式不一致')
    result.update(verification_mode=mode, evaluation_scope='practice' if mode == 'sim' else 'step_facts')
    spec = content.get('environment_spec')
    requirements = spec.get('devices') if isinstance(spec, dict) else None
    if not isinstance(requirements, list) or any(not isinstance(d, dict) or not isinstance(d.get('role'), str) or not d['role'].strip() for d in requirements):
        return fail('missing_roles', '本会话内容没有格式有效的任务角色')
    required_roles = [d['role'] for d in requirements]
    if not required_roles or len(required_roles) != len(set(required_roles)):
        return fail('missing_roles', '本会话内容没有明确且唯一的任务角色')
    bindings = frozen.get('devices')
    if not isinstance(bindings, list):
        return fail('missing_roles', '绑定环境的设备格式不受支持')
    devices = [d for d in bindings if isinstance(d, dict) and d.get('role') in required_roles]
    if any(type(d.get('device_id')) is not int or d['device_id']<=0 for d in devices):
        return fail('missing_roles', '绑定环境缺少有效的设备身份')
    if (len(devices) != len(required_roles) or len({d.get('role') for d in devices}) != len(devices)
            or len({d.get('device_id') for d in devices}) != len(devices)):
        return fail('missing_roles', '绑定环境缺少任务角色，或多个角色重复使用同一设备')
    by_device = {d['device_id']: d for d in devices}
    result['roles'] = required_roles
    if not ids:
        return fail('no_evidence', '请选择服务端观察记录')
    if len(ids) != len(set(ids)):
        return fail('duplicate_evidence', '不能重复使用同一观察充当前后证据')
    by_id = {r.id: r for r in rows}
    if set(ids) != set(by_id):
        return fail('missing_evidence', '部分观察不存在或不可读取')
    eligible_actions = ({'interface_brief'} if kind == 'interface_expectations' else
                        {'ospf_route'} if kind == 'route_filter_effect' else {'ospf_peer', 'ospf_route'})
    grouped = {}
    for row in rows:
        if user.get('role') != 'admin' and row.created_by != user.get('user_id'):
            return fail('not_owner', '观察记录不属于当前用户')
        if row.device_id not in by_device or row.environment_id != env['id']:
            return fail('target_mismatch', '观察设备或环境不属于本步冻结角色')
        if row.source != 'server_observed':
            return fail('untrusted_source', '客户端操作记录不能作为服务端核对证据')
        if row.parser_version not in SUPPORTED_PARSERS:
            return fail('unsupported_parser', '观察解析版本不受支持')
        if row.completeness != 'complete' or row.status != 'ok' or not isinstance(row.facts, dict):
            return fail('incomplete', '观察为空、截断或采集失败，请重新采集完整输出')
        if (row.adapter_mode or row.mode) != mode:
            return fail('mode_mismatch', '观察与本会话设备方式不一致')
        if row.action_id not in eligible_actions:
            return fail('wrong_action', '观察命令不属于该步骤支持的事实类型')
        if row.environment_version != env['version']:
            return fail('stale_environment_version', '观察环境版本与本会话不一致')
        captured = row.environment_snapshot or {}
        if not isinstance(captured, dict) or captured.get('content_hash') != frozen['content_hash']:
            return fail('stale_environment_content', '观察环境内容与本会话不一致')
        collected = _utc(row.collected_at)
        if not collected:
            return fail('missing_time', '观察缺少可核对的采集时间')
        age = (now-collected).total_seconds()
        if age < -60:
            return fail('future_evidence', '观察时间在未来，请核对时钟')
        if age > SERVER_MAX_AGE_SECONDS:
            return fail('stale_evidence', '观察已超过五分钟，请重新采集', 'stale')
        if not _utc(session.started_at) or collected < _utc(session.started_at):
            return fail('before_session', '观察早于本会话，不能作为本步当前证据')
        key = (by_device[row.device_id]['role'], row.action_id)
        grouped.setdefault(key, []).append(row)
    try:
        if kind == 'route_filter_effect':
            spec = rule.get('filter') or {}
            role = spec.get('role')
            if role not in required_roles or not spec.get('target') or not spec.get('control'):
                return fail('missing_filter_plan', '该步骤尚未冻结接收角色、目标和保留控制前缀；请教员配置后新开会话')
            target, control = str(IPv4Network(spec['target'])), str(IPv4Network(spec['control']))
            if target == control:
                return fail('invalid_expected', '目标和控制前缀不能相同')
            pair = sorted(grouped.get((role, 'ospf_route'), []), key=lambda r: r.collected_at)
            if len(rows) != 2 or len(pair) != 2 or pair[0].collected_at >= pair[1].collected_at:
                return fail('missing_before_after', '需同一接收角色、严格先后两份完整路由观察')
            before, after = [_set([r['destination'] for r in p.facts.get('routes', [])], IPv4Network) for p in pair]
            if not before or not after:
                return fail('empty_facts', '空表不能证明目标过滤且其他路由保留')
            result['expected'] = {'role': role, 'target_removed': target, 'control_preserved': control}
            result['observed'] = {'before': sorted(before), 'after': sorted(after)}
            matched = {target, control} <= before and target not in after and control in after
            result['limitations'] += ' 仅证明这两份OSPF路由变化，不单独证明ABR/Type3过滤因果、LSDB或业务转发。'
        else:
            for device in devices:
                role = device['role']
                if kind == 'interface_expectations':
                    planned = [i for i in device.get('interfaces', []) if isinstance(i, dict) and i.get('purpose') in {'link', 'loopback'}]
                    expected = {i['purpose']: i for i in planned}
                    if len(planned) != 2 or set(expected) != {'link', 'loopback'}:
                        return fail('missing_interface_plan', '请在绑定环境中明确link/loopback两种接口用途及精确地址')
                    candidates = grouped.get((role, 'interface_brief'), [])
                    if len(candidates) != 1:
                        return fail('missing_action', '每个任务角色需一份当前完整接口观察，不能拼接多次输出')
                    interfaces = candidates[0].facts.get('interfaces') or []
                    for purpose, wanted in expected.items():
                        name = _normalize_ifname(wanted['name'])
                        address = str(IPv4Interface(wanted['address']))
                        found = [i for i in interfaces if _normalize_ifname(i.get('name','')) == name]
                        if len(found) != 1:
                            return fail('missing_interface', f'{role} 缺少唯一目标接口 {wanted["name"]}')
                        actual = found[0]
                        if actual.get('state') not in {'up','down'} or not actual.get('address'):
                            return fail('unknown_interface', f'{role} 目标接口状态或地址未知')
                        equal = str(IPv4Interface(actual['address'])) == address and actual['state']=='up'
                        result['checks'].append({'role':role,'component':purpose,'expected':{'name':wanted['name'],'address':address,'state':'up'},
                                                 'observed':actual, 'matched':equal})
                else:
                    components = rule.get('components', ['neighbors','routes'])
                    if not components or any(c not in {'neighbors','routes'} for c in components):
                        return fail('invalid_expected', '步骤缺少明确的核对组件')
                    for component in components:
                        action = 'ospf_peer' if component=='neighbors' else 'ospf_route'
                        candidates = grouped.get((role, action), [])
                        if len(candidates) != 1:
                            return fail('missing_action', f'{role} 需要一份当前{component}观察，不能合并多份快照')
                        expected_values = device.get('expected_'+component)
                        if expected_values is None and len(devices)==1 and len(frozen.get('devices',[]))==1:
                            expected_values = frozen.get('expected_'+component)
                        convert = IPv4Address if component=='neighbors' else IPv4Network
                        expected = _set(expected_values or [], convert)
                        if not expected:
                            return fail('missing_expected', f'{role} 尚未登记非空{component}预期')
                        facts = candidates[0].facts
                        items = facts.get('peers' if component=='neighbors' else 'routes')
                        if not isinstance(items, list):
                            return fail('empty_facts', '没有受支持的结构化事实')
                        observed = _set([i['neighbor_id' if component=='neighbors' else 'destination'] for i in items
                                         if component!='neighbors' or i.get('state')=='Full'], convert)
                        counts = facts.get('reported_peer_counts')
                        known_zero = (component=='neighbors' and candidates[0].parser_version=='v7b.4'
                                      and isinstance(counts, list) and len(counts)==1
                                      and counts[0].get('peer_count')==0)
                        if not items and not known_zero:
                            return fail('empty_facts', '空输出不能当作已知没有对象')
                        equal = expected == observed
                        result['checks'].append({'role':role, 'component':component, 'expected':sorted(expected),
                                                 'observed':sorted(observed), 'matched':equal})
            matched = bool(result['checks']) and all(c['matched'] for c in result['checks'])
    except (ValueError, TypeError, KeyError, AttributeError):
        return fail('invalid_facts_or_expected', '预期或结构化事实格式不受支持，不能推断通过')
    return {**result, 'status': 'satisfied' if matched else 'not_matched',
            'reason': '本步指定事实符合冻结预期；技能成绩未判定' if matched else '本步指定事实与冻结预期不一致',
            'rejected_reason': '' if matched else 'objects_mismatch'}
