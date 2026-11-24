"""Keep a complete observation and its same-page qualification."""
from dataclasses import dataclass
import re
from unicodedata import normalize

from core.markdown_blocks import blocks, complete_prefix, unclosed_fence_start
from modules.knowledge.query_focus import compact_text, passage_concepts, protocol_names


_OBSERVATION = re.compile(r"回显|读回|输出|表(?:格|项|中|内|里)|图(?:里|中|上|例|注)|截图")
_INTERPRETATION = re.compile(r"为什么|有(?:何|什么)风险|(?:符合|满足)?(?:哪些?|什么)条件|前提|能否(?:证明|说明|判断|验收)|"
                             r"(?:能|足以|足够|可以)(?:顺便)?(?:证明|说明|给出?|判断|验收)|(?:说明|表示)(?:什么|哪)|"
                             r"意味着|还需|是否(?:已|足以)|区别|怎么读")
_MULTIPLE_FIELDS = re.compile(r"分别|各自|以及|同时|另外|还要|又是|和.{1,20}(?:分别|各)")
_OUTSIDE = re.compile(r"另一(?:实验|场景|个表|个图|张|页)|不同实验|(?:另一|独立的)(?:回显|对等体记录|输出)|分别见|整章|全表|所有行|原句|逐字")
_SCOPE_BREAK = re.compile(r"(?:上一|下一|另一个|另一组|另一台)(?:步|实验|场景|页|图|表)|(?m:^\s*(?:步骤\s*\d|[-*]{3,}\s*$))")
_FROM_EXHIBIT = re.compile(r"从(?:上面|上述|该|这份|输出|回显|表中|图中)|(?:这份|该|上面|上述)(?:回显|输出|表格|表|图)|"
                            r"原(?:页|图)的[^，。\n]{0,16}(?:表|回显)|表中|图(?:中|里|例中)")
_TO_EXHIBIT = re.compile(r"如下(?:表|图|显示|回显|输出)|(?:表中|图中|下表|下图|原图指令|回显中|输出中|同一回显)")
_QUALIFIER = re.compile(r"因此|意味着|从而|防环|说明|仅能|只(?:能|证明|说明)|还需|另(?:需|按)|仍(?:需|应)|不能|不代表|"
                          r"(?:前|条)件|只有|前提|当.{1,65}时|若|否则|结果|风险|需要|判读|表示")
_LIMITATION = re.compile(r"不能|不足以|不代表|不表示|只(?:能|证明|说明)|(?:才|方)能(?:证实|确认|判断|证明)|"
                           r"(?:仍|还|另)需|(?:需(?:要)?|须)[^。!?！？]{1,70}(?:验证|证实|另查|核对|读回)|"
                           r"(?:没有|无|不产生|未产生)(?:任何)?(?:回显|输出)|(?:回显|输出)(?:为|仍)?空")
_PHASE = re.compile(r"(?P<event>调整|调|修改|切换|故障|恢复|聚合|汇总|引入|重分发|重选)(?:发生|完成)?(?:之|以)?(?P<time>前|后)")
_PHASE_ALIASES = {"调": "调整", "修改": "调整", "汇总": "聚合", "重分发": "引入"}
_COMPLETED_PHASE = {("聚合", "后"): re.compile(r"(?m)^\s*Aggregated route\.\s*$", re.I)}
_DEVICE = re.compile(r"(?<![A-Za-z0-9])(?:ar|ce|fw|ne|pe|pc|sw|ap|ac|p|r|s)[0-9]+(?![A-Za-z0-9])", re.I)
_ADDRESS = re.compile(r"(?<![A-Za-z0-9_.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?:/[0-9]{1,2})?(?![A-Za-z0-9_./])")
_IFACE = re.compile(r"(?<![a-z0-9])(?:ge|gigabitethernet|eth|xge|10ge)\s*(\d+/\d+/\d+)(?![a-z0-9./])", re.I)
_PROMPT = re.compile(r"^\s*(?:<(?P<angle>[^>]+)>|\[(?P<bracket>[^]]+)\])\s*(?P<command>\S.*)$")
_READ_ONLY = re.compile(r"(?:display|show)\s+\S", re.I)
_END_SENTENCE = re.compile(r"[。！？!?；：:.][”’）》)\]`*]*$")


@dataclass(frozen=True)
class CoverageRequest:
    identifiers: frozenset[str]
    protocols: frozenset[str]
    phase: frozenset[tuple[str, str]]
    concepts: frozenset[str]
    interpretation: bool


def _identifiers(text):
    text = normalize("NFKC", text).casefold()
    return frozenset([*_DEVICE.findall(text), *_ADDRESS.findall(text), *_IFACE.findall(text)])


def _phases(text):
    return frozenset((_PHASE_ALIASES.get(match["event"], match["event"]), match["time"]) for match in _PHASE.finditer(text))


def coverage_request(query):
    if not _OBSERVATION.search(query) or _OUTSIDE.search(query):
        return None
    concepts = frozenset(passage_concepts(query))
    interpretation = bool(_INTERPRETATION.search(query))
    phase = _phases(query)
    if len(phase) > 1 or not (interpretation or (len(concepts) >= 2 and _MULTIPLE_FIELDS.search(query))):
        return None
    return CoverageRequest(_identifiers(query), frozenset(protocol_names(query)), phase, concepts, interpretation)


def _exhibit(kind, text):
    if kind == "table":
        lines = text.splitlines()
        return len(lines) >= 3 and len({line.strip().strip("|").count("|") for line in lines}) == 1
    if kind != "fence" or unclosed_fence_start(text) is not None:
        return False
    rows = [line.strip() for line in text.splitlines()[1:-1] if line.strip()]
    if len(rows) < 2 or not (start := _PROMPT.fullmatch(rows[0])) or not _READ_ONLY.match(start["command"]):
        return False
    return not any(_PROMPT.fullmatch(line) for line in rows[1:]) and any(re.search(r"[A-Za-z0-9\u4e00-\u9fff]", row) for row in rows[1:])


def _same_experiment(prose, exhibit, *, preceding, sole_exhibit):
    if _SCOPE_BREAK.search(prose) or _SCOPE_BREAK.search(exhibit):
        return False
    connection = (_TO_EXHIBIT if preceding else _FROM_EXHIBIT).search(prose)
    if not connection:
        return False
    prose_ids, exhibit_ids = _identifiers(prose), _identifiers(exhibit)
    if prose_ids and exhibit_ids and not (prose_ids & exhibit_ids):
        return False
    if sole_exhibit or prose_ids & exhibit_ids:
        return True
    return bool(re.search(r"从(?:输出|回显)信息|原(?:页|图)的[^，。\n]{0,16}(?:表|回显)|回显如下|输出如下|如下回显", prose))


def paired_excerpt(page, current, request, *, max_chars=1100):
    """Propose only a contiguous readout with its directly related conditions."""
    if max_chars <= 0:
        return None
    visible_text = complete_prefix(current, max_chars)
    visible = compact_text(visible_text)
    if not visible:
        return None
    spans = [(kind, start, end, page[start:end].strip()) for kind, start, end in blocks(page)]
    exhibits = {i for i, (kind, _, _, text) in enumerate(spans) if _exhibit(kind, text)}
    current_has_exhibit = any(_exhibit(kind, visible_text[a:b].strip()) for kind, a, b in blocks(visible_text))
    same_scope = (len(request.identifiers) >= 2 and any("." in key or "/" in key for key in request.identifiers)
                  and request.identifiers <= _identifiers(visible_text))
    old_concepts = request.concepts & passage_concepts(current)
    visible_limits = {compact_text(text) for kind, _, _, text in spans
                      if kind == "paragraph" and _LIMITATION.search(text) and compact_text(text) in visible}
    proposals = {}
    for i in sorted(exhibits):
        _, _, _, exhibit = spans[i]
        exhibit_visible = compact_text(exhibit) in visible
        # Look only across two paragraphs immediately adjoining this exhibit.
        for direction in (-1, 1):
            adjacent = []
            for distance in (1, 2):
                at = i + direction * distance
                if not 0 <= at < len(spans) or spans[at][0] != "paragraph" or _SCOPE_BREAK.search(spans[at][3]):
                    break
                adjacent.append(at)
                qualifiers = [spans[index][3] for index in adjacent
                              if _same_experiment(spans[index][3], exhibit, preceding=direction < 0, sole_exhibit=len(exhibits) == 1)
                              and (not request.interpretation or _QUALIFIER.search(spans[index][3]))]
                if not qualifiers:
                    continue
                visible_qualifier = any(compact_text(prose) in visible for prose in qualifiers)
                if exhibit_visible and visible_qualifier:
                    break
                if not (exhibit_visible or visible_qualifier or (same_scope and not current_has_exhibit)):
                    continue
                text = page[spans[min(i, at)][1]:spans[max(i, at)][2]].strip()
                if direction > 0 and not _END_SENTENCE.search(spans[at][3]):
                    continue
                compact_excerpt = compact_text(text)
                if any(limit not in compact_excerpt for limit in visible_limits):
                    continue
                evidence_phases = _phases(text) | {phase for phase, pattern in _COMPLETED_PHASE.items() if pattern.search(exhibit)}
                if not (len(text) <= max_chars and request.identifiers <= _identifiers(text) and request.phase <= evidence_phases):
                    continue
                if any((event, "前" if when == "后" else "后") in evidence_phases for event, when in request.phase):
                    continue
                source_protocols = protocol_names(text)
                if source_protocols and not request.protocols.issubset(source_protocols):
                    continue
                new_concepts = request.concepts & passage_concepts(text)
                if not old_concepts <= new_concepts or (not request.interpretation and old_concepts == new_concepts):
                    continue
                proposals[i, direction] = text
                break
    return next(iter(proposals.values())) if len(proposals) == 1 else None
