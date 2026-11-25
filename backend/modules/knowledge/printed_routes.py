"""Verify a printed readout of multiple paths to one destination."""

from dataclasses import dataclass
from ipaddress import ip_address, ip_network
import re

from core.source_units import reading_units
from .query_focus import compact_text, protocol_names


_COUNT = r'(?P<count>[2-8二两三四五六七八])\s*(?:条|项|个)'
_DIGITS = str.maketrans('二两三四五六七八', '22345678')
_DEVICE = re.compile(r'(?<![a-z0-9_-])(?:ar|ce|cr|ne|pe|sw|r|p)[-_]?\d{1,4}(?![a-z0-9_/-])', re.I)
_NETWORK = re.compile(r'(?<![a-z0-9.:])(?:\d{1,3}(?:\.\d{1,3}){3}|[0-9a-f:]+:[0-9a-f:]+)\s*/\s*\d{1,3}(?![\d/])', re.I)
_NEXT_HOPS = re.compile(r'下一跳|next[ _-]*hop', re.I)
_OUTPUT_INTERFACE = re.compile(r'出接口|出口网口|(?:out|egress)[ _-]*interface', re.I)
_MATCHING_COLUMNS = re.compile(r'一样|一致|相同|有没有区别|有无差别')
_PREFERENCE = re.compile(r'优先级|\bpre(?:ference)?\b', re.I)
_METRIC = re.compile(r'度量|开销|\b(?:cost|metric)\b', re.I)
_SCOPE_CONFLICT = re.compile(r'另一(?:个|组|次|台|例)|不同(?:案例|设备|实验)|例如|预计|预期|规划|应该|假设|如果|可能|'
                             r'(?:更换|切换|重启|故障|调整)(?:前后|之前|之后|前|后)')
_COUNTS_RECORDED = re.compile(rf'(?:显示|列出|命中|读到|记录(?:为|了)|返回)\s*{_COUNT}')
_READ_COMMAND = re.compile(r'\b(?:display\s+(?:ip\s+)?routing-table|show\s+(?:ip\s+|ipv6\s+)?route)\b', re.I)
_PATHS = re.compile(r'下一跳(?:分别(?:是|为)?|依次(?:是|为)?)|next[ _-]*hops?\s*(?:are|:)', re.I)
_INTERFACE = r'(?:GE|XGE|GigabitEthernet|Ethernet|TenGigE|Eth|Vlanif|Vlan|Eth-Trunk|Port-channel|ae|xe)[-_]?\d+(?:/\d+){0,3}(?:\.\d+)?'
_PAIR = re.compile(rf'(?<![a-z0-9.:])(?P<hop>\d{{1,3}}(?:\.\d{{1,3}}){{3}}|[0-9a-f:]+:[0-9a-f:]+)`?'
                   rf'\s*(?:/|经(?:由)?|的出接口为)\s*`?(?P<interface>{_INTERFACE})(?![a-z0-9/-])', re.I)
_PREFERENCE_VALUE = re.compile(r'(?:优先级|\bpre(?:ference)?\b)\s*(?:为|[:：=])?\s*\d+', re.I)
_METRIC_VALUE = re.compile(r'(?:度量|开销|\b(?:cost|metric)\b)\s*(?:为|[:：=])?\s*\d+', re.I)
_SEPARATE_METRICS = re.compile(r'不同|不等|不一致|其中(?:一|仅)|另一?(?:条|路)|各为|分别为')


@dataclass(frozen=True)
class PrintedRoutes:
    owner: str
    destination: str
    protocol: str
    count: int
    clauses: tuple[str, ...]


def _route_labels(pattern, text):
    return {compact_text(match.group()) for match in pattern.finditer(text)}


def printed_routes_request(clauses: tuple[str, ...]) -> PrintedRoutes | None:
    if not 1 <= len(clauses) <= 2 or _SCOPE_CONFLICT.search('。'.join(clauses)):
        return None
    question = clauses[0]
    identifiers = _route_labels(_DEVICE, question)
    destinations = _route_labels(_NETWORK, question)
    protocols = protocol_names(question)
    counts = {int(match['count'].translate(_DIGITS)) for match in re.finditer(_COUNT, question)}
    if (len(identifiers) != 1 or len(destinations) != 1 or len(protocols) != 1 or len(counts) != 1
            or not _NEXT_HOPS.search(question) or not _OUTPUT_INTERFACE.search(question)
            or not re.search(r'回显|读回|输出|显示|路由表', question)):
        return None
    if len(clauses) == 2:
        followup = clauses[1]
        if (not all(pattern.search(followup) for pattern in (_PREFERENCE, _METRIC, _MATCHING_COLUMNS))
                or _DEVICE.search(followup) or _NETWORK.search(followup) or protocol_names(followup)):
            return None
    try:
        destination = str(ip_network(next(iter(destinations)), strict=True))
    except ValueError:
        return None
    return PrintedRoutes(next(iter(identifiers)), destination, next(iter(protocols)), next(iter(counts)), clauses)


def complete_printed_routes(text: str, request: PrintedRoutes) -> str | None:
    """Check the physical source's jointly attributed rows and shared fields."""
    verified = []
    for unit in reading_units(text):
        if unit.kind != 'paragraph':
            continue
        statement = text[unit.start:unit.end].strip()
        for sentence in re.split(r'[。；!?！？\n]', statement):
            if (_SCOPE_CONFLICT.search(sentence) or _route_labels(_NETWORK, sentence) != {request.destination}
                    or request.protocol not in protocol_names(sentence)):
                continue
            count = _COUNTS_RECORDED.search(sentence)
            paths = _PATHS.search(sentence)
            command = _READ_COMMAND.search(sentence)
            if (not count or not paths or not command or not command.end() < count.start() < paths.start()
                    or int(count['count'].translate(_DIGITS)) != request.count
                    or _route_labels(_DEVICE, sentence[:command.start()]) != {request.owner}):
                continue
            hops = _PAIR.finditer(sentence, paths.end())
            try:
                shown = [(str(ip_address(hit['hop'])), compact_text(hit['interface'])) for hit in hops]
            except ValueError:
                continue
            if len(shown) != request.count or len(set(shown)) != request.count:
                continue
            shared = sentence[count.end():paths.start()]
            if len(request.clauses) == 2 and (_SEPARATE_METRICS.search(shared)
                    or len(_PREFERENCE_VALUE.findall(shared)) != 1 or len(_METRIC_VALUE.findall(shared)) != 1):
                continue
            verified.append(sentence.lstrip('* \t').rstrip())
    return verified[0] if len(verified) == 1 else None
