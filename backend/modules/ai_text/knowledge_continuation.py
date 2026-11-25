"""Reopen bounded textbook sources for explicit continuation within an owned conversation."""
from dataclasses import dataclass
import asyncio
import re

from modules.knowledge.query_focus import lookup_parts, protocol_names

from .context_bundle import cited_indices
from .question_intent import guided_page_question, new_device_read_scope, plain_question
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
_OPENED_READING = re.compile(
    r'(?:我(?:刚才|刚|已|已经)?(?:在[^。！？；，\n]{0,18})?|从(?:教材|资料)?目录)'
    r'(?:打开|点开|选中|选了|查阅)(?:了)?(?P<location>[^。！？；，\n]+)')
_CURRENT_READING_PAGE = re.compile(
    r'本页|当前(?:教材|正文|整理稿)?页|(?:这|刚打开的那)(?:一)?页|(?:这|当前)(?:一)?份整理稿')
_READING_FOLLOWUP = re.compile(r'(?:这个|此|本)(?:教材|课本|实验|例题|示例|案例|章节|表)|这(?:一)?步')


def cited_locators(response: dict) -> list[dict]:
    """Persist locator metadata of actually used citations, never earlier prose."""
    sources = response.get('sources') or []
    used = set(cited_indices(response.get('answer') or '', sources))
    locators = []
    for index, source in enumerate(sources, 1):
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


def wants_open_page(data) -> bool:
    context = data.context
    if (not context or not context.page_record
            or context.page_record.kind != 'original_page' or context.config_comparison
            or data.want_draft or data.attachments or data.attachment_message_id):
        return False
    question = plain_question(data.message)
    guided = guided_page_question(question)
    if guided:
        question = question[guided.end():].lstrip()
    if _CHANGE_SOURCE.search(question) or new_device_read_scope(question):
        return False
    if guided:
        titles, _, pages, _ = lookup_parts(question)
        return int(guided['page']) == context.page_record.page and not (titles or pages)
    if context.route != '/knowledge':
        return False
    titles, _, pages, _ = lookup_parts(question)
    if titles or pages:
        return False
    opened = _OPENED_READING.search(question)
    return bool(_CURRENT_READING_PAGE.search(question)
                or opened and _READING_FOLLOWUP.search(question[opened.end():]))


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


def _quote_excerpt(excerpt, phrases):
    from modules.knowledge.edition import literal_excerpt
    from modules.knowledge.query_focus import compact_text

    literals = tuple(filter(None, map(compact_text, phrases)))
    if not literals:
        return excerpt
    normalized = compact_text(excerpt)
    if not all(phrase in normalized for phrase in literals):
        return None
    return literal_excerpt(excerpt, literals) if len(literals) == 1 else excerpt


async def continue_open_page(data, service_factory) -> SourceContinuity:
    """Use the current authorized reading page when the learner refers to it."""
    from modules.knowledge.reader import DocumentReadError
    from modules.knowledge.query_focus import compact_text

    unavailable = SourceContinuity('unavailable', [])
    independent = SourceContinuity('independent', [])
    reference = data.context.page_record
    edition = service_factory().edition()
    if not edition:
        return unavailable
    question = plain_question(data.message)
    guided = guided_page_question(question)
    if guided:
        scope = question[:guided.end()]
        question = question[guided.end():].lstrip()
        _, chapters, documents, _, _ = edition.search_scope(scope)
        _, phrases, _, _ = lookup_parts(question)
    else:
        _, chapters, documents, _, phrases = edition.search_scope(question)
    document = edition.documents.get(reference.document_id)
    if guided and not document:
        return unavailable
    if (chapters and reference.document_id not in {entry['id'] for entry in chapters}
            or documents is not None and reference.document_id not in documents):
        return independent
    if not document or not document.get('ingest') or document['sha256'] != reference.version:
        return unavailable
    # A current page pointer cannot override a different specific book or
    # chapter named in the open action.
    if opened := _OPENED_READING.search(question):
        location = opened['location']
        catalog = getattr(edition, 'books', {})
        book = catalog.get(document['book'], {})
        names = [name for name in (document.get('title'), book.get('title'), book.get('filename')) if name]
        if not _CURRENT_READING_PAGE.search(location) and not any(
            compact_text(name) in compact_text(location) for name in names
        ):
            return independent
    try:
        pages = await asyncio.to_thread(_cited_pages, edition, reference.document_id, reference.version)
    except (DocumentReadError, OSError, ValueError, KeyError):
        return unavailable
    if reference.page not in pages:
        return unavailable
    section, excerpt = pages[reference.page]
    excerpt = _quote_excerpt(excerpt, phrases)
    if not excerpt:
        return SourceContinuity('missing_quote', [])
    hit = edition._bound_hit({'retriever': 'edition_open_page'}, document, excerpt.strip(), section, reference.page)
    return SourceContinuity('page', [hit])


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
    _, chapters, document_ids, physical_range, phrases = edition.search_scope(data.message)
    if chapters or document_ids is not None or physical_range:
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
        excerpt = _quote_excerpt(excerpt, phrases)
        if not excerpt:
            return SourceContinuity('missing_quote', [])
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
    if phrases:
        # Re-check the quoted words against the reader-visible page text.
        # Do not replace a missing phrase with recap passages or other books.
        verified = []
        for page in dict.fromkeys([*(hit['page'] for hit in hits), *cited]):
            section, excerpt = pages[page]
            if excerpt := _quote_excerpt(excerpt, phrases):
                verified.append(edition._bound_hit({'retriever': 'edition_continued_chapter'}, document,
                                                   excerpt.strip(), section, page))
        return SourceContinuity('chapter', verified[:data.top_k]) if verified else SourceContinuity('missing_quote', [])
    seen = {hit['page'] for hit in hits}
    for page in cited:
        if page not in seen:
            section, excerpt = pages[page]
            hits.append(edition._bound_hit({'retriever': 'edition_continued_chapter'}, document, excerpt.strip(), section, page))
    return SourceContinuity('chapter', hits[:data.top_k])
