"""Keep complete, device-scoped route records from a single verified page."""

from dataclasses import dataclass
from ipaddress import ip_address, ip_network
import re

from .markdown_blocks import FENCE, blocks, unclosed_fence_start


_DEVICE = r"(?:ar|pe|p|r|ce|fw|sw|s|ne)[0-9]+"
_DEVICES = rf"{_DEVICE}(?:\s*(?:、|和|与|及|跟|[,，])\s*{_DEVICE})*"
_DEVICE_SCOPE = re.compile(
    rf"(?:在|从|看|查看|查阅|核对|对照|比较|读回)\s*"
    rf"(?P<devices>{_DEVICES})(?![a-z0-9])(?P<context>[^，。；？\n]{{0,24}}?)"
    r"(?:路由表|转发表|(?:is-is|isis|ospf)\s*(?:的)?\s*表|回显)", re.I,
)
_DEVICE_NAME = re.compile(rf"(?<![a-z0-9]){_DEVICE}(?![a-z0-9])", re.I)
_ADDRESS = r"(?:[0-9]{1,3}(?:\.[0-9]{1,3}){3}|[0-9a-f:]*:[0-9a-f:.]+)"
_CIDR = re.compile(rf"(?<![a-z0-9:.]){_ADDRESS}/[0-9]{{1,3}}(?![a-z0-9./%])", re.I)
_ONE_PREFIX = re.compile(r"(?:哪(?:一)?条|哪(?:一)?个|什么|精确)(?:目的|IPv[46]|\s)*前缀", re.I)
_PHASE = re.compile(r"(汇总|引入|重分发|切换|重选|故障|调整|启用)(前|后)")
_ROUTE_REDISTRIBUTION = ("引入", "重分发")
_ROUTE_CONTEXT = re.compile(r"路由|转发表|\b(?:bgp|is-is|isis|ospf|rip)\b", re.I)
_UNSUPPORTED = re.compile(
    r"总数|共计|多少条|几条(?:路由|记录)|所有(?:路由|记录)|每(?:一)?[行条]|相邻[行条]|"
    r"前后|排除|除了|不(?:含|包括|等于)|Flags?|保护类型|\b(?:total|except|exclude)\b", re.I,
)
_PHYSICAL_PAGE = re.compile(r"^### PDF 第 [0-9]+ 页\b.*$", re.M)
_PROMPT = re.compile(r"\s*(?:<(?P<angle>[^>]+)>|\[(?P<bracket>[^\]]+)\])\s*(?P<command>\S.*)")
_READ_TABLE = re.compile(
    rf"display\s+(?:ospf\s+routing|isis\s+route\s+ipv6\s+(?P<filter>{_ADDRESS}(?:/[0-9]{{1,3}})?))\s*", re.I,
)
_RELATED_TABLE = re.compile(r"display\s+(?:ospf\s+routing|isis\s+route)\b", re.I)
_OSPF_HEADER = re.compile(r"\s*Destination\s+Cost\s+Type\s+NextHop\s+AdvRouter\s+Area\s*", re.I)
_ISIS_HEADER = re.compile(r"\s*IPV6\s+Dest\.\s+ExitInterface\s+NextHop\s+Cost\s+Flags\s*", re.I)
_OSPF_CONTEXT = re.compile(
    r"\s*(?:OSPF Process [0-9]+ with Router ID [0-9.]+|Routing Tables|Routing for Network)\s*", re.I,
)
_ISIS_CONTEXT = re.compile(
    r"\s*(?:Route information for ISIS\([0-9]+\)|ISIS\([0-9]+\) Level-[12] Forwarding Table)\s*", re.I,
)
_OSPF_FOOTER = re.compile(
    r"\s*(?:Total Nets:\s*[0-9]+|Intra Area:\s*[0-9]+\s+Inter Area:\s*[0-9]+\s+ASE:\s*[0-9]+\s+NSSA:\s*[0-9]+)\s*",
    re.I,
)
_ISIS_FOOTER = re.compile(r"\s*(?:Flags:\s+.+|U-Up/Down Bit Set(?:,.*)?|Protect Type:\s+.+)\s*", re.I)
_OSPF_TYPES = {"stub", "transit", "inter-area", "external", "ase", "nssa"}
_SEPARATOR = re.compile(r"\s*-{8,}\s*")
_LABEL = "**同页只读回显摘录。** 各表保留原设备命令、表头和所问记录。"


@dataclass(frozen=True)
class RouteTable:
    device: str
    address_filter: str | None
    heading: tuple[str, ...]
    records: tuple[tuple[str, str], ...]
    page_offset: int


def _network(value):
    try:
        return str(ip_network(value)) if "/" in value else None
    except ValueError:
        return None


def _ip_version(value):
    try:
        return ip_address(value).version
    except ValueError:
        return None


def _row_key(line, ipv6):
    fields = line.split()
    if not fields:
        return None
    prefix = _network(fields[0])
    if not prefix:
        return None
    if ipv6:
        return prefix if (len(fields) == 5 and ":" in prefix and fields[3].isdigit()
                          and _ip_version(fields[2]) == 6 and re.fullmatch(r"[a-z0-9/-]+", fields[4], re.I)) else None
    return prefix if (len(fields) == 6 and ":" not in prefix and fields[1].isdigit()
                      and fields[2].casefold() in _OSPF_TYPES
                      and all(_ip_version(value) == 4 for value in fields[3:])) else None


def _parse_table(lines, device, address_filter, page_offset):
    ipv6 = bool(address_filter)
    header = _ISIS_HEADER if ipv6 else _OSPF_HEADER
    context = _ISIS_CONTEXT if ipv6 else _OSPF_CONTEXT
    footer = _ISIS_FOOTER if ipv6 else _OSPF_FOOTER
    header_position = next((position for position, line in enumerate(lines) if header.fullmatch(line)), None)
    if header_position is None or not all(
        not line.strip() or _SEPARATOR.fullmatch(line) or context.fullmatch(line) for line in lines[1:header_position]
    ):
        return None
    row_start = header_position + 1
    if row_start < len(lines) and _SEPARATOR.fullmatch(lines[row_start]):
        row_start += 1
    records = []
    after_rows = False
    for line in lines[row_start:]:
        if not line.strip():
            continue
        if footer.fullmatch(line):
            after_rows = True
            continue
        key = _row_key(line, ipv6)
        if not key or after_rows:
            return None
        records.append((key, line))
    if not records or len({key for key, _ in records}) != len(records):
        return None
    heading = tuple(line for line in lines[:row_start] if not _SEPARATOR.fullmatch(line))
    return RouteTable(device, address_filter, heading, tuple(records), page_offset)


def _read_tables(body, devices):
    tables = []
    if unclosed_fence_start(body) is not None:
        return None
    for kind, start, end in blocks(body):
        if kind != "fence":
            continue
        fence = body[start:end].splitlines()
        marker = FENCE.match(fence[0])
        if fence[0][marker.end():].strip().casefold() not in {"", "text", "plaintext", "console"}:
            continue
        lines = fence[1:-1]
        prompts = [(index, match) for index, line in enumerate(lines) if (match := _PROMPT.fullmatch(line))]
        boundaries = [index for index, _ in prompts[1:]] + [len(lines)]
        for (index, prompt), next_index in zip(prompts, boundaries):
            device = (prompt["angle"] or prompt["bracket"]).casefold()
            if device not in devices or not _RELATED_TABLE.match(prompt["command"]):
                continue
            command = _READ_TABLE.fullmatch(prompt["command"])
            if not command:
                return None
            table = _parse_table(lines[index:next_index], device, command["filter"], start)
            if not table:
                return None
            tables.append(table)
    return tables


def _observed_single_prefix(table):
    if not table.address_filter or len(table.records) != 1:
        return None
    observed = table.records[0][0]
    try:
        query_address = ip_address(table.address_filter.split("/")[0])
        network = ip_network(observed)
        if query_address == network.network_address and ("/" not in table.address_filter
                                                         or _network(table.address_filter) == observed):
            return observed
    except ValueError:
        return None
    return None


def _selection(tables, devices, requested):
    selected = []
    for device in devices:
        compatible = [table for table in tables if table.device == device and
                      (requested <= {key for key, _ in table.records} if requested else _observed_single_prefix(table))]
        if len(compatible) != 1:
            return None
        selected.append(compatible[0])
    if not requested and len({_observed_single_prefix(table) for table in selected}) != 1:
        return None
    return [table for table in tables if table in selected]


def _phase_context(body, phase, boundary):
    operation, moment = phase
    operations = _ROUTE_REDISTRIBUTION if operation in _ROUTE_REDISTRIBUTION else (operation,)
    actions = "|".join(map(re.escape, operations))
    phrase = re.compile(rf"({actions})[^，。？！；]{{0,24}}?(前后|前(?!缀)|后)")
    # A later labelled snapshot supersedes an earlier one for subsequent
    # tables. Two results in the same unlabelled fence remain ambiguous.
    context = None
    for kind, start, end in blocks(body):
        if start >= boundary:
            break
        if kind != "paragraph" or end > boundary:
            continue
        paragraph = body[start:end].strip()
        moments = {when for action, when in phrase.findall(paragraph)
                   if action == operation or _ROUTE_CONTEXT.search(paragraph)}
        if moments:
            context = paragraph if moments == {moment} else None
    return context


def select_readonly_route_excerpt(body: str, query: str, *, max_chars: int = 1040) -> str | None:
    """Select complete rows from uniquely identified same-page device tables."""
    if _UNSUPPORTED.search(query):
        return None
    scopes = list(_DEVICE_SCOPE.finditer(query))
    phases = {(_ROUTE_REDISTRIBUTION[0] if operation in _ROUTE_REDISTRIBUTION else operation, when)
              for operation, when in _PHASE.findall(query)}
    if len(scopes) != 1 or len(phases) > 1 or _DEVICE_NAME.search(scopes[0]["context"]):
        return None
    devices = {name.casefold() for name in _DEVICE_NAME.findall(scopes[0]["devices"])}
    prefixes = {_network(value) for value in _CIDR.findall(query)}
    if None in prefixes or len(prefixes) > 4 or (not prefixes and not _ONE_PREFIX.search(query)):
        return None
    pages = list(_PHYSICAL_PAGE.finditer(body))
    if len(pages) != 1 or body[:pages[0].start()].strip():
        return None
    tables = _read_tables(body, devices)
    if not tables:
        return None
    phase = next(iter(phases), None)
    contexts = {table.page_offset: _phase_context(body, phase, table.page_offset) for table in tables} if phase else {}
    selection = _selection([table for table in tables if not phase or contexts[table.page_offset]], devices, prefixes)
    if not selection:
        return None
    fragments = [pages[0].group().strip(), _LABEL]
    if phase:
        fragments.extend(dict.fromkeys(contexts[table.page_offset] for table in selection))
    for table in selection:
        records = [line for key, line in table.records if not prefixes or key in prefixes]
        fragments.append("\n".join(("```text", *table.heading, *records, "```")))
    excerpt = "\n\n".join(fragment for fragment in fragments if fragment)
    return excerpt if len(excerpt) <= max_chars else None
