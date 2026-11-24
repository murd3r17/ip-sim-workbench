"""Bounded evidence selection from admitted passages in one textbook edition."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, replace
from hashlib import sha256
import re
from typing import Any

from core.markdown_blocks import blocks, unclosed_fence_start
from .device_alias_facets import device_aliases
from .edition import _page_texts, _source_excerpt
from .evidence_limits import evidence_limit_target, evidence_limit_witnesses
from .facet_evidence import FacetEvidence, FacetEvidenceRef
from .local_provider import _NETWORK_LABEL, _network_labels, _passage_role, _query_tokens
from .principle_evidence import direct_principle, multiple_principle_requests, principle_request
from .query_focus import compact_text, passage_concepts, passage_query, protocol_names
from .reader import DocumentReadError


_SEPARATORS = re.compile(r"[。；;？?！!\n]+|[,，]\s*(?=另外|再(?:看|问|核对|说明)|以及|还(?:有|想)|同时核对|"
                         r"(?:能|能否|能不能|可以|是否能)(?:单独|直接|据此)?(?:当|作为|证明|认定|确认)|还(?:缺什么|要看什么))")
_CITATION_INSTRUCTION = re.compile(
    r"(?:(?:请|并|另|还要)?(?:只)?(?:给出?|附|标明|补充)(?:具体)?"
    r"(?:出处|(?:教材|原书)?页码|物理页|引用|(?:图表|图中|表中)文字)(?:即可|就好)?"
    r"|(?:我)?(?:只|仅)(?:问|看)(?:教材|原书|课本)(?:的)?(?:原理|内容|材料)?"
    r"|(?:仅限|只用)(?:教材|原书|课本)(?:资料|内容)?"
    r"|(?:不要|不用|无需|别)(?:去)?(?:查看|登录|操作|连接)(?:任何|实际|真实)?设备"
    r"|(?:请)?看(?:真实|实际)?(?:回显|读回|输出)"
    r"|(?:要|请)?(?:使用|保留|给出)?同一(?:次|份)(?:回显|输出|读回)(?:和|与|及)(?:其)?(?:说明|解释))"
)
_NAME = r"(?:[A-Za-z][A-Za-z0-9_]*(?:[- ][A-Za-z0-9]+){0,3}|[\u3400-\u9fff]{2,12}?)"
_PAIR = re.compile(rf"^(?:(?:请|对比|比较)\s*)*[‘“`\"]?(?P<a>{_NAME})[’”`\"]?\s*(?:和|与|vs\.?)\s*"
                   rf"[‘“`\"]?(?P<b>{_NAME})[’”`\"]?(?=\s*(?:分别|各自|有何|有什么|的区别|怎么|如何|两者|差别|[:：,，]))", re.I)
_DEVICE = r"(?:ar|ce|fw|ne|pe|pc|sw|p|r|s)[0-9]+|(?:ar|ce|fw|ne|pe|pc|sw|leaf|spine|edge|acc|router)[0-9]*[-_][a-z0-9]{1,4}"
_DEVICES = re.compile(rf"(?<![a-z0-9_-])(?:{_DEVICE})(?![a-z0-9_/-])", re.I)
_BINDING = r"(?:\s*`?(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?`?)?"
_UI_DIRECTION = re.compile(rf"(?<![a-z0-9_-])(?P<a>{_DEVICE}){_BINDING}\s*(?:→|->|向|到|至|发给|测到)\s*(?P<b>{_DEVICE})(?![a-z0-9_/-])", re.I)
_OBSERVATION_OWNER = re.compile(rf"(?<![a-z0-9_-])(?P<device>{_DEVICE})(?![a-z0-9_/-])\s*"
                                r"(?:(?:的|上)[^，。；？！\n]{0,16}?)?(?:回显|读回|输出|状态表|邻接表|路由表)", re.I)
_JOINT_OBSERVATION_OWNER = re.compile(rf"(?<![a-z0-9_-])(?:{_DEVICE})\s*(?:和|与|及|、)\s*(?:{_DEVICE})\s*的"
                                      r"[^，。；？！\n]{0,16}?(?:回显|读回|输出|状态表|邻接表|路由表)", re.I)
_GROUP_DIRECTION = re.compile(rf"(?<![a-z0-9_-])(?P<a>{_DEVICE}){_BINDING}\s*(?:、|和|与|以及)\s*(?P<b>{_DEVICE}){_BINDING}"
                              rf"\s*(?:各自|分别|均)?\s*(?:→|->|向|到|至)\s*(?P<target>{_DEVICE})(?![a-z0-9_/-])", re.I)
_RECIPROCAL = re.compile(rf"(?<![a-z0-9_-])(?P<a>{_DEVICE}){_BINDING}\s*(?:和|与|、)\s*(?P<b>{_DEVICE}){_BINDING}"
                         r"\s*(?:做|进行)?\s*双向(?:互测|探测|测试)", re.I)
_NAMED_ROLE = r"客户端|服务端|发送端|接收端|发起端|响应端|上游|下游|主设备|备设备|主根桥|备份根桥|根端口|指定端口|备用端口"
_ROLES = re.compile(rf"{_NAMED_ROLE}|服务器|\bclient\b|\bserver\b|\bmaster\b|\bbackup\b", re.I)
_ROLE_OWNER = re.compile(rf"(?<![a-z0-9_-])(?P<device>{_DEVICE})\s*(?:作为|是|为|担任|成为|充当)\s*(?:本例|该组)?\s*(?P<role>{_NAMED_ROLE})", re.I)
_MODE = re.compile(r"分布式网关|集中式网关|透明模式|路由模式|主备模式|负载分担模式|传输模式|隧道模式|主动模式|被动模式|"
                   r"(?<![a-z0-9_-])(?:active[- ]standby|load sharing)(?![a-z0-9_-])|(?:配置)?方式\s*[一二三四1-4A-D]", re.I)
_PHASE = re.compile(r"(?P<action>故障|切换|重选|恢复|调整|配置|引入|重分发|汇总|重启)(?:之前|之后|发生前|发生后|完成后|前|后)")
_STEP = re.compile(r"(?:第|阶段\s*)[一二三四五六1-6]\s*阶段|阶段\s*[一二三四五六1-6]")
_SCOPE = re.compile(r"^(?:(?:第\s*)?[0-9一二三四五六]+(?:[.、 ]+|\s*))?(?:实验|案例|方案|场景)\s*(?:[0-9一二三四五六A-D]|[:：、]).{0,140}$", re.I)
_FIELD = re.compile(r"(?<![A-Za-z0-9_/-])(?:[A-Z][A-Z0-9_-]{1,18}|[A-Z][a-z]{2,20}(?:[ \t]+[A-Za-z][a-z]{2,18}){1,3})(?![A-Za-z0-9_/-])")
_FIELD_REFERENT = re.compile(r"^(?:(?:请|再)?(?:说说|说明)?(?:这|该)(?:个|一)?(?:字段|列))(?:的(?:含义|作用)|(?:说明|表示|描述|反映|代表))")
_FIELD_COUNT = re.compile(r"哪\s*([一二三四五六七八九1-9])\s*(?:个|条|项)\s*(?:地址|条目|记录|数值)")
_COUNT_DIGITS = str.maketrans("一二三四五六七八九", "123456789")
_READ = re.compile(r"回显|读回|日志|实际(?:结果|显示|探测|测得)|(?:表|输出)(?:中|里|内)|字段(?:值|里)|实测|几(?:个|次)回复|互测|确认.*(?:状态|结果)")
_ASKED_DISPLAY = re.compile(r"(?:显示|列出|读到|查到|写着|测到)(?:了|的)?(?:是|为)?\s*(?:哪|什么|多少|几)")
_OPERATION_BEFORE = re.compile(r"(?:动手|操作|做这一步|执行这(?:一)?步)(?:之前|以前|前)")
_OPERATION_AFTER = re.compile(r"(?:动手|操作|做完这(?:一)?步|执行完这(?:一)?步)(?:之后|以后|后)")
_OBSERVATION_ASK = re.compile(r"什么|谁|哪|几(?:个|位|次)|多少|怎样|如何|怎么")
_OBSERVATION_ROLE = re.compile(r"(?:端口|接口|设备|两端|两台|各自)(?:的)?角色|角色(?:各是|是|分别是|是什么)|"
                               r"(?:什么|哪(?:种|一?类|一?个))角色")
_OBSERVATION_STATE = re.compile(r"(?:邻接|邻居|端口|接口|链路|会话|对等体)(?:的)?状态|状态(?:各是|是|分别是|是什么)|"
                                r"(?:什么|哪(?:种|一?类|一?个))状态")
_ROLE_VALUE = re.compile(r"(?:根端口|指定端口|备用端口|主设备|备设备)|\b(?:root(?: port)?|desi(?:gnated)?|alte(?:rnate)?|backup|master)\b", re.I)
_STATE_VALUE = re.compile(r"(?:阻塞|转发|未建立|已建立)|\b(?:up|down|discarding|forwarding|full|established)\b", re.I)
_ACTUAL_PROSE = re.compile(r"(?:实际(?:读回|回显|输出|探测|显示|记录|结果)|(?:回显|读回|日志|记录)(?:中|里|显示|列出|的?结果)|观察到|实测|命令输出)")
_PROSE_ASSIGNMENT = re.compile(r"(?:角色|状态|结果|字段)|(?:均|已)?(?:为|回到|转入|恢复为|达到|列出|进入)")
_EXPECTED_ONLY = re.compile(r"预期|预计|计划|规划|建议|应当|应该|目标是|拟用|将会|如果|假设|用于查看")
_FIGURE_ID = re.compile(r"图\s*([0-9]+(?:\s*[-—.–－]\s*[0-9]+)*)")
_DIAGRAM = re.compile(r"图中|图上|图题|图注|图例|图示|拓扑图|箭头|从图|图表|图\s*[0-9]")
_CONFIG = re.compile(r"如何配置|怎么配置|(?:配置|设置|启用|禁用)(?:在哪|什么|哪些|哪一)|用什么命令|配置步骤")
_MECHANISM = re.compile(r"为什么|如何(?:工作|处理|影响|传|收|选)|(?:谁|哪一端)(?:发|收|建立|负责)|方向|动作|工作流程|触发|根据什么")
_MECHANISM_TITLE = re.compile(r"^\s*\*\*([^*\r\n]{2,100})\*\*")
_TITLE_COMPARISON = re.compile(r"[A-Za-z][A-Za-z0-9_-]+\s*(?:和|与|或|vs\.?|/)\s*[A-Za-z][A-Za-z0-9_-]+", re.I)
_ROLE_DESTINATION = re.compile(r"(?:向|到|至|发给)(?:集中)?(?P<role>服务端|服务器|客户端|接收端|发送端)")
_FIELD_EXPLANATION = re.compile(r"为什么|什么(?:含义|意思|作用)|(?:有什么|何种)作用")
_CAUSAL_PROOF = re.compile(r"依赖|因此|导致|所以|代表|表示|意味着|用于|负责")
_EXPERIMENT_WORDS = re.compile(r"同一(?:次|轮|组|实验|案例)|本(?:次|轮|例)|这(?:次|轮|一例|个实验)|该(?:回显|页|表|实验)|实验中的")
_SAME_CASE = re.compile(r"同一(?:个)?(?:次|轮|组|实验|案例|场景|方案|拓扑|组设备|台设备)|同一个?例子")
_INDEPENDENT_CASES = re.compile(r"(?:不同的?|独立的?|互相独立的?|另一个|另一组)(?:实验|案例|场景|方案|拓扑)|"
                                r"(?:比较|对比|分别看).{0,12}(?:两个|两组|两种)(?:不同的?)?(?:实验|案例|场景|方案|拓扑)")
_SWITCH_SCOPE = re.compile(r"^(?:然后|之后|接着|另外|还)?\s*(?:再看|另看|再核对|再问)")
_SOURCE_PHASE = re.compile(r"^步骤\s*[0-9一二三四五六七八九十]+[.、：:\-\s]+\s*(?P<title>\S.*)$")
_NUMBERED_CASE = re.compile(r"^\d+(?:\.\d+)+\s+(?P<title>(?=\S).*?(?:案例|实验|场景|方案).*)$")
_GENERIC_SCOPE = re.compile(r"^(?:实验|案例|场景|方案)?(?:组网介绍|配置步骤|配置|结果|验证|介绍|概述|说明|小结|目标|准备|背景|列表|概览)$")
_OBSERVED = re.compile(r"显示|回显|日志|返回|收到|测得|观察到|(?<!\d)\d+\s*发\s*\d+\s*收|\b(?:established|full|discarding|forwarding)\b", re.I)
_OBSERVED_VALUE = re.compile(r"\d|\b(?:up|down|full|normal|established|discarding|forwarding|backup|master)\b|为空|留空|未建立|无回显", re.I)
_LOOK_ONLY = re.compile(r"(?:需要|建议|应该|应当)(?:再次|先|另行)?(?:参见|查看|读回|核对|观察)|用于(?:查看|读取|验证)|目录|下(?:一)?页(?:展示|显示)")
_OBSERVATION_CLAUSE = re.compile(r"[。；;,，\n]")
_DIRECTED_RESULT = re.compile(r"(?<!\d)\d+\s*发\s*\d+\s*收|\b(?:is|state\s*[:=])\s*(?:up|down|full|normal|discarding|forwarding)\b", re.I)
_ALL_OBSERVATIONS = re.compile(r"(?:均(?:为|是|返回|收到)?|都是|各自.{0,16}(?:为|收到|返回)|皆为)\s*[:：]?\s*$")
_UNOBSERVED = re.compile(r"预期|预计|理论上|应当|应该|可能|建议|用于|若|如果|将会|目标是|下(?:一)?页|未执行|未观察到|无回显")
_READ_COMMAND = re.compile(r"^\s*(?:<[^>]+>|\[[^]\s]+\])?\s*(?:display|show)\s+", re.I)
_PROMPT = re.compile(r"^\s*(?:<[^>]+>|\[[^]\s]+\])\s*\S+")
_COMMAND_DEVICE = re.compile(r"^\s*(?:<([^>]+)>|\[([^]\s]+)\])")
_AFTER_CAPTION = re.compile(r"(?:如下|见下(?:表|图)|如(?:下表|下图)所示|输出如下|回显如下)[：:。\s]*$")
_BEFORE_CAPTION = re.compile(r"^(?:由|从)?(?:上表|上图|上述(?:命令)?(?:输出|回显)|(?:该|此)(?:表|图|回显|输出))(?:中|可见|显示|记录|给出|说|的)")
_OUTPUT_EXPLANATION = re.compile(r"^(?:由|从|据)(?:该|这份|上述)?(?:命令)?(?:输出|回显|读回)(?:信息)?(?:中)?(?:可以|可|能够)?(?:看到|看出|发现|得知|说明)")
_FIELD_RELATION = re.compile(r"描述|表示|反映|代表|用于|指的是|对应")
_FIGURE_EXPLANATION = re.compile(r"^(?:(?:由|从)?(?:该图|此图|本图|上图|图中|图内)|(?:该|此)?图(?:题|例|注))")
_OTHER_PAGE_FIGURE = re.compile(r"(?:图题|图注|图例|图)\s*(?:见|详见|在|移至)\s*(?:下一页|上一页|(?:PDF\s*)?(?:第|物理)\s*[0-9])")
_ACTION = re.compile(r"发送|发起|发布|收到|接收|响应|转发|返回|丢弃|替换|保留|封装|请求|注册|设置|协商|建立|加密|转换|允许|校验|等待|拒绝|变成|改写|通过")
_DEFINITION = re.compile(r"指(?:的是)?|是(?:一种|一种用来|指)|用于|表示|作用是|负责|由.{1,32}(?:产生|发布|发送|组成)|作用范围")
_CONFIG_PROOF = re.compile(r"(?m)^[ \t]*(?:\[[^]\s]+\]\s*)?(?:interface|ip route-static|peer|router-id|vlan|bridge-domain|network|undo|ospf|isis|bgp|enable)\s", re.I)
_NAVIGATION = re.compile(r"^(?:\*\*)?(?:目录|学习目标|练习|本章小结|本节将|接下来介绍)(?:[:：。]|\*\*|\s|$)")
_PHYSICAL_HEADING = re.compile(r"^PDF\s*第\s*[0-9]+\s*页")
_HEADING_MARK = re.compile(r"^(#{1,6})\s+(\S.*?)\s*$")
_STAGE_SUFFIX = re.compile(r"(?:之前|发生前|前)$")
_FIELD_STOP = frozenset({"pdf", "cli", "ip", "ipv4", "ipv6"})
_COLUMN_SPLIT = re.compile(r" {2,}|\t+")
_OUTPUT_RECORD_LABEL = re.compile(r"^(?:[A-Za-z][A-Za-z0-9.\-]*\s+){0,5}(?:entry information|record details)\s+(?:of|for)\s+", re.I)
_MULTIPLE_RECORDS = re.compile(r"除了|之外|以外|其他(?:条目|记录|对端|邻居|接口)|(?:所有|全部|每一)(?:行|条|入口|接口|邻居|记录)|"
                               r"(?:共|总共|一共)(?:有|应有)?(?:几|多少)|另(?:一|两|三)(?:条|行|个邻居)")
_ROLE_COLUMNS = frozenset({"role", "portrole", "角色", "端口角色"})
_STATE_COLUMNS = frozenset({"state", "portstate", "stpstate", "状态", "端口状态", "转发状态"})
_PRINCIPLE_KINDS = frozenset({"principle_definition", "principle_purpose"})


@dataclass(frozen=True)
class _Facet:
    number: int
    text: str
    kind: str
    topic: str
    subjects: frozenset[str]
    labels: frozenset[str]
    devices: frozenset[str]
    directions: frozenset[tuple[str, str]]
    roles: frozenset[str]
    owners: frozenset[tuple[str, str]]
    phases: frozenset[tuple[str, str]]
    modes: frozenset[str]
    fields: frozenset[str]
    concepts: frozenset[str]
    limit_target: str
    figures: frozenset[str]
    observation_owner: str


@dataclass(frozen=True)
class _Plan:
    facets: tuple[_Facet, ...]
    same_experiment: bool
    compare_phases: bool = False


@dataclass(frozen=True)
class PreciseCase:
    scope: tuple[str, ...]
    matches: tuple[tuple[int, FacetEvidenceRef], ...]
    directions: tuple[tuple[int, tuple[tuple[str, str], ...]], ...]


@dataclass(frozen=True)
class RankedEvidence:
    query_sha256: str
    edition_version: str
    facets: tuple[tuple[int, str, str], ...]
    matches: tuple[tuple[int, FacetEvidenceRef], ...]
    missing: tuple[int, ...]
    precise_case: PreciseCase | None = None
    ambiguous_precise_case: bool = False
    observation_facets: tuple[int, ...] = ()
    verified_observation: tuple[tuple[int, FacetEvidenceRef], ...] = ()
    ambiguous_observation_facets: tuple[int, ...] = ()
    verified_explanation: tuple[tuple[int, FacetEvidenceRef], ...] = ()
    comparison_topics: tuple[tuple[int, str], ...] = ()

    def select_hits(self, query: str, pool: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        return self._select(query, pool, self.matches)

    def select_precise_hits(self, query: str, pool: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        if self.precise_case is None or self.ambiguous_precise_case:
            return None
        return self._select(query, pool, self.precise_case.matches)

    def select_verified_observations(self, query: str, pool: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        return self._select(query, pool, self.verified_observation)

    def select_verified_explanations(self, query: str, pool: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        return self._select(query, pool, self.verified_explanation)

    def _select(self, query, pool, matches):
        if sha256(query.encode("utf-8")).hexdigest() != self.query_sha256:
            return None
        ordered = tuple(dict.fromkeys(ref for _, ref in matches))
        found = {FacetEvidenceRef.from_hit(hit): hit for hit in pool if hit.get("edition_version") == self.edition_version}
        if not ordered or any(ref not in found for ref in ordered):
            return None
        return [found[ref] for ref in ordered]


@dataclass(frozen=True)
class EvidenceSearchResult:
    hits: list[dict[str, Any]]
    facet_evidence: FacetEvidence | None
    pool: list[dict[str, Any]]
    ranked: RankedEvidence | None


def _subjects(text):
    return frozenset(protocol_names(text))


def _devices(text):
    plain = _DEVICES.findall(text.casefold())
    return frozenset(name for name in plain if "_" not in name and "-" not in name) | device_aliases(text)


def _directions(text):
    directed = {(item["a"].casefold(), item["b"].casefold()) for item in _UI_DIRECTION.finditer(text)}
    for match in _GROUP_DIRECTION.finditer(text):
        directed.update((side.casefold(), match["target"].casefold()) for side in (match["a"], match["b"]))
    for match in _RECIPROCAL.finditer(text):
        start, end = match["a"].casefold(), match["b"].casefold()
        directed.update(((start, end), (end, start)))
    return frozenset(directed)


def _observed_directions(text):
    observed = set()
    for clause in _OBSERVATION_CLAUSE.split(text):
        if _UNOBSERVED.search(clause) or _EXPECTED_ONLY.search(clause):
            continue
        start = 0
        for result in _DIRECTED_RESULT.finditer(clause):
            claim = clause[start:result.start()]
            start = result.end()
            directions = _directions(claim)
            if len(directions) == 1 or directions and _ALL_OBSERVATIONS.search(claim):
                observed.update(directions)
    return frozenset(observed)


def _phases(text):
    stages = {(match["action"], "before" if _STAGE_SUFFIX.search(match[0]) else "after") for match in _PHASE.finditer(text)}
    stages.update((compact_text(value), "ordinal") for value in _STEP.findall(text))
    if _OPERATION_BEFORE.search(text):
        stages.add(("操作", "before"))
    if _OPERATION_AFTER.search(text):
        stages.add(("操作", "after"))
    return frozenset(stages)


def _markers(text):
    return frozenset(compact_text(value) for value in _MODE.findall(text))


def _roles(text):
    normalized = {"client": "客户端", "server": "服务端", "服务器": "服务端", "master": "主设备", "backup": "备设备"}
    return frozenset(normalized.get(token.casefold(), token.casefold()) for token in _ROLES.findall(text))


def _owners(text):
    return frozenset((m["device"].casefold(), m["role"]) for m in _ROLE_OWNER.finditer(text))


def _kind(text):
    for marker, kind in ((_CONFIG, "configuration"), (_READ, "readback"), (_DIAGRAM, "diagram"),
                         (_ASKED_DISPLAY, "readback"), (_MECHANISM, "mechanism")):
        if marker.search(text):
            return kind
    return "concept"


def _fields(text):
    text = _NETWORK_LABEL.sub(" ", text)
    return frozenset(compact_text(token) for token in _FIELD.findall(text)) - _subjects(text) - _devices(text) - _FIELD_STOP


def _observation_owner(text):
    if _JOINT_OBSERVATION_OWNER.search(text):
        return ""
    owners = {match['device'].casefold() for match in _OBSERVATION_OWNER.finditer(text)}
    return next(iter(owners)) if len(owners) == 1 else ""


def _figures(text):
    return frozenset(compact_text(value).translate(str.maketrans("—.–－", "----")) for value in _FIGURE_ID.findall(text))


def _independent_cases(text, facets):
    if len(facets) < 2 or _SAME_CASE.search(text):
        return False
    if _INDEPENDENT_CASES.search(text):
        return True
    for previous, following in zip(facets, facets[1:]):
        if not _SWITCH_SCOPE.match(following.text):
            continue
        if previous.modes and following.modes and previous.modes.isdisjoint(following.modes):
            return True
        if (previous.subjects and following.subjects and previous.subjects.isdisjoint(following.subjects)
                and previous.devices and following.devices and previous.devices.isdisjoint(following.devices)):
            return True
    return False


def _compares_phases(facets):
    if len(facets) != 2 or any(len(facet.phases) != 1 for facet in facets):
        return False
    (first, when), = facets[0].phases
    (second, other), = facets[1].phases
    return first == second and {when, other} == {"before", "after"} or first != second and when == other == "ordinal"


def _plan(terms):
    terms = terms.strip()
    if not terms or len(terms) > 1600:
        return None
    clauses = [clause.strip(" ，,、：:") for clause in _SEPARATORS.split(terms)]
    clauses = [clause for clause in clauses if len(clause) >= 2 and not _CITATION_INSTRUCTION.fullmatch(clause)]
    if not clauses or len(clauses) > 12:
        return None
    substantive = "。".join(clauses)
    pair = _PAIR.match(clauses[0])
    case = bool(_EXPERIMENT_WORDS.search(substantive) or _devices(substantive) or _phases(substantive))
    bindings = [(part, "") for part in clauses]
    if pair and not case:
        remainder = clauses[0][pair.end():].strip(" ，,：:")
        bindings = [(f"{pair[side]} {remainder}", pair[side].strip()) for side in ("a", "b")] + bindings[1:]
    common_subjects = _subjects(substantive)
    common_modes = _markers(substantive)
    facets = []
    for index, (text, topic) in enumerate(bindings, 1):
        subjects = _subjects(text) or (common_subjects if len(common_subjects) == 1 else frozenset())
        modes = _markers(text) or (common_modes if len(common_modes) == 1 else frozenset())
        limit_target = evidence_limit_target(text)
        kind = "evidence_limit" if limit_target else _kind(text)
        if (not limit_target and _FIELD_REFERENT.match(text) and facets
                and (earlier := facets[-1]).kind == "readback" and len(earlier.fields) == 1
                and not (_devices(text) or any(_network_labels(text)))):
            facets.append(_Facet(index, text, "output_interpretation", "", earlier.subjects, earlier.labels,
                                 earlier.devices, earlier.directions, frozenset(), frozenset(), earlier.phases,
                                 earlier.modes, earlier.fields, frozenset(), "", earlier.figures, earlier.observation_owner))
            continue
        facets.append(_Facet(index, text, kind, topic, subjects, frozenset(_network_labels(text)),
                             _devices(text), _directions(text), _roles(text), _owners(text), _phases(text), modes,
                             _fields(text), frozenset(passage_concepts(text)), limit_target, _figures(text),
                             _observation_owner(text) if kind == "readback" else ""))
    if len(facets) == 1 and not case and facets[0].kind in {"concept", "mechanism"}:
        if request := principle_request(facets[0].text):
            kind, topic = request
            facets[0] = replace(facets[0], kind=kind, topic=topic)
    scoped = case or any(f.kind in {"configuration", "readback", "diagram"} for f in facets)
    same_experiment = scoped and not _independent_cases(substantive, facets)
    return _Plan(tuple(facets), same_experiment, same_experiment and _compares_phases(facets))


def _independent_principles(terms, plan):
    if not plan or plan.same_experiment or any(facet.topic or facet.kind not in {"concept", "mechanism"} for facet in plan.facets):
        return None
    requests = multiple_principle_requests(terms, tuple(facet.text for facet in plan.facets))
    if not requests:
        return None
    return replace(plan, facets=tuple(replace(facet, kind=kind, topic=topic)
                                      for facet, (kind, topic) in zip(plan.facets, requests, strict=True)))


def _heading_paths(reading):
    stack = []
    paths = {}
    for section in reading["sections"]:
        level, title = section["level"], section["title"]
        if not _PHYSICAL_HEADING.match(title):
            stack = [entry for entry in stack if entry[0] < level]
            stack.append((level, title, section["line"]))
        paths[section["id"]] = tuple(stack)
    return paths


def _heading_key(hit, row):
    return f"{hit['document_id']}@{hit['document_version']}:{row[2]}"


def _source_metadata(hit, path):
    context = {"source_heading_path": tuple(row[1] for row in path)}
    if path:
        context["source_heading_key"] = _heading_key(hit, path[-1])
    phase = next((row for row in reversed(path) if (match := _SOURCE_PHASE.match(row[1]))
                  and not _GENERIC_SCOPE.fullmatch(match["title"])), None)
    experiment = next((row for row in reversed(path) if _SCOPE.match(row[1]) or (
        (match := _NUMBERED_CASE.match(row[1])) and not _GENERIC_SCOPE.fullmatch(match["title"]))), None)
    if experiment:
        context["source_experiment_key"] = _heading_key(hit, experiment)
    if phase:
        context["source_phase_key"] = _heading_key(hit, phase)
    return context


def _adjacent_caption(kind, text, other, *, preceding):
    other = other.strip("* \t")
    if kind in {"fence", "table"}:
        if kind == "fence" and not preceding and _OUTPUT_EXPLANATION.match(other) and _FIELD_RELATION.search(other):
            return True
        return bool((_AFTER_CAPTION if preceding else _BEFORE_CAPTION).search(other))
    figures = _figures(text)
    nearby = _figures(other)
    return (len(figures) == 1 and not (_OTHER_PAGE_FIGURE.search(text) or _OTHER_PAGE_FIGURE.search(other))
            and (nearby == figures if nearby else not preceding and bool(_FIGURE_EXPLANATION.match(other))))


def _units(body, parent, page_line):
    path = list(parent)
    first_line = body.splitlines()[0]
    units = []
    for kind, start, end in blocks(body):
        text = body[start:end].strip()
        if kind == "heading":
            match = _HEADING_MARK.fullmatch(text)
            if match and not _PHYSICAL_HEADING.match(match[2]):
                level = len(match[1])
                path = [row for row in path if row[0] < level]
                path.append((level, match[2], page_line + body[:start].count("\n")))
            continue
        if unclosed_fence_start(text) is None and first_line != text:
            units.append((kind, start, end, text, tuple(path)))
    for kind, start, end, text, path in units:
        yield kind, text, path, None

    for index, (kind, start, end, text, path) in enumerate(units):
        if kind not in {"fence", "table", "paragraph"}:
            continue
        neighbors = []
        if index:
            before = units[index - 1]
            if _adjacent_caption(kind, text, before[3], preceding=True) and not body[before[2]:start].strip():
                neighbors.append((before, before[1], end))
        if index + 1 < len(units):
            after = units[index + 1]
            if _adjacent_caption(kind, text, after[3], preceding=False) and not body[end:after[1]].strip():
                neighbors.append((after, start, after[2]))
        for neighbor, span_start, span_end in neighbors:
            if neighbor[0] == "paragraph" and neighbor[4] == path and 8 <= len(neighbor[3]) <= 320:
                yield kind, body[span_start:span_end].strip(), path, text


def _evidence_type(kind, text, requested):
    out, _, values, visual, interpretation = _passage_role(text)
    if out or _NAVIGATION.match(text):
        return False
    if requested == "readback":
        if kind == "fence":
            rows = [line for line in text.splitlines()[1:-1] if line.strip()]
            return bool(len(rows) >= 2 and _READ_COMMAND.match(rows[0])
                        and not any(_PROMPT.match(line) for line in rows[1:])
                        and any(_OBSERVED_VALUE.search(line) for line in rows[1:]))
        if kind == "table":
            return values or bool(_OBSERVED_VALUE.search(text.splitlines()[-1]))
        return any(not (_LOOK_ONLY.search(sentence) or _EXPECTED_ONLY.search(sentence)) and (
            (_OBSERVED.search(sentence) and _OBSERVED_VALUE.search(sentence)) or (
                _ACTUAL_PROSE.search(sentence) and _PROSE_ASSIGNMENT.search(sentence)
                and (_ROLE_VALUE.search(sentence) or _STATE_VALUE.search(sentence) or _OBSERVED_VALUE.search(sentence))))
                   for sentence in re.split(r"[。；\n]", text))
    if requested == "configuration":
        return bool(_CONFIG_PROOF.search(text) if kind == "fence" else re.search(r"(?:配置|设置|启用|绑定).{2,48}(?:`|为|到|向|使用|在)", text))
    if requested == "diagram":
        return kind != "fence" and bool(visual and (_ACTION.search(text) or (values and _DIAGRAM.search(text))))
    if kind == "fence":
        return False
    if requested == "mechanism":
        return bool(_ACTION.search(text) and (_DEFINITION.search(text) or _roles(text) or _directions(text)
                                             or re.search(r"当|若|如果|由于|随后|再|从.{1,18}到|必须", text)))
    return bool(interpretation and _ACTION.search(text) or _DEFINITION.search(text))


def _topic_in_text(topic, text):
    return compact_text(topic) in compact_text(text) if topic else True


def _title_scopes_action(facet, text):
    lead = _MECHANISM_TITLE.match(text)
    destination = _ROLE_DESTINATION.search(facet.text)
    if not facet.topic or not lead or not destination or _TITLE_COMPARISON.search(lead[1]):
        return False
    if not compact_text(lead[1]).startswith(compact_text(facet.topic)):
        return False
    if facet.topic.isascii() and not re.search(rf"(?<![a-z0-9_-]){re.escape(facet.topic)}(?![a-z0-9_-])", lead[1], re.I):
        return False
    role = destination["role"]
    role_names = r"(?:服务端|服务器)" if role in {"服务端", "服务器"} else re.escape(role)
    relation = re.compile(rf"(?:向|到|至|发给|请求)\s*(?:集中)?(?:的)?{role_names}")
    return any(_ACTION.search(clause) and relation.search(clause) and not _EXPECTED_ONLY.search(clause)
               for clause in re.split(r"[。；\n]", text[lead.end():]))


def _field_explanation(facet, text):
    if facet.topic or not facet.fields or not facet.subjects or not _FIELD_EXPLANATION.search(facet.text):
        return False
    fields = [re.escape(term.replace("-", "_")) for term in facet.fields]
    for clause in re.split(r"[。；\n]", text):
        if _CAUSAL_PROOF.search(clause) and not _EXPECTED_ONLY.search(clause):
            lexemes = compact_text(clause).replace("-", "_")
            if all(re.search(rf"(?<![a-z0-9_]){field}(?![a-z0-9_])", lexemes) for field in fields):
                return True
    return False


def _mechanism_witness(facet, kind, text):
    return kind == "paragraph" and facet.kind == "mechanism" and not _NAVIGATION.match(text) and (
        _title_scopes_action(facet, text) or _field_explanation(facet, text))


def _matched_fields(expected, text):
    matched = expected & _fields(text)
    for field in expected - matched:
        if "_" in field or "-" in field:
            spelling = r"[-_]".join(map(re.escape, re.split(r"[-_]", field)))
            if re.search(rf"(?<![A-Za-z0-9_-]){spelling}(?![A-Za-z0-9_-])", text, re.I):
                matched |= {field}
    return matched


def _record_labels(rows):
    headings = [row for row in rows if _OUTPUT_RECORD_LABEL.match(row)]
    if len(headings) != 1:
        return frozenset()
    identifiers = frozenset(_network_labels(headings[0]))
    return identifiers if len(identifiers) == 1 else frozenset()


def _output_interpretation(facet, kind, text, core):
    if facet.kind != "output_interpretation" or kind != "fence" or not core or not _evidence_type(kind, core, "readback"):
        return False
    rows = [row.strip() for row in core.splitlines()[1:-1] if row.strip()]
    owner = _COMMAND_DEVICE.match(rows[0])
    owners = {facet.observation_owner} if facet.observation_owner else facet.devices
    if owners and (not owner or owners != {(owner[1] or owner[2]).casefold()}):
        return False
    explanation = text.partition(core)[2].lstrip("* \r\n\t")
    if not _OUTPUT_EXPLANATION.match(explanation) or _EXPECTED_ONLY.search(explanation):
        return False
    record_labels = _record_labels(rows[1:])
    return (any(_FIELD_RELATION.search(clause) and _matched_fields(facet.fields, clause) == facet.fields
                for clause in re.split(r"[。；\n]", explanation))
            and any(_readback_value(facet, row) and facet.labels <= record_labels | frozenset(_network_labels(row))
                    and facet.devices - owners <= _devices(row) for row in rows[1:]))


def _readback_value(facet, row):
    if _OBSERVATION_ROLE.search(facet.text):
        if not _ROLE_VALUE.search(row):
            return False
    elif _OBSERVATION_STATE.search(facet.text):
        if not _STATE_VALUE.search(row):
            return False
    elif not facet.fields:
        return False
    if facet.fields:
        columns = re.split(r"\s*[:：]\s*| {2,}", row.strip(), maxsplit=1)
        if len(columns) != 2 and len(facet.fields) == 1 and any("_" in field or "-" in field for field in facet.fields):
            columns = row.strip().split(maxsplit=1)
        if len(columns) != 2 or not columns[1] or _matched_fields(facet.fields, columns[0]) != facet.fields:
            return False
    return True


def _observed_column_row(facet, rows, peers):
    if len(rows) < 2:
        return None
    columns = _COLUMN_SPLIT.split(rows[0].strip())
    if any(_NETWORK_LABEL.fullmatch(column) for column in columns):
        return None
    headers = tuple(map(compact_text, columns))
    names = set(headers)
    if len(headers) < 2 or not (names & (_ROLE_COLUMNS | _STATE_COLUMNS | facet.fields)):
        return None
    if (_MULTIPLE_RECORDS.search(facet.text) or not (facet.labels or peers)
            or len(names) != len(headers) or not facet.fields <= names):
        return False
    required = []
    for ask, labels, values in ((_OBSERVATION_ROLE, _ROLE_COLUMNS, _ROLE_VALUE),
                                (_OBSERVATION_STATE, _STATE_COLUMNS, _STATE_VALUE)):
        if ask.search(facet.text):
            columns = [index for index, name in enumerate(headers) if name in labels]
            if len(columns) != 1:
                return False
            required.append((columns[0], values))
    if not (required or facet.fields):
        return False
    matches = []
    for row in rows[1:]:
        if re.fullmatch(r"[-=\s]+", row):
            continue
        cells = _COLUMN_SPLIT.split(row.strip())
        if len(cells) != len(headers) or _EXPECTED_ONLY.search(row):
            return False
        if peers <= _devices(row) and facet.labels <= frozenset(_network_labels(row)):
            matches.append(cells)
    return len(matches) == 1 and all(pattern.fullmatch(matches[0][index]) is not None for index, pattern in required)


def _has_observation_witness(facet, kind, text, path, core):
    if facet.kind != "readback":
        return False
    actual = core or text
    step = next((row[1] for row in reversed(path) if _SOURCE_PHASE.match(row[1])), "")
    phase_context = _phases(step)
    if facet.directions:
        for clause in re.split(r"[。；\n]", actual):
            if (facet.directions <= _observed_directions(clause) and facet.phases <= (_phases(clause) | phase_context)
                    and facet.labels <= frozenset(_network_labels(clause))):
                if not (facet.fields or _OBSERVATION_ROLE.search(facet.text) or _OBSERVATION_STATE.search(facet.text)):
                    return True
                if _readback_value(facet, clause):
                    return True
        return False
    if not facet.devices or not _OBSERVATION_ASK.search(facet.text):
        return False
    owners = {facet.observation_owner} if facet.observation_owner else facet.devices
    peers = facet.devices - owners
    if kind == "fence":
        rows = [row.strip() for row in actual.splitlines()[1:-1] if row.strip()]
        if (not rows or not (device := _COMMAND_DEVICE.match(rows[0])) or not _READ_COMMAND.match(rows[0])
                or owners != {(device[1] or device[2]).casefold()}
                or not facet.phases <= (_phases(text) | phase_context)):
            return False
        if (table_witness := _observed_column_row(facet, rows[1:], peers)) is not None:
            return table_witness
        record_labels = _record_labels(rows[1:])
        matched = [row for row in rows[1:] if not _EXPECTED_ONLY.search(row) and _readback_value(facet, row)
                   and peers <= _devices(row)
                   and facet.labels <= record_labels | frozenset(_network_labels(row))]
        if facet.fields and (count := _FIELD_COUNT.search(facet.text)):
            return len(matched) == len(set(matched)) == int(count[1].translate(_COUNT_DIGITS))
        return len(matched) == 1
    if kind != "paragraph":
        # A table without its read-only prompt can also be an address plan.
        return False
    for clause in re.split(r"[。；\n]", actual):
        if (_ACTUAL_PROSE.search(clause) and not _EXPECTED_ONLY.search(clause) and facet.devices == _devices(clause)
                and (not peers or _observation_owner(clause) == facet.observation_owner)
                and facet.labels <= frozenset(_network_labels(clause))
                and facet.phases <= (_phases(clause) | phase_context) and _readback_value(facet, clause)):
            return True
    return False


def _grade(facet, kind, text, path, core=None):
    if facet.kind in _PRINCIPLE_KINDS:
        proof = kind == "paragraph" and direct_principle(text, facet.kind, facet.topic) == text
        return (0, 0, 0, 0) if proof else None
    if core and facet.kind not in {"readback", "diagram", "output_interpretation"}:
        return None
    mechanism_witness = _mechanism_witness(facet, kind, text)
    linked = _output_interpretation(facet, kind, text, core)
    if facet.kind == "output_interpretation" and not linked:
        return None
    if facet.limit_target:
        if kind != "paragraph" or _NAVIGATION.match(text) or not evidence_limit_witnesses(facet.limit_target, text):
            return None
    elif not (mechanism_witness or linked) and not _evidence_type(kind, core if core and facet.kind == "readback" else text, facet.kind):
        return None
    context = "\n".join(row[1] for row in path[-2:]) + "\n" + text
    if not _topic_in_text(facet.topic, text) or not facet.subjects <= _subjects(context) or not facet.figures <= _figures(text):
        return None
    if not facet.labels <= frozenset(_network_labels(text)) or not facet.devices <= _devices(text):
        return None
    if not facet.directions <= _directions(text) or not facet.roles <= _roles(text) or not facet.owners <= _owners(text):
        return None
    modes, stages = _markers(context), _phases(context)
    if facet.modes and (not facet.modes <= modes or modes - facet.modes):
        # An ordinary contrast can state both modes in one complete paragraph.
        # Use just the actual sentence that binds this arm, keeping the source intact.
        same_arm = (sentence for sentence in re.split(r"[。；\n]", text) if _markers(sentence) == facet.modes)
        if not facet.topic or not any(_topic_in_text(facet.topic, sentence) and _ACTION.search(sentence) for sentence in same_arm):
            return None
    if not facet.phases <= stages or any(action == target and when != wanted for action, when in stages for target, wanted in facet.phases):
        return None
    field_hits = _matched_fields(facet.fields, text)
    if field_hits != facet.fields and not (mechanism_witness and _field_explanation(facet, text)):
        return None
    if facet.limit_target or linked:
        return (len(facet.directions), len(facet.owners), len(field_hits), 0)
    if facet.topic and not mechanism_witness and not any(_topic_in_text(facet.topic, clause) and _evidence_type(kind, clause, facet.kind)
                               for clause in re.split(r"[。；\n]", text) if clause.strip()):
        return None
    concept_hits = facet.concepts & passage_concepts(text)
    if facet.concepts and not concept_hits:
        return None
    shared = set(_query_tokens(passage_query(facet.text))) & set(_query_tokens(text))
    if len(shared) < (1 if facet.topic or facet.subjects else 2) and not (facet.directions or field_hits or concept_hits):
        return None
    return (len(facet.directions), len(facet.owners), len(concept_hits) + len(field_hits), len(shared))


def _principle_units(units, facets):
    for kind, text, location, core in units:
        if kind != "paragraph" or core or _NAVIGATION.match(text):
            continue
        statements = dict.fromkeys(direct_principle(text, facet.kind, facet.topic, separate_heading=len(facets) > 1)
                                   for facet in facets)
        for statement in statements:
            if statement and not (_devices(statement) or any(_network_labels(statement))):
                yield kind, statement, location, None


class _Passages:
    def __init__(self, edition, *, reusable=None):
        self.edition = edition
        self.documents = reusable.documents if reusable else {}
        self.pages_seen = set()
        self.units = reusable.units if reusable else {}
        self.pool = {}
        self.by_facet = defaultdict(list)
        self.ambiguous = set()
        self.scoped_claims = {}

    def add(self, hits, plan):
        for rank, hit in enumerate(hits, 1):
            ref = FacetEvidenceRef.from_hit(hit)
            if ref is None or ref.edition_version != self.edition.version:
                continue
            key = ref.document_id, ref.document_version
            if key not in self.documents:
                try:
                    reading = self.edition.read(*key, include_original_status=False)
                    self.documents[key] = (_page_texts(reading), _heading_paths(reading),
                                           {section["id"]: section["line"] for section in reading["sections"]})
                except (DocumentReadError, KeyError, OSError, ValueError):
                    self.documents[key] = ({}, {}, {})
            pages, contexts, lines = self.documents[key]
            mapped = pages.get(ref.page)
            if not mapped or mapped[0] != ref.section_id:
                continue
            if not _source_excerpt(hit["text"], mapped[1]):
                continue
            page_key = key, ref.page
            if page_key not in self.units:
                self.units[page_key] = tuple(_units(mapped[1], contexts.get(ref.section_id, ()), lines[ref.section_id]))
            units = self.units[page_key]
            locations = {location for _, unit, location, _ in units if _source_excerpt(hit["text"], unit)}
            location = next(iter(locations)) if len(locations) == 1 else ()
            self.pool.setdefault(ref, {**hit, **_source_metadata(hit, location), "facet_ids": ()})
            if not plan.facets or page_key in self.pages_seen:
                continue
            self.pages_seen.add(page_key)
            if plan.facets[0].kind in _PRINCIPLE_KINDS:
                units = _principle_units(units, plan.facets)
            for kind, text, location, core in units:
                if len(text) > 2450 or len(text) < 18 and not (plan.facets[0].kind in _PRINCIPLE_KINDS):
                    continue
                linked_output = bool(core and any(_output_interpretation(facet, kind, text, core) for facet in plan.facets))
                matches = [(facet.number, grade) for facet in plan.facets
                           if (grade := _grade(facet, kind, text, location, core)) is not None
                           and (not core or linked_output or _grade(facet, kind, core, location) is None)
                           and (len(text) <= 1080 or _has_observation_witness(facet, kind, text, location, core))]
                if not matches:
                    continue
                candidate = {**hit, **_source_metadata(hit, location), "text": text,
                             "facet_ids": tuple(number for number, _ in matches)}
                witnesses = tuple((facet.number, witness) for facet in plan.facets
                                  if facet.number in candidate["facet_ids"] and facet.limit_target
                                  for witness in evidence_limit_witnesses(facet.limit_target, text))
                if witnesses:
                    candidate["facet_witnesses"] = witnesses
                limit_ids = {number for number, witness in witnesses if witness in {"excluded_inference", "separate_observation"}}
                explanation = tuple(facet.number for facet in plan.facets if facet.number in candidate["facet_ids"]
                                    and (facet.number in limit_ids or _mechanism_witness(facet, kind, text)
                                         or _output_interpretation(facet, kind, text, core)
                                         or facet.kind in _PRINCIPLE_KINDS))
                if explanation:
                    candidate["facet_explanation_ids"] = explanation
                observation_witnesses = tuple(facet.number for facet in plan.facets if facet.number in candidate["facet_ids"]
                                              and _has_observation_witness(facet, kind, text, location, core))
                if observation_witnesses:
                    candidate["facet_readback_ids"] = observation_witnesses
                if plan.compare_phases:
                    step = next((row[1] for row in reversed(location) if _SOURCE_PHASE.match(row[1])), "")
                    explicit_stages = _phases(text) | _phases(step)
                    candidate["facet_phase_ids"] = tuple(facet.number for facet in plan.facets
                                                         if facet.number in candidate["facet_ids"] and facet.phases <= explicit_stages)
                passage_ref = FacetEvidenceRef.from_hit(candidate)
                if passage_ref is None:
                    continue
                self.scoped_claims[(self._scope(candidate, passage_ref), passage_ref)] = candidate
                old = self.pool.get(passage_ref)
                if old and old["facet_ids"] and old.get("source_heading_key") != candidate.get("source_heading_key"):
                    self.ambiguous.add(passage_ref)
                    self.pool[passage_ref] = {**candidate, "facet_ids": ()}
                    self.pool[passage_ref].pop("source_experiment_key", None)
                    self.pool[passage_ref].pop("source_phase_key", None)
                    continue
                if passage_ref in self.ambiguous:
                    continue
                self.pool[passage_ref] = candidate
                for number, score in matches:
                    self.by_facet[number].append(((*score, -rank), passage_ref))

    def _feasible_groups(self, plan):
        claims = {number: [(score, ref) for score, ref in matches if ref not in self.ambiguous]
                  for number, matches in self.by_facet.items()}
        if not plan.same_experiment or len(plan.facets) == 1:
            return [claims]
        groups = defaultdict(lambda: defaultdict(list))
        for number, matches in claims.items():
            for score, ref in matches:
                source = self.pool[ref]
                if plan.compare_phases and number not in source.get("facet_phase_ids", ()):
                    continue
                # Two separately numbered pages only share a case by an explicit
                # original heading, never by name overlap, book or page distance.
                group = self._claim_scope(plan, number, source, ref)
                groups[group][number].append((score, ref))
        return list(groups.values())

    @staticmethod
    def _scope(source, ref):
        if phase := source.get("source_phase_key"):
            return "phase", phase
        if experiment := source.get("source_experiment_key"):
            return "experiment", experiment
        return "page", ref.document_id, ref.document_version, str(ref.page), ref.section_id

    def _claim_scope(self, plan, facet_id, source, ref):
        if plan.compare_phases and facet_id in source.get("facet_phase_ids", ()):
            if experiment := source.get("source_experiment_key"):
                return "experiment", experiment
        return self._scope(source, ref)

    def _record_observation(self, choices, key, ref):
        if key not in choices:
            choices[key] = ref
            return
        existing = choices[key]
        if existing is None or existing == ref:
            return
        same_page = (existing.document_id, existing.document_version, existing.page, existing.section_id) == (
            ref.document_id, ref.document_version, ref.page, ref.section_id)
        if same_page:
            previous = compact_text(self.pool[existing]["text"])
            arrival = compact_text(self.pool[ref]["text"])
            if previous in arrival or arrival in previous:
                if len(arrival) > len(previous):
                    choices[key] = ref
                return
        choices[key] = None

    def verified_sources(self, plan, capacity, witness_key):
        if witness_key == "facet_explanation_ids" and plan.facets and plan.facets[0].kind in _PRINCIPLE_KINDS:
            witnesses = []
            for facet in plan.facets:
                referents = [(ref, compact_text(hit["text"]).rstrip("。；;")) for ref, hit in self.pool.items()
                             if ref not in self.ambiguous and facet.number in hit.get(witness_key, ())]
                if len({statement for _, statement in referents}) != 1:
                    return (), ()
                witnesses.append((facet.number, referents[0][0]))
            return (tuple(witnesses) if len({ref for _, ref in witnesses}) <= capacity else ()), ()
        claims = defaultdict(dict)
        for (_, ref), source in self.scoped_claims.items():
            if ref in self.ambiguous:
                continue
            for number in source.get(witness_key, ()):
                if not plan.compare_phases or number in source.get("facet_phase_ids", ()):
                    scope = self._claim_scope(plan, number, source, ref)
                    self._record_observation(claims[number], scope, ref)
        ambiguous = tuple(sorted(number for number, choices in claims.items() if len(choices) > 1 or None in choices.values()))
        if plan.same_experiment and len({scope for alternatives in claims.values() for scope in alternatives}) != 1:
            return (), ambiguous
        witnesses = []
        seen = set()
        for facet in plan.facets:
            choices = claims.get(facet.number, {})
            if len(choices) == 1:
                ref = next(iter(choices.values()))
                if ref is not None and (ref in seen or len(seen) < capacity):
                    seen.add(ref)
                    witnesses.append((facet.number, ref))
        return tuple(witnesses), ambiguous

    def precise_case(self, plan, capacity):
        if not plan.same_experiment or any(facet.kind != "readback" or not facet.directions for facet in plan.facets):
            return None, False
        claims = defaultdict(dict)
        for (_, ref), source in self.scoped_claims.items():
            directions = _observed_directions(source["text"])
            for facet in plan.facets:
                if (facet.number in source["facet_ids"] and facet.directions <= directions
                        and (not plan.compare_phases or facet.number in source.get("facet_phase_ids", ()))):
                    scope = self._claim_scope(plan, facet.number, source, ref)
                    # Without a labeled case, one contiguous passage must
                    # witness the entire readback; a page can contain two cases.
                    key = scope, ref if scope[0] == "page" else None
                    self._record_observation(claims[key], facet.number, ref)
        # Candidate rank can order alternatives inside one scope, but cannot
        # determine which of two fully witnessed experiments the reader meant.
        complete = [(scope, found) for (scope, _), found in claims.items()
                    if len(found) == len(plan.facets) and len(set(found.values())) <= capacity]
        if len(complete) != 1:
            return None, len(complete) > 1
        scope, found = complete[0]
        if any(ref is None or ref in self.ambiguous for ref in found.values()):
            return None, True
        ordered = tuple((facet.number, found[facet.number]) for facet in plan.facets)
        directions = tuple((facet.number, tuple(sorted(facet.directions))) for facet in plan.facets)
        return PreciseCase(scope, ordered, directions), False

    @staticmethod
    def _first_pass(facets, groups, capacity):
        selected = []
        covered = []
        scores = []
        by_facet = {}
        for facet in facets:
            alternatives = groups.get(facet.number, ())
            if not alternatives:
                continue
            score, ref = max(alternatives, key=lambda item: item[0])
            already = next(((value, old) for value, old in alternatives if old in selected), None)
            if already is not None:
                score, ref = already
            elif len(selected) == capacity:
                continue
            else:
                selected.append(ref)
            covered.append(facet.number)
            scores.append(score)
            by_facet[facet.number] = ref
        return (len(covered), tuple(sorted(scores, reverse=True)), -len(selected)), selected, by_facet

    def select(self, plan, limit):
        choices = [self._first_pass(plan.facets, group, limit) for group in self._feasible_groups(plan)]
        if not choices:
            return [], {}
        score, refs, matches = max(choices, key=lambda option: option[0])
        if plan.same_experiment and len({tuple(items) for grade, items, _ in choices if grade == score}) > 1:
            # A tie between two source-local experiments is not a verified match.
            return [], {}
        return refs, matches

    def ordered_pool(self, chosen):
        order = list(chosen)
        seen = set(order)
        for matches in self.by_facet.values():
            alternatives = sorted(matches, key=lambda item: item[0], reverse=True)
            used_pages = set()
            for _, ref in alternatives:
                key = ref.document_id, ref.page
                if key in used_pages or ref in seen or ref in self.ambiguous:
                    continue
                seen.add(ref)
                used_pages.add(key)
                order.append(ref)
                if len(used_pages) == 4:
                    break
        order.extend(ref for ref in self.pool if ref not in seen)
        return [self.pool[ref] for ref in order[:48]]


async def _rank_passages(edition, workspace, terms, initial_hits, plan, capacity, passages):
    await asyncio.to_thread(passages.add, initial_hits, plan)
    chosen, matches = passages.select(plan, capacity)
    missing = [facet for facet in plan.facets if facet.number not in matches]
    if missing:
        keyword = edition.keyword_index
        # Never do another identical corpus query. A separate focus may recover
        # a source missed by the original broad pool; the physical gate still applies.
        focuses = [facet for facet in missing if compact_text(facet.text) != compact_text(terms)][:3]
        lanes = await asyncio.gather(*(keyword.search_pages(facet.text, 16, phrases=(facet.topic,) if facet.topic else ())
                                     for facet in focuses))
        newly_bound = []
        for (_, raw), facet in zip(lanes, focuses, strict=True):
            newly_bound.extend(await asyncio.to_thread(edition.resolve_hits, raw, keyword, workspace, query=facet.text))
        if newly_bound:
            await asyncio.to_thread(passages.add, newly_bound, plan)
            chosen, matches = passages.select(plan, capacity)
    return chosen, matches


async def rank_edition_evidence(edition, workspace, query, terms, initial_hits, *, top_k, preserve_selection=False):
    """Select at most six verified references; unresolved facets stay explicit."""
    plan = _plan(terms) if not preserve_selection else None
    if plan and len(plan.facets) == 1:
        facet = plan.facets[0]
        if (facet.kind in {"concept", "mechanism"} and not (facet.directions or facet.owners or (facet.fields and facet.devices))
                or facet.kind == "evidence_limit" and not (facet.subjects or facet.labels or facet.devices)):
            plan = None
    principle_plan = _independent_principles(terms, plan)
    plan = plan or _Plan((), False)
    capacity = min(max(top_k, 1), 6)
    passages = _Passages(edition)
    chosen, matches = await _rank_passages(edition, workspace, terms, initial_hits, principle_plan or plan, capacity, passages)
    if principle_plan:
        complete, _ = passages.verified_sources(principle_plan, capacity, "facet_explanation_ids")
        if complete:
            plan = principle_plan
        else:
            # Preserve the old selection contract when one named claim is absent or contested.
            # The second pass reuses documents and source units already verified by physical page.
            passages = _Passages(edition, reusable=passages)
            chosen, matches = await _rank_passages(edition, workspace, terms, initial_hits, plan, capacity, passages)
    precise, ambiguous = await asyncio.to_thread(passages.precise_case, plan, capacity)
    precise_refs = tuple(ref for _, ref in precise.matches) if precise else ()
    observation_ids = tuple(facet.number for facet in plan.facets if facet.kind == "readback")
    verified, ambiguous_observations = passages.verified_sources(plan, capacity, "facet_readback_ids")
    explanations, _ = passages.verified_sources(plan, capacity, "facet_explanation_ids")
    proofs = tuple(ref for _, ref in (*verified, *explanations))
    pool = passages.ordered_pool(dict.fromkeys((*precise_refs, *proofs, *chosen)))
    if not matches and precise is None and not ambiguous and not observation_ids and not explanations:
        return pool, None
    ranked = RankedEvidence(sha256(query.encode("utf-8")).hexdigest(), edition.version,
                            tuple((facet.number, facet.text, facet.kind) for facet in plan.facets),
                            tuple(matches.items()), tuple(facet.number for facet in plan.facets if facet.number not in matches),
                            precise, ambiguous, observation_ids, verified, ambiguous_observations, explanations,
                            tuple((facet.number, facet.topic) for facet in plan.facets if facet.topic))
    return pool, ranked
