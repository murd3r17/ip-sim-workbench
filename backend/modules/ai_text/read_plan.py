"""Short path for a single explicit, server-resolved read request.

This selects an existing read-only tool; authorization, locks, budget, parsing,
provenance and cancellation still run through the normal executor. Ambiguous,
diagnostic and contextual requests retain model planning.
"""
import json
import re

from .trusted_context import DEVICE_LABEL_PATTERN, ResolvedTaskTargets

_COMMANDS = (
    (re.compile(r'接口(?:摘要|概览|简表|地址|状态)|接口\s*是\s*up|接口\s*(?:现在|当前)\s*(?:是|为)?\s*(?:什么|多少|up)\s*(?:状态|地址)?|display\s+ip\s+interface\s+brief', re.I), 'display ip interface brief'),
    (re.compile(r'OSPF\s*邻居(?:摘要|列表)?|display\s+ospf\s+peer', re.I), 'display ospf peer'),
    (re.compile(r'(?:IP\s*)?路由表|display\s+ip\s+routing-table', re.I), 'display ip routing-table'),
)
_READ_ACTION = re.compile(r'查看|读取|核对|查询|采集|读(?:一下|一读|下)|看(?:一下|一看|看|下)')
_OTHER_READ_DOMAIN = re.compile(r'设备(?:清单|列表)|库存|监控|告警|审计|日志')
_UNSAFE_SHORTCUT = re.compile(
    r'(?:不要|别|不用|不必|无需|禁止|不)(?:再|重新)?(?:读|看|查看|核对|查询|采集|调用)'
    r'|无需|禁止|历史|刚才|昨天|此前|先前|当时|旧记录|不是'
    r'|解释|怎么|如何|原理|含义|什么意思|机制'
    r'|(?<!不)(?:下发|写入|改配置|修改配置)')


def explicit_status_question(message):
    # Entire utterance must be one field question, not a conceptual inference
    # containing the same words (e.g. Full does not prove business forwarding).
    field_followup = re.fullmatch(
        r'\s*(?:那\s*)?' + DEVICE_LABEL_PATTERN
        + r'\s*(?:(?:现在|当前)\s*的?|的)?\s*'
        + r'(?:IP\s*路由表|路由表|OSPF\s*邻居(?:摘要|列表)?|接口(?:摘要|简表|概览|地址|状态))'
        + r'\s*(?:呢|有哪些|有啥|是什么|是多少|怎么样)\s*[？?。]?\s*', message, re.I)
    return bool(field_followup or re.fullmatch(
        r'\s*(?:请问|请告诉我)?\s*' + DEVICE_LABEL_PATTERN
        + r'\s*(?:(?:现在|当前)\s*的?|的)?\s*'
        + r'(?:接口(?:地址|状态)\s*(?:是|为)?\s*(?:什么|多少|up)\s*(?:吗)?'
        + r'|接口(?:地址|状态)?\s*(?:现在|当前)\s*(?:是|为)?\s*(?:什么(?:状态|地址)?|多少|up)\s*(?:吗)?'
        + r'|接口\s*是\s*up\s*吗'
        + r'|OSPF\s*邻居(?:状态)?\s*(?:是|为)?\s*(?:Full|什么状态)\s*(?:吗)?)'
        + r'\s*[？?。]?\s*', message, re.I))


def initial_read(message, skill_id, targets, allowed):
    if (skill_id != 'live_evidence' or 'run_display_command' not in allowed
            or not isinstance(targets, ResolvedTaskTargets)
            or targets.unresolved or targets.ambiguous or len(targets.resolved) != 1):
        return None
    # Prefer falling back to planning over misreading a negation, past-context
    # question, compound request or conceptual explanation as a new read.
    if (not (_READ_ACTION.search(message) or explicit_status_question(message))
            or _UNSAFE_SHORTCUT.search(message) or _OTHER_READ_DOMAIN.search(message)):
        return None
    row = targets.resolved[0]
    hostname = str(row.get('hostname') or '').upper().replace('-', '')
    names = {name.upper().replace('-', '') for name in re.findall(DEVICE_LABEL_PATTERN, message, re.I)}
    if names != {hostname} or type(row.get('device_id')) is not int or row['device_id'] <= 0:
        return None
    commands = [command for pattern, command in _COMMANDS if pattern.search(message)]
    if len(commands) != 1:
        return None
    return {'id':'explicit-read', 'type':'function', 'function':{
        'name':'run_display_command',
        'arguments':json.dumps({'device_id':row['device_id'], 'command':commands[0]})}}


def initial_diagnostic_reads(message, skill_id, targets, allowed):
    """Known two-end connectivity begins with the existing minimal summaries.

    No presumed traffic address or root cause. Later checks still depend on
    actual executor feedback and the unchanged round/read/generation budgets.
    """
    if (skill_id!='troubleshooting' or 'run_display_command' not in allowed
            or not isinstance(targets,ResolvedTaskTargets) or targets.unresolved or targets.ambiguous
            or len(targets.resolved)!=2 or not re.search(r'访问不了|不通|连不上',message)
            or re.search(r'不要|不读取|不采集|无需|禁止|历史|刚才|原理|机制|下发|写入|改配置',message)):
        return []
    rows=targets.resolved
    names={name.upper().replace('-','') for name in re.findall(DEVICE_LABEL_PATTERN,message,re.I)}
    if (names!={str(row.get('hostname') or '').upper().replace('-','') for row in rows}
            or any(type(row.get('device_id')) is not int or row['device_id']<=0 for row in rows)):
        return []
    return [{'id':f'endpoint-summary-{row["device_id"]}','type':'function','function':{
        'name':'run_display_command','arguments':json.dumps({
            'device_id':row['device_id'],'command':'display ip interface brief'})}} for row in rows]


def initial_comparison_reads(message, skill_id, targets, allowed):
    """A bounded explicit two-device interface comparison needs both summaries.

    Identity, execution permission, locks and budgets remain with the existing
    resolver/executor. Composite/history/unknown-target requests keep planning.
    """
    if (skill_id != 'live_evidence' or 'run_display_command' not in allowed
            or not isinstance(targets, ResolvedTaskTargets) or targets.unresolved or targets.ambiguous
            or len(targets.resolved) != 2 or not re.search(r'对比|比较', message)
            or not re.search(r'接口(?:地址|状态|摘要|概览)', message)
            or re.search(r'不要|不读|不采|无需|禁止|历史|刚才|原理|机制|路由|邻居|OSPF|下发|配置|为什么', message, re.I)):
        return []
    rows = targets.resolved
    names = {name.upper().replace('-', '') for name in re.findall(DEVICE_LABEL_PATTERN, message, re.I)}
    if (names != {str(row.get('hostname') or '').upper().replace('-', '') for row in rows}
            or any(type(row.get('device_id')) is not int or row['device_id'] <= 0 for row in rows)):
        return []
    return [{'id':f'comparison-summary-{row["device_id"]}', 'type':'function', 'function':{
        'name':'run_display_command', 'arguments':json.dumps({
            'device_id':row['device_id'], 'command':'display ip interface brief'})}} for row in rows]


def initial_followup_read(message, skill_id, targets, allowed, history):
    """Carry only the previous user's explicit field request to a new target.

    Past assistant prose never selects a field, device ID, permission or fact.
    A bare device followup after a diagnosis/concept keeps model planning.
    """
    target_name = re.fullmatch(r'\s*(?:那|那么)?\s*(?P<target>'+DEVICE_LABEL_PATTERN+r')\s*呢\s*[？?。]?\s*',message,re.I)
    if not target_name:
        target_name = re.fullmatch(
            r'\s*(?:等等[，,]?\s*我说的是|更正[，,]?\s*(?:是)?|不是\s*'+DEVICE_LABEL_PATTERN
            + r'\s*[，,]?\s*是)\s*(?P<target>'+DEVICE_LABEL_PATTERN+r')\s*[。！!]?\s*',message,re.I)
    if not target_name:
        target_name = re.fullmatch(
            r'\s*(?:(?:刚才)?(?:设备|对象)?(?:说错了|选错了)[，,]?\s*)?'
            r'(?:更正(?:为|成)?|(?:对象)?改为)\s*(?P<target>'+DEVICE_LABEL_PATTERN+r')'
            r'\s*(?:[，,]\s*(?:同样|照样)(?:读取|查询|读一下))?\s*[。！!]?\s*', message, re.I)
    if not target_name:
        target_name = re.fullmatch(
            r'\s*(?:再)?(?:把|看|读取)?\s*(?P<target>'+DEVICE_LABEL_PATTERN+r')\s*(?:的)?'
            r'(?:相同|同样|一样)(?:的)?(?:两列|字段|项目|信息)\s*'
            r'(?:取出来|读出来|读取|查询)?\s*(?:对照|对比|比较)(?:一下)?\s*[。！!]?\s*', message, re.I)
    if (skill_id!='live_evidence' or 'run_display_command' not in allowed
            or not isinstance(targets,ResolvedTaskTargets) or targets.unresolved or targets.ambiguous
            or len(targets.resolved)!=1
            or not target_name):
        return None
    prior=next((str(item.get('content') or '') for item in reversed(history or [])
                if isinstance(item,dict) and item.get('role')=='user'),'')
    if (not (_READ_ACTION.search(prior) or re.search(r'对比|比较',prior) or explicit_status_question(prior))
            or _UNSAFE_SHORTCUT.search(prior)
            or re.search(r'不要|生成|配置|原因|为什么',prior)):
        return None
    row=targets.resolved[0]
    prior_names={name.upper().replace('-','') for name in re.findall(DEVICE_LABEL_PATTERN,prior,re.I)}
    if str(row.get('hostname') or '').upper().replace('-','') in prior_names:
        return None  # already part of the requested view; do not force a repeat
    names={target_name.group('target').upper().replace('-','')}
    commands=[command for pattern,command in _COMMANDS if pattern.search(prior)]
    if (names!={str(row.get('hostname') or '').upper().replace('-','')}
            or type(row.get('device_id')) is not int or row['device_id']<=0 or len(commands)!=1):
        return None
    return {'id':f'field-followup-{row["device_id"]}','type':'function','function':{
        'name':'run_display_command','arguments':json.dumps({'device_id':row['device_id'],'command':commands[0]})}}


def initial_lab_observation_reads(message, skill_id, targets, allowed, history, lab_steps):
    """A bounded live followup can verify the server-owned step's read fields.

    Step text never supplies commands, identity, permission or expected results.
    The user's own previous question supplies protocol scope, not assistant prose.
    """
    if (skill_id != 'live_evidence' or 'run_display_command' not in allowed
            or not isinstance(targets, ResolvedTaskTargets) or targets.unresolved or targets.ambiguous
            or len(targets.resolved) != 1 or not isinstance(lab_steps, list) or not lab_steps):
        return []
    match = re.fullmatch(r'\s*(?:现场|实际|当前)\s*(?P<target>'+DEVICE_LABEL_PATTERN
        + r')\s*也(?:这么做|这样)吗\s*[？?。]?\s*', message, re.I)
    prior = next((str(item.get('content') or '') for item in reversed(history or [])
                  if isinstance(item, dict) and item.get('role') == 'user'), '')
    if not match or not re.search(r'OSPF', prior, re.I):
        return []
    step = '\n'.join(str(row.get(key) or '') for row in lab_steps[:4] if isinstance(row, dict)
                     for key in ('name', 'title', 'goal', 'description'))[:2000]
    if not all(term in step for term in ('只读', '核对', '接口', '邻居')):
        return []
    row = targets.resolved[0]
    if (match.group('target').upper().replace('-', '') != str(row.get('hostname') or '').upper().replace('-', '')
            or type(row.get('device_id')) is not int or row['device_id'] <= 0):
        return []
    return [{'id':f'lab-observation-{index}', 'type':'function', 'function':{
        'name':'run_display_command', 'arguments':json.dumps({'device_id':row['device_id'], 'command':command})}}
        for index, command in enumerate(('display ip interface brief', 'display ospf peer'))]
