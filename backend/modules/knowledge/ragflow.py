"""RAGFlow KnowledgeProvider — retrieval for DeepSeek synthesis."""
from __future__ import annotations

import re
from typing import Any

import httpx

from core.logger import get_logger
from modules.knowledge.provider import KnowledgeProvider

logger = get_logger("knowledge")

# RAGFlow 文档 run 状态：0=UNSTART 1=RUNNING 2=CANCEL 3=DONE FAIL=failed
# 前端契约统一为 ready / processing / failed / unknown
_DOC_STATUS_MAP = {
    "0": "processing",
    "1": "processing",
    "2": "processing",
    "3": "ready",
    "done": "ready",
    "success": "ready",
    "ready": "ready",
    "fail": "failed",
    "failed": "failed",
    "cancel": "processing",
}


def _normalize_doc_status(status: str) -> str:
    key = str(status or "").strip().lower()
    return _DOC_STATUS_MAP.get(key, "processing")


class RagflowKnowledgeProvider(KnowledgeProvider):
    """RAGFlow HTTP API integration (datasets / documents / retrieval)."""

    name = "ragflow"

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        dataset_id: str = "",
        dataset_name: str = "huawei-ip-ops",
        top_k: int = 8,
        similarity_threshold: float = 0.2,
        request_timeout: int = 180,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.dataset_id = dataset_id
        self.dataset_name = dataset_name
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold
        self.request_timeout = request_timeout
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            from core.shared_http import get_managed_client
            self._client = get_managed_client(timeout=self.request_timeout, trust_env=False, follow_redirects=True)
        return self._client

    async def close(self) -> None:
        # 客户端为进程级共享池（trust_env=False 规避代理劫持），不随单个 provider 关闭
        return None

    def _headers(self, json_body: bool = False) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        client = await self._ensure_client()
        headers = self._headers(json_body=kwargs.get("json") is not None)
        extra = kwargs.pop("headers", None)
        if extra:
            headers.update(extra)
        resp = await client.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
        resp.raise_for_status()
        if not resp.content:
            return {}
        data = resp.json()
        if isinstance(data, dict) and data.get("code") not in (None, 0):
            raise RuntimeError(data.get("message") or f"RAGFlow error code={data.get('code')}")
        return data

    def _dataset(self, workspace_id: str | None = None) -> str:
        if workspace_id and workspace_id not in {"", self.dataset_name, "1"}:
            return workspace_id
        return self.dataset_id or workspace_id or ""

    async def ensure_dataset(self) -> str:
        """Return dataset id, creating by name if needed."""
        if self.dataset_id:
            return self.dataset_id
        listed = await self._request("GET", f"/api/v1/datasets?page=1&page_size=100&name={self.dataset_name}")
        rows = listed.get("data") if isinstance(listed, dict) else None
        if isinstance(rows, dict):
            rows = rows.get("data") or rows.get("datasets") or []
        if isinstance(rows, list):
            for item in rows:
                if isinstance(item, dict) and item.get("name") == self.dataset_name:
                    self.dataset_id = str(item["id"])
                    return self.dataset_id
        created = await self._request(
            "POST",
            "/api/v1/datasets",
            json={
                "name": self.dataset_name,
                "embedding_model": "BAAI/bge-m3@SILICONFLOW",
                "chunk_method": "naive",
                "parser_config": {
                    "chunk_token_num": 512,
                    "delimiter": "\n",
                },
            },
        )
        data = created.get("data") if isinstance(created, dict) else {}
        self.dataset_id = str((data or {}).get("id") or "")
        if not self.dataset_id:
            raise RuntimeError("RAGFlow create dataset returned no id")
        return self.dataset_id

    async def health_check(self) -> dict[str, Any]:
        try:
            # Prefer lightweight list; healthz may vary by version
            await self._request("GET", "/api/v1/datasets?page=1&page_size=1")
            ds = self.dataset_id or "(unset)"
            return {
                "available": True,
                "provider": self.name,
                "base_url": self.base_url,
                "dataset_id": ds,
                "dataset_name": self.dataset_name,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("ragflow_health_failed", error=str(exc))
            return {
                "available": False,
                "provider": self.name,
                "base_url": self.base_url,
                "error": str(exc),
            }

    async def get_workspace(self, workspace_id: str | None = None) -> dict[str, Any]:
        dataset_id = self._dataset(workspace_id) or await self.ensure_dataset()
        data = await self._request("GET", f"/api/v1/datasets/{dataset_id}")
        raw = data.get("data") if isinstance(data, dict) else data
        return {
            "id": dataset_id,
            "name": (raw or {}).get("name") if isinstance(raw, dict) else self.dataset_name,
            "provider": self.name,
            "raw": raw,
        }

    async def list_documents(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        dataset_id = self._dataset(workspace_id) or await self.ensure_dataset()
        out: list[dict[str, Any]] = []
        page = 1
        while page <= 50:
            data = await self._request(
                "GET",
                f"/api/v1/datasets/{dataset_id}/documents?page={page}&page_size=100",
            )
            payload = data.get("data") if isinstance(data, dict) else data
            docs = []
            if isinstance(payload, dict):
                docs = payload.get("docs") or payload.get("documents") or payload.get("data") or []
            elif isinstance(payload, list):
                docs = payload
            if not docs:
                break
            for raw in docs:
                if not isinstance(raw, dict):
                    continue
                out.append(
                    {
                        "id": str(raw.get("id") or ""),
                        "filename": raw.get("name") or raw.get("location") or "",
                        "title": raw.get("name") or "",
                        "size": raw.get("size"),
                        "status": _normalize_doc_status(raw.get("run") or raw.get("status") or ""),
                        "created_at": raw.get("create_date") or raw.get("create_time"),
                        "metadata": {},
                        "raw": raw,
                    }
                )
            if len(docs) < 100:
                break
            page += 1
        return out

    async def upload_document(
        self,
        workspace_id: str | None,
        filename: str,
        content: bytes,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        dataset_id = self._dataset(workspace_id) or await self.ensure_dataset()
        client = await self._ensure_client()
        files = {"file": (filename, content, content_type or "text/markdown")}
        resp = await client.post(
            f"{self.base_url}/api/v1/datasets/{dataset_id}/documents",
            headers=self._headers(),
            files=files,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("code") not in (None, 0):
            raise RuntimeError(data.get("message") or "upload failed")
        payload = data.get("data") if isinstance(data, dict) else data
        # API may return list of docs
        doc = payload[0] if isinstance(payload, list) and payload else payload
        doc_id = ""
        if isinstance(doc, dict):
            doc_id = str(doc.get("id") or "")
        if doc_id:
            await self.parse_documents(dataset_id, [doc_id])
        return {"id": doc_id, "filename": filename, "status": "parsing", "raw": doc}

    async def parse_documents(self, dataset_id: str, document_ids: list[str]) -> None:
        if not document_ids:
            return
        await self._request(
            "POST",
            f"/api/v1/datasets/{dataset_id}/chunks",
            json={"document_ids": document_ids},
        )

    async def delete_document(self, workspace_id: str | None, document_id: str) -> dict[str, Any]:
        dataset_id = self._dataset(workspace_id) or await self.ensure_dataset()
        await self._request(
            "DELETE",
            f"/api/v1/datasets/{dataset_id}/documents",
            json={"ids": [document_id]},
        )
        return {"id": document_id, "deleted": True}

    async def search(
        self,
        query: str,
        workspace_id: str | None = None,
        top_k: int = 4,
    ) -> list[dict[str, Any]]:
        # 无实际检索内容的查询（纯符号/空白）直接短路：RAGFlow 对这类查询可能断言报错
        if not re.search(r"[\w\u4e00-\u9fff]", query or ""):
            return []
        dataset_id = self._dataset(workspace_id) or await self.ensure_dataset()
        k = top_k or self.top_k
        try:
            data = await self._request(
                "POST",
                "/api/v1/retrieval",
                json={
                    "question": query,
                    "dataset_ids": [dataset_id],
                    "top_k": k,
                    "similarity_threshold": self.similarity_threshold,
                },
            )
        except Exception as exc:
            # 检索失败优雅降级为空结果（不 500）：问答走静态降级文案，页面不报错
            logger.warning("ragflow_retrieval_degraded", error=str(exc))
            return []
        payload = data.get("data") if isinstance(data, dict) else data
        chunks = []
        if isinstance(payload, dict):
            chunks = payload.get("chunks") or payload.get("docs") or []
        sources: list[dict[str, Any]] = []
        for raw in chunks or []:
            if not isinstance(raw, dict):
                continue
            content = raw.get("content") or raw.get("content_with_weight") or ""
            sources.append(
                {
                    "id": str(raw.get("id") or raw.get("chunk_id") or ""),
                    "document_id": str(raw.get("document_id") or ""),
                    "filename": raw.get("document_keyword") or raw.get("docnm_kwd") or raw.get("document_name") or "",
                    "title": raw.get("document_keyword") or raw.get("docnm_kwd") or "",
                    "content": content,
                    "score": raw.get("similarity") or raw.get("score") or raw.get("vector_similarity"),
                    "metadata": {
                        "dataset_id": raw.get("dataset_id"),
                        "document_id": raw.get("document_id"),
                    },
                    "raw": raw,
                }
            )
        return sources

    async def ask(
        self,
        question: str,
        workspace_id: str | None = None,
        top_k: int = 4,
    ) -> dict[str, Any]:
        """Retrieval only — workbench DeepSeek synthesizes the answer."""
        sources = await self.search(question, workspace_id=workspace_id, top_k=top_k or self.top_k)
        return {
            "answer": "",
            "sources": sources,
            "status": "ok" if sources else "empty",
            "provider": self.name,
        }
