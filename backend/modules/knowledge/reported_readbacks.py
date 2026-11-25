"""Bind actual textbook values reported in prose for several named devices."""

import re


_FIELD_FOLLOWUP = re.compile(r"^(?:它们)?(?:各自|分别)(?:在|的)\s*`?"
                             r"(?P<field>[A-Z][A-Za-z0-9_-]*(?:[ \t]+[A-Za-z][A-Za-z0-9_-]*){1,5})"
                             r"`?\s*(?:的)?(?:[一二两三四1-4](?:个|项|条))?\s*(?:写|列|显示|记载)(?:了|的是)?什么$")
_DEVICE = r"[A-Za-z][A-Za-z_-]{0,7}\d{1,4}(?:[-_][A-Za-z0-9]+)?"
_DEVICE_TOKEN = re.compile(rf"(?<![A-Za-z0-9_-]){_DEVICE}(?![A-Za-z0-9_/-])", re.I)
_REPORTED_STATE = re.compile(rf"(?<![A-Za-z0-9_-])(?P<owners>{_DEVICE}(?:\s*(?:与|和|、|及)\s*{_DEVICE})+)\s*的\s*`(?:display|show)\s+[^`\n]+`\s*"
                             r"(?:结果|回显|状态|输出)\s*(?:均|都|各自)\s*(?:回到|恢复为|显示为|变成|进入|为)\s*"
                             r"(?:[A-Za-z0-9_-]+|[\u3400-\u9fff]{2,12})", re.I)
_ASSIGNMENT = re.compile(rf"(?<![A-Za-z0-9_-])(?P<owner>{_DEVICE})(?![A-Za-z0-9_/-])\s*(?:是|为|显示|列出|写着)", re.I)
_CELL = re.compile(r"`(?P<key>[^`:：\n]{2,50})[:：]\s*(?P<value>[^`\n]+)`")
_HYPOTHETICAL = re.compile(r"预期|预计|如果|计划|模拟规划|另一个案例|另一份结果")
_ASKED_STATE = re.compile(r"(?:都|均|分别|各自)(?:已(?:经)?)?(?:恢复|回到|进入|变成)(?:到|为)?\s*(?:[a-z0-9-]{2,}|正常|稳定|什么)", re.I)
_ACTUAL_FIELD = re.compile(r"(?:区别在|分别核对|查看|读到|列出|显示|字段(?:为|是)?)\s*$")
_COUNT = re.compile(r"([一二两三四1-4])(?:项|个|条)")
_DIGITS = str.maketrans("一二两三四", "12234")


def repeated_readback_field(text):
    """Read a field label from a question explicitly referring to each prior observer."""
    return match["field"] if (match := _FIELD_FOLLOWUP.fullmatch(text)) else ""


def _complete_field_group(owners, quoted_fields, count):
    records = list(_ASSIGNMENT.finditer(quoted_fields))
    if {record["owner"].casefold() for record in records} != owners or len(records) != len(owners):
        return False
    schemas = []
    for index, owner in enumerate(records):
        stop = records[index + 1].start() if index + 1 < len(records) else len(quoted_fields)
        fields = [match["key"].strip().casefold() for match in _CELL.finditer(quoted_fields, owner.end(), stop)
                  if match["value"].strip()]
        if not fields or len(set(fields)) != len(fields) or count and len(fields) != count:
            return False
        schemas.append(frozenset(fields))
    return len(set(schemas)) == 1


def reported_readback_witness(facet, text):
    if facet.kind != "readback" or len(facet.devices) < 2 or _HYPOTHETICAL.search(text):
        return False
    if _ASKED_STATE.search(facet.text):
        for state in _REPORTED_STATE.finditer(text):
            owners = [match[0].casefold() for match in _DEVICE_TOKEN.finditer(state["owners"])]
            if len(owners) == len(facet.devices) and set(owners) == facet.devices:
                return True
        return False
    if not facet.readback_label or not repeated_readback_field(facet.text):
        return False
    field = re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(facet.readback_label)}(?![A-Za-z0-9_-])", re.I)
    numeric = _COUNT.search(facet.text)
    count = int(numeric[1].translate(_DIGITS)) if numeric else 0
    return any((found := field.search(clause)) and _ACTUAL_FIELD.search(clause[:found.start()])
               and _complete_field_group(facet.devices, clause[found.end():], count)
               for clause in re.split(r"[。；\n]", text))
