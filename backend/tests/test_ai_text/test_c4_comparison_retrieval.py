from modules.ai_text.retrieval import rerank


def hit(key, body, score):
    return {'id': key, 'content': body, 'score': score}


def test_comparison_covers_each_named_subject_from_existing_candidates():
    candidates = [
        hit('source', '# 源NAT与目的NAT\n## 源NAT\n转换源地址。', 1),
        hit('source-extra', '# 源NAT与目的NAT\n## 源NAT\n源NAT配置示例。', .9),
        hit('destination', '# 源NAT与目的NAT\n## 目的NAT\n转换目的地址。', .5)]
    result = rerank(candidates, '源NAT和目的NAT的区别', 2)
    assert [h['id'] for h in result] == ['source', 'destination']
    assert result[1] is candidates[2]  # exact source identity/text retained


def test_original_question_not_expansion_controls_comparison():
    candidates = [hit('a', '## 源NAT\n源NAT', 1), hit('b', '## 源NAT\n源NAT', .9), hit('c', '## 目的NAT\n目的NAT', .5)]
    result = rerank(candidates, '源NAT和目的NAT的区别', 2, original_query='配置源NAT')
    assert [h['id'] for h in result] == ['a', 'b']


def test_shared_book_heading_and_partial_english_words_are_not_aspect_evidence():
    candidates = [
        hit('first', '# RS和RA\n## Router说明\n路由器。', 1),
        hit('ra', '# RS和RA\n## RA\n路由器通告。', .9),
        hit('partial', '# RS和RA\n## ROUTERS\nThe routers advertise.', .5)]
    assert [h['id'] for h in rerank(candidates, 'RS和RA的区别', 2)] == ['first', 'ra']


def test_missing_subject_or_too_small_budget_does_not_guess_or_expand_count():
    candidates = [hit('first', '## 源NAT\n源NAT', 1), hit('second', '## 目的NAT\n目的NAT', .9)]
    assert len(rerank(candidates, '源NAT和目的NAT的区别', 1)) == 1
    assert rerank(candidates, '源NAT和不存在概念的区别', 2) == candidates


def test_already_jointly_covered_short_acronyms_do_not_promote_another_domain():
    candidates = [hit('discovery', '## 路由器发现\n主机发送 RS，路由器发送 RA。', 1),
                  hit('parameters', '## 前缀参数\nRA 通告链路参数。', .9),
                  hit('certificate', '## RA\n证书注册审批机构。', .3)]
    assert [h['id'] for h in rerank(candidates, 'RS和RA的区别', 2)] == ['discovery', 'parameters']
    # The same guard is general to short acronyms, not hard-coded to IPv6.
    candidates = [hit('pki', '## PKI\nCA 签发证书，RA 审核申请。', 1),
                  hit('revoke', '## 证书撤销\n由 CA 更新。', .9),
                  hit('ipv6', '## RA\n路由器通告。', .3)]
    assert [h['id'] for h in rerank(candidates, 'CA与RA的区别', 2)] == ['pki', 'revoke']
