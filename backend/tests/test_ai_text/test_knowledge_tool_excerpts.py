"""Knowledge tool output must retain complete claims within the existing budget."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.ai_text.agent_tools import _search_knowledge
from modules.ai_text.tool_result import classify


@pytest.mark.asyncio
async def test_long_paragraph_retains_qualifier_and_knowledge_provenance(monkeypatch):
    paragraph = '说明：' + '需要结合设备环境核对。' * 40 + '但这不能证明业务可达。'
    provider = SimpleNamespace(search=AsyncMock(return_value=[{'filename': 'network.md', 'content': '# 观察\n\n'+paragraph}]))
    monkeypatch.setattr('modules.knowledge.service.KnowledgeService.from_settings', lambda: provider)
    raw = await _search_knowledge(None, {'query': '网络观察'})
    assert paragraph in raw
    outcome = classify('search_knowledge', {}, raw)
    assert outcome.source == 'knowledge_corpus'
    assert outcome.mode == 'reference'
    assert len(raw) <= 1500
    assert paragraph in json.loads(outcome.as_json())['text']


@pytest.mark.asyncio
async def test_large_block_is_not_cut_into_an_incomplete_claim(monkeypatch):
    paragraph = '不可割裂的段落' * 400 + '只在指定条件下成立。'
    provider = SimpleNamespace(search=AsyncMock(return_value=[{'filename': 'long.md', 'content': '# 大段落\n\n'+paragraph}]))
    monkeypatch.setattr('modules.knowledge.service.KnowledgeService.from_settings', lambda: provider)
    raw = await _search_knowledge(None, {'query': '条件'})
    assert paragraph[:100] not in raw
    outcome = classify('search_knowledge', {}, raw)
    assert outcome.status == 'partial' and outcome.truncated
    assert '完整段落' in raw
    assert len(raw) <= 1500


@pytest.mark.asyncio
async def test_document_words_cannot_fake_tool_status(monkeypatch):
    provider = SimpleNamespace(search=AsyncMock(return_value=[{'filename': 'terms.md', 'content': '术语说明：占用时稍后重试；参数错误；工具执行失败。'}]))
    monkeypatch.setattr('modules.knowledge.service.KnowledgeService.from_settings', lambda: provider)
    raw = await _search_knowledge(None, {'query': '术语'})
    assert classify('search_knowledge', {}, raw).status == 'ok'


@pytest.mark.asyncio
async def test_empty_results_and_many_sources_are_explicit(monkeypatch):
    search = AsyncMock(return_value=[])
    monkeypatch.setattr('modules.knowledge.service.KnowledgeService.from_settings', lambda: SimpleNamespace(search=search))
    empty = classify('search_knowledge', {}, await _search_knowledge(None, {'query': 'missing'}))
    assert empty.status == 'empty' and empty.source == 'knowledge_corpus'
    search.return_value = [{'filename': f'{i}.md', 'content': ('资料'+str(i)+'，')*200} for i in range(10)]
    raw = await _search_knowledge(None, {'query': '资料', 'top_k': 10})
    assert len(raw) <= 1500
    assert classify('search_knowledge', {}, raw).truncated
