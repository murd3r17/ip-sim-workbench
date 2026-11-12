from modules.ai_text.retrieval import rerank, _configuration_coverage, expand_query


def hit(text, score):
    return {'content':text, 'score':score}


def test_configuration_question_keeps_existing_procedure_before_generic_catalog():
    hits=[hit('# 安全\n## 原则\nSSH 加密访问与安全加固。',1),
          hit('# SSH基本配置\n## 本机防攻击\n### 课程目录\n介绍SSH配置。',.9),
          hit('# 安全\n## SSH 基本配置\n### 思考题\n如何配置SSH？',.8),
          hit('# 安全\n## SSH 基本配置\n### SSH 配置示例\n1. 使能设备的SSH服务。\n2. 配置用户认证。',.3)]
    chosen=rerank(hits,'设备安全加固里 SSH 应该怎么配？',2)
    assert chosen[0] is hits[0]
    assert chosen[1] is hits[3]


def test_configuration_coverage_is_not_ssh_specific():
    hits=[hit('# OSPF\n## OSPF 简介\nOSPF 是链路状态协议。',1),
          hit('# OSPF\n## OSPF 报文\nHello用于发现邻居。',.8),
          hit('# OSPF\n## OSPF 基本配置\n进入OSPF视图，配置区域与接口。',.2)]
    assert rerank(hits,'如何配置 OSPF？',2)==[hits[0],hits[2]]


def test_concept_and_multi_protocol_questions_keep_existing_order():
    hits=[hit('# SSH\n## SSH 原理\nSSH用于安全远程登录。',1),
          hit('# SSH\n## CLI 简介\n介绍SSH操作。',.8),
          hit('# SSH\n## SSH 基本配置\n配置SSH用户和认证。',.2)]
    for question in ['SSH 是什么？','SSH 无需配置，解释它的原理']:
        assert rerank(hits,question,2)==hits[:2]
    assert _configuration_coverage(hits,'OSPF 和 BGP 如何配置？',2) is hits


def test_real_corpus_security_configuration_question_keeps_authentication_procedure(tmp_path):
    from modules.knowledge.local_provider import LocalKnowledgeProvider, DEFAULT_CORPUS_DIR
    provider=LocalKnowledgeProvider(corpus_dir=DEFAULT_CORPUS_DIR,storage_dir=tmp_path/'uploads')
    question='设备安全加固里 SSH 应该怎么配？'
    # One existing search of24 candidates, then the unchanged six-result budget.
    candidates=provider._search(expand_query(question),24)
    chosen=rerank(candidates,expand_query(question),6,original_query=question)
    assert len(chosen)==6
    assert any('配置 SSH 用户的认证方式' in row['text'] for row in chosen)


def test_authentication_expansion_does_not_rewrite_comparison_or_negated_howto():
    for question in ['SSH和OSPF如何配置？','SSH无需配置，解释原理','SSH不需要配置命令，说明作用']:
        assert '用户 认证 公钥' not in expand_query(question)
