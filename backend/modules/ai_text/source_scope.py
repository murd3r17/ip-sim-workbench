"""Prepare Copilot evidence within a verified physical page or chapter boundary."""
from dataclasses import dataclass
import re

from core.markdown_blocks import blocks
from modules.knowledge.query_focus import _SOURCE_QUOTE, lookup_parts, separate_pdf_pages
from modules.knowledge.reviewed_source_notes import notes_for_excerpt

from .context_bundle import prepare_sources


_PHYSICAL_PAGE = re.compile(r'(?:PDF\s*(?:物理)?|物理)\s*第?\s*\d{1,5}', re.I)
_AMBIGUOUS_SCOPE = re.compile(r'印刷(?:第|页(?:码)?\s*\d)|纸本第|另一本|任一页|任选|页或|除了|'
                              r'(?:不要|不)(?:查|看|用|引用)(?:这|那|第|PDF)')
_PAGE_NAVIGATION_REQUEST = re.compile(r'(?:哪(?:一)?页|哪里|在哪|何处).{0,10}(?:另有|实例|示例|读回|可查)|'
                                      r'(?:后文|另页|后续|其它页|其他页|其他章节).{0,10}(?:见|查|出处|在哪)|'
                                      r'(?:引用|列出|找).{0,10}(?:指路|交叉引用|跨页引用|参见)')
_PAGE_LOCATOR = r'(?:PDF\s*)?(?:物理\s*)?第\s*(\d{1,5})(?:\s*页?\s*[–—~～至到-]\s*第?\s*(\d{1,5}))?\s*页'
_PAGE_REFERENCE = re.compile(_PAGE_LOCATOR, re.I)
_SEE_PAGE = re.compile(
    rf'(?:(?:详情|示例|图示|读回示例|读回实例)\s*[:,：，]?\s*)?'
    rf'(?:请)?(?:另参见|另见|参见|详见|见)\s*{_PAGE_LOCATOR}[。！？]', re.I,
)
_PAGE_WITH_EXAMPLE = re.compile(
    rf'{_PAGE_LOCATOR}(?:另有|有|列有|展示了?|提供了?|给出)'
    rf'[^\r\n，,；;。！？]{{1,125}}?(?:示例|实例|样例|示意图|例图)[。！？]', re.I,
)


@dataclass(frozen=True)
class PageScope:
    document_ids: frozenset[str]
    ranges: tuple[tuple[int, int], ...]
    requested: tuple[int, ...] = ()
    keep_pointers: bool = False

    def contains(self, first: int, last: int) -> bool:
        if self.requested:
            return 0 <= last - first < len(self.requested) and all(
                page in self.requested for page in range(first, last + 1))
        return any(low <= first <= last <= high for low, high in self.ranges)

    def keeps(self, hit: dict, edition) -> bool:
        document_id = hit.get('document_id')
        page = hit.get('page')
        return (document_id in self.document_ids and document_id in edition.documents
                and hit.get('edition_version') == edition.version
                and hit.get('document_version') == edition.documents[document_id]['sha256']
                and bool(hit.get('section_id')) and type(page) is int and self.contains(page, page))

    def missing_notice(self, sources: list[dict]) -> str:
        available = {source.get('page') for source in sources}
        missing = [str(page) for page in self.requested if page not in available]
        if missing:
            return f'未核对到所选同版 PDF 物理页（{"、".join(missing)}）可用于本题的片段。请在「原教材页位」核对该页。'
        return ''


def explicit_physical_scope(question: str) -> bool:
    outside = _SOURCE_QUOTE.sub(' ', question)
    return bool(_PHYSICAL_PAGE.search(outside) and not _AMBIGUOUS_SCOPE.search(outside))


def _page_scope(question, edition, hits, continuity) -> PageScope | None:
    if explicit_physical_scope(question):
        requested = ()
        if selected := separate_pdf_pages(question):
            requested, before, after = selected
            query = f'{before}PDF 第 {requested[0]} 页{after}'
            ranges = tuple((page, page) for page in requested)
        else:
            query = question
            _, _, pages, _ = lookup_parts(question)
            if not pages or not 0 < pages[0] <= pages[1] or len(_PAGE_REFERENCE.findall(_SOURCE_QUOTE.sub(' ', question))) > 1:
                # Two standalone page numbers without an unambiguous list do not
                # authorize assuming that the first page is the entire scope.
                return None
            ranges = (pages,)
            if pages[0] == pages[1]:
                requested = (pages[0],)
        _, _, doc_ids, _, phrases = edition.search_scope(query)
        if not doc_ids or len({edition.documents[doc_id]['book'] for doc_id in doc_ids}) != 1:
            return None
        return PageScope(frozenset(doc_ids), ranges, requested, bool(phrases or _PAGE_NAVIGATION_REQUEST.search(question)))
    if continuity not in {'page', 'chapter'} or not hits:
        return None
    # These hits were reopened from one server-owned, current, authorized
    # textbook reference. Client conversation history cannot provide this scope.
    document_id = hits[0].get('document_id')
    document = edition.documents.get(document_id)
    if not document:
        return None
    page = hits[0].get('page')
    ranges = ((page, page),) if continuity == 'page' and type(page) is int else ((document['page_start'], document['page_end']),)
    return PageScope(frozenset({document_id}), ranges, keep_pointers=bool(_PAGE_NAVIGATION_REQUEST.search(question)))


def _remove_outside_pointers(text: str, scope: PageScope) -> str:
    """Drop whole editorial directions. Leave source claims and Markdown blocks intact."""
    kept = []
    end = 0
    for kind, start, stop in blocks(text):
        kept.append(text[end:start])
        block = text[start:stop]
        if kind == 'paragraph':
            sentences = []
            for sentence in re.split(r'(?<=[。！？])', block):
                line = sentence.strip()
                match = _SEE_PAGE.fullmatch(line) or _PAGE_WITH_EXAMPLE.fullmatch(line)
                if match:
                    first, last = match.groups()
                    if not scope.contains(int(first), int(last or first)):
                        continue
                sentences.append(sentence)
            block = ''.join(sentences)
        kept.append(block)
        end = stop
    return ''.join(kept) + text[end:]


def _scoped_hit(hit: dict, scope: PageScope) -> dict:
    if scope.keep_pointers:
        return hit
    text = hit.get('text') or hit.get('content') or ''
    bounded = _remove_outside_pointers(text, scope)
    if bounded == text:
        return hit
    filename = hit.get('filename') or hit.get('title')
    version = hit.get('document_version')
    if notes_for_excerpt(filename, text, version) != notes_for_excerpt(filename, bounded, version):
        return hit
    if not any(kind != 'heading' for kind, _, _ in blocks(bounded)):
        return {**hit, 'text': '', 'content': ''}
    return {**hit, 'text': bounded, 'source_range_reduced': True}


def missing_physical_page_notice(question: str, sources: list[dict], edition) -> str:
    scope = _page_scope(question, edition, [], '') if edition else None
    return scope.missing_notice(sources) if scope else ''


def prepare_scoped_sources(question: str, hits: list[dict], limit: int, edition, continuity: str,
                           *, keep_page_pointers: bool = False) -> tuple[list[dict], str]:
    scope = _page_scope(question, edition, hits, continuity) if edition else None
    if scope is None:
        if explicit_physical_scope(question):
            return [], '未能核定这次指定的教材和 PDF 物理页。请提供教材全名及物理页码，或从知识库打开对应页面。'
        if continuity in {'page', 'chapter'}:
            return [], '未能回读指定的同版教材。请从知识库重新打开对应页面。'
        return prepare_sources(hits[:limit]), ''
    selected = [hit if keep_page_pointers else _scoped_hit(hit, scope) for hit in hits if scope.keeps(hit, edition)]
    sources = prepare_sources(selected, max_documents=limit)
    return sources, scope.missing_notice(sources)
