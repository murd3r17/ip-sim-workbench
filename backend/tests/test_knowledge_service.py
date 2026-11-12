"""KnowledgeService provider 选择测试。"""
import pytest
from unittest.mock import patch, MagicMock


class TestKnowledgeServiceFromSettings:
    def _mock_settings(self, provider="ragwebui"):
        mock = MagicMock()
        mock.knowledge_provider = provider
        mock.rag_base_url = "http://localhost:80"
        mock.rag_username = "admin"
        mock.rag_password = ""
        mock.rag_default_kb_id = "1"
        mock.knowledge_top_k = 4
        mock.knowledge_similarity_threshold = 0.25
        mock.knowledge_request_timeout = 60
        mock.knowledge_max_upload_mb = 10
        mock.knowledge_max_upload_files = 20
        mock.knowledge_base_url = "http://localhost:3001"
        mock.knowledge_api_key = ""
        mock.knowledge_workspace_slug = "ip-ops-kb"
        mock.knowledge_workspace_id = "1"
        mock.knowledge_dataset_id = ""
        mock.knowledge_corpus_dir = ""
        return mock

    def test_selects_ragwebui_provider(self):
        with patch("modules.knowledge.service.get_settings", return_value=self._mock_settings("ragwebui")):
            from modules.knowledge.service import KnowledgeService
            svc = KnowledgeService.from_settings()
            assert svc.provider.name == "ragwebui"

    def test_selects_anythingllm_provider(self):
        with patch("modules.knowledge.service.get_settings", return_value=self._mock_settings("anythingllm")):
            from modules.knowledge.service import KnowledgeService
            svc = KnowledgeService.from_settings()
            assert svc.provider.name == "anythingllm"

    def test_selects_ragflow_provider(self):
        mock = self._mock_settings("ragflow")
        mock.knowledge_base_url = "http://127.0.0.1:9380"
        mock.knowledge_workspace_slug = "huawei-ip-ops"
        with patch("modules.knowledge.service.get_settings", return_value=mock):
            from modules.knowledge.service import KnowledgeService
            svc = KnowledgeService.from_settings()
            assert svc.provider.name == "ragflow"

    def test_unknown_provider_raises(self):
        with patch("modules.knowledge.service.get_settings", return_value=self._mock_settings("unknown")):
            from modules.knowledge.service import KnowledgeService
            with pytest.raises(ValueError, match="未知"):
                KnowledgeService.from_settings()


class _OverReturningProvider:
    """模拟返回超过 top_k 条结果的 provider（RAGFlow v0.26 retrieval 的实际行为）。"""

    name = "fake"

    async def search(self, query, workspace_id=None, top_k=4):
        return [{"id": i, "content": f"doc{i}"} for i in range(top_k + 5)]

    async def ask(self, question, workspace_id=None, top_k=4):
        return {
            "answer": "fake-answer",
            "sources": [{"id": i, "content": f"doc{i}"} for i in range(top_k + 5)],
            "status": "ok",
            "provider": self.name,
        }


class TestKnowledgeServiceTopK:
    """top_k 必须在契约层生效：provider 返回过多 source 时截断。"""

    def _service(self):
        from modules.knowledge.service import KnowledgeService, UploadPolicy
        policy = UploadPolicy(
            allowed_extensions=[".md"],
            allowed_content_types=["text/markdown"],
            max_file_size_mb=10,
            max_upload_files=10,
        )
        return KnowledgeService(provider=_OverReturningProvider(), policy=policy)

    @pytest.mark.asyncio
    async def test_search_truncates_to_top_k(self):
        svc = self._service()
        sources = await svc.search("q", top_k=3)
        assert len(sources) == 3

    @pytest.mark.asyncio
    async def test_ask_truncates_sources_to_top_k(self):
        svc = self._service()
        result = await svc.ask("q", top_k=3)
        assert len(result["sources"]) == 3
        assert result["answer"] == "fake-answer"

    @pytest.mark.asyncio
    async def test_ask_degrades_when_provider_down(self):
        from modules.knowledge.service import KnowledgeService, UploadPolicy

        class _DownProvider:
            name = "fake"

            async def ask(self, question, workspace_id=None, top_k=4):
                raise ConnectionError("All connection attempts failed")

        policy = UploadPolicy(
            allowed_extensions=[".md"],
            allowed_content_types=["text/markdown"],
            max_file_size_mb=10,
            max_upload_files=10,
        )
        svc = KnowledgeService(provider=_DownProvider(), policy=policy)
        result = await svc.ask("q", top_k=3)
        assert result["status"] == "degraded"
        assert result["sources"] == []
        assert result["answer"] == ""

    @pytest.mark.asyncio
    async def test_default_top_k_used_when_none(self):
        svc = self._service()
        mock_settings = MagicMock()
        mock_settings.knowledge_top_k = 2
        with patch("modules.knowledge.service.get_settings", return_value=mock_settings):
            sources = await svc.search("q")
            assert len(sources) == 2
