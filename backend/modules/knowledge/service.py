"""知识库服务编排层。"""
from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass
from typing import Any

from core.config import get_settings
from core.logger import get_logger
from modules.knowledge.provider import KnowledgeProvider

logger = get_logger("knowledge")


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

    async def health_check(self) -> dict[str, Any]:
        settings = get_settings()
        try:
            provider_health = await self.provider.health_check()
        except Exception as exc:
            provider_health = {
                "available": False,
                "provider": self.provider.name,
                "base_url": getattr(settings, "knowledge_base_url", ""),
                "error": str(exc),
            }
        workspace_id = self.resolve_workspace_id()
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

        return {
            "available": bool(provider_health.get("available")),
            "provider": self.provider.name,
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

    async def list_documents(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        workspace = self.resolve_workspace_id(workspace_id)
        items = await self.provider.list_documents(workspace)
        edition = self.edition()
        if not edition:
            return items
        managed = set(edition.documents) | {row[0]["document_id"] for row in edition.aliases.values()}
        return edition.catalog() + [item for item in items if item["id"] not in managed]

    async def document_catalog(self) -> dict:
        from .reader import catalog
        workspace = self.resolve_workspace_id()
        edition = self.edition()
        if not edition:
            return await catalog(self.provider, await self.provider.list_documents(workspace), workspace)
        from datetime import datetime, timezone
        managed_ids = set(edition.documents) | {row[0]["document_id"] for row in edition.aliases.values()}
        try:
            items = await self.provider.list_documents(workspace)
        except Exception as exc:
            logger.warning("edition_current_upload_catalog_unavailable", error=type(exc).__name__)
            items = []
        other = await catalog(self.provider, [item for item in items if item["id"] not in managed_ids], workspace)
        rows = edition.catalog() + other["documents"]
        return {"provider": self.provider.name, "documents": rows, "count": len(rows),
                "readable_count": sum(row["readable"] for row in rows),
                "catalog_version": f'{edition.version}:{other["catalog_version"]}',
                "checked_at": datetime.now(timezone.utc).isoformat()}

    async def read_document(self, document_id: str | None, filename: str | None, version: str | None) -> dict:
        from .reader import read_current
        edition = self.edition()
        if edition and document_id in edition.documents:
            return await asyncio.to_thread(edition.read, document_id, version)
        workspace = self.resolve_workspace_id()
        return await read_current(self.provider, await self.provider.list_documents(workspace),
                                  workspace, document_id, filename, version)

    @staticmethod
    def edition():
        from .edition import open_edition
        directory = getattr(get_settings(), "knowledge_edition_dir", "")
        return open_edition(directory) if isinstance(directory, str) and directory.strip() else None

    async def original_figure(self, document_id: str, version: str, page: int) -> bytes:
        from .reader import DocumentReadError
        edition = self.edition()
        if not edition:
            raise DocumentReadError("preview_unavailable", "当前知识库未配置原页图。", 404)
        return await asyncio.to_thread(edition.figure, document_id, version, page)

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
        workspace = self.resolve_workspace_id(workspace_id)
        limit = top_k or get_settings().knowledge_top_k
        edition = self.edition()
        from .local_provider import _query_tokens
        from .query_focus import context_only_query, protocol_names, technical_aliases

        if context_only_query(query):
            return []
        if self.provider.name == "local" and (
            technical_aliases(query) or (len(protocol_names(query)) == 1 and len(set(_query_tokens(query))) == 1)
        ):
            # Short lookups go directly to passages that explain the subject.
            # General reading notes can otherwise displace the relevant page.
            direct = await self.provider.search(query, workspace, limit)
            return (await asyncio.to_thread(edition.resolve_hits, direct, self.provider, workspace)
                    if edition else direct)
        focused = []
        if edition and (self.provider.name == "local"
                        or (self.provider.name == "anythingllm" and workspace == edition.vector["workspace"])):
            from .query_focus import focused_queries
            focuses = focused_queries(query)
            if focuses:
                focused = await self._focused_originals(edition, workspace, focuses, limit)
                if len(focused) >= limit:
                    return focused
        references = await self._reviewed_learning_hits(query, workspace, edition)
        if references and edition is None:
            return references[:limit]
        learning = list(focused)
        known = {(row["document_id"], row.get("page")) for row in learning}
        learning.extend(row for row in references if (row["document_id"], row.get("page")) not in known)
        if len(learning) >= limit:
            return learning[:limit]
        if edition and len(learning) < limit:
            additional = await asyncio.to_thread(edition.learning_hits, query, min(4, limit - len(learning)))
            reference_pages = {(row["document_id"], row.get("page")) for row in learning}
            learning.extend(row for row in additional if (row["document_id"], row.get("page")) not in reference_pages)
        if len(learning) == limit:
            return learning
        frozen_workspace = edition and self.provider.name == "anythingllm" and workspace == edition.vector["workspace"]
        provider_limit = limit
        if frozen_workspace:
            # The frozen workspace has the same source files as the local
            # index. Prefer the exact-text results for identifiers and page
            # facts, leaving spare slots to the configured vector provider.
            local = await edition.keyword_index.search(query, workspace, limit)
            local = await asyncio.to_thread(edition.resolve_hits, local, edition.keyword_index, workspace)
            learning.extend(hit for hit in local if hit.get("document_id") in edition.documents and hit.get("document_version"))
            if len(learning) >= limit:
                return learning[:limit]
            provider_limit -= len(learning)
        try:
            sources = await self.provider.search(query, workspace, provider_limit)
        except Exception as exc:
            if not learning:
                raise
            logger.warning("edition_search_provider_unavailable", error=type(exc).__name__)
            sources = []
        if edition:
            sources = await asyncio.to_thread(edition.resolve_hits, sources, self.provider, workspace)
        # 部分 provider（如 RAGFlow v0.26 retrieval）可能返回超过 top_k 的 chunk，
        # 统一在契约层截断，保证所有路由（/ask、/copilot/*、/knowledge/search）遵守 top_k。
        return (learning + sources)[:limit]

    async def _focused_originals(self, edition, workspace, focuses, limit):
        from .local_provider import _query_tokens
        from .query_focus import subject_pattern

        async def originals(focus):
            hits = await edition.keyword_index.search(focus.query, workspace, max(8, limit))
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
                    hits.extend(await asyncio.to_thread(edition.reviewed_page_hits, note, workspace, self.provider.name))
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
