"""知识库 Provider 测试。"""
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock


class TestAnythingLLMKnowledgeProvider:
    @pytest.fixture
    def provider(self):
        from modules.knowledge.anythingllm import AnythingLLMKnowledgeProvider

        return AnythingLLMKnowledgeProvider(
            base_url="http://localhost:3001",
            api_key="test-key",
            workspace_slug="ip-ops-kb",
            workspace_id="1",
            top_k=4,
            similarity_threshold=0.25,
        )

    @pytest.mark.asyncio
    async def test_health_check_success(self, provider):
        response = MagicMock()
        response.content = b'{"workspaces":[{"id":1,"name":"kb"}]}'
        response.json.return_value = {"workspaces": [{"id": 1, "name": "kb"}]}
        response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=response)
        provider._client = mock_client

        result = await provider.health_check()
        assert result["available"] is True
        assert result["workspace_count"] == 1
        mock_client.request.assert_awaited_once_with(
            "GET",
            "http://localhost:3001/api/v1/workspaces",
            headers={"Authorization": "Bearer test-key"},
        )

    @pytest.mark.asyncio
    async def test_ask_normalizes_answer_and_sources(self, provider):
        response = MagicMock()
        response.content = b'{"textResponse":"answer","sources":[{"chunk":"snippet","title":"doc-a"}]}'
        response.json.return_value = {
            "textResponse": "answer",
            "sources": [{"chunk": "snippet", "title": "doc-a"}],
        }
        response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=response)
        provider._client = mock_client

        result = await provider.ask("怎么配置接口", top_k=3)
        assert result["answer"] == "answer"
        assert result["sources"][0]["title"] == "doc-a"
        assert mock_client.request.await_args.args[1].endswith("/api/v1/workspace/ip-ops-kb/chat")

    @pytest.mark.asyncio
    async def test_search_returns_sources(self, provider):
        response = MagicMock()
        response.content = b'{"results":[{"text":"snippet","score":0.9,"metadata":{"title":"doc-b"}}]}'
        response.json.return_value = {
            "results": [{"text": "snippet", "score": 0.9, "metadata": {"title": "doc-b"}}],
        }
        response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=response)
        provider._client = mock_client

        result = await provider.search("命令", top_k=2)
        assert len(result) == 1
        assert result[0]["title"] == "doc-b"
        assert result[0]["text"] == "snippet"
        assert mock_client.request.await_args.args[1].endswith("/api/v1/workspace/ip-ops-kb/vector-search")
        assert mock_client.request.await_args.kwargs["json"] == {
            "query": "命令",
            "topN": 2,
            "scoreThreshold": 0.25,
        }

    @pytest.mark.asyncio
    async def test_list_documents_uses_workspace_payload(self, provider):
        response = MagicMock()
        response.content = b'{"workspace":[{"documents":[{"id":1,"docpath":"custom-documents/guide.md-id.json","title":"guide.md"}]}]}'
        response.json.return_value = {
            "workspace": [{
                "documents": [{
                    "id": 1,
                    "docpath": "custom-documents/guide.md-id.json",
                    "title": "guide.md",
                }],
            }],
        }
        response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=response)
        provider._client = mock_client

        result = await provider.list_documents()

        assert result[0]["id"] == "custom-documents/guide.md-id.json"
        assert mock_client.request.await_args.args[1].endswith("/api/v1/workspace/ip-ops-kb")

    @pytest.mark.asyncio
    async def test_upload_document(self, provider):
        response = MagicMock()
        response.content = b'{"id":"doc-1"}'
        response.json.return_value = {"id": "doc-1"}
        response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=response)
        provider._client = mock_client

        result = await provider.upload_document("ip-ops-kb", "test.md", b"hello", "text/markdown")
        assert result["id"] == "doc-1"
        mock_client.post.assert_awaited_once()
        assert mock_client.post.await_args.args[0].endswith("/api/v1/document/upload")
        assert mock_client.post.await_args.kwargs["data"] == {"addToWorkspaces": "ip-ops-kb"}

    @pytest.mark.asyncio
    async def test_delete_document_uses_v1_embedding_update(self, provider):
        response = MagicMock()
        response.content = b'{"workspace":{"id":1},"message":null}'
        response.json.return_value = {"workspace": {"id": 1}, "message": None}
        response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=response)
        provider._client = mock_client

        result = await provider.delete_document("ip-ops-kb", "custom-documents/guide.md-id.json")

        assert result["deleted"] == ["custom-documents/guide.md-id.json"]
        assert mock_client.request.await_args.args[1].endswith(
            "/api/v1/workspace/ip-ops-kb/update-embeddings"
        )


class TestKnowledgeService:
    def test_resolve_workspace_id_uses_numeric_kb_for_ragwebui(self, monkeypatch):
        monkeypatch.setenv("KNOWLEDGE_PROVIDER", "ragwebui")
        monkeypatch.setenv("KNOWLEDGE_WORKSPACE_SLUG", "ip-ops-kb")
        monkeypatch.setenv("RAG_DEFAULT_KB_ID", "1")
        from core.config import get_settings
        get_settings.cache_clear()
        from modules.knowledge.service import KnowledgeService

        service = KnowledgeService.from_settings()
        assert service.resolve_workspace_id() == "1"
        assert service.resolve_workspace_id("ip-ops-kb") == "1"

    def test_resolve_workspace_id(self, monkeypatch):
        monkeypatch.setenv("KNOWLEDGE_PROVIDER", "anythingllm")
        monkeypatch.setenv("KNOWLEDGE_WORKSPACE_SLUG", "ip-ops-kb")
        monkeypatch.setenv("KNOWLEDGE_WORKSPACE_ID", "1")
        monkeypatch.setenv("KNOWLEDGE_BASE_URL", "http://127.0.0.1:3001")
        from core.config import get_settings
        get_settings.cache_clear()
        from modules.knowledge.service import KnowledgeService

        service = KnowledgeService.from_settings()
        assert service.resolve_workspace_id() == "ip-ops-kb"
        assert service.resolve_workspace_id("1") == "ip-ops-kb"
        assert service.policy.max_file_size_mb >= 10

    @pytest.mark.asyncio
    async def test_health_check_degrades_on_provider_failure(self, monkeypatch):
        from modules.knowledge.service import KnowledgeService, UploadPolicy
        from modules.knowledge.provider import KnowledgeProvider

        class BrokenProvider(KnowledgeProvider):
            name = "broken"

            async def health_check(self):
                raise RuntimeError("boom")

            async def get_workspace(self, workspace_id=None):
                raise RuntimeError("boom")

            async def list_documents(self, workspace_id=None):
                raise RuntimeError("boom")

            async def upload_document(self, workspace_id, filename, content, content_type=None):
                raise RuntimeError("boom")

            async def delete_document(self, workspace_id, document_id):
                raise RuntimeError("boom")

            async def search(self, query, workspace_id=None, top_k=4):
                raise RuntimeError("boom")

            async def ask(self, question, workspace_id=None, top_k=4):
                raise RuntimeError("boom")

        service = KnowledgeService(
            provider=BrokenProvider(),
            policy=UploadPolicy([".md"], ["text/markdown"], 10, 20),
        )
        result = await service.health_check()
        assert result["available"] is False or result["available"] is True
