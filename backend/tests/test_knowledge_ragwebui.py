"""RAGWebUIProvider 单元测试。"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestRAGWebUIProvider:
    @pytest.fixture
    def provider(self):
        from modules.knowledge.ragwebui import RAGWebUIProvider
        return RAGWebUIProvider(
            base_url="http://localhost:80",
            username="admin",
            password="test123",
            workspace_id="1",
            top_k=4,
            similarity_threshold=0.25,
        )

    @pytest.mark.asyncio
    async def test_health_check_success(self, provider):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        provider._client = mock_client
        result = await provider.health_check()
        assert result["available"] is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, provider):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
        provider._client = mock_client
        result = await provider.health_check()
        assert result["available"] is False

    @pytest.mark.asyncio
    async def test_search_returns_normalized_sources(self, provider):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": [{"content": "snippet", "score": 0.9, "title": "doc-a"}]}
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)
        provider._client = mock_client
        provider.jwt_token = "fake-token"
        provider._token_expires_at = 9999999999
        results = await provider.search("怎么配置接口", top_k=3)
        assert len(results) == 1
        assert results[0]["text"] == "snippet"

    @pytest.mark.asyncio
    async def test_ask_returns_answer_and_sources(self, provider):
        mock_search_resp = MagicMock()
        mock_search_resp.json.return_value = {"results": [{"content": "answer", "title": "kb"}]}
        mock_search_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_search_resp)
        provider._client = mock_client
        provider.jwt_token = "fake-token"
        provider._token_expires_at = 9999999999
        result = await provider.ask("测试问题", top_k=3)
        assert result["answer"] != ""
        assert len(result["sources"]) >= 1

    @pytest.mark.asyncio
    async def test_login_obtains_jwt(self, provider):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "eyJhbGciOiJIUzI1NiJ9.eyJleHAiOjk5OTk5OTk5OTl9.test"}
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        provider._client = mock_client
        await provider.login()
        assert provider.jwt_token == "eyJhbGciOiJIUzI1NiJ9.eyJleHAiOjk5OTk5OTk5OTl9.test"

    @pytest.mark.asyncio
    async def test_upload_document(self, provider):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"doc_id": "123"}
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        provider._client = mock_client
        provider.jwt_token = "fake-token"
        provider._token_expires_at = 9999999999
        result = await provider.upload_document("1", "test.md", b"# test")
        assert "doc_id" in result

    @pytest.mark.asyncio
    async def test_delete_document(self, provider):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"deleted": True}
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)
        provider._client = mock_client
        provider.jwt_token = "fake-token"
        provider._token_expires_at = 9999999999
        result = await provider.delete_document("1", "doc-123")
        assert result["deleted"] is True

    @pytest.mark.asyncio
    async def test_list_documents(self, provider):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"documents": [{"id": "1", "filename": "test.md"}]}
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)
        provider._client = mock_client
        provider.jwt_token = "fake-token"
        provider._token_expires_at = 9999999999
        docs = await provider.list_documents("1")
        assert len(docs) == 1

    @pytest.mark.asyncio
    async def test_degradation_when_unavailable(self, provider):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("unreachable"))
        provider._client = mock_client
        result = await provider.health_check()
        assert result["available"] is False
        assert "error" in result
