"""知识库服务编排层。"""
from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from core.config import get_settings
from core.logger import get_logger
from modules.knowledge.provider import KnowledgeProvider

from .facet_evidence import FacetEvidence

if TYPE_CHECKING:
    from .ranked_evidence import EvidenceSearchResult

logger = get_logger("knowledge")
_EDITION_VECTOR_TIMEOUT = 4.0


def _blend_same_edition(local, vector, limit):
    """Rank verified physical pages with bounded vector-only admission."""
    if not vector:
        return local
    pages = {}
    for channel, hits in (("lexical", local), ("vector", vector)):
        for rank, hit in enumerate(hits, 1):
            page = (hit["book"], hit["page"])
            candidate = pages.setdefault(page, {"hit": hit})
            candidate.setdefault(channel, rank)

    ranked = []
    for item in pages.values():
        lexical = item.get("lexical")
        semantic = item.get("vector")
        score = (1 / (8 + lexical) if lexical else 0) + (.85 / (8 + semantic) if semantic else 0)
        ranked.append((score, lexical, semantic, item["hit"]))
    ranked.sort(key=lambda item: item[0], reverse=True)

    results = []
    novel = 0
    novel_limit = min(2, max(1, limit // 3))
    best = ranked[0][0]
    for score, lexical, semantic, hit in ranked:
        if lexical is None:
            if novel >= novel_limit:
                continue
            novel += 1
        ranked_hit = {**hit, "score": round(score / best, 4), "score_kind": "relative_within_query",
                      "fusion": {"lexical_rank": lexical, "vector_rank": semantic}}
        if lexical and semantic:
            ranked_hit["retriever"] = "edition_fused"
        results.append(ranked_hit)
        if len(results) == limit:
            break
    # Preserve a same-page lexical continuation when there are too few unique pages.
    if len(results) < limit:
        results.extend(local)
    return results


@dataclass(slots=True)
class UploadPolicy:
    allowed_extensions: list[str]
    allowed_content_types: list[str]
    max_file_size_mb: int
    max_upload_files: int


class KnowledgeService:
    """知识库能力入口，封装 provider 选择和统一降级信息。"""

    def __init__(self, provider: KnowledgeProvider, policy: UploadPolicy) -> None:
        self.provider = provider
        self.policy = policy

    @classmethod
    def from_settings(cls) -> "KnowledgeService":
        settings = get_settings()
        provider_name = getattr(settings, "knowledge_provider", "anythingllm").lower()
        if provider_name == "rag":
            logger.warning("knowledge_provider=rag is deprecated; treating as anythingllm")
            provider_name = "anythingllm"
        top_k = getattr(settings, "knowledge_top_k", 8)
        similarity = getattr(settings, "knowledge_similarity_threshold", 0.2)
        timeout = getattr(settings, "knowledge_request_timeout", 180)
        if provider_name == "ragwebui":
            from modules.knowledge.ragwebui import RAGWebUIProvider
            provider = RAGWebUIProvider(
                base_url=getattr(settings, "rag_base_url", "http://localhost:80"),
                username=getattr(settings, "rag_username", "admin"),
                password=getattr(settings, "rag_password", ""),
                workspace_id=getattr(settings, "rag_default_kb_id", "1"),
                top_k=top_k,
                similarity_threshold=similarity,
                request_timeout=timeout,
            )
        elif provider_name == "local":
            # 最小运行模式：无 AnythingLLM / Ollama 时直接检索仓库内 Markdown 语料
            from modules.knowledge.local_provider import get_local_provider
            provider = get_local_provider(
                corpus_dir=getattr(settings, "knowledge_corpus_dir", "") or None,
                top_k=top_k,
                similarity_threshold=similarity,
                workspace_slug=getattr(settings, "knowledge_workspace_slug", "ip-ops-kb"),
            )
        elif provider_name == "ragflow":
            from modules.knowledge.ragflow import RagflowKnowledgeProvider
            provider = RagflowKnowledgeProvider(
                base_url=getattr(settings, "knowledge_base_url", "http://127.0.0.1:9380"),
                api_key=getattr(settings, "knowledge_api_key", ""),
                dataset_id=getattr(settings, "knowledge_dataset_id", "")
                or getattr(settings, "knowledge_workspace_id", ""),
                dataset_name=getattr(settings, "knowledge_workspace_slug", "ip-ops-kb"),
                top_k=top_k,
                similarity_threshold=similarity,
                request_timeout=timeout,
            )
        elif provider_name == "anythingllm":
            from modules.knowledge.anythingllm import AnythingLLMKnowledgeProvider
            provider = AnythingLLMKnowledgeProvider(
                base_url=getattr(settings, "knowledge_base_url", "http://localhost:3001"),
                api_key=getattr(settings, "knowledge_api_key", ""),
                workspace_slug=getattr(settings, "knowledge_workspace_slug", "ip-ops-kb"),
                workspace_id=getattr(settings, "knowledge_workspace_id", "1"),
                top_k=top_k,
                similarity_threshold=similarity,
                request_timeout=timeout,
            )
        else:
            raise ValueError(f"未知的 knowledge_provider: {provider_name}")
        policy = UploadPolicy(
            allowed_extensions=[".pdf", ".txt", ".md", ".docx", ".csv", ".json", ".xlsx", ".xls", ".pptx", ".png", ".jpg", ".jpeg"],
            allowed_content_types=[
                "application/pdf",
                "text/plain",
                "text/markdown",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "text/csv",
                "application/json",
                "image/png",
                "image/jpeg",
            ],
            max_file_size_mb=getattr(settings, "knowledge_max_upload_mb", 10),
            max_upload_files=getattr(settings, "knowledge_max_upload_files", 200),
        )
        return cls(provider=provider, policy=policy)

    # workspace 标识只允许这类字符，防止客户端传入 `../` 之类穿越到别的库
    _WORKSPACE_ID_RE = re.compile(r"^[A-Za-z0-9_\-. ]{1,64}$")

    def _safe_workspace_id(self, workspace_id: str | None, fallback: str) -> str:
        """校验客户端传入的 workspace/kb 标识；非法值一律回落到配置值。"""
        if not workspace_id:
            return fallback
        candidate = workspace_id.strip()
        if not self._WORKSPACE_ID_RE.match(candidate):
            logger.warning("knowledge_workspace_id_rejected", value=candidate[:64])
            return fallback
        return candidate

    def resolve_workspace_id(self, workspace_id: str | None = None) -> str:
        settings = get_settings()
        if self.provider.name == "ragwebui":
            kb_id = settings.rag_default_kb_id
            if not workspace_id or workspace_id in {settings.knowledge_workspace_slug, settings.knowledge_workspace_id, kb_id}:
                return kb_id
            return self._safe_workspace_id(workspace_id, kb_id)
        if self.provider.name == "ragflow":
            dataset_id = getattr(settings, "knowledge_dataset_id", "") or settings.knowledge_workspace_id
            if workspace_id and workspace_id not in {
                settings.knowledge_workspace_slug,
                settings.knowledge_workspace_id,
                dataset_id,
                "",
            }:
                return self._safe_workspace_id(workspace_id, dataset_id or settings.knowledge_workspace_slug)
            return dataset_id or settings.knowledge_workspace_slug
        if not workspace_id:
            return settings.knowledge_workspace_slug
        if workspace_id in {settings.knowledge_workspace_slug, settings.knowledge_workspace_id}:
            return settings.knowledge_workspace_slug
        return self._safe_workspace_id(workspace_id, settings.knowledge_workspace_slug)

    def policy_dict(self) -> dict[str, Any]:
        return asdict(self.policy)

    async def _provider_state(self, settings, workspace_id):
        try:
            provider_health = await self.provider.health_check()
        except Exception as exc:
            provider_health = {
                "available": False,
                "provider": self.provider.name,
                "base_url": getattr(settings, "knowledge_base_url", ""),
                "error": str(exc),
            }
        workspace_data: dict[str, Any] = {}
        documents: list[dict[str, Any]] = []
        if provider_health.get("available"):
            try:
                workspace_data = await self.provider.get_workspace(workspace_id)
            except Exception as exc:
                workspace_data = {"id": workspace_id, "error": str(exc)}
            try:
                documents = await self.provider.list_documents(workspace_id)
            except Exception as exc:
                documents = []
                provider_health.setdefault("warnings", []).append(str(exc))
        return provider_health, workspace_data, documents

    def _shared_local_index(self, edition):
        from .local_provider import LocalKnowledgeProvider

        if edition is not None and type(self.provider) is LocalKnowledgeProvider:
            keyword = edition.keyword_index
            if self.provider.shares_frozen_corpus(keyword):
                return keyword
        return None

    @staticmethod
    def _managed_document_ids(edition) -> set[str]:
        return set(edition.documents) | {row[0]["document_id"] for row in edition.aliases.values()}

    async def health_check(self) -> dict[str, Any]:
        settings = get_settings()
        workspace_id = self.resolve_workspace_id()
        invalid_edition = False
        try:
            edition = self.edition()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("edition_search_health_unavailable", error=type(exc).__name__)
            edition = None
            invalid_edition = True

        shared = self._shared_local_index(edition)
        local_health = await shared.health_check() if shared is not None else None
        provider_state = None
        if local_health is not None and shared.can_supply_workspace_counts(local_health["document_count"]):
            try:
                extra_documents, extra_chunks = await self.provider.edition_inventory(shared)
            except Exception as exc:
                logger.warning("edition_local_inventory_unavailable", error=type(exc).__name__)
            else:
                provider_state = ({"available": bool(local_health["chunk_count"] or extra_chunks),
                                   "base_url": str(self.provider.corpus_dir)},
                                  {"id": workspace_id or self.provider.workspace_slug, "name": self.provider.workspace_slug,
                                   "document_count": local_health["document_count"] + len(extra_documents),
                                   "chunk_count": local_health["chunk_count"] + extra_chunks}, extra_documents)
        provider_health, workspace_data, documents = provider_state or await self._provider_state(settings, workspace_id)
        provider_available = bool(provider_health.get("available"))
        if invalid_edition:
            search = {**await self._search_status(None, False), "search_provider": None}
        else:
            search = await self._search_status(edition, provider_available, local_health=local_health)
            if edition:
                documents = edition.catalog()

        return {
            "available": search["search_available"],
            "provider": self.provider.name,
            "provider_available": provider_available,
            **search,
            "base_url": provider_health.get("base_url") or getattr(settings, "knowledge_base_url", ""),
            "workspace_slug": settings.knowledge_workspace_slug,
            "workspace_id": settings.knowledge_workspace_id,
            "document_count": len(documents),
            "documents": documents[:5],
            "workspace": workspace_data,
            "upload_policy": self.policy_dict(),
            "top_k": settings.knowledge_top_k,
            "similarity_threshold": settings.knowledge_similarity_threshold,
            "warnings": provider_health.get("warnings", []),
            "error": provider_health.get("error"),
        }

    async def _search_status(self, edition, provider_available: bool, *, local_health=None) -> dict[str, Any]:
        from .original_index import original_quote_status

        fallback_reason = None
        quote_status = None
        if edition:
            if local_health is None:
                local_health = await edition.keyword_index.health_check()
            quote_status = await asyncio.to_thread(original_quote_status, edition)
            available = bool(local_health.get("available"))
            if available and self.provider.name != "local":
                if self.provider.name != "anythingllm" or self.resolve_workspace_id() != edition.vector["workspace"]:
                    fallback_reason = "workspace_mismatch"
                elif not provider_available:
                    fallback_reason = "provider_unavailable"
        else:
            available = provider_available
        return {
            "active_edition": edition.version if edition else None,
            "search_provider": "local" if edition and available else self.provider.name if available else None,
            "search_available": available,
            "search_fallback": fallback_reason is not None,
            "search_fallback_reason": fallback_reason,
            "original_quote_status": quote_status,
        }

    async def list_documents(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        workspace = self.resolve_workspace_id(workspace_id)
        items = await self.provider.list_documents(workspace)
        edition = self.edition()
        if not edition:
            return items
        managed = self._managed_document_ids(edition)
        return edition.catalog() + [item for item in items if item["id"] not in managed]

    async def document_catalog(self) -> dict:
        from .reader import catalog
        workspace = self.resolve_workspace_id()
        edition = self.edition()
        if not edition:
            current = await catalog(self.provider, await self.provider.list_documents(workspace), workspace)
            return {**current, **await self._search_status(None, True)}
        from datetime import datetime, timezone
        managed_ids = self._managed_document_ids(edition)
        shared = self._shared_local_index(edition)
        local_health = await shared.health_check() if shared is not None else None
        try:
            if local_health is not None and shared.can_supply_workspace_counts(local_health["document_count"]):
                try:
                    items, _ = await self.provider.edition_inventory(shared)
                except Exception:
                    items = await self.provider.list_documents(workspace)
            else:
                items = await self.provider.list_documents(workspace)
            provider_available = True
        except Exception as exc:
            logger.warning("edition_current_upload_catalog_unavailable", error=type(exc).__name__)
            items = []
            provider_available = False
        other = await catalog(self.provider, [item for item in items if item["id"] not in managed_ids], workspace)
        rows = edition.catalog() + other["documents"]
        return {**await self._search_status(edition, provider_available, local_health=local_health),
                "provider": self.provider.name, "documents": rows, "count": len(rows),
                "readable_count": sum(row["readable"] for row in rows),
                "catalog_version": f'{edition.version}:{other["catalog_version"]}',
                "checked_at": datetime.now(timezone.utc).isoformat()}

    async def read_document(self, document_id: str | None, filename: str | None, version: str | None) -> dict:
        from .reader import read_current
        edition = self.edition()
        if edition and document_id in edition.documents:
            selected = await asyncio.to_thread(self._document_edition, edition, document_id, version)
            reading = await asyncio.to_thread(selected.read, document_id, version)
            if selected is not edition:
                reading.update(historical_edition=True, message="当前打开的是该引用保存的冻结教材版本。")
            return reading
        workspace = self.resolve_workspace_id()
        return await read_current(self.provider, await self.provider.list_documents(workspace),
                                  workspace, document_id, filename, version)

    @staticmethod
    def edition():
        from .edition import open_edition
        settings = get_settings()
        directory = getattr(settings, "knowledge_edition_dir", "")
        originals = getattr(settings, "knowledge_original_dir", "")
        return open_edition(directory, originals) if isinstance(directory, str) and directory.strip() else None

    @staticmethod
    def _document_edition(edition, document_id, version):
        from .edition import open_edition

        current = edition.documents.get(document_id)
        if not current or not version or version == current["sha256"]:
            return edition
        settings = get_settings()
        directory = getattr(settings, "knowledge_previous_edition_dir", "")
        if not isinstance(directory, str) or not directory.strip():
            return edition
        try:
            previous = open_edition(directory, getattr(settings, "knowledge_original_dir", ""))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("edition_archive_unavailable", error=type(exc).__name__)
            return edition
        archived = previous.documents.get(document_id)
        return previous if archived and version == archived["sha256"] else edition

    async def original_figure(self, document_id: str, version: str, page: int) -> bytes:
        from .reader import DocumentReadError
        edition = self.edition()
        if not edition:
            raise DocumentReadError("preview_unavailable", "当前知识库未配置原页图。", 404)
        selected = await asyncio.to_thread(self._document_edition, edition, document_id, version)
        return await asyncio.to_thread(selected.figure, document_id, version, page)

    async def legacy_locator(self, document_id: str, version: str, section_id: str | None) -> dict:
        edition = self.edition()
        if not edition:
            return {}
        return await asyncio.to_thread(edition.legacy_locator, document_id, version, section_id)

    async def upload_document(
        self,
        filename: str,
        content: bytes,
        content_type: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        workspace = self.resolve_workspace_id(workspace_id)
        result = await self.provider.upload_document(workspace, filename, content, content_type)
        from modules.ai_text.kb_cache import invalidate
        invalidate()
        return result

    async def delete_document(self, document_id: str, workspace_id: str | None = None) -> dict[str, Any]:
        edition = self.edition()
        if edition and (document_id in edition.documents or any(row[0]["document_id"] == document_id for row in edition.aliases.values())):
            return {"deleted": [], "status": "protected", "error": "教材随知识库版本更新。"}
        workspace = self.resolve_workspace_id(workspace_id)
        result = await self.provider.delete_document(workspace, document_id)
        from modules.ai_text.kb_cache import invalidate
        invalidate()
        return result

    async def search(
        self,
        query: str,
        workspace_id: str | None = None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        return await self._search(query, workspace_id, top_k)

    async def search_with_facet_evidence(
        self,
        query: str,
        workspace_id: str | None = None,
        top_k: int | None = None,
    ) -> tuple[list[dict[str, Any]], FacetEvidence | None]:
        """Return normal hits and an optional server-verified pair from one retrieval."""
        evidence: list[FacetEvidence] = []
        hits = await self._search(query, workspace_id, top_k, facet_evidence=evidence)
        return hits, evidence[0] if evidence else None

    async def search_ranked_evidence(self, query: str, workspace_id: str | None = None, top_k: int = 6) -> EvidenceSearchResult:
        """Return normal results and an internal pool of physically verified evidence."""
        from .ranked_evidence import EvidenceSearchResult, rank_edition_evidence

        limit = min(max(top_k, 1), 6)
        evidence: list[FacetEvidence] = []
        captured = []
        hits = await self._search(query, workspace_id, limit, facet_evidence=evidence, ranked_context=captured)
        selection = evidence[0] if evidence else None
        if not captured:
            return EvidenceSearchResult(hits, selection, [], None)
        edition, workspace, terms, initial = captured[0]
        pool, ranked = await rank_edition_evidence(edition, workspace, query, terms, [*hits, *initial], top_k=limit,
                                                  preserve_selection=selection is not None)
        return EvidenceSearchResult(hits, selection, pool, ranked)

    async def _search(self, query, workspace_id, top_k, *, facet_evidence=None, ranked_context=None):
        workspace = self.resolve_workspace_id(workspace_id)
        limit = top_k or get_settings().knowledge_top_k
        from .local_provider import _query_tokens
        from .query_focus import context_only_query, protocol_names, technical_aliases

        if context_only_query(query):
            return []
        edition = self._edition_for_search(workspace)
        short = bool(technical_aliases(query)) or (len(protocol_names(query)) == 1 and len(set(_query_tokens(query))) == 1)
        if edition:
            explicit_vector = bool(workspace_id and workspace_id.strip() == edition.vector["workspace"])
            return await self._search_edition(edition, query, workspace, limit, short, explicit_vector,
                                              facet_evidence=facet_evidence, ranked_context=ranked_context)
        references = [] if self.provider.name == "local" and short else await self._reviewed_learning_hits(query, workspace)
        if references:
            return references[:limit]
        # 部分 provider（如 RAGFlow v0.26 retrieval）可能返回超过 top_k 的 chunk，
        # 统一在契约层截断，保证所有路由（/ask、/copilot/*、/knowledge/search）遵守 top_k。
        return (await self.provider.search(query, workspace, limit))[:limit]

    def _edition_for_search(self, workspace):
        if workspace == self.resolve_workspace_id():
            return self.edition()
        try:
            edition = self.edition()
        except (OSError, ValueError, KeyError, TypeError):
            # Keep an explicitly selected provider workspace usable even when
            # the independent default reading edition cannot be opened.
            return None
        return edition if edition and workspace == edition.vector["workspace"] else None

    async def _search_edition(self, edition, query, workspace, limit, short, explicit_vector, *,
                              facet_evidence=None, ranked_context=None):
        from .complementary_facets import complementary_request, expand_complementary
        from .edition import literal_excerpt
        from .evidence_anchors import evidence_anchor_request, verified_evidence_anchor
        from .local_provider import vlan_mapping_excerpt
        from .page_evidence import coverage_request
        from .query_focus import compact_text, focused_queries, multiple_passage_facets, separate_pdf_pages, vlan_mapping_query
        from .reader import DocumentReadError

        if parts := separate_pdf_pages(query):
            return await self._search_separate_pdf_pages(edition, workspace, limit, *parts)

        terms, chapters, document_ids, pages, phrases = edition.search_scope(query)
        unavailable = DocumentReadError("edition_search_unavailable", "当前教材版本暂不可检索。", 503)
        if chapters:
            titles = await asyncio.to_thread(edition.navigation_hits, chapters, limit)
            if not titles:
                raise unavailable
            return titles
        if pages and (pages[0] < 1 or pages[1] < pages[0]):
            return []

        keyword = edition.keyword_index
        base_depth = max(limit * 5, 16)
        anchor_request = None
        if 4 <= limit <= 8 and not (short or explicit_vector or pages or phrases or document_ids is not None):
            anchor_request = evidence_anchor_request(terms)
        depth = max(base_depth, 64) if anchor_request else base_depth
        available, candidates = await keyword.search_pages(terms, depth, document_ids=document_ids,
                                                          pages=pages, phrases=phrases)
        vlan_ids = vlan_mapping_query(terms) if not phrases else frozenset()
        ranked_candidates = [] if ranked_context is not None and not (
            phrases or pages or vlan_ids or explicit_vector or document_ids is not None) else None
        sources = await asyncio.to_thread(edition.resolve_hits, candidates[:base_depth], keyword, workspace,
                                          query="" if phrases else terms,
                                          **({"original_candidates": ranked_candidates} if ranked_candidates is not None else {}))
        literals = tuple(compact_text(phrase) for phrase in phrases)
        if literals:
            sources = [{**hit, "text": literal_excerpt(hit["text"], literals)} for hit in sources
                       if any(phrase in compact_text(hit["text"]) for phrase in literals)]
        natural = compact_text(terms)
        exact = [hit for hit in sources if literals or (len(natural) >= 4 and natural in compact_text(hit["text"]))]
        results, seen = [], set()

        def add(hits):
            for hit in hits:
                identity = (hit["book"], hit.get("page"), compact_text(hit["text"]))
                if identity not in seen and len(results) < limit:
                    seen.add(identity)
                    results.append(hit)

        add(exact)
        if ranked_candidates is not None:
            ranked_context.append((edition, workspace, terms, [*sources, *ranked_candidates]))
        if vlan_ids:
            add(hit for hit in sources if vlan_mapping_excerpt(hit["text"], vlan_ids))
        if len(results) < limit and not (short or phrases or pages or document_ids is not None):
            focuses = focused_queries(query)
            if focuses:
                add(await self._focused_originals(edition, workspace, focuses, limit))
            if len(results) < limit:
                add(await self._reviewed_learning_hits(query, workspace, edition))
            if len(results) < limit:
                add(await asyncio.to_thread(edition.learning_hits, query, min(4, limit - len(results))))
        # The configured workspace remains the authority for provider access.
        # Precise literal, title and explicit range lookups stay deterministic.
        if (explicit_vector and len(results) < limit and not (short or exact or phrases or pages or document_ids is not None)
                and self.provider.name == "anythingllm" and edition.aliases and workspace == edition.vector["workspace"]):
            try:
                async with asyncio.timeout(_EDITION_VECTOR_TIMEOUT):
                    vector_limit = max(6, min(16, limit * 2))
                    vector_candidates = await self.provider.search(terms or query, workspace, vector_limit)
                    verified = await asyncio.to_thread(edition.resolve_hits, vector_candidates[:vector_limit], self.provider, workspace)
                    vector = await asyncio.to_thread(keyword.topical_hits, terms or query, verified)
            except Exception as exc:
                logger.warning("edition_search_provider_unavailable", error=type(exc).__name__)
            else:
                sources = _blend_same_edition(sources, vector, limit - len(results))
        add(sources)
        if not results and not available:
            raise unavailable
        if results and multiple_passage_facets(terms) and not (short or phrases or exact):
            results = await asyncio.to_thread(edition.improve_page_excerpts, results, terms)
        natural_search = not (short or exact or phrases or pages or vlan_ids or explicit_vector or document_ids is not None)
        covered = False
        if results and natural_search:
            if request := coverage_request(terms):
                enriched = await asyncio.to_thread(edition.cover_page_excerpts, results, request)
                covered = enriched != results
                results = enriched
        if anchor_request and len(results) >= 4 and not (exact or vlan_ids):
            anchored = await asyncio.to_thread(verified_evidence_anchor, edition, keyword, workspace,
                                               candidates, terms, anchor_request)
            if anchored and all((hit["book"], hit["page"]) != (anchored["book"], anchored["page"]) for hit in results):
                results.insert(3, anchored)
                return results[:limit]
        if natural_search and not covered and 4 <= limit <= 8:
            if plan := complementary_request(terms):
                choices = []
                results = await expand_complementary(edition, workspace, plan, results, sources, limit,
                                                    on_pair=choices.append if facet_evidence is not None else None)
                if facet_evidence is not None and choices:
                    evidence = await asyncio.to_thread(FacetEvidence.capture, edition, query, *choices[0])
                    if evidence and evidence.select_hits(query, results) is not None:
                        facet_evidence.append(evidence)
        return results

    async def _search_separate_pdf_pages(self, edition, workspace, limit, pages, before, after):
        from .reader import DocumentReadError

        _, _, document_ids, _, _ = edition.search_scope(f'{before}PDF 第 {pages[0]} 页{after}')
        if not document_ids or len({edition.documents[identifier]['book'] for identifier in document_ids}) != 1:
            return []

        results = []
        unavailable = None
        for physical in pages:
            try:
                sources = await self._search_edition(edition, f'{before}PDF 第 {physical} 页{after}', workspace, 1, False, False)
            except DocumentReadError as exc:
                if exc.code != 'edition_search_unavailable':
                    raise
                unavailable = exc
                continue
            results.extend(hit for hit in sources if hit.get('page') == physical)
            if len(results) == limit:
                break
        if not results and unavailable:
            raise unavailable
        return results

    async def _focused_originals(self, edition, workspace, focuses, limit):
        from .local_provider import _query_tokens
        from .query_focus import subject_pattern

        async def originals(focus):
            _, hits = await edition.keyword_index.search_pages(focus.query, max(12, limit * 2))
            subject = subject_pattern(focus.subject) if focus.subject else None
            terms = set(_query_tokens(focus.facet))
            ranked = []
            for hit in hits:
                body = hit.get("text") or ""
                if subject and not (subject.search(body) or subject.search(hit.get("title") or "")):
                    continue
                overlap = len(terms.intersection(_query_tokens(body)))
                exact = focus.facet.casefold() in body.casefold()
                if not exact and (subject is None or overlap < max(1, (len(terms) + 1) // 2)):
                    continue
                ranked.append((exact, overlap, hit))
            ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
            mapped = await asyncio.to_thread(edition.resolve_hits, [hit for _, _, hit in ranked],
                                             edition.keyword_index, workspace)
            return [hit for hit in mapped if hit.get("document_version") and hit.get("section_id")]

        groups = await asyncio.gather(*(originals(focus) for focus in focuses))
        seen = set()
        evidence = []
        # Include the best supported page for each part before filling extra slots.
        for index in range(max(map(len, groups), default=0)):
            for focus, group in zip(focuses, groups, strict=True):
                if index >= len(group):
                    continue
                hit = group[index]
                identity = (hit["document_id"], hit["section_id"])
                if identity in seen:
                    continue
                seen.add(identity)
                evidence.append({**hit, "retriever": "focused_original", "query_focus": focus.query})
                if len(evidence) == limit:
                    return evidence
        return evidence

    async def _reviewed_learning_hits(self, query: str, workspace: str | None, edition=None) -> list[dict]:
        """Locate a reviewed passage in this provider's active, readable corpus."""
        from core.markdown_blocks import blocks
        from .reader import DocumentReadError, read_current
        from .reviewed_source_notes import matching_learning_notes

        notes = matching_learning_notes(query)
        if not notes:
            return []
        if edition:
            hits = []
            for note in notes:
                if note.get("source_page"):
                    hits.extend(await asyncio.to_thread(edition.reviewed_page_hits, note))
            return hits
        notes = [note for note in notes if not note.get("source_page")]
        if not notes:
            return []
        try:
            documents = await self.provider.list_documents(workspace)
        except Exception as exc:
            logger.warning("reviewed_learning_catalog_unavailable", error=type(exc).__name__)
            return []
        hits = []
        for note in notes:
            matches = [item for item in documents if (item.get("filename") or item.get("title")) == note["filename"]]
            if len(matches) != 1:
                continue
            try:
                document = await read_current(self.provider, documents, workspace, str(matches[0]["id"]))
            except DocumentReadError:
                continue
            body = document["content"]
            compact = "".join(note["match"].split())
            for _, start, end in blocks(body):
                excerpt = body[start:end].strip()
                if compact not in "".join(excerpt.split()):
                    continue
                line = body.count("\n", 0, start) + 1
                chapter = next((section for section in reversed(document["sections"]) if section["line"] <= line), None)
                hits.append({
                    "filename": note["filename"], "title": document["title"], "text": excerpt,
                    "document_id": document["id"], "document_version": document["version"],
                    "section_id": chapter["id"] if chapter else None, "retriever": "reviewed_excerpt",
                })
                break
        return hits

    async def ask(
        self,
        question: str,
        workspace_id: str | None = None,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        workspace = self.resolve_workspace_id(workspace_id)
        limit = top_k or get_settings().knowledge_top_k
        try:
            if self._edition_for_search(workspace):
                sources = await self.search(question, workspace_id, limit)
                result = {
                    "question": question,
                    "answer": "",
                    "sources": sources,
                    "workspace": workspace,
                    "provider": "anythingllm" if sources and all(
                        source.get("retriever") == "edition_vector" for source in sources
                    ) else "local",
                    "status": "ok" if sources else "degraded",
                }
            else:
                result = await self.provider.ask(question, workspace, limit)
        except Exception as exc:
            logger.warning("knowledge_ask_failed", error=type(exc).__name__)
            return {
                "question": question,
                "answer": "",
                "sources": [],
                "workspace": workspace,
                "provider": getattr(self.provider, "name", "unknown"),
                "status": "degraded",
                "error": type(exc).__name__,
                "upload_policy": self.policy_dict(),
            }
        sources = result.get("sources") or []
        if len(sources) > limit:
            result["sources"] = sources[:limit]
        result.setdefault("status", "ok" if result.get("answer") else "degraded")
        result.setdefault("upload_policy", self.policy_dict())
        return result
