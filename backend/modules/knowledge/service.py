"""知识库服务编排层。"""
from __future__ import annotations

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
        return await self.provider.list_documents(workspace)

    async def document_catalog(self) -> dict:
        from .reader import catalog
        workspace = self.resolve_workspace_id()
        return await catalog(self.provider, await self.provider.list_documents(workspace), workspace)

    async def read_document(self, document_id: str | None, filename: str | None, version: str | None) -> dict:
        from .reader import read_current
        workspace = self.resolve_workspace_id()
        return await read_current(self.provider, await self.provider.list_documents(workspace),
                                  workspace, document_id, filename, version)

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
        sources = await self.provider.search(query, workspace, limit)
        # 部分 provider（如 RAGFlow v0.26 retrieval）可能返回超过 top_k 的 chunk，
        # 统一在契约层截断，保证所有路由（/ask、/copilot/*、/knowledge/search）遵守 top_k。
        return sources[:limit]

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
