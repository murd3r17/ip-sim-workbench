"""Conservative Markdown boundaries shared by retrieval and prompt budgets.

Not a renderer. Paragraphs, fenced commands and tables are indivisible when
clipping excerpts, so a budget cannot silently remove a sentence's qualifier.
"""
import re
from collections.abc import Iterator

HEADING = re.compile(r"^(#{1,6})\s+\S")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_CAPTION_FENCE = re.compile(r"^ {0,3}\*\*[^*\r\n]+\*\*[ \t]*(`{3,})(?:cli|text)[ \t]*$")
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*\|[\s|:\-]*$")


def opening_fence(line: str):
    """Recognize a normal fence or an imported CLI block attached to its bold caption."""
    return FENCE.match(line) or _CAPTION_FENCE.match(line.rstrip('\r\n'))


def fence_end(marker: str):
    return re.compile(r'^ {0,3}' + re.escape(marker[0]) + '{' + str(len(marker)) + r',}\s*$')


def blocks(text: str) -> Iterator[tuple[str, int, int]]:
    """Yield (kind, start, end) spans into the unmodified input string."""
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    def is_table(i):
        return i + 1 < len(lines) and '|' in lines[i] and TABLE_RULE.match(lines[i + 1])

    i = 0
    while i < len(lines):
        start = i
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        fence = opening_fence(line)
        if fence:
            start_offset = offsets[start] + fence.start(1)
            if not FENCE.match(line):
                yield 'paragraph', offsets[start], start_offset
            else:
                start_offset = offsets[start]
            closing = fence_end(fence[1])
            i += 1
            while i < len(lines):
                end = bool(closing.match(lines[i]))
                i += 1
                if end:
                    break
            yield 'fence', start_offset, offsets[i]
            continue
        elif HEADING.match(line):
            i += 1
            kind = 'heading'
        elif is_table(i):
            i += 2
            while i < len(lines) and lines[i].strip() and '|' in lines[i]:
                i += 1
            kind = 'table'
        else:
            i += 1
            while i < len(lines) and lines[i].strip() and not HEADING.match(lines[i]) and not opening_fence(lines[i]) and not is_table(i):
                i += 1
            kind = 'paragraph'
        yield kind, offsets[start], offsets[i]


def unclosed_fence_start(text: str) -> int | None:
    """Return the start of a fenced block whose closing marker is missing."""
    for kind, start, end in blocks(text):
        if kind != "fence":
            continue
        lines = text[start:end].splitlines()
        marker = FENCE.match(lines[0])[1]
        if len(lines) == 1 or not fence_end(marker).fullmatch(lines[-1]):
            return start
    return None


def complete_prefix(text: str, limit: int) -> str:
    """A contiguous source prefix ending at a complete substantive block.

    An oversized first block is omitted, not cut. Returning only its heading
    would advertise a source without any supporting body, so return empty.
    """
    if len(text) <= limit:
        return text
    end = 0
    for kind, _start, stop in blocks(text):
        trimmed_stop = stop
        while trimmed_stop and text[trimmed_stop - 1].isspace():
            trimmed_stop -= 1
        if trimmed_stop > limit:
            break
        if kind != 'heading':
            end = stop
    return text[:end].rstrip()


def retrieval_body(text: str) -> str:
    """Ancestor titles provide reading context, not repeated keyword matches."""
    headings = []
    for kind, start, _end in blocks(text):
        if kind != 'heading':
            break
        headings.append(start)
    return text[headings[-1]:] if len(headings) > 1 else text


def split_markdown(text: str, max_chars: int = 900) -> list[str]:
    """Pack source blocks with ancestor headings; max_chars is a soft target.

    Only oversized tables split, on whole rows with their original column
    headers. Long paragraphs and CLI blocks stay intact until the prompt layer
    decides whether they fit; this layer must never invent a shorter assertion.
    """
    chunks, ancestors, pending = [], [], []
    heading_emitted = False

    def emit():
        nonlocal heading_emitted
        if pending:
            chunks.append('\n\n'.join([*(h[1] for h in ancestors), *pending]).strip())
            pending.clear()
            heading_emitted = True

    def append(block):
        size = sum(len(p) + 2 for p in pending) + sum(len(h[1]) + 2 for h in ancestors)
        if pending and size + len(block) > max_chars:
            emit()
        pending.append(block)

    for kind, start, end in blocks(text):
        block = text[start:end].rstrip()
        if kind == 'heading':
            emit()
            level = len(HEADING.match(block)[1])
            if ancestors and not heading_emitted and level <= ancestors[-1][0]:
                chunks.append('\n\n'.join(h[1] for h in ancestors))
            ancestors[:] = [h for h in ancestors if h[0] < level]
            ancestors.append((level, block))
            heading_emitted = False
        elif kind == 'table' and len(block) > 2 * max_chars:
            emit()
            lines = block.splitlines()
            header, segment = lines[:2], lines[:2]
            for row in lines[2:]:
                if len(segment) > 2 and sum(len(s) + 1 for s in segment) + len(row) > max_chars:
                    append('\n'.join(segment))
                    emit()
                    segment = list(header)
                segment.append(row)
            append('\n'.join(segment))
        else:
            append(block)
    emit()
    if ancestors and not heading_emitted:
        chunks.append('\n\n'.join(h[1] for h in ancestors))
    return [chunk for chunk in chunks if chunk.strip()]
