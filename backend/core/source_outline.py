"""Recover the original numbered section hierarchy from a reviewed reader outline."""

import re
from collections.abc import Iterable, Mapping
from typing import Any


Heading = tuple[int, str, int]

_SECTION_NUMBER = re.compile(r"^(?P<number>\d{1,3}(?:[.．]\d{1,3})+|\d{1,2})[.．、]?\s+(?P<title>\S.+)$")
_PDF_PAGE = re.compile(r"^PDF\s*第\s*\d+\s*页", re.I)
_STEP = re.compile(r"^(?:任务\s*)?(?:步骤|阶段)\s*[一二三四五六七八九十0-9]+(?:[\s.、：:\-]+|$)")
_INLINE_STEP = re.compile(r"\*\*((?:任务\s*)?(?:步骤|阶段)\s*[一二三四五六七八九十0-9]+(?:[^*\n]{0,70})?)\*\*")
_GUIDE = re.compile(r"^(?:读(?:本|全文)导览|阅读导览|章节目录|原页查阅|资料信息)")


def _number(title: str) -> tuple[int, ...]:
    match = _SECTION_NUMBER.match(title)
    return tuple(int(value) for value in match['number'].replace('．', '.').split('.')) if match else ()


def authored_step_title(paragraph: str) -> str:
    """Read an explicit source step with an inline bold title at the paragraph start."""
    paragraph = paragraph.lstrip()
    entries = tuple(_INLINE_STEP.finditer(paragraph))
    if len(entries) != 1 or entries[0].start():
        return ''
    title = entries[0][1].rstrip('。．.:： ').strip()
    return title if _STEP.match(title) else ''


def append_heading(path: Iterable[Heading], level: int, title: str, line: int) -> list[Heading]:
    """Advance the in-force headings using the exact title and source line."""
    path = list(path)
    if _PDF_PAGE.match(title):
        return path
    number = _number(title)
    current = (level, title, line)
    if number:
        ancestors = []
        for entry in path:
            earlier = _number(entry[1])
            if earlier == number and ' '.join(entry[1].split()) == ' '.join(title.split()):
                # Repeated running headings do not start another case.
                current = entry
            elif (earlier and len(earlier) < len(number) and number[:len(earlier)] == earlier
                  or not earlier and entry[0] < level and not _GUIDE.search(entry[1])):
                ancestors.append(entry)
    elif _STEP.match(title):
        # Step ordinals are relative to the enclosing numbered section.
        ancestors = [entry for entry in path if (entry[0] < level or _number(entry[1]))
                     and not _GUIDE.search(entry[1])]
    else:
        ancestors = [entry for entry in path if entry[0] < level or level >= 4 and _number(entry[1])]
    return [*ancestors, current]


def heading_paths(sections: Iterable[Mapping[str, Any]], parents: tuple[Heading, ...] = ()) -> dict[str, tuple[Heading, ...]]:
    """Recover numbered ancestry even when all original headings use level four.

    A physical page marker snapshots scope and never creates an experiment.
    """
    path = list(parents)
    result = {}
    for section in sections:
        path = append_heading(path, section['level'], section['title'], section['line'])
        result[section['id']] = tuple(path)
    return result
