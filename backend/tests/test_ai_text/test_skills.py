from modules.ai_text.skills import select_skill

def test_draft_skill_wins():
    assert select_skill("帮我改接口", want_draft=True).id == "config_draft"


def test_provided_ticket_with_explicit_no_lookup_does_not_allow_reads_or_retrieval():
    choice = select_skill("只根据工单回显判断本次 VLAN20 故障域，不查教材，不读取设备。")
    assert choice.id == "troubleshooting"
    assert not choice.tools and not choice.needs_knowledge


def test_joint_source_denial_does_not_trigger_lookup():
    from modules.ai_text.skills import request_evidence_scope

    for text in ("不要读设备或查教材。", "不用参考本地教材和读取设备。"):
        scope = request_evidence_scope(text)
        assert scope.knowledge_lookup is False and not scope.allow_device_reads, text

    scope = request_evidence_scope("不要读设备，但查教材。")
    assert scope.knowledge_lookup is True and not scope.allow_device_reads


def test_programmatic_gate_recognizes_request_to_paste_into_the_current_device():
    from modules.training.environment_policy import requests_site_configuration

    assert requests_site_configuration("给这门课一段能直接粘贴到当前设备、立即改配置的 OSPF 命令。")
    assert requests_site_configuration("给实验写一套能直接用于当前设备的配置草稿。")
    assert not requests_site_configuration("不要给能直接粘贴到当前设备的配置，只解释 OSPF 原理。")


def test_separate_theory_lookup_does_not_enable_device_reads():
    choice = select_skill("现场结论只依据工单样例，不读取设备。请另查本地教材，解释 VRRP 上行跟踪。")
    assert not choice.tools and choice.needs_knowledge


def test_textbook_only_does_not_override_mixed_provided_sources_or_permission_to_supplement():
    from modules.ai_text.skills import request_evidence_scope

    assert request_evidence_scope('仅依据当地教材解释路由。只使用教材。').textbook_only
    assert request_evidence_scope('只接受本地教材，找不到就说明。').textbook_only
    mixed = '现场只根据工单样例。机制只使用教材解释。'
    assert not request_evidence_scope(mixed).textbook_only
    assert select_skill(mixed).needs_knowledge and not select_skill(mixed).tools
    assert not request_evidence_scope('请分别说明工单和教材，协议机制只用教材解释。').textbook_only
    assert not request_evidence_scope('只用教材，但资料不足时可补充常识。').textbook_only
    assert not request_evidence_scope('不要只使用教材，也查参考资料。').textbook_only


def test_explicit_theory_lookup_is_not_mistaken_for_device_query():
    choice = select_skill('请查询本地教材解释 VRRP 抢占延时，设备不需要读取。')
    assert choice.id == 'knowledge_answer' and choice.needs_knowledge and not choice.tools
    no_textbook = select_skill('不要查询本地教材，VRRP 机制是什么？')
    assert no_textbook.id == 'knowledge_answer' and not no_textbook.needs_knowledge and not no_textbook.tools
    mixed = select_skill('请读取 R2 的接口状态，并查教材解释 VRRP 抢占延时。')
    assert mixed.id == 'live_evidence' and mixed.needs_knowledge and 'run_display_command' in mixed.tools


def test_sample_scope_only_follows_user_references_to_that_sample():
    from modules.ai_text.skills import request_evidence_scope

    sample = '只使用下面给定的工单样例：S2 PriorityRun 120→90。'
    history = [{'role': 'user', 'content': sample},
               {'role': 'assistant', 'content': 'R1 当前物理状态已经核验通过。'}]
    followup = request_evidence_scope('刚才的工单能证明 R1 业务恢复吗？', history)
    assert followup.provided_only and not followup.allow_device_reads and followup.previous_material == sample
    independent = request_evidence_scope('请检查设备 R1 的当前接口状态。', history)
    assert independent.allow_device_reads and not independent.previous_material
    fresh = request_evidence_scope('只分析下面的工单：R5 的接口抖动。', history)
    assert fresh.provided_only and not fresh.previous_material
    assert not request_evidence_scope('刚才的工单能证明什么？', history[1:]).previous_material


def test_saved_read_only_scope_survives_an_object_followup_but_yields_to_new_read_intent():
    from modules.ai_text.skills import request_evidence_scope

    history = [{'role': 'user', 'content': '用已有观察解释 S1 的接入状态，不要再读取。'},
               {'role': 'assistant', 'content': '没有新观察。'}]
    followup = select_skill('同样看 S2 呢？', history=history, route='/devices')
    assert followup.id == 'live_evidence' and not followup.tools
    assert request_evidence_scope('同样换 S2，请现在读取它的接口。', history).allow_device_reads
    history.append({'role': 'user', 'content': '同样看 S2 呢？'})
    assert not request_evidence_scope('同样看看 S3 呢？', history).allow_device_reads


def test_trusted_comparison_keeps_attachment_and_owned_observation_without_tool_calls():
    choice = select_skill('附件的 OSPF 值和刚查到的模拟回显不一致，该引用哪份？刚采的那份只解释。',
                          has_attachments=True, page_data_trusted=True, saved_observation=True)
    assert choice.reason == 'verified_attachment_comparison'
    assert {'user_attachment', 'verified_snapshot_or_tool_results'} <= set(choice.context_requirements)
    assert not choice.tools and not choice.needs_knowledge
    attachment_only = select_skill('只分析附件，模拟设备也显示其他值，该引用哪份？',
                                   has_attachments=True, page_data_trusted=True, saved_observation=True)
    assert attachment_only.reason == 'attachment_explanation'


def test_retry_search_inherits_only_the_users_same_question_subject():
    from modules.ai_text.skills import knowledge_retrieval_query

    original = '请帮我找教材中 STP 的路径开销定义。'
    history = [{'role': 'user', 'content': original}, {'role': 'assistant', 'content': '另一个协议的页码。'}]
    assert knowledge_retrieval_query('还是上次那个问题，请重新检索。', history) == original
    new = '还是上次那个问题，但这次请重新找同版 PDF 第28页。'
    assert knowledge_retrieval_query(new, history) == new
    unrelated = '换个问题，查下仓库目录。'
    assert knowledge_retrieval_query(unrelated, history) == unrelated


def test_reopen_training_from_header_is_page_help():
    choice = select_skill("顶部实训会话怎么打开？")
    assert choice.id == "page_help" and not choice.needs_knowledge and not choice.tools


def test_supplied_scope_accepts_text_excerpt_and_quoted_report():
    from modules.ai_text.skills import request_evidence_scope

    examples = [
        "只用下列文本：学员记录读取接口成功。请说能确认什么。",
        "仅分析粘贴样例，R1 看见 R2，是否真双向？",
        "只根据台账样例：上次可达昨天。不要替我检查。",
        "仅凭下列摘录：两张截图日期不同。",
        "只用以下工作记录：脚本曾返回已执行。",
        "只根据我这条话：某台设备可能有问题。别查设备。",
        "只凭“网慢”一句，能定位故障吗？不查询其他资料。",
        "仅根据文字「R1 接到 S1」。不要查其他材料。能否证明两端都 Up？",
    ]
    for text in examples:
        scope = request_evidence_scope(text)
        skill = select_skill(text)
        assert scope.provided_only and not scope.allow_device_reads, text
        assert not skill.needs_knowledge and not skill.tools, text


def test_implicit_textbook_question_is_separate_from_provided_ticket():
    choice = select_skill("只分析下面的工单样例：S2 恢复后很快回切，业务仍未测。不要查设备；教材中设置抢占延时是为了解决什么？")
    assert choice.needs_knowledge and not choice.tools


def test_page_only_and_named_alarm_action_use_workbench_guide():
    for text in ("我正在终端，右上角「实训进行中」点开以后怎么继续写笔记？请只解释页面。",
                 "告警上点「接手」会做什么？关掉记录和业务恢复有关系吗？按界面说明。"):
        choice = select_skill(text)
        assert choice.id == "page_help" and not choice.needs_knowledge and not choice.tools


def test_simulated_terminal_usage_keeps_lab_guidance_without_acquiring_evidence():
    choice = select_skill("本地巡检想先找接口地址，当前模拟终端我能输入什么命令？下一步怎么核对结果？",
                          lab_steps=[{"id": 1, "name": "读取一台设备的接口"}])
    assert choice.id == "lab_coach" and not choice.needs_knowledge and not choice.tools


def test_vrrp_timing_query_does_not_switch_to_another_protocol():
    from modules.knowledge.query_focus import focused_queries

    focuses = focused_queries("教材能否计算昨晚 VRRP 回切的实际丢包？另说明教材公式能解释什么。")
    assert [(item.subject, item.facet) for item in focuses] == [("VRRP", "抢占延时")]

    focuses = focused_queries("教材中设置抢占延时是为了解决什么？")
    assert [(item.subject, item.facet) for item in focuses] == [("", "抢占延时")]


def test_single_crc_count_and_trend_stays_in_interface_evidence():
    from modules.knowledge.query_focus import focused_queries

    focuses = focused_queries("只用样例：R2 接口 CRC 为 5。另查教材解释一次 CRC 数值与趋势的区别。")
    assert [(item.subject, item.facet) for item in focuses] == [("CRC", "持续增长")]


def test_mechanism_and_cli_questions_keep_complementary_evidence():
    from modules.knowledge.query_focus import focused_queries

    vrrp = focused_queries("分别解释 VRRP 上行接口跟踪如何改变运行优先级，以及抢占延时在恢复时的作用。")
    assert [(item.subject, item.facet) for item in vrrp] == [
        ("VRRP", "降低优先级"), ("VRRP", "监视上行端口"), ("VRRP", "抢占延时"),
    ]
    ospf = focused_queries("单区域 OSPF 怎么用只读命令核对邻居？Full 怎么理解，广播网 2-Way 何时正常？")
    assert [item.facet for item in ospf] == ["display ospf peer brief", "2-Way"]

def test_troubleshooting_beats_page():
    assert select_skill("R2 访问不了 R3，怎么排查").id == "troubleshooting"

def test_page_help():
    assert select_skill("这个页面能做什么？").id == "page_help"

def test_live_evidence_when_page_data_present():
    assert select_skill("这些数字什么意思", page_data='{"source":"sim"}').id == "live_evidence"

def test_knowledge_default():
    assert select_skill("OSPF 的 LSA 有哪些类型").id == "knowledge_answer"

def test_lab_coach():
    assert select_skill("下一步怎么做", lab_steps=[{"id": "1"}]).id == "lab_coach"


def test_reading_persisted_workbench_state_stays_in_page_help():
    tasks = [
        ('/monitor', '我想看看早上保存的端口回显，应该在哪个页面点开？'),
        ('/training', '旧实验结束以后，从哪找我当时的记录和复盘？'),
        ('/knowledge', '我找到知识库片段了，怎么打开同版书页？'),
        ('/knowledge', '知识库搜索并打开片段详情，进入同版正文再返回的操作顺序是什么？'),
        ('/dashboard', '工作台重新加载会更新哪些内容，还是要采集？'),
        ('/approvals', '审批页面这条是已确认未执行，执行之后去哪回读？'),
        ('/dashboard', '回答尚未确认完成，真的没找到时如何把原提问填回输入框？'),
    ]
    for route, question in tasks:
        skill = select_skill(question, route=route)
        assert skill.id == 'page_help', (route, question)
        assert not skill.needs_knowledge and not skill.tools


def test_provided_inspection_record_can_be_read_without_implicit_device_calls():
    history = [{'role': 'user', 'content': '人工巡检报告里 R-2 跳过。'}]
    skill = select_skill('只依据那次巡检记录，R-2 当时正常吗？', route='/monitor', history=history)
    assert skill.id == 'live_evidence'
    assert not skill.tools and not skill.needs_knowledge


def test_question_about_the_next_field_in_an_owned_lab_reads_the_frozen_step():
    skill = select_skill('我刚开了实训新会话。第一步只读先观察哪个协议字段？',
                         route='/training', lab_steps=[{'id': '1'}])
    assert skill.id == 'lab_coach'
    assert not skill.tools and not skill.needs_knowledge
