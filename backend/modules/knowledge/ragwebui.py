"""RAG Web UI KnowledgeProvider 实现。"""
from __future__ import annotations

import base64
import json as _json
import time
from typing import Any

import httpx

from core.logger import get_logger
from modules.knowledge.provider import KnowledgeProvider

logger = get_logger("knowledge")


class RAGWebUIProvider(KnowledgeProvider):
    """V5.0 RAG Web UI 过渡接入实现。"""

    name = "ragwebui"

    def __init__(
        self,
        base_url: str,
        username: str = "admin",
        password: str = "",
        workspace_id: str = "1",
        top_k: int = 4,
        similarity_threshold: float = 0.25,
        request_timeout: int = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.workspace_id = workspace_id
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold
        self.request_timeout = request_timeout
        self._client: httpx.AsyncClient | None = None
        self.jwt_token: str = ""
        self._token_expires_at: float = 0

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            from core.shared_http import get_managed_client
            self._client = get_managed_client(timeout=self.request_timeout, trust_env=False, follow_redirects=False)
        return self._client

    async def close(self) -> None:
        # 客户端为进程级共享池（trust_env=False 规避代理劫持），不随单个 provider 关闭
        return None

    async def __aenter__(self) -> RAGWebUIProvider:
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        await self.close()

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.jwt_token:
            headers["Authorization"] = f"Bearer {self.jwt_token}"
        return headers

    def _parse_token_expiry(self, token: str) -> float:
        """Extract exp claim from JWT, return epoch seconds or fallback."""
        try:
            payload_b64 = token.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)
            payload = _json.loads(base64.urlsafe_b64decode(payload_b64))
            return payload.get("exp", 0)
        except Exception:
            return time.time() + 1500

    async def _ensure_token(self) -> None:
        # Lazy-init expiry from an externally-set token (tests pre-set jwt_token)
        if self.jwt_token and self._token_expires_at == 0:
            self._token_expires_at = self._parse_token_expiry(self.jwt_token) - 300
        if self.jwt_token and time.time() < self._token_expires_at:
            return
        await self.login()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        client = await self._ensure_client()
        await self._ensure_token()
        headers = self._headers()
        extra = kwargs.pop("headers", None)
        if extra:
            headers.update(extra)
        resp = await client.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    async def login(self, username: str | None = None, password: str | None = None) -> dict:
        client = await self._ensure_client()
        resp = await client.post(
            f"{self.base_url}/api/auth/token",
            data={"username": username or self.username, "password": password or self.password},
        )
        resp.raise_for_status()
        data = resp.json()
        self.jwt_token = data.get("access_token", "")
        self._token_expires_at = self._parse_token_expiry(self.jwt_token) - 300
        logger.info("ragwebui_jwt_refreshed")
        return data

    async def health_check(self) -> dict[str, Any]:
        try:
            client = await self._ensure_client()
            resp = await client.get(f"{self.base_url}/api/health", timeout=5)
            if resp.status_code == 200:
                return {"available": True, "provider": self.name, "base_url": self.base_url}
            return {"available": False, "provider": self.name, "base_url": self.base_url, "error": f"status {resp.status_code}"}
        except Exception as exc:
            logger.warning("ragwebui_health_check_failed", error=str(exc))
            return {"available": False, "provider": self.name, "base_url": self.base_url, "error": str(exc)}

    async def get_workspace(self, workspace_id: str | None = None) -> dict[str, Any]:
        kb_id = workspace_id or self.workspace_id
        return await self._request("GET", f"/api/knowledge-base/{kb_id}")

    async def list_documents(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        kb_id = workspace_id or self.workspace_id
        data = await self._request("GET", f"/api/knowledge-base/{kb_id}")
        items = data.get("documents", []) if isinstance(data, dict) else []
        return [{"id": str(d.get("id", "")), "filename": d.get("filename", d.get("name", "")), **d} for d in items]

    async def upload_document(
        self, workspace_id: str | None, filename: str, content: bytes, content_type: str | None = None,
    ) -> dict[str, Any]:
        kb_id = workspace_id or self.workspace_id
        client = await self._ensure_client()
        await self._ensure_token()
        resp = await client.post(
            f"{self.base_url}/api/knowledge-base/{kb_id}/documents/upload",
            files={"file": (filename, content, content_type or "application/octet-stream")},
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {"filename": filename}

    async def delete_document(self, workspace_id: str | None, document_id: str) -> dict[str, Any]:
        kb_id = workspace_id or self.workspace_id
        return await self._request("DELETE", f"/api/knowledge-base/{kb_id}/documents/{document_id}")

    async def search(self, query: str, workspace_id: str | None = None, top_k: int = 4) -> list[dict[str, Any]]:
        kb_id = workspace_id or self.workspace_id
        data = await self._request(
            "POST", "/api/knowledge-base/test-retrieval",
            json={"query": query, "kb_id": int(kb_id), "top_k": top_k},
        )
        results = data.get("results", []) if isinstance(data, dict) else []
        return [
            {"text": r.get("content", ""), "title": r.get("title", ""), "score": r.get("score", 0), "metadata": r.get("metadata", {}), "raw": r}
            for r in results
        ]

    async def ask(self, question: str, workspace_id: str | None = None, top_k: int = 4) -> dict[str, Any]:
        sources = await self.search(question, workspace_id, top_k)
        context = "\n\n".join([s["text"] for s in sources if s["text"]])
        answer = context if context else "知识库中未找到相关内容。"
        return {
            "question": question,
            "answer": answer,
            "sources": sources,
            "workspace": workspace_id or self.workspace_id,
            "provider": self.name,
        }
