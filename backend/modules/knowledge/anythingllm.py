"""AnythingLLM KnowledgeProvider 实现。"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from typing import Any, Optional

import httpx

from core.logger import get_logger
from modules.knowledge.provider import KnowledgeProvider

logger = get_logger("knowledge")


def _first_list(data: Any, keys: tuple[str, ...] = ("items", "documents", "results", "sources", "data", "workspaces")) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = value.get("items") or value.get("documents") or value.get("results")
                if isinstance(nested, list):
                    return [item for item in nested if isinstance(item, dict)]
    return []


class AnythingLLMKnowledgeProvider(KnowledgeProvider):
    """AnythingLLM 过渡接入实现。"""

    name = "anythingllm"

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        workspace_slug: str = "ip-ops-kb",
        workspace_id: str = "1",
        top_k: int = 4,
        similarity_threshold: float = 0.25,
        request_timeout: int = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.workspace_slug = workspace_slug
        self.workspace_id = workspace_id
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

    async def __aenter__(self) -> "AnythingLLMKnowledgeProvider":
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    def _workspace(self, workspace_id: str | None = None) -> str:
        if not workspace_id:
            return self.workspace_slug
        if workspace_id in {self.workspace_slug, self.workspace_id}:
            return self.workspace_slug
        return workspace_id

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        client = await self._ensure_client()
        headers = self._headers()
        extra_headers = kwargs.pop("headers", None)
        if extra_headers:
            headers.update(extra_headers)
        resp = await client.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
        resp.raise_for_status()
        if not resp.content:
            return {}
        return resp.json()

    @staticmethod
    def _decode_metadata(value: Any) -> dict[str, Any]:
        """AnythingLLM 的 workspace_documents.metadata 常为 JSON 字符串，统一解码为 dict。"""
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value:
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else {}
            except (ValueError, TypeError):
                return {}
        return {}

    @staticmethod
    def _pretty_doc_name(raw: dict[str, Any], metadata: dict[str, Any]) -> str:
        """生成人类可读的文档显示名。

        优先级：真实中文标题（json 内部 metadata.title）> 上传名（元数据里的 url
        文件名）> json 文件名（剔除 AnythingLLM 追加的 -{uuid}.json 后缀）。
        """
        # 1) json 内部的原始标题（如 01-内容安全过滤实验.md / core-lab-vision-full.md）
        title = metadata.get("title") or metadata.get("name") or ""
        if title:
            return str(title)
        # 2) 从 url 取真实上传文件名（metadata 里已解码出的 url）
        url = metadata.get("url") or ""
        if isinstance(url, str) and url:
            name = os.path.basename(url.replace("\\", "/"))
            if name:
                return name
        # 3) json 文件名剔除 -{uuid}.json
        raw_name = raw.get("filename") or raw.get("name") or ""
        raw_name = re.sub(r"-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.json$", "", str(raw_name))
        if raw_name.endswith(".json"):
            raw_name = raw_name[:-5]
        return raw_name or "未命名文档"

    @staticmethod
    def _normalize_document(raw: dict[str, Any]) -> dict[str, Any]:
        doc_id = (
            raw.get("docpath")
            or raw.get("location")
            or raw.get("id")
            or raw.get("document_id")
            or raw.get("doc_id")
            or raw.get("name")
            or raw.get("title")
        )
        metadata = AnythingLLMKnowledgeProvider._decode_metadata(raw.get("metadata"))
        display_name = AnythingLLMKnowledgeProvider._pretty_doc_name(raw, metadata)
        return {
            "id": str(doc_id or display_name or ""),
            "filename": display_name,
            "title": display_name,
            "size": raw.get("size") or raw.get("bytes") or raw.get("file_size"),
            "status": raw.get("status") or raw.get("state") or "ready",
            "created_at": raw.get("created_at") or raw.get("createdAt") or raw.get("updated_at"),
            "metadata": metadata,
            "raw": raw,
        }

    @staticmethod
    def _normalize_source(raw: dict[str, Any]) -> dict[str, Any]:
        metadata = raw.get("metadata") or {}
        return {
            "text": raw.get("text") or raw.get("content") or raw.get("snippet") or raw.get("chunk") or "",
            "title": (
                raw.get("title")
                or metadata.get("title")
                or raw.get("document_name")
                or raw.get("filename")
                or raw.get("source")
                or "unknown"
            ),
            "score": raw.get("score") or raw.get("similarity") or raw.get("confidence") or 0,
            "page": raw.get("page") or raw.get("page_number") or raw.get("pageNumber"),
            "metadata": metadata,
            "raw": raw,
        }

    @staticmethod
    def _default_storage_dir() -> str:
        """AnythingLLM 桌面版本地存储根目录（Windows 默认）。"""
        from core.config import get_settings

        configured = os.getenv("KNOWLEDGE_ANYTHINGLLM_STORAGE")
        if configured is None:
            configured = get_settings().knowledge_anythingllm_storage
        configured = configured.strip()
        if configured:
            return os.path.abspath(os.path.expanduser(configured))
        appdata = os.getenv("APPDATA", "")
        if appdata:
            return os.path.join(appdata, "anythingllm-desktop", "storage")
        return ""

    @staticmethod
    def _persist_upload(
        source_url: str | None,
        filename: str,
        content: bytes,
        doc_meta_id: str | None = None,
    ) -> str | None:
        """把上传文档持久化到 storage\\documents\\uploads\\，并修正 custom-documents 下对应 json 的 url。

        背景：AnythingLLM 桌面版 collector 每次启动清空 hotdir，
        而上传生成的 json url 默认指向 hotdir\\<上传名>，重启后源文件丢失、
        无法重新嵌入。本函数把源文件落到稳定目录（uploads）并改写 json url，返回新 url。
        """
        storage = AnythingLLMKnowledgeProvider._default_storage_dir()
        if not storage or not os.path.isdir(storage):
            logger.warning("anythingllm_storage_dir_not_found", storage=storage)
            return None

        uploads_dir = os.path.join(storage, "documents", "uploads")
        docs_dir = os.path.join(storage, "documents", "custom-documents")
        os.makedirs(uploads_dir, exist_ok=True)

        # AnythingLLM 对中文文件名有 bug：统一 ASCII 命名（保留可读前缀）
        safe_base = re.sub(r"[^\w\-.]", "_", os.path.splitext(filename)[0])[:60] or "doc"
        safe_name = f"{safe_base}-{doc_meta_id[:8] if doc_meta_id else 'x'}.md" if doc_meta_id else f"{safe_base}.md"
        dest = os.path.join(uploads_dir, safe_name)
        try:
            with open(dest, "wb") as fh:
                fh.write(content)
        except OSError as exc:
            logger.warning("anythingllm_upload_persist_failed", error=str(exc))
            return None

        # 修正 json url：找到 url 指向 hotdir 且与本次上传匹配的 json
        try:
            src_basename = os.path.basename((source_url or "").replace("\\", "/"))
            for jf in os.listdir(docs_dir):
                if not jf.endswith(".json"):
                    continue
                jpath = os.path.join(docs_dir, jf)
                try:
                    with open(jpath, encoding="utf-8") as fh:
                        doc = json.load(fh)
                except (ValueError, OSError):
                    continue
                url = doc.get("url") or ""
                hot_name = os.path.basename(url.replace("\\", "/"))
                if hot_name == src_basename or doc.get("title") == filename or (doc_meta_id and doc.get("id") == doc_meta_id):
                    doc["url"] = "file://" + dest
                    with open(jpath, "w", encoding="utf-8") as fh:
                        json.dump(doc, fh, ensure_ascii=False, indent=2)
                    logger.info("anythingllm_upload_json_url_fixed", json=jf, url=doc["url"])
                    break
        except OSError as exc:
            logger.warning("anythingllm_upload_json_fix_failed", error=str(exc))

        return dest

    @staticmethod
    def _remove_persisted_files(doc_id: str, workspace_doc: dict[str, Any] | None = None) -> None:
        """删除 uploads 中的持久源文件以及 custom-documents 下的 json（AnythingLLM 不会自动删）。"""
        storage = AnythingLLMKnowledgeProvider._default_storage_dir()
        if not storage or not os.path.isdir(storage):
            return
        uploads_dir = os.path.join(storage, "documents", "uploads")
        docs_dir = os.path.join(storage, "documents", "custom-documents")

        metadata = AnythingLLMKnowledgeProvider._decode_metadata((workspace_doc or {}).get("metadata"))
        # delete_ref 可能是 custom-documents/xxx.json 全路径；取 basename 做匹配
        base_doc_id = os.path.basename(doc_id.replace("\\", "/")).replace("/", "")
        marker_ids = {
            doc_id,
            base_doc_id,
            str(metadata.get("id") or ""),
            str(metadata.get("title") or ""),
        }
        marker_ids.discard("")
        for jf in os.listdir(docs_dir):
            if not jf.endswith(".json"):
                continue
            jpath = os.path.join(docs_dir, jf)
            try:
                with open(jpath, encoding="utf-8") as fh:
                    doc = json.load(fh)
            except (ValueError, OSError):
                continue
            url = doc.get("url") or ""
            if doc.get("id") in marker_ids or doc.get("title") in marker_ids or jf.startswith(base_doc_id) or base_doc_id in jf:
                m = re.match(r"file://(.+)", url)
                if m:
                    try:
                        local = m.group(1)
                        if "/" in local and "\\" not in local:
                            local = local.replace("/", os.sep)
                        if os.path.exists(local) and os.path.commonpath(
                            [os.path.abspath(local), os.path.abspath(uploads_dir)]
                        ) == os.path.abspath(uploads_dir):
                            os.remove(local)
                    except (OSError, ValueError):
                        pass
                try:
                    os.remove(jpath)
                except OSError:
                    pass
                break


    async def health_check(self) -> dict[str, Any]:
        try:
            workspaces = await self._request("GET", "/api/v1/workspaces")
            return {
                "available": True,
                "workspace_count": len(_first_list(workspaces, ("workspaces", "items", "data"))),
                "provider": self.name,
                "base_url": self.base_url,
            }
        except Exception as exc:
            logger.warning("knowledge_health_check_failed", error=str(exc))
            return {
                "available": False,
                "provider": self.name,
                "base_url": self.base_url,
                "error": str(exc),
            }

    async def get_workspace(self, workspace_id: str | None = None) -> dict[str, Any]:
        workspace = self._workspace(workspace_id)
        data = await self._request("GET", f"/api/v1/workspace/{workspace}")
        items = _first_list(data, ("workspace",))
        result = items[0] if items else data
        if not isinstance(result, dict):
            return {"id": workspace, "raw": result}
        result.setdefault("id", workspace)
        return result

    async def list_documents(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        data = await self.get_workspace(workspace_id)
        return [self._normalize_document(item) for item in _first_list(data, ("documents",))]

    async def read_document(self, workspace_id: str | None, document: dict) -> dict:
        return await asyncio.to_thread(self._read_document, document)

    def _read_document(self, document: dict) -> dict:
        from pathlib import Path, PurePosixPath
        from urllib.parse import unquote
        from .reader import DocumentReadError, document_payload, read_bounded, MAX_SOURCE_BYTES
        storage = self._default_storage_dir()
        reference = PurePosixPath(str(document['id']).replace('\\', '/'))
        # Workspace membership was checked before this call. IDs must still be
        # exact local metadata paths; no basename search or cross-provider fallback.
        if (not storage or len(reference.parts) != 2 or reference.parts[0] != 'custom-documents'
                or reference.suffix.lower() != '.json' or '..' in reference.parts):
            raise DocumentReadError('reader_unavailable', '该资料缺少可核验的持久源文件映射。')
        metadata_root = (Path(storage) / 'documents' / 'custom-documents').resolve()
        metadata_path = (metadata_root / reference.name).resolve()
        if not metadata_path.is_relative_to(metadata_root):
            raise DocumentReadError('reader_unavailable', '源文件映射不可读取。')
        try:
            with metadata_path.open('rb') as stream:
                raw_metadata = stream.read(MAX_SOURCE_BYTES + 1)
            if len(raw_metadata) > MAX_SOURCE_BYTES:
                raise ValueError('metadata too large')
            metadata = json.loads(raw_metadata)
            source_url = metadata.get('url') or ''
            if not source_url.startswith('file://'):
                raise ValueError('not a persistent file URL')
            # Existing desktop adapter stores file://D:\... as well as file:///D:/...
            source = unquote(source_url[7:])
            if os.name == 'nt' and re.match(r'^/[A-Za-z]:', source):
                source = source[1:]
            uploads = (Path(storage) / 'documents' / 'uploads').resolve()
            # Reject lexical escapes before resolve can traverse an arbitrary
            # drive/UNC path. Resolve afterward also blocks links leaving uploads.
            path = Path(os.path.abspath(source))
            if not path.is_relative_to(uploads):
                raise ValueError('outside persistent uploads')
            raw, modified = read_bounded(path, uploads)
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            raise DocumentReadError('source_unavailable', '持久源文件或映射不可读取，请管理员核对uploads与同步；不读取易失hotdir。') from exc
        return document_payload(document, raw, modified, 'anythingllm_persistent_upload')

    async def upload_document(
        self,
        workspace_id: str | None,
        filename: str,
        content: bytes,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        workspace = self._workspace(workspace_id)
        client = await self._ensure_client()
        headers = self._headers()
        data = await client.post(
            f"{self.base_url}/api/v1/document/upload",
            headers=headers,
            files={"file": (filename, content, content_type or "application/octet-stream")},
            data={"addToWorkspaces": workspace},
        )
        data.raise_for_status()
        payload = data.json() if data.content else {}
        if isinstance(payload, dict):
            payload.setdefault("filename", filename)
            # 持久化：hotdir 会被 collector 启动清空，把源文件落到 uploads 并修正 json url
            docs = payload.get("documents") or []
            doc_meta_id = docs[0].get("id") if docs and isinstance(docs[0], dict) else None
            source_url = docs[0].get("url") if docs and isinstance(docs[0], dict) else None
            try:
                # 文件 IO 放线程池：同步读写会阻塞事件循环（上传路径最明显）
                persisted = await asyncio.to_thread(
                    self._persist_upload, source_url, filename, content, doc_meta_id
                )
                if persisted:
                    payload["persisted_url"] = persisted
                    if docs and isinstance(docs[0], dict):
                        docs[0]["url"] = "file://" + persisted
            except Exception as exc:  # noqa: BLE001
                logger.warning("anythingllm_upload_persist_exception", error=str(exc))
        return payload

    async def delete_document(self, workspace_id: str | None, document_id: str) -> dict[str, Any]:
        workspace = self._workspace(workspace_id)
        # AnythingLLM deletes 需要 docpath（custom-documents/xxx.json）；兼容直接传 json 文件名
        delete_ref = document_id
        if "/" not in document_id and document_id.endswith(".json"):
            delete_ref = f"custom-documents/{document_id}"
        data = await self._request(
            "POST",
            f"/api/v1/workspace/{workspace}/update-embeddings",
            json={"deletes": [delete_ref]},
        )
        # 清理持久文件（uploads 源文件 + custom-documents json）；同样放线程池
        try:
            await asyncio.to_thread(self._remove_persisted_files, delete_ref)
        except Exception as exc:  # noqa: BLE001
            logger.warning("anythingllm_delete_cleanup_failed", error=str(exc))
        if isinstance(data, dict):
            data.setdefault("deleted", [document_id])
        return data if isinstance(data, dict) else {"deleted": [document_id], "raw": data}

    async def search(
        self,
        query: str,
        workspace_id: str | None = None,
        top_k: int = 4,
    ) -> list[dict[str, Any]]:
        workspace = self._workspace(workspace_id)
        payload = {
            "query": query,
            "topN": top_k,
            "scoreThreshold": self.similarity_threshold,
        }
        data = await self._request("POST", f"/api/v1/workspace/{workspace}/vector-search", json=payload)
        sources = _first_list(data, ("sources", "results", "items", "data"))
        if not sources and isinstance(data, dict):
            raw_text = data.get("text") or data.get("response") or data.get("answer")
            if raw_text:
                return [{
                    "text": raw_text,
                    "title": workspace,
                    "score": 0,
                    "metadata": {},
                    "raw": data,
                }]
        return [self._normalize_source(item) for item in sources]

    async def ask(
        self,
        question: str,
        workspace_id: str | None = None,
        top_k: int = 4,
    ) -> dict[str, Any]:
        workspace = self._workspace(workspace_id)
        payload = {
            "message": question,
            "mode": "chat",
        }
        data = await self._request("POST", f"/api/v1/workspace/{workspace}/chat", json=payload)
        sources = [self._normalize_source(item) for item in _first_list(data, ("sources", "results", "items", "data"))]
        answer = ""
        if isinstance(data, dict):
            answer = (
                data.get("textResponse")
                or data.get("text")
                or data.get("response")
                or data.get("answer")
                or data.get("message")
                or ""
            )
        return {
            "question": question,
            "answer": answer,
            "sources": sources,
            "workspace": workspace,
            "provider": self.name,
            "raw": data,
        }
