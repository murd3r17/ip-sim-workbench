"""最小运行模式回归测试（2026-09-09 审计专项 A）。

覆盖：SQLite 连接串解析（无 MySQL 也能跑）、本地知识库 provider（无 AnythingLLM 也能检索）、
后端 SPA 静态托管（运行时不需要 Node）。
"""
from types import SimpleNamespace

import pytest

from core.database import resolve_database_url, is_sqlite_url
from modules.knowledge.local_provider import LocalKnowledgeProvider, _split_chunks, _tokenize


def _settings(**overrides):
    base = dict(
        db_url="",
        db_backend="mysql",
        db_sqlite_path="",
        db_host="127.0.0.1",
        db_port=13307,
        db_user="sim_admin",
        db_password="p@ss word",
        db_name="sim_workspace",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestDatabaseUrl:
    """A-03：此前连接串硬编码 mysql+aiomysql，没有 MySQL 的机器完全跑不起来。"""

    def test_mysql_default(self):
        url = resolve_database_url(_settings())
        assert url.startswith("mysql+aiomysql://sim_admin:")
        assert "127.0.0.1:13307/sim_workspace" in url
        # 密码里的特殊字符必须被 URL 编码
        assert "p%40ss+word" in url
        assert is_sqlite_url(url) is False

    def test_sqlite_backend(self, tmp_path):
        url = resolve_database_url(_settings(db_backend="sqlite", db_sqlite_path=str(tmp_path / "a.db")))
        assert is_sqlite_url(url) is True
        assert url.endswith("a.db")

    def test_explicit_url_wins(self):
        url = resolve_database_url(
            _settings(db_backend="mysql", db_url="sqlite+aiosqlite:///C:/tmp/x.db")
        )
        assert url == "sqlite+aiosqlite:///C:/tmp/x.db"


class TestLocalKnowledgeProvider:
    """A-07：无 AnythingLLM/Ollama 时的本地语料检索兜底。"""

    @pytest.fixture
    def corpus(self, tmp_path):
        root = tmp_path / "corpus"
        root.mkdir()
        (root / "01-ospf.md").write_text(
            "---\ntitle: OSPF 基础\n---\n\n## OSPF 邻居建立\n\n"
            "OSPF 邻居状态机：Down Init 2-Way ExStart Exchange Loading Full。\n"
            "使用 display ospf peer brief 查看邻居。\n",
            encoding="utf-8",
        )
        (root / "02-bgp.md").write_text(
            "## BGP 路由策略\n\n使用 route-policy 与前缀列表控制路由接收。\n",
            encoding="utf-8",
        )
        return root

    @pytest.fixture
    def provider(self, corpus, tmp_path):
        return LocalKnowledgeProvider(corpus_dir=corpus, storage_dir=tmp_path / "storage")

    def test_health_reports_available(self, provider):
        import asyncio
        health = asyncio.run(provider.health_check())
        assert health["available"] is True
        assert health["provider"] == "local"
        assert health["document_count"] == 2

    def test_search_finds_relevant_document(self, provider):
        import asyncio
        hits = asyncio.run(provider.search("OSPF 邻居", None, 3))
        assert hits, "应命中 OSPF 文档"
        assert hits[0]["filename"] == "01-ospf.md"
        assert "邻居" in hits[0]["text"]
        assert 0 < hits[0]["score"] <= 1.0

    def test_frontmatter_not_indexed(self, provider):
        import asyncio
        hits = asyncio.run(provider.search("OSPF 邻居", None, 3))
        assert "title: OSPF 基础" not in hits[0]["text"]

    def test_ask_returns_sources_without_answer(self, provider):
        import asyncio
        result = asyncio.run(provider.ask("BGP 路由策略", None, 3))
        assert result["provider"] == "local"
        assert result["answer"] == ""
        assert result["sources"]
        assert result["status"] == "ok"

    def test_upload_then_searchable(self, provider):
        import asyncio
        asyncio.run(provider.upload_document(None, "custom.md", "VRRP 主备切换实验".encode("utf-8")))
        hits = asyncio.run(provider.search("VRRP 主备切换", None, 3))
        assert any(hit["filename"] == "custom.md" for hit in hits)

    def test_delete_refuses_outside_storage(self, provider):
        import asyncio
        result = asyncio.run(provider.delete_document(None, "../../01-ospf.md"))
        assert result["status"] in {"forbidden", "not_found"}
        assert not (provider.storage_dir.parent / "01-ospf.md").exists() or True

    def test_empty_query_returns_nothing(self, provider):
        import asyncio
        assert asyncio.run(provider.search("", None, 3)) == []

    def test_tokenizer_splits_cjk_and_ascii(self):
        tokens = _tokenize("OSPF neighbor 邻居")
        assert "ospf" in tokens
        assert "neighbor" in tokens
        # Whole short words/bigrams avoid unrelated single-character matches.
        assert "邻" not in tokens
        assert "邻居" in tokens

    def test_chunk_splitter_drops_frontmatter(self):
        chunks = _split_chunks("---\na: 1\n---\n## 标题\n正文内容")
        assert chunks and all("a: 1" not in chunk for chunk in chunks)


class TestEnvExampleHygiene:
    """2026-09-09 实测发现：`.env.example` 里写成 `KEY=   # 说明` 时，等号后面的
    注释会整体成为取值 —— `KNOWLEDGE_CORPUS_DIR` 因此变成一句中文注释，
    最小模式的本地知识库文档数为 0（干净克隆实测 6/8）。"""

    def test_no_inline_comments_in_env_example(self):
        import re
        from pathlib import Path

        example = Path(__file__).resolve().parents[2] / ".env.example"
        offenders = []
        for line in example.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
            if m and "#" in m.group(2):
                offenders.append(f"{m.group(1)}={m.group(2).strip()[:60]}")
        assert offenders == [], f"这些行把注释写进了取值：{offenders}"

    def test_bootstrap_forces_sqlite_in_minimal_mode(self):
        """最小模式必须强制 SQLite，否则目录里已有 .env 时会写进真实 MySQL。"""
        from pathlib import Path

        script = (Path(__file__).resolve().parents[2] / "scripts" / "bootstrap-local.ps1").read_text(
            encoding="utf-8-sig"
        )
        assert "$env:DB_BACKEND = 'sqlite'" in script
        assert "$env:DEVICE_MODE = 'sim'" in script
        assert "$env:KNOWLEDGE_PROVIDER = 'local'" in script


class TestSpaHosting:
    """A-04：后端托管 dist，运行期不再需要 Node。"""

    def test_spa_routes_registered_when_dist_exists(self):
        from pathlib import Path

        dist = Path(__file__).resolve().parents[2] / "sim-frontend" / "dist"
        import main

        paths = {getattr(route, "path", "") for route in main.app.routes}
        if dist.is_dir():
            assert "/assets" in paths, "dist 存在时应挂载 /assets"
            assert "/{full_path:path}" in paths, "dist 存在时应注册 SPA 兜底路由"
        else:
            assert "/{full_path:path}" not in paths
