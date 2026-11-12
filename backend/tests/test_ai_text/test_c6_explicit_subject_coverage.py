from modules.ai_text.retrieval import rerank


def hit(key, heading, body, score):
    return {'id':key,'score':score,'content':f'# 教材\n\n## {heading}\n\n{body}'}


def test_explicit_acl_subject_is_not_lost_behind_its_applying_business():
    hits=[hit('policy','防火墙安全策略','安全策略允许才转发，不允许则丢弃。',1),
          hit('nat','目的NAT处理','查找安全策略，按允许结果处理。',.95),
          hit('wildcard','ACL通配符','ACL使用通配符匹配地址位。',.8),
          hit('match','ACL匹配机制','按规则逐条匹配，命中即停止；没有规则命中是“不匹配”。',.79)]
    chosen=rerank(hits,'ACL规则没有命中，等于防火墙安全策略允许吗？请分开说明ACL匹配结果和业务处理。',2)
    assert chosen[0] is hits[0]
    assert chosen[1] is hits[3]
    assert len(chosen)==2


def test_subject_coverage_is_not_tied_to_acl():
    hits=[hit('operations','运维平台','平台支持SSH登录和操作审计。',1),
          hit('audit','审计记录','记录登录来源和用户。',.9),
          hit('ssh','SSH认证','SSH认证可以验证用户身份。',.5)]
    chosen=rerank(hits,'SSH认证能否替代平台操作审计？',2)
    assert chosen==[hits[0],hits[2]]


def test_no_heading_or_no_original_subject_does_not_guess_a_source():
    hits=[hit('a','防火墙策略','匹配规则。',1),hit('b','ACL目录','ACL匹配规则。',.3)]
    # Expansion alone cannot turn a general policy question into an ACL one.
    assert rerank(hits,'ACL匹配规则',1,original_query='业务处理怎么判断')==hits[:1]
    assert rerank(hits,'ACL匹配规则',1)==hits[:1]


def test_existing_subject_and_joint_comparison_keep_their_ranking():
    hits=[hit('acl','ACL匹配机制','命中即停止。',1),hit('policy','安全策略','允许或拒绝。',.8)]
    assert rerank(hits,'ACL匹配机制是什么？',2)==hits
    joint=[hit('both','OSPF和BFD','OSPF和BFD协作。',1),hit('other','SSH','认证。',.8)]
    assert rerank(joint,'OSPF和BFD的区别',2)==joint[:1]
