"""Require independently timed state observations before binding a two-page example."""

from dataclasses import dataclass
import re


_OWNER = r'(?:ar|ce|fw|ne|pe|pc|sw|ac|ap|p|r|s)\d{1,4}(?:[-_][a-z0-9]{1,4})?'
_OWNER_TOKEN = re.compile(rf'(?<![a-z0-9_/-]){_OWNER}(?![a-z0-9_/-])', re.I)
_PHASE = re.compile(r'(?P<event>故障|切换|恢复|重启|倒换)(?:发生|完成)?(?P<time>之前|以前|之后|以后|[前后])(?![缀台端备向者置])')
_STATE_ASK = re.compile(r'(?:什么|哪种|怎样|有何)(?:样的)?状态|状态(?:各自)?(?:是什么|如何|怎样|有何变化)')
_INVALID_INTENT = re.compile(r'现场|接入设备|执行命令|预期|预计|计划|预测|通常|理论上|可能|应该|何时|多少秒|中断多久|原理')
_LOOKUP = re.compile(r'PDF\s*第|逐字|原句|原文是|第\s*\d+\s*页', re.I)
_SAME_CASE = re.compile(r'同一(?:次|例|个)(?:实验|案例|操作|故障|记录)|同一实验')
_VALUE = r'up|down|full|init|open|normal|standby|stdby|established|discarding|forwarding|master|backup'
_STATES = re.compile(rf'(?:{_VALUE})', re.I)
_CAPTION = re.compile(r'^\s*#*\s*(?:在[^。!?！？]{1,36}(?:看|查)|检查|查看|核对)[^。!?！？]{1,70}(?:状态|记录|表)\s*$')
_OTHER = re.compile(r'预计|预期|假如|如果|可能|待(?:查|验证)|计划|假设|另一个|另一组|另一例|配置为|通常|应当')
_PHASE_LINE = re.compile(r'^\s*\*{0,2}(?P<heading>[^。！？；\n]{2,24})(?:。|[：:]|\*\*)')
_FAMILY = (('会话', 'session'), ('邻居', 'peer|neighbor|neighbour'), ('链路', 'link'), ('接口', 'interface'), ('接入点', 'ap'))
_TARGET = re.compile(r'(?P<topic>[a-z][a-z0-9_.-]{1,19})\s*(?P<class>会话|邻居|链路|接口|接入点)', re.I)


@dataclass(frozen=True)
class StateRequest:
    owner: str
    topic: str
    family: str
    event: str
    side: str


def phase_key(marker):
    return marker['event'], 'before' if marker['time'].endswith('前') else 'after'


def requests(query, clauses):
    if len(clauses) != 2 or not _SAME_CASE.search(query) or _LOOKUP.search(query) or _INVALID_INTENT.search(query):
        return ()
    result = []
    for clause in clauses:
        if not _STATE_ASK.search(clause):
            return ()
        owners = {owner.casefold() for owner in _OWNER_TOKEN.findall(clause)}
        phases = {phase_key(marker) for marker in _PHASE.finditer(clause)}
        target = tuple(_TARGET.finditer(clause))
        if len(owners) != 1 or len(phases) != 1 or len(target) != 1:
            return ()
        event, side = next(iter(phases))
        result.append(StateRequest(next(iter(owners)), target[0]['topic'].casefold(), target[0]['class'], event, side))
    first, second = result
    return tuple(result) if first.side != second.side and first.owner == second.owner and first.topic == second.topic and first.family == second.family and first.event == second.event else ()


def explicit_stage(paragraph):
    heading = _PHASE_LINE.match(paragraph)
    if not heading or not re.search(r'回读|回显|观测|实测|记录|观察', heading['heading']) or _OTHER.search(heading['heading']):
        return None
    markers = {phase_key(mark) for mark in _PHASE.finditer(heading['heading'])}
    return next(iter(markers)) if len(markers) == 1 else None


def prose_state(request, paragraph):
    subject = rf'(?<![a-z0-9_/-]){re.escape(request.owner)}(?![a-z0-9_/-])\s*(?:上|的)?\s*'
    subject += rf'(?:[一二两三四五六七八九十\d]+\s*(?:个|条)\s*)?{re.escape(request.topic)}\s*{request.family}'
    actual = rf'\s*(?:(?:的)?状态\s*)?(?:均|都|已经|实际)?\s*(?:由\s*(?:{_VALUE})\s*)?'
    actual += rf'(?:变为|转为|显示为|回读为|处于|恢复为|保持为|[为是:：])\s*(?P<value>{_VALUE})(?![a-z])'
    matcher = re.compile(subject + actual, re.I)
    values = {match['value'].casefold() for sentence in re.split(r'[。；\n]', paragraph)
              if not _OTHER.search(sentence) for match in matcher.finditer(sentence)}
    return next(iter(values)) if len(values) == 1 else None


def table_state(request, body, unit):
    command_family = dict(_FAMILY)[request.family]
    owned = [record for record in unit.commands if record.kind == 'observation' and record.owner == request.owner
             and record.output and re.search(rf'\b{re.escape(request.topic)}\s+(?:{command_family})\b', record.command, re.I)]
    if len(owned) != 1:
        return None
    lines = body[slice(*owned[0].output)].splitlines()
    headers = [(index, fields.index('state'), len(fields)) for index, line in enumerate(lines)
               if (fields := line.casefold().split()).count('state') == 1 and len(fields) >= 3]
    if len(headers) != 1:
        return None
    start, column, width = headers[0]
    states = set()
    for line in lines[start + 1:]:
        if not line.strip() or set(line.strip()) <= {'-'}:
            continue
        if re.match(r'^\s*(?:Total|Summary)\b', line, re.I):
            break
        cells = line.split()
        if len(cells) != width or not _STATES.fullmatch(cells[column]):
            return None
        states.add(cells[column].casefold())
    return next(iter(states)) if len(states) == 1 else None


def page_witnesses(request, page, *, units):
    """A page must carry its own phase marker and its own attributed state assertion."""
    for index, unit in enumerate(units):
        paragraph = page[unit.start:unit.end].strip()
        if unit.kind != 'paragraph' or explicit_stage(paragraph) != (request.event, request.side):
            continue
        if value := prose_state(request, paragraph):
            yield value, paragraph
            continue
        tail = units[index + 1:index + 3]
        if tail and tail[0].kind == 'paragraph' and _CAPTION.fullmatch(page[tail[0].start:tail[0].end].strip()):
            tail = tail[1:]
        if tail and tail[0].kind == 'fence' and tail[0].end - unit.start <= 2000:
            if value := table_state(request, page, tail[0]):
                yield value, page[unit.start:tail[0].end].strip()
