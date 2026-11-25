"""Find original textbook scopes by the joint coverage of a natural question."""

from array import array
from collections import Counter, defaultdict
from dataclasses import dataclass
from math import log
import re
from threading import Lock

from .edition import _page_texts, _source_excerpt
from .local_provider import _query_tokens
from .query_focus import passage_query, protocol_names
from .reader import DocumentReadError


_MATERIAL = {
    'observation': re.compile(r'回显|读回|显示|输出|看到|读到|报文|记录|观察|实测|抓包|路由表|验证结果'),
    'illustration': re.compile(r'图中|图表|表[中内]|图片|绘制|图示|拓扑|箭头|图例|表格|画'),
    'relation': re.compile(r'发出|发给|发送|收到|接收|响应|返回|由.{0,12}(?:产生|发)|角色|对应|用来|用于|决定|因为'),
    'change': re.compile(r'变化|之前|之后|前后|调整|恢复|改成|改为|保留|变为|阶段|重新|增加|减少'),
}
_OBSERVATION_REQUIREMENTS = frozenset({'observation', 'change'})
_PLANNED = re.compile(r'^\s*\**(?:计划|预期|仿真设计|配置任务|练习目标|目录|阅读导览|原页查阅)')


def _roles(text):
    return frozenset(role for role, pattern in _MATERIAL.items() if pattern.search(text))


@dataclass(frozen=True, slots=True)
class _Passage:
    document: str
    version: str
    page: int
    section: str
    text: str
    scope: str
    scope_title: str
    original_experiment: bool
    phase: str
    phase_title: str
    roles: frozenset[str]
    subjects: frozenset[str]
    planned: bool


@dataclass(frozen=True, slots=True)
class ScopeMatch:
    scope: str
    original_experiment: bool
    coverage: int
    weight: float
    overlap: int
    passages: tuple[tuple[int, tuple[int, ...]], ...]


class OriginalScopeIndex:
    def __init__(self, edition):
        self.edition = edition
        self._lock = Lock()
        self._snapshot = None

    def _load(self):
        with self._lock:
            if self._snapshot is not None:
                return self._snapshot
            from .ranked_evidence import _case_root_lines, _heading_paths, _source_metadata, _units

            records = []
            postings = defaultdict(lambda: array('I'))
            scope_terms = defaultdict(set)
            phase_pages = defaultdict(list)
            headings_cache = {}
            for identifier, doc in self.edition.documents.items():
                if not doc.get('ingest'):
                    continue
                key = {'document_id': identifier, 'document_version': doc['sha256']}
                try:
                    reading = self.edition.read(identifier, doc['sha256'], include_original_status=False)
                    pages = _page_texts(reading)
                    headings = _heading_paths(reading)
                    lines = {section['id']: section['line'] for section in reading['sections']}
                    case_roots = _case_root_lines(reading)
                except (DocumentReadError, OSError, KeyError, ValueError):
                    continue
                for physical, (section, body) in pages.items():
                    if not body.strip():
                        continue
                    for _, excerpt, path, core in _units(body, headings.get(section, ()), lines[section]):
                        if core or not 8 <= len(excerpt) <= 2450:
                            continue
                        words = set(_query_tokens(excerpt))
                        if len(words) < 2 or not path:
                            continue
                        cached = headings_cache.get((identifier, path))
                        if cached is None:
                            metadata = _source_metadata(key, path, case_roots)
                            experiment = metadata.get('source_experiment_key')
                            scope = experiment or metadata['source_heading_key']
                            phase = metadata.get('source_phase_key') or metadata.get('source_step_boundary_key', '')
                            titles = {str(row[2]): row[1] for row in path}
                            heading = '\n'.join(row[1] for row in path)
                            cached = (scope, titles[scope.rsplit(':', 1)[-1]], bool(experiment), phase,
                                      titles.get(phase.rsplit(':', 1)[-1], ''),
                                      frozenset(_query_tokens(heading)),
                                      frozenset(protocol_names(heading)))
                            headings_cache[identifier, path] = cached
                        scope, scope_title, is_experiment, phase, phase_title, heading_words, heading_protocols = cached
                        row = _Passage(identifier, doc['sha256'], physical, section, excerpt, scope, scope_title, is_experiment,
                                       phase, phase_title,
                                       _roles(excerpt), heading_protocols | protocol_names(excerpt), bool(_PLANNED.match(excerpt)))
                        scope_terms[scope].update(words, heading_words)
                        for word in words:
                            postings[word].append(len(records))
                        if is_experiment and phase:
                            phase_pages[(scope, phase, physical)].append(len(records))
                        records.append(row)
            frequency = Counter(token for terms in scope_terms.values() for token in terms)
            weights = {token: log((len(scope_terms) + 1) / (seen + 1)) for token, seen in frequency.items()}
            self._snapshot = tuple(records), dict(postings), weights, dict(phase_pages)
            return self._snapshot

    def rank(self, clauses, *, subjects=frozenset()):
        """Rank by independently matching each clause within the original scope."""
        prepared = [(index, set(_query_tokens(passage_query(text))), _roles(text)) for index, text in clauses]
        prepared = [(index, words, roles) for index, words, roles in prepared if len(words) >= 2]
        if not prepared or not any(roles for _, _, roles in prepared):
            return (), 0
        records, postings, weights, _ = self._load()
        per_scope = defaultdict(dict)
        for index, words, expected in prepared:
            overlap = defaultdict(list)
            for term in sorted(words):
                for unit in postings.get(term, ()):
                    overlap[unit].append(term)
            for unit, common in overlap.items():
                if len(common) < 2:
                    continue
                item = records[unit]
                if ((subjects and item.subjects and subjects.isdisjoint(item.subjects))
                        or expected and expected.isdisjoint(item.roles)
                        or item.planned and expected & _OBSERVATION_REQUIREMENTS):
                    continue
                evidence = (sum(weights[term] for term in common) / max(2, len(words)), len(common))
                values = per_scope[item.scope]
                previous = values.get(index)
                if previous is None or previous[0] < evidence:
                    values[index] = evidence, [unit]
                elif previous[0] == evidence:
                    previous[1].append(unit)
        matches = []
        for scope, values in per_scope.items():
            positions = tuple((index, tuple(unit_ids)) for index, (_, unit_ids) in values.items())
            first = records[positions[0][1][0]]
            matches.append(ScopeMatch(scope, first.original_experiment, len(values),
                                      sum(score[0] for score, _ in values.values()),
                                      sum(score[1] for score, _ in values.values()), positions))
        matches.sort(key=lambda row: (-row.coverage, -row.weight, -row.overlap, row.scope))
        return tuple(matches), len(prepared)

    def locate(self, matches, *, clauses=(), limit=8):
        """Reread exact candidate panes. Ranking is not proof or quote permission."""
        if limit <= 0:
            return []
        records, _, weights, phase_pages = self._load()
        words_by_clause = {index: set(_query_tokens(passage_query(text))) for index, text in clauses}
        documents = {}
        accepted = []
        visited = set()
        best_units = []
        neighbours = {}
        seen_for_clause = defaultdict(set)
        for match in matches:
            for clause, ids in match.passages:
                for unit_id in ids[:2]:
                    best_units.append(unit_id)
                    seen_for_clause[unit_id].add(clause)
                    anchor = records[unit_id]
                    if not anchor.phase or not (words := words_by_clause.get(clause)):
                        continue
                    for distance in (-2, -1, 1, 2):
                        group = anchor.scope, anchor.phase, anchor.page + distance
                        for candidate_id in phase_pages.get(group, ()):
                            candidate = records[candidate_id]
                            shared = words & set(_query_tokens(candidate.text))
                            if len(shared) >= 2 and not candidate.planned:
                                strength = sum(weights[word] for word in sorted(shared)), -abs(distance)
                                if group not in neighbours or strength > neighbours[group][0]:
                                    neighbours[group] = strength, candidate_id, clause
        more_units = []
        for _, unit_id, clause in sorted(neighbours.values(), reverse=True):
            more_units.append(unit_id)
            seen_for_clause[unit_id].add(clause)
        best_set = set(best_units)
        for unit_id in dict.fromkeys([*best_units, *more_units]):
            unit = records[unit_id]
            key = unit.document, unit.version
            if (key, unit.page) in visited:
                continue
            visited.add((key, unit.page))
            if key not in documents:
                try:
                    reading = self.edition.read(*key, include_original_status=False)
                    documents[key] = _page_texts(reading)
                except (DocumentReadError, OSError, KeyError, ValueError):
                    documents[key] = {}
            page = documents[key].get(unit.page)
            if not page or page[0] != unit.section or not _source_excerpt(unit.text, page[1]):
                continue
            document = self.edition.documents[unit.document]
            retriever = 'edition_original_scope' if unit_id in best_set else 'edition_original_phase_neighbor'
            candidate = {'retriever': retriever, 'score': 0, 'scope_candidate_key': unit.scope,
                         'scope_candidate_title': unit.scope_title[:100], 'scope_candidate_phase': unit.phase_title[:80],
                         'scope_candidate_clauses': tuple(sorted(seen_for_clause[unit_id]))}
            accepted.append(self.edition._bound_hit(candidate, document, unit.text, unit.section, unit.page))
            if len(accepted) == limit:
                break
        return accepted

    def discover(self, clauses, *, subjects, amount=8):
        matches, required = self.rank(clauses, subjects=subjects)
        if not matches or required < 2 or amount <= 0:
            return []
        leader = matches[0]
        competing = tuple(match for match in matches[:3] if match.coverage == required and match.weight >= .85 * leader.weight)
        return self.locate(competing or matches[:2], clauses=clauses, limit=amount)
