"""Find short, protocol-scoped query parts without changing the user's question."""
from dataclasses import dataclass
import re


_SUBJECT = re.compile(r"(?<![A-Za-z0-9])(?:VRRP|HRP|OSPF(?:v3)?|BGP|BFD|MSTP|STP|RSTP|LDP|MPLS|IS-IS|ISIS|LLDP|VLAN|DHCP|ARP)(?![A-Za-z0-9])", re.I)
_PREEMPTION_DELAY = re.compile(r"(?:抢占|回切)(?:延时|延迟)")
_CRC_COUNTER = re.compile(r"(?<![A-Za-z0-9])CRC(?![A-Za-z0-9])", re.I)
_ALIASES = (
    (re.compile(r"(?:上行(?:接口|端口|链路)?(?:跟踪|监视)|(?:跟踪|监视)上行(?:接口|端口|链路)?)"), "监视上行端口"),
    (_PREEMPTION_DELAY, "抢占延时"),
)
_QUESTION_WORDS = re.compile(r"^(?:请|帮我|分别|想了解|解释|说明|讲讲|讲解|介绍|查询|请问|对照|教材中|关于)\s*")
_QUESTION_END = re.compile(r"(?:的?(?:机制|原理|含义|工作过程)|是什么|怎么做|如何工作|有何区别)\s*$")


@dataclass(frozen=True)
class QueryFocus:
    query: str
    subject: str
    facet: str


def focused_queries(text: str) -> list[QueryFocus]:
    """A part must describe its own mechanism, not just name a second protocol."""
    results = []
    for clause in re.split(r"[。；;！!？?，,\n]", text):
        clause = clause.strip()
        if not clause or len(clause) > 96 or not _SUBJECT.search(clause):
            continue
        subject = _SUBJECT.search(clause).group().upper()
        # Stripping lightweight phrasing retains the discriminating technical terms.
        for _ in range(3):
            clause = _QUESTION_WORDS.sub("", clause)
        pieces = re.split(r"(?:以及|分别是|和|与|、)", clause, maxsplit=3)
        parts = []
        for piece in pieces:
            match = _SUBJECT.search(piece)
            name = match.group().upper() if match else subject
            term = _QUESTION_END.sub("", _SUBJECT.sub("", piece)).strip(" 的：:　\t")
            if len(term) < 2 or len(term) > 32:
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
        subjects = {match.group().upper() for match in _SUBJECT.finditer(text)}
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
