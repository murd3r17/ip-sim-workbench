"""Choose independently validated complementary evidence for a named device pair."""
import asyncio
from dataclasses import dataclass
import re
from unicodedata import normalize

from core.markdown_blocks import blocks, complete_prefix, unclosed_fence_start
from modules.knowledge.edition import _page_texts
from modules.knowledge.query_focus import compact_text
from modules.knowledge.reader import DocumentReadError


_DEVICE_ALIAS = r"(?:fw\d*|ce\d*|pe\d*|ar\d*|sw\d*|ne\d*|ap\d*|leaf\d*|spine\d*|edge\d*|acc\d*|router\d*|switch\d*|node\d*|gw\d*)[-_][a-z0-9]{1,4}"
_ALIASES = re.compile(rf"(?<![a-z0-9_-]){_DEVICE_ALIAS}(?![a-z0-9_/-])", re.I)
_PROMPTS = re.compile(rf"(?m)^\s*(?:<(?P<read>{_DEVICE_ALIAS})>|\[(?P<owner>{_DEVICE_ALIAS})(?:-(?:[a-z][^]\r\n]*))?\])\s*\S", re.I)
_RESERVED = {"pe", "ce", "leaf", "id", "list", "bgp", "ospf", "net", "if", "port", "rpc", "l2", "l3"}
_SPLIT = re.compile(r"[？?；;。！!\n]+|[,，]\s*(?=再(?:看|查|核对)|另外|接着|同时核对|还有)")
_QUESTION = re.compile(r"哪|谁|几|多少|什么|怎么|如何|是否|怎样|了吗|有无|是[不是]|还是|有没有|吗")
_UNRELATED = re.compile(r"(?:另一|其他|别的|不同的)(?:[一两]?(?:个|组|次|种))?(?:实验|案例|场景)|逐字|原句|除了|排除|(?<!分)别把|不要(?:混|找|查|用)")
_STATE = re.compile(r"(?P<distributed>分布式(?:网关)?|\bdistributed\s+gateway\b)|(?P<central>集中式(?:网关)?|\bcentralized\s+gateway\b)|"
                    r"(?P<static_l2>静态[^。；，]{0,15}二层(?:互通)?|静态VXLAN\s*隧道实现二层互通)|"
                    r"(?P<active_standby>主备(?:模式|同步|状态)|\bactive[- /]standby\b)|"
                    r"(?P<balance>负载分担(?:模式)?|\bload\s+sharing\b)|"
                    r"(?P<transparent>透明(?:模式|防火墙)|\btransparent\s+mode\b)|(?P<routed>路由模式|\brouted\s+mode\b)", re.I)
_PHASE = re.compile(r"(配置|切换|倒换|故障|恢复|调整|重选)(?:完成|发生)?(?:之|以)?(前|后)")
_VARIANT = re.compile(r"(?:方案|案例|场景|模式|配置方式)\s*([一二三四1-4A-D])(?=[\s：:，。；、]|$)", re.I)
_COLLECTIVE = re.compile(r"两(?:个\s*)?(?:Edge|Leaf|CE|NVE|VTEP|网关|设备|防火墙|台|端|侧)|分别.*(?:配置|回显|学习)|由.*集中部署", re.I)
_EXACT_TERM = re.compile(r"(?<![A-Za-z0-9_-])(?:[A-Z][a-z]{2,15}[0-9]*|[A-Z]{2,12}[0-9]*)(?![A-Za-z0-9_-])")
_FIELDS = re.compile(
    r"(?P<bridge>桥域|\bbd\s*[0-9]+|bridge-domain)|(?P<local_attach>二层子接口|本地接入|子接口|(?:\bge|gigabitethernet)[0-9/]+\.[0-9]+)|"
    r"(?P<replication>复制列表|head-end|头端复制)|(?P<tunnel>NVE|隧道|tunnel)|"
    r"(?P<peer_method>手写|手工指定|静态配置对端|协议发现|协议[^。；，]{0,10}建)|"
    r"(?P<peer>对等体|邻居|\bpeer\b)|(?P<advertisement>通告|\badvertise\b)|(?P<configuration>配没配|配置|启用|打开)|"
    r"(?P<readback>回显|读回|\bdisplay\s|\bshow\s)|(?P<state>状态|\bestablished\b|\b(?:up|down)/static\b|\bstatic/(?:up|down)\b)|"
    r"(?P<number>条数|几条|收(?:到)?\s*[0-9]+\s*条|各\s*[一二三四五0-9]\s*条|\bPrefRcv\b)|"
    r"(?P<learn>学(?:到|习|得)|\blearn(?:ed|ing)\b)|(?P<mac>\bMAC\b)|(?P<gateway>网关角色|VBDIF|网关设备)|"
    r"(?P<probe>探测|应答|\bping\b)|(?P<owner>主用|备用|主设备|备设备|主防火墙|备防火墙)|"
    r"(?P<role>角色|优先级|客户端|服务端|发起端|接收端)|(?P<mode>工作模式|运行模式|协商模式|配置模式)", re.I,
)


@dataclass(frozen=True)
class AliasFacet:
    query: str
    fields: frozenset[str]
    aliases: frozenset[str]
    phases: frozenset[tuple[str, str]]
    specific_terms: frozenset[str]


@dataclass(frozen=True)
class AliasRequest:
    mode: str | None
    shared_phases: frozenset[tuple[str, str]]
    aliases: frozenset[str]
    facets: tuple[AliasFacet, AliasFacet]


@dataclass(frozen=True)
class AliasProof:
    hit: dict
    aliases: frozenset[str]


def device_aliases(text):
    plain = normalize("NFKC", text).casefold()
    names = {*_ALIASES.findall(plain), *(left or right for left, right in _PROMPTS.findall(plain))}
    return frozenset(name for name in names if re.split("[-_]", name)[-1] not in _RESERVED)


def _fields(text):
    return frozenset(match.lastgroup for match in _FIELDS.finditer(text))


def _modes(text):
    return frozenset(match.lastgroup for match in _STATE.finditer(text))


def alias_request(query):
    modes = _modes(query)
    phases = frozenset(_PHASE.findall(query))
    aliases = device_aliases(query)
    if len(modes) > 1 or (not modes and len(phases) != 1) or len(aliases) != 2 or _UNRELATED.search(query):
        return None
    parts = [part.strip() for part in _SPLIT.split(query) if _QUESTION.search(part) and 6 <= len(part) <= 150]
    if len(parts) != 2:
        return None
    overlap = _fields(parts[0]) & _fields(parts[1])
    name = next(iter(modes), None)
    qualifiers = [match[0] for match in _STATE.finditer(query)] if modes else ["".join(phase) for phase in phases]
    shared = " ".join([*qualifiers, *sorted(aliases)])
    left, right = (AliasFacet(f"{shared} {part}", _fields(part) - overlap - {"readback"}, device_aliases(part),
                              frozenset(_PHASE.findall(part)), frozenset(word.casefold() for word in _EXACT_TERM.findall(part)))
                   for part in parts)
    return AliasRequest(name, phases if not modes else frozenset(), aliases, (left, right)) if min(len(left.fields), len(right.fields)) >= 2 else None


def _same_mode(hit, request):
    if request.mode is None:
        return request.shared_phases <= set(_PHASE.findall(hit["text"] + "\n" + hit.get("title", "")))
    modes = _modes(hit["text"]) or _modes(hit.get("title", ""))
    return modes == {request.mode}


def _matches(hit, facet, request, aliases, *, leading=False):
    text = complete_prefix(hit["text"], 1080)
    if not text or not _same_mode(hit, request) or not facet.phases <= set(_PHASE.findall(text)):
        return False
    candidates = [text] if leading else [text[start:end] for kind, start, end in blocks(text) if kind != "heading"]
    for witness in candidates:
        if not facet.fields <= _fields(witness) or unclosed_fence_start(witness) is not None:
            continue
        declared = device_aliases(witness) & request.aliases
        if (declared and facet.aliases <= declared) or (leading and _COLLECTIVE.search(witness) and request.aliases <= aliases):
            return True
    return False


def _identity(hit):
    return hit.get("document_id"), hit.get("section_id"), compact_text(hit["text"])


def _compatible(lhs, rhs, request):
    left, right = lhs.hit, rhs.hit
    if left["document_id"] != right["document_id"] or abs(left["page"] - right["page"]) > 4:
        return False
    phases = set(_PHASE.findall(left["text"] + "\n" + right["text"]))
    if any((action, "前" if when == "后" else "后") in phases for action, when in phases):
        return False
    if len(set(_VARIANT.findall(left["text"] + "\n" + right["text"]))) > 1:
        return False
    return request.aliases <= (lhs.aliases | rhs.aliases)


def _leading_windows(page):
    units = list(blocks(page))
    leading = next((index for index, unit in enumerate(units) if unit[0] != "heading"), None)
    if leading is None or units[leading][0] != "paragraph":
        return []
    _, start, end = units[leading]
    options = [page[start:end].strip()]
    next_unit = leading + 1
    if next_unit < len(units) and units[next_unit][0] in {"fence", "table"} and units[next_unit][2] - start <= 1080:
        options.append(page[start:units[next_unit][2]].strip())
    return options


def _read_pages(edition, identifier, version):
    try:
        return _page_texts(edition.read(identifier, version, include_original_status=False))
    except (DocumentReadError, OSError, ValueError, KeyError):
        return {}


async def expand_alias(edition, workspace, request, current, broad, limit, *, on_pair=None):
    if len(current) < 4:
        return current

    def verified(hit):
        return hit.get("edition_version") == edition.version and hit.get("section_id") and type(hit.get("page")) is int

    def visible(hits, facet):
        return [AliasProof(hit, device_aliases(hit["text"])) for hit in hits if verified(hit)
                and _matches(hit, facet, request, device_aliases(hit["text"]))]

    current_keys = {_identity(hit) for hit in current}
    by_page = {}
    for hit in current:
        if verified(hit):
            by_page.setdefault((hit["document_id"], hit["section_id"]), []).append(hit)
    first, second = (visible(current, facet) for facet in request.facets)
    if any(_compatible(left, right, request) for left in first for right in second):
        return current
    scope = {doc_id for doc_id, doc in edition.documents.items() if doc["ingest"] and _modes(doc["title"]) == {request.mode}}
    documents = scope if 1 <= len(scope) <= 16 else None
    provider = edition.keyword_index
    runs = await asyncio.gather(*(provider.search_pages(facet.query, 48, document_ids=documents) for facet in request.facets))
    groups = []
    bodies = {}
    for facet, (_, candidates) in zip(request.facets, runs, strict=True):
        bound = await asyncio.to_thread(edition.resolve_hits, candidates, provider, workspace, query=facet.query)
        unique = {(hit["document_id"], hit["page"]): hit for hit in [*bound, *broad, *current] if verified(hit) and _same_mode(hit, request)
                  and not (hit.get("partial_readonly_table") or hit.get("source_range_reduced"))}
        proofs = {_identity(proof.hit): proof for proof in visible([*bound, *broad, *current], facet)}
        for hit in unique.values():
            identifier, version = hit["document_id"], hit["document_version"]
            if (identifier, version) not in bodies:
                bodies[identifier, version] = await asyncio.to_thread(_read_pages, edition, identifier, version)
            mapped = bodies[identifier, version].get(hit["page"])
            if not mapped or mapped[0] != hit["section_id"]:
                continue
            aliases = device_aliases(mapped[1])
            for excerpt in _leading_windows(mapped[1]):
                candidate = {**hit, "text": excerpt}
                if _matches(candidate, facet, request, aliases, leading=True) and unclosed_fence_start(excerpt) is None:
                    same_page = by_page.get((identifier, mapped[0]), ())
                    already_visible = next((item for item in same_page
                                            if compact_text(excerpt) in compact_text(complete_prefix(item["text"], 1080))), None)
                    shown = already_visible or candidate
                    proofs.setdefault(_identity(shown), AliasProof(shown, aliases))
                    break
        groups.append(list(proofs.values()))
    def rank(left, right):
        specificity = sum(len(facet.specific_terms & {word.casefold() for word in _EXACT_TERM.findall(proof.hit["text"])})
                          for facet, proof in zip(request.facets, (left, right), strict=True))
        existing = sum(_identity(proof.hit) in current_keys for proof in (left, right))
        return specificity, existing, -abs(left.hit["page"] - right.hit["page"])

    pairs = [(left.hit, right.hit, rank(left, right))
             for left in groups[0] for right in groups[1]
             if _compatible(left, right, request) and (left.hit["document_id"], left.hit["page"]) != (right.hit["document_id"], right.hit["page"])]
    if not pairs:
        return current
    left, right, score = max(pairs, key=lambda item: item[2])
    if len({(l["document_id"], l["page"], r["page"]) for l, r, rank in pairs if rank == score}) != 1:
        return current
    extra = [hit for hit in (left, right) if _identity(hit) not in current_keys]
    protected = {_identity(proof.hit) for group in groups for proof in group if _identity(proof.hit) in current_keys}
    replace = [i for i, hit in enumerate(current) if i >= 2 and hit.get("retriever") in {"edition_local", "focused_original"}
               and not (hit.get("partial_readonly_table") or hit.get("source_range_reduced")) and _identity(hit) not in protected]
    if not extra or len(extra) > len(replace):
        return current
    result = list(current)
    for i, hit in zip(replace[-len(extra):], extra, strict=True):
        result[i] = hit
    if on_pair is not None:
        on_pair(("alias_case", (left, right)))
    return result[:limit]
