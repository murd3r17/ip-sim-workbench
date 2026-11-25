"""Discover original physical pages inside already verified textbook documents."""

from collections import Counter, defaultdict
from math import log
from operator import itemgetter

from .edition import _source_excerpt
from .local_provider import _network_labels, _query_tokens
from .query_focus import protocol_names
from .source_claims import observed_prose_witness


def _section_index(pages, headings, lines, *, case_scope, iter_units):
    sections = defaultdict(list)
    page_scopes = defaultdict(set)
    for physical, (section, body) in pages.items():
        for kind, text, path, _ in iter_units(body, headings.get(section, ()), lines[section]):
            if not 18 <= len(text) <= 2450:
                continue
            scope = case_scope(path)
            if scope is None:
                continue
            page_scopes[physical].add(scope)
            sections[scope].append((physical, kind, text, path, set(_query_tokens(text)),
                                    set(_network_labels(text)), protocol_names(text)))
    sections_per_word = Counter(word for rows in sections.values() for word in set().union(*(row[4] for row in rows)))
    weights = {word: log((len(sections) + 1) / (count + 0.5)) for word, count in sections_per_word.items()}
    return sections, page_scopes, weights


def _matching_pages(sections, weights, facets, existing_scopes, protocols, labels):
    terms = [(facet, set(_query_tokens(facet.text))) for facet in facets]
    scored_sections = []
    for scope, units in sections.items():
        grades = [0.0] * len(terms)
        per_page = defaultdict(dict)
        excerpts = {}
        for page, kind, text, path, words, unit_labels, unit_protocols in units:
            if protocols and unit_protocols and protocols.isdisjoint(unit_protocols):
                continue
            for i, (facet, cues) in enumerate(terms):
                shared = words & cues
                if len(shared) < 2:
                    continue
                points = sum(weights[word] for word in sorted(shared)) + 2 * len(labels & unit_labels)
                if kind == 'paragraph' and observed_prose_witness(facet, text, path):
                    points += 2.5
                if points > per_page[page].get(i, 0):
                    per_page[page][i] = points
                if page not in excerpts or points > excerpts[page][0]:
                    excerpts[page] = points, text
                grades[i] = max(grades[i], points)
        if per_page:
            section_grade = sum(bool(value) for value in grades), sum(grades) + (scope in existing_scopes)
            scored_sections.append((section_grade, per_page, excerpts))
    for score, per_page, excerpts in sorted(scored_sections, key=itemgetter(0), reverse=True)[:2]:
        for physical, grades in per_page.items():
            yield (len(grades), sum(grades.values()), score[1]), physical, excerpts[physical][1]


def section_discovery_hits(edition, plan, initial_hits, documents, *, iter_units, scope_for, limit=8):
    """Offer page discovery candidates to the existing same-edition qualifier.

    Scores combine facet coverage and terms distinctive within a document. They
    locate pages only. Exact experiment, phase and factual scope remain the
    responsibility of the regular passage qualifier.
    """
    if limit <= 0 or not plan.facets or not plan.same_experiment:
        return []
    seeds = defaultdict(list)
    occupied = set()
    for hit in initial_hits:
        document_id, version = hit.get('document_id'), hit.get('document_version')
        physical = hit.get('page')
        if hit.get('edition_version') != edition.version or type(physical) is not int:
            continue
        key = document_id, version
        loaded = documents.get(key)
        if loaded is None:
            continue
        pages, _, _ = loaded
        mapped = pages.get(physical)
        if (mapped and hit.get('section_id') == mapped[0] and _source_excerpt(hit.get('text', ''), mapped[1])):
            occupied.add((key, physical))
            seeds[key].append(hit)
        if len(seeds) >= 4 and len(occupied) >= 6:
            break
    protocols = set().union(*(protocol_names(facet.text) for facet in plan.facets))
    labels = set().union(*(set(_network_labels(facet.text)) for facet in plan.facets))
    proposals = []
    for rank, (key, hits) in enumerate(seeds.items()):
        if rank == 4:
            break
        source = edition.documents.get(key[0])
        pages, headings, lines = documents[key]
        if not source or source.get('sha256') != key[1] or not source.get('ingest') or not 1 <= len(pages) <= 420:
            continue
        sections, page_scopes, weights = _section_index(pages, headings, lines,
                                                        case_scope=lambda path: scope_for(hits[0], path),
                                                        iter_units=iter_units)
        existing = {scope for hit in hits for scope in page_scopes[hit['page']]}
        for score, physical, text in _matching_pages(sections, weights, plan.facets, existing, protocols, labels):
            if (key, physical) not in occupied:
                proposals.append(((*score, -rank), key, physical, text))
    result = []
    for _, key, physical, text in sorted(proposals, key=itemgetter(0), reverse=True):
        if (key, physical) in occupied:
            continue
        section, original = documents[key][0][physical]
        if _source_excerpt(text, original):
            result.append(edition._bound_hit({'retriever': 'edition_section_discovery', 'score': 0}, edition.documents[key[0]],
                                             text, section, physical))
            occupied.add((key, physical))
        if len(result) == limit:
            break
    return result
