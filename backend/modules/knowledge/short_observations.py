"""Literal field proof for short, retrospective queries with one named device."""

from dataclasses import dataclass
from ipaddress import ip_address, ip_interface
import re
from typing import NamedTuple


_OWNER = r'(?:ar|sw|fw|ce|pe|ne|pc|ac|ap|r|s|p|edge|leaf|spine)[-_]?[0-9]{1,4}(?:[-_][a-z0-9]{1,4})?'
_OWNER_ONLY = re.compile(rf'(?<![a-z0-9_/-]){_OWNER}(?![a-z0-9_/-])', re.I)
_ASK = re.compile(r'哪个|哪条|哪一条|哪一个|是多少|是什么|什么前缀|什么地址|何值')
_PAST = re.compile(r'见到|看到|查到|记下|留下|读到|抄下|报出的')
_DENY_QUESTION = re.compile(r'现场|现在|重新连|执行|登录|通常|理论|为什么|含义|意思|作用|用途|应该|应当|打算|预期|计划|规划|假如|要是|如果|能否|能不能|能证明|是否|分别|各自|两条|两项|前后')
_DENY_SOURCE = re.compile(r'预期|应该|应当|预计|理论上|计划|规划|假设|如果|(?:待|需)(?:再|实际)?(?:核对|确认|测量)|(?:上一|下一)页|参考值|读不到|未(?:读到|看到|显示)|(?:另|其他)(?:一|个)(?:组|例|台)')
_REPORT = re.compile(rf'(?<![a-z0-9_/-])(?P<owner>{_OWNER})(?![a-z0-9_/-])\s*'
                     r'(?:的\s*(?:路由表|转发表|邻居表|记录)\s*)?'
                     r'(?:(?:刚|先|后|最后|当时|实际|随后|确实|这次|这边|现场)\s*)*'
                     r'(?:读到|看到|看见|查到|查见|记录到|测得|实测为|报出|列出)\s*(?P<result>.+)$', re.I)
_ADDRESS = r'(?:\d{1,3}\.){3}\d{1,3}'
_PREFIX = r'(?:\d{1,3}\.){3}\d{1,3}/\d{1,2}'
_VALID_POINT = re.compile(rf'(?<![\d.]){_PREFIX}(?![\d/])')
_NAME = re.compile(r'(?<![a-z0-9_-])(?:[A-Z][A-Z0-9_-]{2,}|[A-Z][a-z]{2,}(?:[ -]\d+)?|[a-z]{3,}(?:[-_][\w]+)?)(?![a-z0-9_-])')
_CASE_WORDS = frozenset({'IPV4', 'IPV6', 'IP', 'NEXT_HOP', 'NEXTHOP', 'ROUTE', 'DISPLAY', 'SHOW'})
_LEADING_STAGE = re.compile(r'^[\u4e00-\u9fffA-Za-z0-9 _-]{2,22}?(?:之|以)?[前后时](?=\s*[,，:：])')
_ORDINAL_STAGE = re.compile(r'(?:首次|初次|第一次)[\u4e00-\u9fff]{2,8}?(?:之|以)?[前后时]')
_INLINE_HEADING = re.compile(r'^\s*\*\*([^*]+)\*\*')
_INHERENTLY_DIRECTIONAL = re.compile(r'(?:从|由|向|对|跟|与|给|经|来自|通往|途经|为|至|借助)\s*(?:\x60)?$')
_LINKED_PREVIOUS = re.compile(r'(?:上一|前一)(?:页|图|张|次)|前文|所述|第\s*\d+\s*页')


class Field(NamedTuple):
    name: str
    asked: re.Pattern
    values: re.Pattern


FIELDS = (
    Field('next_hop', re.compile(r'下一跳|next[ -]?hop', re.I),
          re.compile(rf'(?:下一跳|next[ -]?hop)\s*(?:为|是|[:：=])?\s*[` ]*(?P<value>{_ADDRESS})(?![\d./])', re.I)),
    Field('prefix', re.compile(r'前缀|区间缺省|默认路由|prefix', re.I),
          re.compile(rf'(?:^\s*[` ]*|(?:前缀|网段|区间汇总|区间缺省|默认路由)\s*(?:为|是|[:：=])?[` ]*)'
                     rf'(?P<value>{_PREFIX})(?![\d/])')),
    Field('endpoint_address', re.compile(r'(?:终端|客户端|站点|发送端|接收端)(?:的)?(?:IP )?地址', re.I),
          re.compile(rf'^(?:终端|客户端|站点|发送端|接收端)?(?:地址)?\s*[` ]*(?P<value>{_ADDRESS})(?![\d./])')),
)


@dataclass(frozen=True)
class RecordedField:
    owner: str
    field: Field
    literals: frozenset[str]
    subjects: tuple[str, ...]
    stage: str


def short_record_request(question):
    if not _ASK.search(question) or not _PAST.search(question) or _DENY_QUESTION.search(question):
        return None
    parts = [item for item in re.split(r'[。！？；!?;]', question) if item.strip()]
    if len(parts) != 1:
        return None
    owners = frozenset(match.casefold() for match in _OWNER_ONLY.findall(question))
    fields = [field for field in FIELDS if field.asked.search(question)]
    if len(owners) != 1 or len(fields) != 1:
        return None
    literals = frozenset(_VALID_POINT.findall(question)) if fields[0].name == 'next_hop' else frozenset()
    if len(literals) > 1:
        return None
    names = tuple(dict.fromkeys(item.casefold() for item in _NAME.findall(question)
                                if item.upper() not in _CASE_WORDS and not _OWNER_ONLY.fullmatch(item)))
    cue = _LEADING_STAGE.search(question.strip()) or _ORDINAL_STAGE.search(question)
    stage = _normalized_stage(cue[0]) if cue else ''
    if not (literals or names or stage):
        return None
    return RecordedField(next(iter(owners)), fields[0], literals, names, stage)


def _normalized_stage(text):
    text = text.replace('初次', '首次').replace('第一次', '首次').casefold()
    return re.sub(r'\s|(?<=[^\W\d_])[之以](?=[前后时])', '', text)


def _has_subject(subject, context):
    return re.search(rf'(?<![a-z0-9_-]){re.escape(subject)}(?![a-z0-9_-])', context.casefold())


def _scalar_values(request, result):
    if _REPORT.search(result):
        return ()
    all_targets = frozenset(_VALID_POINT.findall(result))
    if request.literals and all_targets != request.literals:
        return ()
    return (field['value'] for field in request.field.values.finditer(result))


def original_observation(request, paragraph, headings=()):
    """Bind a scalar field to its owner and clause before selecting an intact source paragraph."""
    if not paragraph.strip() or _LINKED_PREVIOUS.search(paragraph):
        return None
    local_heading = _INLINE_HEADING.match(paragraph)
    named_context = ' '.join((*headings, local_heading[1] if local_heading else ''))
    found = set()
    previous = ''
    for clause in re.split(r'[。；\n]', paragraph):
        assertion = _REPORT.search(clause)
        previous, setup = clause, previous
        if not assertion or assertion['owner'].casefold() != request.owner or _DENY_SOURCE.search(clause):
            continue
        left = clause[:assertion.start()].strip().removeprefix('**').strip()
        if _INHERENTLY_DIRECTIONAL.search(left):
            continue
        if left and left[-1] not in '，,：:。？！后时' and left != '此时':
            continue
        if request.stage:
            marked = _normalized_stage(left)
            if request.stage not in marked and (not request.stage.endswith('时') or request.stage[:-1] not in marked):
                continue
        result = assertion['result']
        scope = f'{named_context} {clause}'
        if request.literals and any(device.casefold() == request.owner for device in _OWNER_ONLY.findall(setup)):
            scope += ' ' + setup
        if any(not _has_subject(subject, scope) for subject in request.subjects):
            continue
        for value in _scalar_values(request, result):
            try:
                value = str(ip_interface(value)) if '/' in value else str(ip_address(value))
            except ValueError:
                continue
            found.add(value)
    return next(iter(found)) if len(found) == 1 else None
