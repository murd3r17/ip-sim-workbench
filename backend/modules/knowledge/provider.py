"""知识库 Provider 抽象。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class KnowledgeProvider(ABC):
    """知识库访问抽象。"""

    name: str = "base"

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def get_workspace(self, workspace_id: str | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def list_documents(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def upload_document(
        self,
        workspace_id: str | None,
        filename: str,
        content: bytes,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def delete_document(self, workspace_id: str | None, document_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def search(
        self,
        query: str,
        workspace_id: str | None = None,
        top_k: int = 4,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def ask(
        self,
        question: str,
        workspace_id: str | None = None,
        top_k: int = 4,
    ) -> dict[str, Any]:
        raise NotImplementedError
