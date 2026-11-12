from modules.knowledge.local_provider import LocalKnowledgeProvider


def test_named_unknown_protocol_does_not_retrieve_another_protocol_by_generic_noun(tmp_path):
    corpus = tmp_path/'corpus'; corpus.mkdir()
    (corpus/'other.md').write_text('# 协议介绍\n\nL2TP协议用于隧道。OSPF协议用于内部路由。',encoding='utf8')
    provider=LocalKnowledgeProvider(corpus,tmp_path/'uploads')
    assert provider._search('AsterLink-7协议是什么？',6)==[]
    assert provider._search('OSPF 协议是什么？',6)
    assert provider._search('L2TP协议是什么？',6)
