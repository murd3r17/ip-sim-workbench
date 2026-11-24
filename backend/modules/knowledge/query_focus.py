"""Find short, protocol-scoped query parts without changing the user's question."""
from dataclasses import dataclass
import re
from unicodedata import normalize


_SUBJECT = re.compile(r"(?<![A-Za-z0-9])(?:VRRP|HRP|OSPF(?:v3)?|BGP|BFD|MSTP|STP|RSTP|LDP|MPLS|IS-IS|ISIS|LLDP|VLAN|DHCP|ARP)(?![A-Za-z0-9])", re.I)
_PREEMPTION_DELAY = re.compile(r"(?:抢占|回切)(?:延时|延迟)")
_UPLINK = r"(?:上行|上联)(?:接口|端口|链路|口)?"
_UPLINK_TRACK = re.compile(rf"(?:{_UPLINK}(?:跟踪|监视)|(?:跟踪|监视){_UPLINK})")
_UPLINK_OUTAGE = re.compile(rf"{_UPLINK}.{{0,14}}(?:故障|断开|断掉|不可用|物理(?:上)?\s*down|\bdown\b)", re.I)
_CRC_COUNTER = re.compile(r"(?<![A-Za-z0-9])CRC(?![A-Za-z0-9])", re.I)
_ALIASES = (
    (_UPLINK_TRACK, "监视上行端口"),
    (_PREEMPTION_DELAY, "抢占延时"),
)
_QUESTION_WORDS = re.compile(r"^(?:请|帮我|分别|想了解|解释|说明|讲讲|讲解|介绍|查询|请问|对照|教材中|关于)\s*")
_QUESTION_END = re.compile(r"(?:的?(?:机制|原理|含义|工作过程)|是什么|怎么做|如何工作|有何区别)\s*$")
_INTRO_LOOKUP = re.compile(
    r"(?:(?:请问|请)?(?:解释|介绍|讲解|了解)(?:一下)?|什么是)?"
    r"(?:的?(?:基础|概述|概念|原理|机制|作用|含义|工作过程|邻居(?:关系|状态)?|邻接(?:关系|状态)?)"
    r"|是什么|用来做什么|如何工作)?"
)
_INSPECTION_LOOKUP = re.compile(r"命令|回显|(?:怎么|如何|怎样)\s*(?:查看|检查|查询|核对|确认)")
_BOOK_OR_TITLE = re.compile(r"《([^》\n]{2,160})》")
_SOURCE_QUOTE = re.compile(r'“([^”\n]+)”|‘([^’\n]+)’|「([^」\n]+)」|『([^』\n]+)』|"([^"\n]+)"|`([^`\n]+)`')
_RELAXED_QUOTE = re.compile(
    r"(?:不(?:必|用|需(?:要)?|要求|追求)|无需|无须|没必要|并非要)\s*"
    r"(?:(?:完全|严格|精确|必须|照搬|对照|按|找|查|匹配|引用|保留)\s*)*"
    r"(?:逐字|逐句|原句|原话|原文|引文|字面|一字不差)|(?:大意|同义表达|意思相近)(?:即可|就好|就行)"
)
_EXPLICIT_QUOTE = re.compile(r"原句|原话|原文|逐字|逐句|引文|一字不差|字面(?:一致|一样|匹配)|照录")
_LOOK_UP_QUOTE = re.compile(
    r"^(?:(?:请|帮我|先)\s*)*(?:从|在)?(?:这本|本)?(?:教材|课件|原书)?(?:里|中)?\s*"
    r"(?:查|找)(?:一下)?[\s：:]*$"
)
_QUOTE_CONTEXT = re.compile(
    r"(?:这|那|该|原|同一|上|下|前|后)\s*(?:一)?(?:句|段|行|列|页)|"
    r"(?:同?一句话|同一句)(?:里|中|内)|"
    r"(?:所在(?:的)?(?:页|段|表)|附近|前面|后面|上下文|出自(?:哪|何)|在哪一?(?:页|段)|哪一(?:页|段))"
)
_PDF_PAGE = re.compile(r"(?:PDF\s*第?|第)\s*(\d{1,5})(?:\s*页?\s*[-–—~～至到]\s*第?\s*(\d{1,5}))?\s*页", re.I)
_LIST_PAGE = r"(?:PDF\s*)?(?:物理\s*)?第\s*[1-9]\d{0,4}\s*页"
_PDF_PAGE_LIST = re.compile(
    rf"PDF\s*(?:物理\s*)?第\s*[1-9]\d{{0,4}}\s*页(?:\s*(?:、|和|以及|及|与)\s*{_LIST_PAGE}){{1,4}}",
    re.I,
)
_AMBIGUOUS_PAGE_LIST = re.compile(r"印刷页|印的页|印刷(?:第|页码)|另一本|分别见|任一页|任选|或者|页或|"
                                  r"不要(?:查|用|看|找|引用)|不(?:看|查|用|是|引用)(?:这|那|PDF|第)|除了")
_TITLE_LOOKUP = re.compile(r"^(?:(?:请|帮我|查找|搜索|找一下|打开|查看|定位)\s*)+|(?:这一[章节]|在哪一[章节页]|在哪[里儿]|的位置)[？?。！!\s]*$")
_TITLE_NUMBER = re.compile(r"^\d+(?:[.．]\d+)*[.、．]?\s+")
_SCOPE_CONNECTORS = re.compile(r"^(?:请问|请|根据|按照|参考|在|从|只查|只看|仅查|仅看)+|(?:中|里|的)$")
_QUERY_FILLER = re.compile(
    r"(?:教材|课件|原书|书里|这本书|这一章|本章)(?:中|里|的)?|"
    r"(?:原|本|这个|该)例(?:子|中|里)?|(?:请问|请帮我|帮我看一下|能否说一下)|"
    r"(?:是什么|有哪些|分别是|哪个|哪一[种条项个]|为什么|怎么回事|能列出来吗|说明了什么)"
)
_LOOKUP_OVERVIEW = re.compile(r"目录|章名|章节结构|培训内容|学习目标|本章讲什么|课程概览|复习题")
_LOOKUP_OBSERVATION = re.compile(r"回显|读回|截图|表(?:项|格|内|中|里)|哪一(?:行|列)|试验时.*显示|端口|接口号")
_LOOKUP_VISUAL = re.compile(r"(?:原|示意|组网|拓扑|连线)图|图(?:里|中|上|例)|图示|表(?:里|中|格)|哪一(?:行|列)")
_LOOKUP_INTERPRETATION = re.compile(r"含义|表示什么|代表什么|指的是什么|怎么理解|分别表示|帮助区分|有什么区别")
_MULTI_FACET = re.compile(r"分别|各自|各[是多少]|对照|对比|两(?:者|个|台|处|条)|前后|不同|区别|还是|对不对")
_MSTP_INSTANCE = re.compile(r"\bMST[IP]\b|多(?:实例)?生成树", re.I)
_EXPLICIT_VLAN = re.compile(r"(?<![A-Za-z0-9])VLAN[ \t]*(\d{1,4})(?![A-Za-z0-9])", re.I)
_PASSAGE_CONCEPTS = re.compile(
    r"(?P<next_hop>下一跳|下一个转发设备|转发下一站|\bnext\s*hop\b)|"
    r"(?P<egress_interface>出接口|出口网口|出方向(?:端口|接口)|出去的(?:端口|接口)|\begress\s+interface\b)|"
    r"(?P<ingress_interface>入接口|入口网口|入方向(?:端口|接口)|进来的(?:端口|接口)|\bingress\s+interface\b)|"
    r"(?P<session_table>会话(?:记录|表项|表)|连接(?:清单|明细|表项|表)|\bsession\s+table\b)|"
    r"(?P<session_state>会话状态|建连状态|连接状态|对等状态)|"
    r"(?P<received_prefixes>收到的(?:路由|前缀)(?:数|条数|数量)|接收(?:路由|前缀)(?:数|条数|数量)|\bprefrcv\b)|"
    r"(?P<source_address>源地址|来源地址|发送方(?:的)?地址|发件方(?:的)?地址|\bsource\s+address\b)|"
    r"(?P<destination_address>目的地址|目标地址|接收方(?:的)?地址|收件方(?:的)?地址|\bdestination\s+address\b)|"
    r"(?P<private_network>私网|内网|私有网络|内部网络|\bprivate\s+network\b)|"
    r"(?P<public_network>公网|外网|公有网络|外部网络|\bpublic\s+network\b)|"
    r"(?P<route_leaking>路由渗透|路由泄露|\broute\s+leak(?:ing)?\b)|"
    r"(?P<load_sharing>带宽比例|流量比例|流量分流|流量分配|负载分担|负荷分配|\bload\s+(?:sharing|balancing)\b)|"
    r"(?P<peer_output>邻居回显|邻接回显|邻居输出|邻接输出|\bdisplay\s+[a-z-]+\s+peer\b)|"
    r"(?P<operational_output>命令回显|状态回显|状态输出|命令输出|终端(?:回显|输出))|"
    r"(?P<link_failure>链路故障|链路中断|链路断开|链路中止|断链)|"
    r"(?P<identity_authentication>身份校验|身份核验|身份验证|身份认证|\bauthentication\b)", re.I,
)
OSPF_PEER_COMMAND = "display ospf peer brief"
_SHORT_TECHNICAL_ALIASES = {
    "isis 邻接": "Hello 邻居 级别 建立",
    "ospf stub": "Stub 区域 缺省路由 外部 LSA",
    "vlan trunk": "Trunk 允许多个 VLAN 802.1Q 标签",
    "dhcp relay": "DHCP 中继 广播 转发 跨网段",
    "lacp": "LACP 链路聚合 协商 成员",
    "mpls php": "PHP 次末跳 弹出 隐式空标签",
}


def compact_text(text: str) -> str:
    """Keep punctuation and token content while normalizing layout whitespace."""
    return "".join(normalize("NFKC", text).casefold().split())


def title_lookup(text: str) -> str:
    return _TITLE_LOOKUP.sub("", text.strip()).strip("《》‘’“”\"？?。！! ")


def title_key(text: str) -> str:
    return compact_text(_TITLE_NUMBER.sub("", text.strip()))


def scoped_terms(text: str) -> str:
    return _SCOPE_CONNECTORS.sub("", title_lookup(text).strip("，、：: ")).strip("，、：: ")


def passage_query(text: str) -> str:
    """Remove reading-request language while retaining evidence terms and labels."""
    return _QUERY_FILLER.sub(" ", text)


def passage_intent(text: str) -> tuple[bool, bool, bool, bool]:
    observed = bool(_LOOKUP_OBSERVATION.search(text) or re.search(r"邻接输出|邻居输出|字段|接收.*条数|出口网口", text))
    return bool(_LOOKUP_OVERVIEW.search(text)), observed, bool(_LOOKUP_VISUAL.search(text)), bool(_LOOKUP_INTERPRETATION.search(text))


def passage_concepts(text: str) -> set[str]:
    """Index equivalent reading vocabulary without inferring answers or topics."""
    return {match.lastgroup for match in _PASSAGE_CONCEPTS.finditer(text)}


def multiple_passage_facets(text: str) -> bool:
    return bool(_MULTI_FACET.search(text))


def vlan_mapping_query(text: str) -> frozenset[int]:
    if not (_MSTP_INSTANCE.search(text) and re.search(r"实例|映射|instance", text, re.I)):
        return frozenset()
    ids = frozenset(int(match[1]) for match in _EXPLICIT_VLAN.finditer(text) if 1 <= int(match[1]) <= 4094)
    return ids if len(ids) >= 2 else frozenset()


def lookup_parts(text: str) -> tuple[list[str], list[str], tuple[int, int] | None, str]:
    """Extract user-stated titles, literal phrases and physical PDF page scope."""
    titles = _BOOK_OR_TITLE.findall(text)
    outside = _SOURCE_QUOTE.sub(" ", text)
    page = _PDF_PAGE.search(outside)
    pages = (int(page[1]), int(page[2] or page[1])) if page else None
    phrases = []
    if not _RELAXED_QUOTE.search(outside):
        explicit = _SOURCE_QUOTE.fullmatch(text.strip()) or _EXPLICIT_QUOTE.search(outside)
        for match in _SOURCE_QUOTE.finditer(text):
            phrase = next(value for value in match.groups() if value is not None)
            length = len(compact_text(phrase))
            prefix = _BOOK_OR_TITLE.sub("", text[:match.start()]).strip("，、。 ")
            suffix = _SOURCE_QUOTE.sub(" ", text[match.end():])
            referring_to_quote = _LOOK_UP_QUOTE.fullmatch(prefix) and _QUOTE_CONTEXT.search(suffix)
            if (explicit and length >= 2) or (length >= 10 and (pages or referring_to_quote)):
                phrases.append(phrase)
    remainder = _PDF_PAGE.sub("", _BOOK_OR_TITLE.sub("", text)).strip()
    return titles, phrases, pages, remainder


def separate_pdf_pages(text: str) -> tuple[tuple[int, ...], str, str] | None:
    """Read an explicit list of non-contiguous PDF page references in one named source."""
    if not _BOOK_OR_TITLE.search(text):
        return None
    outside = _BOOK_OR_TITLE.sub(lambda match: ' ' * len(match[0]), text)
    outside = _SOURCE_QUOTE.sub(lambda match: ' ' * len(match[0]), outside)
    if _AMBIGUOUS_PAGE_LIST.search(outside):
        return None
    selection = _PDF_PAGE_LIST.search(outside)
    if not selection or _PDF_PAGE.search(outside[:selection.start()] + outside[selection.end():]):
        return None
    pages = tuple(dict.fromkeys(int(n) for n in re.findall(r"第\s*(\d+)\s*页", selection[0])))
    if len(pages) < 2:
        return None
    return pages, text[:selection.start()], text[selection.end():]


def technical_aliases(text: str) -> str:
    key = " ".join(text.casefold().replace("is-is", "isis").split())
    return _SHORT_TECHNICAL_ALIASES.get(key, "")


def introductory_query(text: str) -> bool:
    if len(protocol_names(text)) != 1:
        return False
    remainder = re.sub(r"[\s？?。！!]+", "", _SUBJECT.sub("", text))
    return bool(_INTRO_LOOKUP.fullmatch(remainder))


def ospf_peer_lookup(text: str) -> bool:
    return (protocol_names(text) == {"ospf"} and ("邻居" in text or "邻接" in text)
            and bool(_INSPECTION_LOOKUP.search(text)))


@dataclass(frozen=True)
class QueryFocus:
    query: str
    subject: str
    facet: str


def focused_queries(text: str) -> list[QueryFocus]:
    """A part must describe its own mechanism, not just name a second protocol."""
    subjects = {match.group().upper() for match in _SUBJECT.finditer(text)}
    results = []
    if subjects == {"VRRP"} and "优先级" in text and (_UPLINK_TRACK.search(text) or _UPLINK_OUTAGE.search(text)):
        results.append(QueryFocus("VRRP 上行接口故障 降低优先级", "VRRP", "降低优先级"))
    if ospf_peer_lookup(text):
        results.append(QueryFocus(f"OSPF 邻居关系 {OSPF_PEER_COMMAND}", "OSPF", OSPF_PEER_COMMAND))
        if re.search(r"2[- ]?Way|DROther", text, re.I):
            results.append(QueryFocus("OSPF 广播网 DROther 2-Way Full 邻接", "OSPF", "2-Way"))
    for clause in re.split(r"[。；;！!？?，,\n]", text):
        clause = clause.strip()
        if not clause or len(clause) > 96:
            continue
        named = _SUBJECT.search(clause)
        if named is None:
            # A follow-on clause can omit VRRP when the rest of the question
            # names only that protocol and the clause names its mechanism.
            if subjects == {"VRRP"}:
                for pattern, canonical in _ALIASES:
                    item = QueryFocus(f"VRRP {canonical}", "VRRP", canonical)
                    if pattern.search(clause) and item not in results:
                        results.append(item)
            continue
        subject = named.group().upper()
        # Stripping lightweight phrasing retains the discriminating technical terms.
        for _ in range(3):
            clause = _QUESTION_WORDS.sub("", clause)
        pieces = re.split(r"(?:以及|分别是|和|与|、)", clause, maxsplit=3)
        parts = []
        for piece in pieces:
            match = _SUBJECT.search(piece)
            name = match.group().upper() if match else subject
            term = _QUESTION_END.sub("", _SUBJECT.sub("", piece)).strip(" 的：:　\t")
            if len(term) < 2 or len(term) > 32 or term.isdecimal():
                # Comparisons such as “OSPF 和 IS-IS” need the full query.
                parts = []
                break
            alias = next((canonical for pattern, canonical in _ALIASES if pattern.search(term)), None)
            parts.append((QueryFocus(f"{name} {alias or term}", name, alias or term), bool(alias)))
        if len(parts) > 1 or any(known for _, known in parts):
            for part, _ in parts:
                if part not in results:
                    results.append(part)
        if len(results) >= 3:
            break
    if not results:
        if subjects == {"VRRP"} and "回切" in text and re.search(r"公式|定时器", text):
            results.append(QueryFocus("VRRP 抢占延时", "VRRP", "抢占延时"))
        elif not subjects and _PREEMPTION_DELAY.search(text):
            # The question did not identify a protocol. Find the stated facet
            # without inventing a device or protocol on the user's behalf.
            results.append(QueryFocus("抢占延时", "", "抢占延时"))
        elif not subjects and _CRC_COUNTER.search(text) and re.search(r"趋势|累计|单次|一次|增量", text):
            results.append(QueryFocus("CRC 错包计数 持续增长", "CRC", "持续增长"))
    return results[:3]


def subject_pattern(subject: str):
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(subject)}(?![A-Za-z0-9])", re.I)


def protocol_names(text: str) -> set[str]:
    return {match.group().lower().replace("is-is", "isis") for match in _SUBJECT.finditer(text)}


def context_only_query(text: str) -> bool:
    return bool(re.fullmatch(
        r"(?:请问\s*)?(?:这里|这个|这一步|这步|这)?\s*(?:该)?(?:怎么做|怎么办|如何操作|下一步呢|继续)[？?。！!\s]*",
        text.strip(),
    ))
