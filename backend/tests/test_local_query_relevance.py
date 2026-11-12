from modules.knowledge.local_provider import LocalKnowledgeProvider


def provider(tmp_path):
    corpus = tmp_path / 'corpus'
    corpus.mkdir()
    (corpus / 'questions.md').write_text('# 其他实验\n\n## 思考题\n\nNETCONF 与 SNMP 有什么区别？这是什么？', encoding='utf-8')
    (corpus / 'answer.md').write_text('# IPv6\n\n## 路由器发现\n\n主机发出 RS 请求，路由器回复 RA 通告。', encoding='utf-8')
    return LocalKnowledgeProvider(corpus_dir=corpus, storage_dir=tmp_path / 'uploads')


def test_generic_question_words_cannot_make_unknown_term_a_relevant_hit(tmp_path):
    assert provider(tmp_path)._search('xyzNonexistentProtocol是什么？', 6) == []


def test_comparison_question_ranks_substantive_answer_before_unrelated_question(tmp_path):
    found = provider(tmp_path)._search('RS 和 RA 有什么区别？', 2)
    assert found and found[0]['filename'] == 'answer.md'
    assert not any(hit['filename'] == 'questions.md' for hit in found)


def test_negative_output_format_does_not_request_cli_material():
    from modules.knowledge.local_provider import _query_tokens
    terms = _query_tokens('源NAT与目的NAT有什么区别？不需要配置命令。')
    assert {'源', '目的', 'nat'} <= set(terms)
    assert not {'不需', '需要', '配置', '命令', '什么', '区别'} & set(terms)
    assert {'display', 'ip', 'interface', 'brief'} <= set(_query_tokens('display ip interface brief'))
    assert '配置' in _query_tokens('请说明如何配置 SSH')
