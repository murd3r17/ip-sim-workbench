"""Use explicit independent question parts to fill missing same-case evidence."""
import asyncio
from dataclasses import dataclass
import re
from unicodedata import normalize

from core.markdown_blocks import blocks, complete_prefix, unclosed_fence_start
from modules.knowledge.query_focus import compact_text, passage_concepts, protocol_names

from .device_alias_facets import AliasRequest, alias_request, expand_alias


_KEY = re.compile(r"(?<![a-z0-9.:])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?:/[0-9]{1,2})?(?![a-z0-9./])", re.I)
_NAMED = re.compile(r"(?<![a-z0-9])(?:vlan|vsi|bd|eth[ -]?trunk)[ \t-]*[0-9]+(?![a-z0-9])", re.I)
_DEVICE = re.compile(r"(?<![a-z0-9])(?:ar|ce|fw|ne|pe|pc|sw|ap|ac|p|r|s)[0-9]+(?![a-z0-9])", re.I)
_TERM = re.compile(r"(?<![a-z0-9_/-])[a-z][a-z0-9_-]{1,24}(?![a-z0-9_/-])", re.I)
_SPLIT = re.compile(r"[？?；;。！!\n]+|(?:[,，])\s*(?=另外|还想|再问|以及|同时核对|再看|接着)")
_QUESTION = re.compile(r"哪|谁|几|多少|什么|怎么|如何|为何|为什么|是否|有无|能否|了吗|吗|分别|各自|又是|[？?]")
_OUTSIDE = re.compile(r"(?:另外|另一|别的|其他|不同的)(?:[一两]?(?:次|种|个|组))?(?:实验|案例|场景|设备)|逐字|原句|别把|不要(?:混|找|查|用)")
_STAGE = re.compile(r"(?P<action>故障|恢复|切换|调整|聚合|汇总|引入|重分发|重选|断链|启用)(?:发生|完成)?(?:之|以)?(?P<when>前|后)")
_ORDINAL = re.compile(r"第\s*([一二三四五六0-9])\s*阶段")
_DIGITS = str.maketrans("一二三四五六", "123456")
_VARIANT = re.compile(r"(?P<same>相同|同一个|同一套|不同|另一组|更换)(?:的)?(?:\s*Cluster\s*ID|集群|实验|方案|拓扑|配置)", re.I)
_PROMPT_OWNER = re.compile(r"(?m)^\s*(?:<([^>]+)>|\[([^\]\s]+)\])\s*(?:display|show)\s", re.I)
_SEMANTIC = re.compile(
    r"(?P<upstream>上游|\bupstream\b)|(?P<downstream>下游|\bdownstream\b)|"
    r"(?P<label_adv>标签(?:映射|广告|发布|绑定)|通告[^，。；]{0,8}标签|发布[^，。；]{0,8}标签|(?:分配|普通|直连)标签)|"
    r"(?P<client>客户端|\bclient\b)|(?P<server>服务端|\bserver\b)|"
    r"(?P<primary>主设备|主根桥)|(?P<backup>备设备|备份根桥)|"
    r"(?P<root_port>根端口|\broot\s+port\b)|(?P<alternate>备份端口|\balternate\b)|"
    r"(?P<border>出口边界|边界网关)|(?P<reflector>反射器|\brr\b)|"
    r"(?P<cost>路由(?:开销|代价)|\b(?:cost|metric)\b)|"
    r"(?P<preference>协议优先级|\bpre(?:ference)?\s*[0-9]+)|"
    r"(?P<feedback>回灌|重新回到)|(?P<zone>安全区|源区域|目的区域|\b(?:untrust|trust)\b)|"
    r"(?P<reachability>连通(?:试验|验证|性)|\bping\b)|(?P<tree>构树|入树|SPF\s*树)|"
    r"(?P<proof>足以(?:证明|确认)|不能(?:证明|确认)|仍需(?:验证|确认)|需要(?:另测|另查))", re.I,
)
_STOP = {"pdf", "ip", "ipv4", "ipv6", "and", "the", "in", "out", "show", "display", "of", "is", "are", "to", "or"}


@dataclass(frozen=True)
class Facet:
    query: str
    marks: frozenset[str]
    subjects: frozenset[str]
    stage: frozenset[str]
    devices: frozenset[str]


@dataclass(frozen=True)
class FacetPlan:
    keys: frozenset[str]
    facets: tuple[Facet, ...]


def _stages(text):
    return (frozenset(match["action"] + match["when"] for match in _STAGE.finditer(text))
            | frozenset("阶段" + value.translate(_DIGITS) for value in _ORDINAL.findall(text)))


def _marks(text):
    roles = {"concept:" + match.lastgroup for match in _SEMANTIC.finditer(text)}
    roles.update("concept:" + value for value in passage_concepts(text))
    terms = {token.casefold() for token in _TERM.findall(text)
             if not (_DEVICE.fullmatch(token) or _SEMANTIC.fullmatch(token))}
    return frozenset(roles | (terms - _STOP - protocol_names(text)))


def _case_keys(text):
    return {key for key in _KEY.findall(text) if "/" in key} | {compact_text(key).replace("-", "") for key in _NAMED.findall(text)}


def complementary_request(query):
    plain = normalize("NFKC", query)
    keys = frozenset(_case_keys(plain))
    if not keys:
        return alias_request(plain)
    if _OUTSIDE.search(query) or not 1 <= len(keys) <= 3:
        return None
    clauses = [part.strip(" ，,、") for part in _SPLIT.split(plain)]
    clauses = [part for part in clauses if _QUESTION.search(part) and 6 <= len(part) <= 128]
    if len(clauses) != 2:
        return None
    all_marks = [_marks(part) for part in clauses]
    facets = []
    scope = " ".join(sorted(keys))
    for part, marks, other in zip(clauses, all_marks, reversed(all_marks), strict=True):
        separate = marks - other
        if not separate:
            return None
        facets.append(Facet(f"{scope} {part}", frozenset(separate), frozenset(protocol_names(part)), _stages(part),
                            frozenset(_DEVICE.findall(part.casefold()))))
    return FacetPlan(keys, tuple(facets))


def _variant(text):
    labels = {"different" if match["same"] in {"不同", "另一组", "更换"} else "same" for match in _VARIANT.finditer(text[:180])}
    return labels


def _signature(hit, facet, keys):
    text = complete_prefix(hit["text"], 1080)
    if not text or not keys <= _case_keys(text):
        return frozenset()
    if facet.subjects and not facet.subjects <= protocol_names(text + " " + hit.get("title", "")):
        return frozenset()
    if facet.stage and not facet.stage <= _stages(text):
        return frozenset()
    points = set()
    for kind, start, stop in blocks(text):
        excerpt = text[start:stop]
        if kind == "heading" or not keys <= _case_keys(excerpt) or (kind == "fence" and unclosed_fence_start(excerpt) is not None):
            continue
        owners = {(left or right).casefold() for left, right in _PROMPT_OWNER.findall(excerpt)}
        if facet.devices and (not facet.devices <= set(_DEVICE.findall(excerpt.casefold())) or (owners and facet.devices != owners)):
            continue
        signs = facet.marks & _marks(excerpt)
        if len(signs) >= min(2, len(facet.marks)):
            points.update(signs)
    return frozenset(points)


def _compatible(left, right, plan):
    if left["document_id"] != right["document_id"] or abs(left["page"] - right["page"]) > 4:
        return False
    if len(_variant(left["text"]) | _variant(right["text"])) > 1:
        return False
    stages = _stages(left["text"]) | _stages(right["text"])
    if any(stage[:-1] + ("后" if stage[-1] == "前" else "前") in stages for stage in stages if stage[-1] in "前后"):
        return False
    return _key(left) == _key(right) or len(plan.keys) > 1 or bool(
        set(_DEVICE.findall(left["text"].casefold())) & set(_DEVICE.findall(right["text"].casefold())))


def _strong_case(left, right, plan):
    """Both missing facets need a tighter locator than a shared lab address alone."""
    devices = set(_DEVICE.findall(left["text"].casefold())) & set(_DEVICE.findall(right["text"].casefold()))
    return abs(left["page"] - right["page"]) <= 2 and (len(plan.keys) >= 2 or len(devices) >= 2)


def _key(hit):
    return hit["document_id"], hit["section_id"], compact_text(hit["text"])


async def expand_complementary(edition, workspace, plan, current, broad, limit, *, on_pair=None):
    if isinstance(plan, AliasRequest):
        return await expand_alias(edition, workspace, plan, current, broad, limit, on_pair=on_pair)
    if len(plan.facets) != 2 or len(current) < 3:
        return current

    def eligible(hit):
        return hit.get("edition_version") == edition.version and hit.get("section_id") and type(hit.get("page")) is int

    current = list(current)
    known = {_key(hit): hit for hit in [*current, *broad] if eligible(hit)}
    sides = [{key: (hit, _signature(hit, facet, plan.keys)) for key, hit in known.items()} for facet in plan.facets]
    keys = {_key(hit) for hit in current if eligible(hit)}
    already_visible = [[hit for key, (hit, marks) in side.items() if key in keys and marks] for side in sides]
    if any(_compatible(a, b, plan) for a in already_visible[0] for b in already_visible[1]):
        return current
    keyword = edition.keyword_index
    focused = await asyncio.gather(*(keyword.search_pages(facet.query, 16) for facet in plan.facets))
    for facet, side, (_, captured) in zip(plan.facets, sides, focused, strict=True):
        verified = await asyncio.to_thread(edition.resolve_hits, captured, keyword, workspace, query=facet.query)
        for hit in verified:
            if eligible(hit):
                side.setdefault(_key(hit), (hit, _signature(hit, facet, plan.keys)))
    left, right = [[(hit, marks) for hit, marks in side.values() if marks] for side in sides]
    pairs = [(a, b, (len(x) + len(y), int(_key(a) in keys) + int(_key(b) in keys), -abs(a["page"] - b["page"])))
             for a, x in left for b, y in right if _compatible(a, b, plan)
             and (_key(a) in keys or _key(b) in keys or (x == plan.facets[0].marks and y == plan.facets[1].marks and _strong_case(a, b, plan)))]
    if not pairs:
        return current
    a, b, grade = max(pairs, key=lambda pair: pair[2])
    if len({(x["document_id"], x["page"], y["page"]) for x, y, score in pairs if score == grade}) != 1:
        return current
    missing = list({_key(hit): hit for hit in (a, b) if _key(hit) not in keys}.values())
    protected = {key for side in sides for key, (_, points) in side.items() if points}
    positions = [i for i, hit in enumerate(current) if i >= 2 and hit.get("retriever") in {"edition_local", "focused_original"}
                 and not (hit.get("partial_readonly_table") or hit.get("source_range_reduced")) and _key(hit) not in protected]
    if not missing or len(missing) > len(positions):
        return current
    for position, hit in zip(positions[-len(missing):], missing, strict=True):
        current[position] = hit
    if on_pair is not None:
        on_pair(("case_key", (a, b)))
    return current[:limit]
