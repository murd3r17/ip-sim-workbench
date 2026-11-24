"""Select a cited record inside a recognized, read-only CLI table."""
from dataclasses import dataclass
from ipaddress import IPv4Address
import re

from .markdown_blocks import FENCE, blocks, unclosed_fence_start


_IPV4 = r"[0-9]{1,3}(?:\.[0-9]{1,3}){3}"
_IP_IN_QUERY = re.compile(rf"(?<![\w.]){_IPV4}(?![A-Za-z0-9./])", re.ASCII)
_ROW_ID = re.compile(rf"(?:\bLink\s*State\s+ID\b|链路状态\s*ID)\s*(?:为|是|等于|[:：=])?\s*`?({_IPV4})(?![A-Za-z0-9./])", re.I)
_AREA_IN_QUERY = re.compile(rf"(?:\bArea\b|区域)\s*[:：]?\s*({_IPV4}|[0-9]+)(?![A-Za-z0-9./])", re.I)
_UNSUPPORTED_QUERY = re.compile(r"全部|所有|总数|共计|一共|表项数量|多少条|几条|几行|每(?:一)?(?:条|行)|另一(?:条|行)|各(?:条|行)|"
                               r"相邻(?:条|行)|比较|对比|两(?:个)?区域|(?:故障|切换|调整|重选)[前后]|"
                               r"排除|除了|以外|之外|不(?:含|包括|等于)|\b(?:all|total|compare|except|exclude)\b", re.I)
_DEVICE_IN_QUERY = re.compile(r"(?<![a-z0-9])(?:r|ar|pe|p|ce|fw|s|ne|sw)[0-9]+(?![a-z0-9])", re.I)
_PROCESS_IN_QUERY = re.compile(r"(?:\bProcess\b|进程)\s*[:：]?\s*([0-9]+)", re.I)
_AREA = re.compile(rf"\s*Area\s*:\s*({_IPV4})\s*", re.I)
_TABLE_HEAD = re.compile(r"\s*Type\s+LinkState\s+ID\s+AdvRouter\s+Age\s+Len\s+Sequence\s+Metric\s*", re.I)
_SEPARATOR = re.compile(r"\s*-{10,}\s*")
_TABLE_ROW = re.compile(rf"\s*(?:Router|Network|Sum-Net|Sum-Asbr|External|NSSA)\s+({_IPV4})\s+({_IPV4})"
                        r"\s+[0-9]+\s+[0-9]+\s+(?:0x)?[0-9a-f]{8}\s+[0-9]+\s*", re.I)
_COMMAND = re.compile(r"\s*(?:<([a-z0-9_.-]+)>|\[([a-z0-9_.-]+)\])\s*display\s+ospf\s+lsdb\s*", re.I)
_PROCESS = re.compile(rf"\s*OSPF\s+Process\s+([0-9]+)\s+with\s+Router\s+ID\s+({_IPV4})\s*", re.I)
_INTRO = re.compile(r"\s*Link\s+State\s+Database\s*", re.I)
_EXCERPT_LABEL = "###### 只读回显摘录，仅显示所查记录。\n\n"


@dataclass(frozen=True)
class _AreaTable:
    address: IPv4Address
    header: tuple[str, ...]
    rows: tuple[tuple[IPv4Address, str], ...]


def _read_tables(lines):
    """Reject the entire fence if even one row or context line is unknown."""
    prologue = []
    device = process = None
    position = 0
    for pattern in (_COMMAND, _PROCESS, _INTRO):
        if position < len(lines) and (match := pattern.fullmatch(lines[position])):
            prologue.append(lines[position])
            position += 1
            if pattern is _COMMAND:
                device = (match[1] or match[2]).casefold()
            elif pattern is _PROCESS:
                process = int(match[1])
                IPv4Address(match[2])

    tables = []
    while position < len(lines):
        if not lines[position].strip():
            position += 1
            continue
        if position + 1 >= len(lines):
            return None
        area = _AREA.fullmatch(lines[position])
        if not area or not _TABLE_HEAD.fullmatch(lines[position + 1]):
            return None
        header = [lines[position], lines[position + 1]]
        position += 2
        if position < len(lines) and _SEPARATOR.fullmatch(lines[position]):
            header.append(lines[position])
            position += 1
        rows = []
        while position < len(lines) and (row := _TABLE_ROW.fullmatch(lines[position])):
            key = IPv4Address(row[1])
            IPv4Address(row[2])
            rows.append((key, lines[position]))
            position += 1
        if not rows:
            return None
        tables.append(_AreaTable(IPv4Address(area[1]), tuple(header), tuple(rows)))
    return prologue, device, process, tables


def select_readonly_cli_excerpt(text: str, query: str, *, max_chars: int = 980) -> str | None:
    """Extract a complete LSDB record only from an already verified single-page excerpt."""
    if len(text) <= max_chars or _UNSUPPORTED_QUERY.search(query):
        return None
    requested_id = _ROW_ID.findall(query)
    requested_area = _AREA_IN_QUERY.findall(query)
    requested_process = _PROCESS_IN_QUERY.findall(query)
    requested_devices = {device.casefold() for device in _DEVICE_IN_QUERY.findall(query)}
    if len(requested_id) != 1 or len(requested_area) > 1 or len(requested_process) > 1:
        return None
    if set(_IP_IN_QUERY.findall(query)) - set(requested_id + requested_area):
        return None
    spans = [(kind, start, end) for kind, start, end in blocks(text) if kind != "heading"]
    if len(spans) != 1 or spans[0][0] != "fence" or unclosed_fence_start(text) is not None:
        return None
    _, start, end = spans[0]
    if text[end:].strip():
        return None
    lines = text[start:end].rstrip().splitlines(keepends=True)
    marker = FENCE.match(lines[0])
    if lines[0][marker.end():].strip().casefold() not in {"", "text", "plaintext", "console"}:
        return None
    try:
        target = IPv4Address(requested_id[0])
        required_process = int(requested_process[0]) if requested_process else None
        area = None
        if requested_area:
            value = requested_area[0]
            area = IPv4Address(int(value) if value.isdecimal() else value)
        parsed = _read_tables(lines[1:-1])
    except ValueError:
        return None
    if parsed is None:
        return None
    prologue, device, process, tables = parsed
    if requested_devices and requested_devices != {device}:
        return None
    if required_process is not None and required_process != process:
        return None
    selected = [(table, row) for table in tables if area is None or table.address == area for key, row in table.rows if key == target]
    if len(selected) != 1:
        return None
    table, row = selected[0]
    excerpt = "".join((text[:start], _EXCERPT_LABEL, lines[0], *prologue, *table.header, row, lines[-1]))
    return excerpt if len(excerpt) <= max_chars else None
