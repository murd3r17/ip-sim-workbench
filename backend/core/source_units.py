"""Exact text ranges for the evidence on one reviewed textbook page."""

from dataclasses import dataclass
import re

from .markdown_blocks import blocks, fence_end, opening_fence


Span = tuple[int, int]

_CAPTION = re.compile(r"(?:\A\s*\**表\s*\d+[\d.–—-]*\s*\S|(?:如下(?:表|图|回显|输出)|"
                      r"下表(?:给出|列出|记录|显示)|(?:回显|输出)(?:如下|见下文))[:：。]?\s*\**\Z)")
_EXPLANATION = re.compile(r"\A\s*\**(?:从(?:上述|上面|上表|输出|回显)|由(?:上表|上面的回显)|"
                          r"(?:这份|上述|上面的|该)(?:回显|输出|表格)|表中|图中|"
                          r"(?:上述|以上)(?:结果|命令回显))")
_SCOPE_BREAK = re.compile(r"(?:另一(?:个|张|台|组|份|次)|下一(?:个|张|步|节)|上一(?:个|张|节))"
                          r"(?:图|表|设备|记录|实验|回显|输出|配置)?|\A\s*(?:步骤|实验|案例)\s*\d")
_LIST_LINE = re.compile(r"^\s*(?:[-+*]|\d+[.)、])\s+\S")
_PROMPT = re.compile(
    r"^\s*(?:<(?P<angle>[\w.:-]{1,96})>|\[[~*]?(?P<bracket>[\w.:/()~-]{1,96})\]|"
    r"(?P<host>[A-Za-z][\w.:-]{0,63})(?:\([\w.:-]{1,50}\))?[>#])\s*(?P<command>[A-Za-z?][^\r\n]*)?\s*$"
)
_READ = re.compile(r"(?:display|show)\s+\S", re.I)
_CONFIG_READ = re.compile(r"(?:display\s+(?:current|saved)-configuration|show\s+(?:running|startup)-config)\b", re.I)
_MEASURE = re.compile(r"(?:ping|tracert|traceroute)\s+\S", re.I)
_REJECTED = re.compile(r"^\s*(?:%\s*)?(?:Error:|Invalid input|Unrecognized command|Incomplete command|\^)\s*", re.I | re.M)
_FENCE_LANG = {"", "cli", "console", "plaintext", "text"}


@dataclass(frozen=True)
class CommandRecord:
    owner: str
    command: str
    prompt: Span
    output: Span | None
    kind: str


@dataclass(frozen=True)
class ReadingUnit:
    kind: str
    start: int
    end: int
    table_header: Span | None = None
    table_rows: tuple[Span, ...] = ()
    commands: tuple[CommandRecord, ...] = ()
    caption: Span | None = None
    explanation: Span | None = None


def _lines(text: str, start: int, end: int):
    for line in text[start:end].splitlines(keepends=True):
        stop = start + len(line)
        yield line.rstrip('\r\n'), start, stop
        start = stop


def _pipe_cells(line: str) -> int | None:
    """Count separators, rejecting ambiguous inline markup in a table row."""
    value = line.strip()
    if not value:
        return None
    delimiters = []
    code_ticks = None
    for token in re.finditer(r"\\.|`+|\|", value):
        if token[0].startswith('`'):
            if code_ticks is None:
                code_ticks = token[0]
            elif code_ticks == token[0]:
                code_ticks = None
        elif token[0] == '|':
            if code_ticks:
                return None
            delimiters.append(token.start())
    if not delimiters:
        return None
    return len(delimiters) + 1 - (delimiters[0] == 0) - (delimiters[-1] == len(value) - 1)


def _table_layout(text: str, start: int, end: int):
    lines = list(_lines(text, start, end))
    if len(lines) < 3 or (columns := _pipe_cells(lines[0][0])) is None or columns < 2:
        return None, ()
    if any(_pipe_cells(line) != columns for line, _, _ in lines[1:]):
        return None, ()
    return (start, lines[1][2]), tuple((row_start, row_end) for _, row_start, row_end in lines[2:])


def _command_records(text: str, start: int, end: int):
    lines = list(_lines(text, start, end))
    first = opening_fence(lines[0][0]) if lines else None
    if not first or len(lines) < 3 or not fence_end(first[1]).fullmatch(lines[-1][0]):
        return None
    if lines[0][0][first.end(1):].strip().casefold() not in _FENCE_LANG:
        return ()
    prompts = [(number, match) for number, (line, _, _) in enumerate(lines[1:-1], 1)
               if (match := _PROMPT.fullmatch(line))]
    records = []
    for index, (line_number, match) in enumerate(prompts):
        limit = prompts[index + 1][0] if index + 1 < len(prompts) else len(lines) - 1
        command = (match['command'] or '').strip()
        if not command:
            continue
        row = lines[line_number]
        output_start, output_end = row[2], lines[limit][1]
        answer = text[output_start:output_end]
        read = _READ.match(command)
        measuring = _MEASURE.match(command)
        if (read or measuring) and answer.strip() and not _REJECTED.search(answer):
            kind = 'configuration_read' if _CONFIG_READ.match(command) else 'measurement' if measuring else 'observation'
        else:
            kind = 'command'
        records.append(CommandRecord((match['angle'] or match['bracket'] or match['host']).casefold(), command,
                                     (row[1], row[2]), (output_start, output_end) if answer.strip() else None, kind))
    return tuple(records)


def reading_units(text: str) -> tuple[ReadingUnit, ...]:
    """Index one page without interpreting fields or connecting its separate cases.

    Linked text must be adjacent, with an explicit reference to an exhibit.
    Callers still need to verify subject, fields, and experiment membership.
    """
    spans = list(blocks(text))
    result = []
    for index, (kind, start, end) in enumerate(spans):
        if kind == 'paragraph' and _LIST_LINE.match(text[start:end]):
            kind = 'list'
        if kind not in {'fence', 'table'}:
            result.append(ReadingUnit(kind, start, end))
            continue
        commands = _command_records(text, start, end) if kind == 'fence' else ()
        if commands is None:
            continue
        header, rows = _table_layout(text, start, end) if kind == 'table' else (None, ())
        caption = explanation = None
        if index:
            previous_kind, a, b = spans[index - 1]
            previous = text[a:b].strip()
            if (previous_kind == 'paragraph' and not text[b:start].strip() and len(previous) <= 320
                    and _CAPTION.search(previous) and not _SCOPE_BREAK.search(previous)):
                caption = (a, b)
        if index + 1 < len(spans):
            following_kind, a, b = spans[index + 1]
            following = text[a:b].strip()
            if (following_kind == 'paragraph' and not text[end:a].strip() and len(following) <= 480
                    and _EXPLANATION.match(following) and not _SCOPE_BREAK.search(following)):
                explanation = (a, b)
        result.append(ReadingUnit(kind, start, end, header, rows, commands, caption, explanation))
    return tuple(result)
