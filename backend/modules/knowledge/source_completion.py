"""Find additional original passages inside an already located textbook section."""

import re

from core.source_outline import append_heading
from core.source_units import reading_units

from .edition import _source_excerpt
from .local_provider import _network_labels, _query_tokens
from .query_focus import protocol_names


_NUMBERED_SECTION = re.compile(r'^(\d+(?:\.\d+){1,3})\s+(\S.*)$')
_GENERIC_TITLE = re.compile(r'^(?:实验|任务|结果|验证|配置|操作|业务|场景|组网)?'
                            r'(?:介绍|概览|背景|目的|步骤|思路|方法|结果|验证|参考|目标|要求|准备|小结)$')
_NAMED_SCOPE = re.compile(r'^(?:实验|案例|场景|分支|方案)\s*(?:[0-9一二三四A-D]+|[:：])\s*\S', re.I)
_HEADING = re.compile(r'^(#{1,6})\s+(.+?)\s*#*\s*$')


def _section_lines(headings):
    scopes = set()
    for _, title, line in headings:
        number = _NUMBERED_SECTION.fullmatch(title)
        if _NAMED_SCOPE.match(title) or number and not _GENERIC_TITLE.fullmatch(number[2]):
            scopes.add(line)
    return scopes


def _page_units(text, headings, line):
    for unit in reading_units(text):
        part = text[unit.start:unit.end].strip()
        if unit.kind == 'heading':
            if match := _HEADING.fullmatch(part):
                headings = append_heading(headings, len(match[1]), match[2], line + text.count('\n', 0, unit.start))
            continue
        yield part, _section_lines(headings)


def additional_document_hits(edition, plan, initial_hits, documents, *, limit=8):
    """Offer nearby exact source excerpts to the regular evidence qualifier.

    An existing, same-edition hit must locate a numbered or named section.
    A neighboring page has to contain a matching section unit and question
    terms. A candidate is only an input to evidence verification.
    """
    if limit <= 0 or not plan.same_experiment or len(plan.facets) < 2:
        return []
    terms = [set(_query_tokens(facet.text)) for facet in plan.facets]
    labels = set().union(*(set(_network_labels(facet.text)) for facet in plan.facets))
    protocols = set().union(*(protocol_names(facet.text) for facet in plan.facets))
    occupied = {(row.get('book'), row.get('page')) for row in initial_hits}
    proposed = {}
    for rank, seed in enumerate(initial_hits[:6]):
        document_id, version, physical = seed.get('document_id'), seed.get('document_version'), seed.get('page')
        document = edition.documents.get(document_id)
        joined = documents.get((document_id, version))
        if (not document or document['sha256'] != version or not document.get('ingest') or not joined
                or seed.get('edition_version') != edition.version or type(physical) is not int):
            continue
        pages, paths, lines = joined
        origin = pages.get(physical)
        if not origin or seed.get('section_id') != origin[0] or not _source_excerpt(seed.get('text', ''), origin[1]):
            continue
        origin_scopes = set().union(*(scope for part, scope in _page_units(origin[1], paths[origin[0]], lines[origin[0]])
                                    if _source_excerpt(seed['text'], part)))
        # Multi-block discovery excerpts may not sit inside a single unit. Use
        # the inherited original outline only when it identifies one section.
        if not origin_scopes:
            origin_scopes = _section_lines(paths[origin[0]])
        if not origin_scopes:
            continue
        for distance in (-2, -1, 1, 2):
            page = physical + distance
            key = document['book'], page
            candidate = pages.get(page)
            if not candidate or key in occupied:
                continue
            section, source = candidate
            for part, scopes in _page_units(source, paths[section], lines[section]):
                if not scopes & origin_scopes or not 20 <= len(part) <= 2450:
                    continue
                matched_labels = set(_network_labels(part)) & labels
                material_protocols = protocol_names(part)
                if (labels and not matched_labels or protocols and material_protocols
                        and protocols.isdisjoint(material_protocols)):
                    continue
                words = set(_query_tokens(part))
                overlap = max((len(words & facet_terms) for facet_terms in terms), default=0)
                if overlap < 2:
                    continue
                grade = (len(matched_labels), len(protocols & material_protocols), overlap, -abs(distance), -rank)
                if key not in proposed or proposed[key][0] < grade:
                    row = edition._bound_hit({'retriever': 'edition_section_candidate', 'score': seed.get('score', 0)},
                                             document, part, section, page)
                    proposed[key] = grade, row
    return [hit for _, hit in sorted(proposed.values(), key=lambda item: item[0], reverse=True)[:limit]]
