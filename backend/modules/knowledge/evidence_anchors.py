"""Recognize strong, locally verifiable anchors for an illustrated readout."""
from dataclasses import dataclass
import re
from unicodedata import normalize

from core.markdown_blocks import blocks
from core.readonly_cli_tables import select_readonly_cli_excerpt

from .edition import _page_texts
from .query_focus import compact_text, protocol_names
from .reader import DocumentReadError
from .reviewed_source_notes import notes_for_excerpt


_TABLE_REQUEST = re.compile(r"回显|读回|输出中|表格|表项|表中|表里|表头|哪一(?:行|列)|字段")
_AMBIGUOUS = re.compile(
    r"(?:汇总|引入|重分发|切换|联动|故障|调整|重选)(?:前|后)|前后|对比|比较|排除|除了|"
    r"不(?:含|包括|等于)|(?:全部|所有|每一)[条行]|总数|一共|另一(?:表|页)|两张(?:表|图)"
)
_LSDB = re.compile(r"\blsdb\b|链路状态数据库", re.I)
_LSDB_KEY = re.compile(r"\blink\s*state\s+id\b|链路状态\s*id", re.I)
_AREA = re.compile(r"(?:\barea\b|区域)(?P<value>[ \t]*[:：]?[ \t]*[0-9]+(?:\.[0-9]+){0,3}(?![A-Za-z0-9./]))?", re.I)
_LSDB_FIELDS = re.compile(
    r"(?P<type>类型|\btype\b)|(?P<advertiser>(?:发布|通告)路由器|\badv[ _-]*router\b)|"
    r"(?P<sequence>序列号|\bsequence\b)|(?P<metric>度量|开销|\bmetric\b)|"
    r"(?P<age>老化时间|\bage\b)|(?P<length>长度|\blen(?:gth)?\b)", re.I,
)
_DEVICE = re.compile(r"(?<![A-Za-z0-9])(?:ar|ce|fw|ne|pe|pc|sw|ap|ac|p|r|s)[0-9]+(?![A-Za-z0-9])", re.I)
_MATRIX_FIELDS = re.compile(
    r"(?P<run_priority>(?:运行|生效)优先级|\bpriority[ _-]*run\b)|"
    r"(?P<configured_priority>配置优先级|\bpriority[ _-]*config\b)|"
    r"(?P<preempt_delay>抢占延[时迟]|\bdelay[ _-]*time\b)|"
    r"(?P<receive_interval>接收间隔|\brx[ _-]*interval\b)|"
    r"(?P<send_interval>发送间隔|\btx[ _-]*interval\b)|"
    r"(?P<detection_multiplier>检测倍数|\bdetect(?:ion)?[ _-]*mult(?:iplier)?\b)|"
    r"(?P<next_hop>下一跳|\bnext[ _-]*hop\b)|"
    r"(?P<egress_interface>出接口|出口网口|\b(?:out|exit|egress)[ _-]*interface\b)|"
    r"(?P<ingress_interface>入接口|入口网口|\b(?:in|ingress)[ _-]*interface\b)", re.I,
)


@dataclass(frozen=True)
class EvidenceAnchor:
    fields: frozenset[str]
    protocol: str
    device: str | None = None


def _fields(pattern, text):
    return frozenset(match.lastgroup for match in pattern.finditer(text))


def output_field_names(text):
    """Identify literal table-label equivalents without inspecting field values."""
    return _fields(_MATRIX_FIELDS, text)


def evidence_anchor_request(query: str) -> EvidenceAnchor | None:
    """Read only explicit field and object constraints without inferring values."""
    text = normalize("NFKC", query).casefold()
    if not _TABLE_REQUEST.search(text) or _AMBIGUOUS.search(text):
        return None
    protocols = protocol_names(text)
    if _LSDB.search(text) and _LSDB_KEY.search(text):
        fields = _fields(_LSDB_FIELDS, text)
        if len(fields) >= 2 and not protocols.difference({"ospf"}) and all(area["value"] for area in _AREA.finditer(text)):
            return EvidenceAnchor(fields, "ospf")
        return None
    fields = output_field_names(text)
    devices = set(_DEVICE.findall(text))
    if len(fields) >= 3 and len(devices) == len(protocols) == 1:
        return EvidenceAnchor(fields, next(iter(protocols)), next(iter(devices)))
    return None


def _matrix_excerpt(candidate, request):
    text = candidate["text"]
    heading_protocols = protocol_names(candidate.get("title", ""))
    preceding = ""
    excerpt = None
    for kind, start, end in blocks(text):
        if kind != "table":
            preceding = text[start:end] if kind == "paragraph" else ""
            continue
        table = text[start:end].rstrip()
        subjects = protocol_names(preceding + "\n" + table) or heading_protocols
        preceding = ""
        if len(table) > 980 or subjects != {request.protocol}:
            continue
        header, _, *rows = [line.strip().strip("|").split("|") for line in table.splitlines()]
        device_columns = [i for i, label in enumerate(header[1:], 1)
                          if _DEVICE.findall(label.casefold()) == [request.device]]
        if len(device_columns) != 1 or any(len(row) != len(header) for row in rows):
            continue
        column = device_columns[0]
        matches = [_fields(_MATRIX_FIELDS, row[0]) for row in rows if row[column].strip()]
        if all(sum(field in match for match in matches) == 1 for field in request.fields):
            if excerpt is not None:
                return None
            excerpt = table
    return excerpt


def _unique_matrix_on_page(edition, hit, excerpt, request):
    try:
        reading = edition.read(hit["document_id"], hit["document_version"], include_original_status=False)
    except (DocumentReadError, OSError, ValueError, KeyError):
        return False
    page = _page_texts(reading).get(hit["page"])
    return bool(page and page[0] == hit["section_id"] and _matrix_excerpt({**hit, "text": page[1]}, request) == excerpt)


def verified_evidence_anchor(edition, keyword, workspace, candidates, query, request):
    """Return one unambiguous admitted page with its complete source excerpt."""
    verified = {}

    def remember(hit):
        key = hit["book"], hit["page"], compact_text(hit["text"])
        verified.setdefault(key, hit)

    if request.device is None:
        plausible = [hit for hit in candidates if select_readonly_cli_excerpt(hit["text"], query)]
        for hit in edition.resolve_hits(plausible, keyword, workspace, query=query):
            if hit.get("partial_readonly_table"):
                remember(hit)
    else:
        for original in candidates:
            if not (excerpt := _matrix_excerpt(original, request)):
                continue
            for hit in edition.resolve_hits([{**original, "text": excerpt}], keyword, workspace):
                filename, version = hit["filename"], hit["document_version"]
                if (notes_for_excerpt(filename, original["text"], version) == notes_for_excerpt(filename, hit["text"], version)
                        and _unique_matrix_on_page(edition, hit, excerpt, request)):
                    remember(hit)
    return next(iter(verified.values())) if len(verified) == 1 else None
