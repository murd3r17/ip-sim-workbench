# -*- coding: utf-8 -*-
"""Candidate-only ranking; explicit protocol context disambiguates shared terms.

Historical hit counts are not current answer-quality acceptance.
"""
from __future__ import annotations

import re
from core.markdown_blocks import blocks, retrieval_body


_PROTOCOL = re.compile(
    r"(?<![a-z0-9])(?:ospf(?:v[23])?|bgp|is-?is|rip(?:ng)?|bfd|vrrp|[mr]?stp|dhcp(?:v6)?|dns|ipsec|qinq|ssh)(?![a-z0-9])",
    re.I,
)


def _protocols(text: str) -> set[str]:
    names = {re.sub(r"(?:v[236]|ng)$", "", name.lower()).replace("is-is", "isis")
             for name in _PROTOCOL.findall(text or "")}
    # Basic STP material remains relevant to its rapid/multiple-tree variants.
    return {"stp" if name in {"stp", "rstp", "mstp"} else name for name in names}


def protocol_context(hits: list[dict] | None, original_query: str) -> list[dict]:
    """Drop clearly other-protocol chapters, not generic or cross-protocol text.

    Use the user's actual terms, never query expansions. Headings are retrieval
    context only, not trusted instructions or evidence of factual correctness.
    """
    wanted = _protocols(original_query)
    result = []
    for hit in hits or []:
        if not isinstance(hit, dict):
            continue
        body = str(hit.get("content") or hit.get("text") or "")
        headings = "\n".join(body[a:b] for kind, a, b in blocks(body) if kind == "heading")
        if not wanted or not _protocols(headings) or _protocols(body) & wanted:
            result.append(hit)
    return result


def _toks(text: str) -> set[str]:
    out = set()
    for run in re.findall(r"[\u4e00-\u9fff]+", text or ""):
        for i in range(len(run) - 1):
            out.add(run[i:i + 2])
    for w in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if len(w) >= 2:
            out.add(w)
    return out


def _comparison_coverage(items: list[dict], question: str, top_k: int) -> list[dict]:
    """Cover explicit comparison subjects without more searches or new text.

    Conservative fallback: every short subject must match an existing candidate;
    ambiguous prose or an insufficient budget leaves the original order intact.
    Repeated book titles and English substrings do not establish coverage.
    """
    if not items or len(question) > 500 or not re.search(r"区别|差异|比较|对比", question):
        return items[:top_k]
    text = re.sub(r"(?:有(?:什么|哪些))?(?:区别|差异).*|谁先比较.*", "", question)
    compact = lambda value: re.sub(r"\s+", "", value).lower()
    terms = [re.sub(r"^(?:请|解释|比较|对比)|(?:的|有)$", "", compact(part)).strip("？?，,。")
             for part in re.split(r"、|和|与|及", text)]
    if not (2 <= len(terms) <= min(4, top_k)) or not all(2 <= len(term) <= 32 for term in terms):
        return items[:top_k]
    # Short acronyms can mean unrelated concepts (e.g. RA in IPv6 versus PKI).
    # If a leading source already discusses them together, preserve that ranking
    # instead of promoting a distant single-acronym heading from another field.
    if all(re.fullmatch(r"[a-z]{2,3}", term) for term in terms):
        for item in items[:top_k]:
            body = retrieval_body(str(item.get("content") or item.get("text") or ""))
            if all(re.search(r"(?<![a-z0-9_])" + re.escape(term) + r"(?![a-z0-9_])", body, re.I)
                   for term in terms):
                return items[:top_k]
    matches = []
    for term in terms:
        pattern = ((r"(?<![a-z0-9_])" if term[0].isascii() else "") + re.escape(term)
                   + (r"(?![a-z0-9_])" if term[-1].isascii() else ""))
        candidates = []
        for rank, item in enumerate(items):
            body = str(item.get("content") or item.get("text") or "")
            headings = "\n".join(body[a:b] for kind, a, b in blocks(body)
                                 if kind == "heading" and not body[a:b].startswith("# "))
            in_heading = bool(re.search(pattern, compact(headings)))
            in_body = bool(re.search(pattern, compact(retrieval_body(body))))
            if in_heading or in_body:
                candidates.append((in_heading, in_body, -rank, rank))
        if not candidates:
            return items[:top_k]
        matches.append(max(candidates)[-1])
    chosen = list(dict.fromkeys([0, *matches]))
    if len(chosen) > top_k:
        return items[:top_k]
    chosen.extend(i for i in range(len(items)) if i not in chosen)
    return [items[i] for i in chosen[:top_k]]


def _vrrp_transition_question(question: str) -> bool:
    return bool(re.search(r"(?<![a-z0-9_])vrrp(?![a-z0-9_])", question, re.I)
                and re.search(r"选举|切换|倒换|切回|回切|主备", question))


def _transition_coverage(items: list[dict], question: str, top_k: int) -> list[dict]:
    """Keep arbitration, failure detection and failback in a VRRP explanation.

    Only select original candidates from the same search, never add neighbouring
    text or presumed answers. All three evidence types must exist and fit. The
    user's question, rather than synonym expansion, controls this narrow policy.
    """
    if not _vrrp_transition_question(question) or top_k < 4:
        return items[:top_k]
    patterns = (
        r"优先级.{0,100}(?:取值|依据)",
        r"MASTER_DOWN.{0,40}超时|超时.{0,40}MASTER_DOWN",
        r"抢占模式|preempt.mode",
    )
    matches = []
    for pattern in patterns:
        selected = None
        for rank, item in enumerate(items):
            content = str(item.get('content') or item.get('text') or '')
            if not re.search(r'(?<![a-z0-9_])vrrp(?![a-z0-9_])', content, re.I):
                continue
            # Unanswered exercise options are not explanatory evidence.
            headings = '\n'.join(content[a:b] for kind, a, b in blocks(content) if kind == 'heading')
            if re.search(r'思考题|练习题|习题|测试题', headings):
                continue
            prose = '\n'.join(content[a:b] for kind, a, b in blocks(content)
                              if kind not in {'heading', 'fence'})
            if re.search(pattern, prose, re.I):
                selected = rank
                break
        if selected is None:
            return items[:top_k]
        matches.append(selected)
    chosen = list(dict.fromkeys([0, *matches]))
    chosen.extend(index for index in range(len(items)) if index not in chosen)
    return [items[index] for index in chosen[:top_k]]


def _configuration_coverage(items: list[dict], question: str, top_k: int) -> list[dict]:
    """Keep one existing procedure for an explicit, single-protocol how-to.

    The generic introduction remains first. No extra search, invented text or
    configuration authorization; an exercise or book title is not a procedure.
    """
    wanted = _protocols(question)
    if (len(wanted) != 1 or top_k < 2
            or not re.search(r'怎么配|如何配|怎样配|配置步骤|配置方法|基本配置|如何设置|怎么设置',question)
            or re.search(r'无需|不(?:需|用|要).*配',question)):
        return items
    for index,item in enumerate(items):
        content = str(item.get('content') or item.get('text') or '')
        headings = [content[a:b] for kind,a,b in blocks(content)
                    if kind=='heading' and not content[a:b].startswith('# ')]
        if any(re.search(r'思考题|练习题|习题|测试题|课程目录|本章结构',text) for text in headings):
            continue
        if any(_protocols(text)&wanted and '配置' in text for text in headings):
            if index < top_k:
                return items
            return [items[0],item,*[row for pos,row in enumerate(items) if pos not in {0,index}]]
    return items


def _explicit_subject_coverage(items: list[dict], question: str, top_k: int) -> list[dict]:
    """Keep an explicit network subject when its surrounding business dominates.

    One existing explanatory section may be promoted, without adding a search,
    text, or result slot. Never use expansion-only terms or short ambiguous
    acronyms; multi-subject comparisons retain their joint-context policy.
    """
    anchors = [name for name in SYNONYMS
               if re.fullmatch(r'[a-z][a-z0-9-]{2,12}', name)
               and re.search(r'(?<![a-z0-9_])'+re.escape(name)+r'(?![a-z0-9_])',question,re.I)]
    if len(anchors)!=1 or top_k<2:
        return items
    pattern=r'(?<![a-z0-9_])'+re.escape(anchors[0])+r'(?![a-z0-9_])'
    q=_toks(question)
    candidates=[]
    for index,item in enumerate(items):
        content=str(item.get('content') or item.get('text') or '')
        headings='\n'.join(content[a:b] for kind,a,b in blocks(content)
                           if kind=='heading' and not content[a:b].startswith('# '))
        if re.search(r'思考题|练习题|习题|测试题|目录',headings):
            continue
        prose=retrieval_body(content)
        if re.search(pattern,headings,re.I) and re.search(pattern,prose,re.I):
            if index<top_k:
                return items
            candidates.append((len(q&_toks(headings)),len(q&_toks(prose)),-index,index))
    if not candidates:
        return items
    chosen=max(candidates)[-1]
    return [items[0],items[chosen],*[item for index,item in enumerate(items) if index not in {0,chosen}]]


def rerank(hits: list[dict] | None, query: str, top_k: int, alpha: float = 0.3,
           *, original_query: str | None = None) -> list[dict]:
    items = protocol_context(hits, query if original_query is None else original_query)
    if not items:
        return []
    q = _toks(query)
    if not q:
        return items[:top_k]

    def blended(h: dict) -> float:
        body = str(h.get("content") or h.get("text") or "")
        lex = len(q & _toks(body)) / len(q)
        vector = float(h.get("score") or 0.0)
        return (1 - alpha) * vector + alpha * lex

    ranked = sorted(items, key=blended, reverse=True)
    question = query if original_query is None else original_query
    ranked = _transition_coverage(ranked, question, len(ranked)) if top_k >= 4 else ranked
    ranked = _configuration_coverage(ranked, question, top_k)
    ranked = _explicit_subject_coverage(ranked, question, top_k)
    return _comparison_coverage(ranked, question, top_k)


# C-R3 6.4：同 K 条件下验证过的网络术语扩展（覆盖 0.692→0.744，任一命中 0.812→0.938）
SYNONYMS = {
    "qinq": "QinQ 双层 VLAN 标签 stack-vlan 灵活 QinQ",
    "vrrp": "VRRP 虚拟路由冗余 主备 抢占 Master Backup",
    "mstp": "MSTP 多生成树 实例 MSTI VLAN 映射",
    "ospf": "OSPF 链路状态 LSA LSDB 邻居 区域",
    "bgp": "BGP 选路 Local_Preference AS_PATH 路由",
    "acl": "ACL 访问控制列表 规则 匹配 通配符",
    "ssh": "SSH Telnet 安全加固 认证 ACL",
    "hrp": "HRP 双机热备 心跳 VGMP 同步",
    "排障": "故障排查 分层 分段 定位 现象 范围 证据 假设 验证",
    "排查": "故障排查 分层 分段 定位 现象 范围 证据 假设 验证",
    "lsa": "LSA 链路状态通告 Type1 Type2 Type3 Type5 Type7 External NSSA Summary Router Network",
    "stub": "Stub 区域 外部路由 Type4 Type5 禁止 过滤 缺省路由 ABR NSSA",
    "nssa": "NSSA Type7 外部 LSA ABR 转换",
    "状态": "状态机 Down Init 2-Way ExStart Exchange Loading Full 邻居",
    "路由反射": "Router Reflector RR Cluster ID Originator ID Cluster List IBGP",
    "reflector": "Router Reflector Cluster ID Originator ID Cluster List IBGP",
    "vrrp": "VRRP 虚拟路由冗余 虚拟网关 虚拟IP Master Backup 抢占",
    "ssh": "SSH Telnet 安全加固 认证 ACL 源地址 口令策略",
    "ipv6": "IPv6 ND 邻居发现 RS RA NS NA 地址解析",
    "acl": "ACL 访问控制列表 规则 匹配 通配符 默认拒绝 首条匹配 ssh server acl 源地址",
}


def expand_query(query: str) -> str:
    # A concrete SSH how-to needs authentication procedures. Broad hardening
    # expansion otherwise fills the same24 candidates with host-security and
    # ACL introductions before the existing configuration section is seen.
    # Keep the original question and search/result budgets; concepts,
    # comparisons and explicitly negated how-tos keep the general expansion.
    if (_protocols(query or '') == {'ssh'}
            and re.search(r'怎么配|如何配|怎样配|配置步骤|配置方法|基本配置|如何设置|怎么设置',query or '')
            and not re.search(r'无需|不(?:需|用|要).*配',query or '')):
        return (query or '') + ' SSH 基本配置 用户 认证 公钥'
    extra = [v for k, v in SYNONYMS.items() if re.search(k, query or "", re.I)]
    if _vrrp_transition_question(query or ''):
        extra.append('优先级 Priority 选举 通告 MASTER_DOWN 定时器 抢占模式')
    return (query or "") + (" " + " ".join(extra) if extra else "")


YAML_RE = __import__("re").compile(r"\A---\s*\n.*?\n---\s*\n", __import__("re").S)
META_RE = __import__("re").compile(r"<document_metadata>.*?</document_metadata>", __import__("re").S | __import__("re").I)


def clean_chunk(text: str) -> str:
    """R5-05：去掉送入生成/判据的 YAML 与 metadata 前言，按正文计 token。"""
    t = META_RE.sub("", text or "").lstrip()
    t = YAML_RE.sub("", t)
    return t.strip()
