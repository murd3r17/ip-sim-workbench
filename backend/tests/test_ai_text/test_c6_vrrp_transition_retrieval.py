"""A role-transition answer needs arbitration, failure detection and failback evidence."""
import pytest

from modules.ai_text.retrieval import expand_query, rerank
from modules.knowledge.local_provider import LocalKnowledgeProvider


@pytest.mark.parametrize('question', [
    'VRRP 的 Master 和 Backup 是怎么切换的？',
    'VRRP主备选举与故障切换有什么关系？',
])
def test_actual_corpus_transition_top_five_covers_mechanisms(tmp_path, question):
    provider = LocalKnowledgeProvider(storage_dir=tmp_path)
    expanded = expand_query(question)
    candidates = [{**hit, 'content': hit['text']} for hit in provider._search(expanded, 24)]
    selected = rerank(candidates, expanded, 6, original_query=question)
    top = '\n'.join(hit['content'] for hit in selected[:5])
    assert '值越大越优先' in top  # original textbook rule, not an injected answer
    assert 'MASTER_DOWN' in top and '超时' in top
    assert '抢占模式' in top
    assert len(selected) == 6
    assert all(any(hit is candidate for candidate in candidates) for hit in selected)


@pytest.mark.parametrize('question', [
    'VRRP报文的目的IP地址是什么？', 'VRRP虚拟MAC格式是什么？',
    'BGP 的主备怎么切换？', 'MYVRRP 的主备切换',
])
def test_unrelated_intents_keep_existing_expansion_and_ranking(question):
    assert 'MASTER_DOWN' not in expand_query(question)
    candidates = [{'content': '无关', 'score': 1}, {'content': '其他', 'score': .5}]
    assert rerank(candidates, expand_query(question), 2, original_query=question) == candidates


def test_expansion_alone_cannot_trigger_transition_promotion():
    candidates = [
        {'content': '# VRRP\n\n普通解释', 'score': 1},
        {'content': '# VRRP\n\n**Priority**：优先级值是选举依据。', 'score': .3},
    ]
    assert rerank(candidates, expand_query('VRRP主备切换'), 1,
                  original_query='VRRP报文目的地址') == candidates[:1]
