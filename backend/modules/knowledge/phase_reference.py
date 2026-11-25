"""Recognize witnessed phases around named operations in experiment questions."""

import re

from .query_focus import compact_text


_ALIAS_GROUPS = {
    '断开': ('拔掉', '拔下', '断开'),
    '接回': ('插回', '重新接入', '重新接上', '接回'),
    '停用': ('停用', '禁用', '关闭'),
    '启用': ('启用', '使能', '开启'),
    '清除': ('清除', '清空', '清理'),
    '替换': ('替换', '换掉', '更换'),
    '添加': ('新增', '添加', '加入'),
    '删除': ('移除', '移走', '删除'),
}
_ACTIONS = {phrase: action for action, phrases in _ALIAS_GROUPS.items() for phrase in phrases}
_VERBS = '|'.join(sorted(map(re.escape, _ACTIONS), key=len, reverse=True))
_OBJECT = r"(?P<object>[^，,。；;？！?！、\n]{2,22}?)"
_SUFFIX = r"(?:(?:发生|完成|生效)(?=前|后)|的)?" \
          r"(?P<phase>之前|以前|之后|以后|前(?!缀|置|提|端|台|向|期|半|述|者|后)|后(?!缀|置|端|台|向|期|半|备))"
_ACTION_PHASE = re.compile(rf"(?P<verb>{_VERBS})\s*{_OBJECT}{_SUFFIX}")
_ACTION_RANGE = re.compile(rf"(?P<verb>{_VERBS})\s*{_OBJECT}(?:前后|前(?:和|与|及|、)后)")
_UNKNOWN = re.compile(r"^(?:它|这个|那个|这项|该项|原有|相关|指定|配置|操作|它们|这一步|前面那条)$")
_NOT_ASSERTED = re.compile(r"(?:预计|预期|假设|计划|试想|如果|建议|应当)")
_LABEL = re.compile(r"^(?:原来的?|本例的?|当时的?|这条|那条|该|原先的?|当前的?|其)\s*")
_OBJECT_AFTER = re.compile(r"(?:在|由|从|时|仍|继续|保持|改为|尚未|之前|之后|目前|打算|准备|本应|过程)")
_NUMBER = r'[一二三四五六七八九十0-9]{1,2}'
_STEP_NUMBER = re.compile(rf'(?:第\s*(?P<inline>{_NUMBER})\s*步(?!骤)|步骤\s*(?P<label>{_NUMBER})(?![0-9一二三四五六七八九十]))')
_BARE_SOURCE_STEP = re.compile(rf'^(?:任务\s*)?步骤\s*{_NUMBER}\s*$')
_NUMBERS = dict(zip('一二三四五六七八九', range(1, 10), strict=True))
_READ_ROLES = {
    '读回': r'回显|读回|命令输出|输出记录',
    '采样': r'实际采样|采样|测量|实测|读数',
    '捕获': r'抓包|报文捕获|捕获的报文',
    '连通探测': r'连通性探测|连通探测|互测|连通测试',
}
_ARTIFACT = '|'.join(f'(?P<{role}>{kind})' for role, kind in _READ_ROLES.items())
_RECORD_ORDER = re.compile(rf'(?:第\s*(?P<ordinal>{_NUMBER})\s*(?:次|轮|份)(?:的)?|(?P<initial>首次|初次))\s*'
                           rf'(?:实际|原始)?\s*(?:{_ARTIFACT})')


def _operation(match: re.Match) -> str:
    label = compact_text(_LABEL.sub('', match['object'].strip()))
    if len(label) < 2 or _UNKNOWN.fullmatch(label) or _OBJECT_AFTER.search(label):
        return ''
    return _ACTIONS[match['verb']] + ' ' + label


def operation_phases(text: str, *, reported: bool = False) -> frozenset[tuple[str, str]]:
    """Retain action and exact object. A planned action supplies no reported phase."""
    spans = re.split(r'[。；;？！?!\n]', text)
    return frozenset((key, 'before' if match['phase'].endswith('前') else 'after')
                     for clause in spans if not (reported and _NOT_ASSERTED.search(clause))
                     for match in _ACTION_PHASE.finditer(clause) if (key := _operation(match)))


def operation_comparison(text: str) -> tuple[str, tuple[int, int]] | None:
    """Find one explicitly contrasted action, leaving two distinct ops separate."""
    matches = [(text[match.start():match.end('object')], match.span()) for match in _ACTION_RANGE.finditer(text)
               if _operation(match)]
    return matches[0] if len(matches) == 1 else None


def source_step_boundary(title: str) -> bool:
    """A numbered source heading isolates steps even when it has no label."""
    return _BARE_SOURCE_STEP.fullmatch(title) is not None


def _positive_number(value: str) -> int:
    if value.isascii() and value.isdigit():
        return int(value)
    if value in _NUMBERS:
        return _NUMBERS[value]
    if value == '十' or value.startswith('十') and value[1:] in _NUMBERS:
        return 10 + _NUMBERS.get(value[1:], 0)
    return 0


def step_phases(text: str, *, reported: bool = False) -> frozenset[tuple[str, str]]:
    values = set()
    clauses = re.split(r'[。；;？！?!\n]', text)
    matches = (match for clause in clauses if not (reported and _NOT_ASSERTED.search(clause))
               for match in _STEP_NUMBER.finditer(clause))
    for match in matches:
        value = match['inline'] or match['label']
        if (number := _positive_number(value)) > 0:
            values.add((f'步骤{number}', 'ordinal'))
    return frozenset(values)


def record_phases(text: str, *, reported: bool = False) -> frozenset[tuple[str, str]]:
    """Order of observations, separate from experiment steps and operation phases."""
    phases = set()
    for clause in re.split(r'[。；;？！?!\n]', text):
        if reported and _NOT_ASSERTED.search(clause):
            continue
        for match in _RECORD_ORDER.finditer(clause):
            number = 1 if match['initial'] else _positive_number(match['ordinal'])
            artifact = match.lastgroup
            if number and artifact in _READ_ROLES:
                phases.add((f'第{number}次{artifact}', 'ordinal'))
    return frozenset(phases)


def same_ordered_record_type(left: str, right: str) -> bool:
    """Keep a numbered readback distinct from a numbered capture or sample."""
    def family(label):
        match = re.fullmatch(r'第\d+次(.+)', label)
        return match[1] if match else ''

    return family(left) == family(right)
