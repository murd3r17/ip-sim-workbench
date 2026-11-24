"""Reopen bounded textbook sources for explicit continuation within an owned conversation."""
from dataclasses import dataclass
import asyncio
import re

from modules.knowledge.query_focus import lookup_parts, protocol_names

from .context_bundle import cited_indices
from .question_intent import new_device_read_scope, plain_question
from .trusted_context import exclude_previous_config_comparison


_SAME_SOURCE = re.compile(
    r'(?:刚才|前面|上一(?:轮|条|次|个回答)|原来|先前|此前).{0,14}(?:教材|课本|原页|同一页|同一章|引用|出处|来源|那[一张幅页条份本]图)|'
    r'(?:继续|仍然|还是|沿用|接着|仍).{0,14}(?:刚才|前面|上次|上一(?:轮|页|条)|同一(?:页|章|张图|本书|本教材)|原(?:来的)?(?:教材|引用|出处|图|页))|'
    r'同一(?:页|章|张图|条引用|个出处|本书|本教材).{0,16}(?:继续|再问|还想|接着|沿用)')
_CHANGE_SOURCE = re.compile(
    r'换(?:个|一)?(?:题|话题|协议)|另一个问题|另问|新问题|改问|重新选(?:了)?|'
    r'(?:换(?:到|成|了)|改(?:看|读|用|成)|(?:现在|这次|本次|我)(?:选|看|读)的是|刚打开了另一个|不再(?:用|看))'
    r'[^，。！？；\n]{0,25}(?:教材|课本|那页|原页|章节|来源|图)|'
    r'另(?:一(?:份|本|章|页|张图)|外选了)|不沿用|清除(?:旧|上次|刚才的)?(?:引用|出处|资料)')


def cited_locators(response: dict) -> list[dict]:
    """Persist locator metadata of actually used citations, never earlier prose."""
    used = set(cited_indices(response.get('answer') or ''))
    locators = []
    for index, source in enumerate(response.get('sources') or [], 1):
        if not isinstance(source, dict) or source.get('reference_index', index) not in used:
            continue
        candidate = {key: source.get(key) for key in
                     ('source_id', 'document_id', 'document_version', 'edition_version', 'page')}
        if (type(candidate['page']) is int and candidate['page'] > 0
                and all(isinstance(candidate[k], str) and 0 < len(candidate[k]) <= 256 for k in candidate if k != 'page')
                and candidate not in locators):
            locators.append(candidate)
    return locators


def refers_to_previous_source(message: str) -> bool:
    return bool(_SAME_SOURCE.search(plain_question(message)))


def wants_same_source(data) -> bool:
    context = data.context
    if (not context or (context.page_record and context.page_record.kind != 'original_page')
            or context.config_comparison or data.want_draft):
        return False
    if context.knowledge_source and context.knowledge_source.mode == 'cleared':
        return False
    question = plain_question(data.message)
    titles, _, pages, _ = lookup_parts(question)
    if (titles or pages or _CHANGE_SOURCE.search(question) or new_device_read_scope(question)
            or exclude_previous_config_comparison(question)):
        return False
    return refers_to_previous_source(question)


@dataclass(frozen=True)
class SourceContinuity:
    status: str
    hits: list[dict]


def _identity(source: dict) -> tuple:
    return source['document_id'], source['document_version'], source['edition_version']


def _cited_pages(edition, document_id: str, document_version: str) -> dict:
    from modules.knowledge.edition import _page_texts

    # ReadingEdition verifies the document hash and page map before it exposes
    # only admitted evidence pages. Historical/archive-only text is not reused.
    body = edition.read(document_id, document_version, include_original_status=False)
    return _page_texts(body)


async def continue_sources(prior, data, service_factory, query: str) -> SourceContinuity:
    from modules.knowledge.reader import DocumentReadError

    unavailable = SourceContinuity('unavailable', [])
    independent = SourceContinuity('independent', [])
    current_page = data.context.page_record
    if prior is None:
        return independent if current_page else unavailable
    prior_id, saved = prior
    source = data.context.knowledge_source
    locators = saved.get('sources') or []
    if source:
        if source.request_id != prior_id:
            return independent if current_page else unavailable
        locators = [item for item in locators if item['source_id'] == source.source_id]
    if current_page:
        locators = [item for item in locators if (item['document_id'], item['document_version'], item['page'])
                    == (current_page.document_id, current_page.version, current_page.page)]
        if not locators:
            return independent
    if not locators or len({_identity(item) for item in locators}) != 1:
        return unavailable
    if source and len({item['page'] for item in locators}) != 1:
        return unavailable
    topics = set(protocol_names(data.message))
    if topics and not topics.issubset(saved.get('subjects') or []):
        return independent
    service = service_factory()
    edition = service.edition()
    if edition is None:
        return unavailable
    if edition.has_search_scope(data.message):
        return independent
    doc_id, version, edition_version = _identity(locators[0])
    document = edition.documents.get(doc_id)
    if (edition.version != edition_version or not document or not document.get('ingest')
            or document['sha256'] != version):
        return unavailable
    try:
        pages = await asyncio.to_thread(_cited_pages, edition, doc_id, version)
    except (DocumentReadError, OSError, ValueError, KeyError):
        return unavailable
    cited = list(dict.fromkeys(item['page'] for item in locators))
    if not all(page in pages for page in cited):
        return unavailable
    if len(cited) == 1:
        page = cited[0]
        section, excerpt = pages[page]
        hit = edition._bound_hit({'retriever': 'edition_continued_page'}, document, excerpt.strip(), section, page)
        return SourceContinuity('page', [hit])

    # Multiple citations qualify only within a single current document. Query
    # the local index under that document constraint and keep the prior cited
    # pages as bounded recap candidates when anaphora has little textual overlap.
    keyword = edition.keyword_index
    available, candidates = await keyword.search_pages(query, max(data.top_k * 3, 12), document_ids={doc_id})
    hits = await asyncio.to_thread(edition.resolve_hits, candidates, keyword, None, query=query) if available else []
    hits = [hit for hit in hits if hit.get('document_id') == doc_id and hit.get('document_version') == version
            and hit.get('page') in pages and hit.get('edition_version') == edition_version]
    seen = {hit['page'] for hit in hits}
    for page in cited:
        if page not in seen:
            section, excerpt = pages[page]
            hits.append(edition._bound_hit({'retriever': 'edition_continued_chapter'}, document, excerpt.strip(), section, page))
    return SourceContinuity('chapter', hits[:data.top_k])
