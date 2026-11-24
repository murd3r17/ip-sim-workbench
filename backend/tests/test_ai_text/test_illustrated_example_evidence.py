from modules.ai_text.example_scope import exclude_conflicting_examples, illustrated_example, select_illustrated_evidence


def source(number, text, *, document='experiment-a', title='OSPF 邻接实验'):
    return {
        'document_id': document, 'document_version': 'edition-sha', 'source_id': str(number),
        'page': number, 'title': title, 'content': text,
    }


QUESTION = '图中 R4 的 OSPF 回显在恢复后显示什么？能确认接收端也已经完成验证吗？'


def test_same_example_retains_the_observation_and_its_evidence_boundary():
    actual = source(3, '恢复后，R4 接收端回显显示邻居为 Full。')
    boundary = source(4, '恢复后，R4 接收端仍需核对两个方向同一时点的记录。')
    earlier = source(1, '恢复前，R4 接收端回显显示邻居为 Down。')
    planned = source(2, '恢复后预期状态：R4 接收端预计进入 Full。')
    duplicate = source(5, actual['content'])
    wrong = source(6, '恢复后 R7 接收端回显显示邻居为 Full。', document='experiment-b')
    selected, notice = select_illustrated_evidence(illustrated_example(QUESTION), [earlier, planned, actual, boundary, duplicate, wrong])
    assert selected == [actual, boundary]
    assert notice == ''


def test_missing_observation_keeps_the_known_limit_and_warns():
    boundary = source(4, '恢复后，R4 接收端仍需核对两个方向同一时点的记录。')
    suggestion = source(5, '恢复后，R4 接收端建议查看邻居回显。')
    selected, notice = select_illustrated_evidence(illustrated_example(QUESTION), [boundary, suggestion])
    assert selected == [boundary]
    assert '实际读回' in notice


def test_same_labels_in_distinct_examples_require_a_source_location():
    actual = source(3, '恢复后，R4 接收端回显显示邻居为 Full。')
    alternative = source(4, '恢复后，R4 接收端回显显示邻居为 Down。', document='experiment-b')
    chosen, notice = select_illustrated_evidence(illustrated_example(QUESTION), [actual, alternative])
    assert chosen == []
    assert '多处' in notice

    competing = source(5, alternative['content'])
    chosen, notice = select_illustrated_evidence(illustrated_example(QUESTION), [actual, competing])
    assert chosen == []
    assert '多处' in notice


def test_unscoped_learning_and_live_asks_do_not_trigger_example_filtering():
    assert illustrated_example('解释 OSPF 邻居 Full 表示什么，能否证明网段互通？') is None
    assert illustrated_example('我这边 R4 的 OSPF 回显里，恢复后实际是哪种状态？') is None
    assert illustrated_example('比较两个不同实验中 R4 的 OSPF 读回结果。') is None
    assert illustrated_example('恢复前 R4 的 BFD 回显中能看到什么？再看 S7 的 MSTP 状态表中端口怎么选？') is None
    assert illustrated_example('同一次实验中，恢复后 R4 的 BFD 回显是什么？再看 S7 的 MSTP 回显如何？')


def test_explicit_principle_question_does_not_pick_up_concrete_practice_steps():
    principle = source(1, '邻接双方交换链路状态。', title='OSPF 邻接机制')
    exercise = source(2, '本例第一步先调整链路。', title='OSPF 原理与配置')
    exercise['source_heading_path'] = ('OSPF 讲义', '配置示例')
    unrelated = source(3, '交换用于更新可达性。', title='BGP 的基本概念')
    assert exclude_conflicting_examples('只讲原理，解释 OSPF 邻接机制。', [exercise, unrelated, principle]) == ([principle], '')


def test_broad_fallback_rejects_other_reporter_other_case_and_future_plan():
    question = '教材案例 2 中 R4 的 OSPF 回显在恢复后显示什么？'
    actual = source(1, '```text\n<R4>display ospf peer\nR7  Full\n```', title='OSPF 案例 2 · 恢复后')
    reverse = source(2, '```text\n<R7>display ospf peer\nR4  Full\n```', title='OSPF 案例 2 · 恢复后')
    wrong_case = source(3, actual['content'], title='OSPF 案例 1 · 恢复后')
    planned = source(4, 'R4 的状态值计划为 Full。', title='OSPF 案例 2 · 恢复后预期状态')
    assert exclude_conflicting_examples(question, [reverse, wrong_case, planned, actual]) == ([actual], '')


def test_protocol_field_between_device_and_readback_is_not_another_device():
    question = 'R1 的 OSPF Network-LSA 读回中，Attached Router 列了什么？'
    actual = source(1, '```text\n[R1]display ospf lsdb network\nAttached Router: 10.1.0.1\n```')
    reverse = source(2, actual['content'].replace('[R1]', '[R7]'))
    assert exclude_conflicting_examples(question, [reverse, actual]) == ([actual], '')


def test_do_not_use_a_concrete_example_is_a_source_constraint():
    principle = source(1, '邻接建立后，交换链路状态数据库。', title='OSPF 邻接机制')
    laboratory = source(2, '### 配置示例\n\nR1 的邻居状态为 Full。', title='OSPF 原理与配置')
    unrelated = source(3, '对等体交换路由可达信息。', title='BGP 基础')
    question = '教材说 OSPF 邻接和拓扑交换的关系是什么？别套具体案例。'
    assert exclude_conflicting_examples(question, [principle, laboratory, unrelated]) == ([principle], '')


def test_a_rejected_reporter_can_still_be_the_peer_in_the_correct_record():
    before = source(1, '```text\n<R4>display ospf peer\nR7  Init\n```', title='OSPF 恢复前')
    after = source(2, '```text\n<R4>display ospf peer\nR7  Full\n```', title='OSPF 恢复完成后')
    reverse = source(3, '```text\n<R7>display ospf peer\nR4  Full\n```', title='OSPF 恢复完成后')
    question = '教材实验中 R4 恢复前、恢复完成后的 OSPF 回显是什么？别把设备换成 R7。'
    assert exclude_conflicting_examples(question, [before, reverse, after]) == ([before, after], '')


def test_same_prefix_before_and_after_uses_the_record_instead_of_a_default_route():
    before = source(1, '```text\n<R4>display ip routing-table\n198.51.100.0/24 OSPF 10\n```', title='OSPF 调整前')
    after = source(2, '```text\n<R4>display ip routing-table\n198.51.100.0/24 OSPF 20\n```', title='OSPF 调整后')
    default = source(3, '```text\n<R4>display ip routing-table\n0.0.0.0/0 OSPF 20\n```', title='OSPF 调整后')
    plan = source(4, '198.51.100.0/24 的代价配置步骤。', title='OSPF 配置计划')
    question = ('代价改成 20 后，我要对照教材 198.51.100.0/24 的前后。拿什么核证？不要答成缺省路由那条。')
    assert exclude_conflicting_examples(question, [before, default, plan, after]) == ([before, after], '')
    assert exclude_conflicting_examples(question, [before, default, plan]) == ([before, plan], '')


def test_multiple_named_participants_and_observation_scope_unlisted_fields():
    query = illustrated_example('图中 OSPF 的 R4 和 R8 同组，R4 的回显里记录了什么？')
    actual = source(3, '本例 R4 与 R8 相邻。\n\nR4 回显显示 Cost 为 35。')
    other = source(4, '本例 R4 与 R9 相邻。\n\nR4 回显显示 Cost 为 20。', document='other-example')
    assert select_illustrated_evidence(query, [other, actual]) == ([actual], '')
    assert illustrated_example('图中 R4 和 R8 的 OSPF 有什么用途？') is None


def test_modes_on_different_axes_qualify_the_same_observation():
    query = illustrated_example('图中静态配置的二层转发实验里，Edge_A 的 VXLAN 回显是什么？')
    actual = source(3, 'Edge_A 的 VXLAN 回显显示会话 Up。', title='VXLAN 静态配置的二层转发')
    other = source(4, 'Edge_A 的 VXLAN 回显显示会话 Down。', title='VXLAN 动态配置的二层转发')
    assert not query.compared_modes
    assert select_illustrated_evidence(query, [other, actual]) == ([actual], '')


def test_mixed_phase_and_mismatched_chapter_are_not_minimal_evidence():
    mixed = source(4, '恢复前 R4 接收端回显显示 Down，恢复后回显显示 Full。')
    wrong = source(5, '恢复后，提到 OSPF 的 R4 接收端回显显示为 Full。', title='IS-IS 邻接实验')
    chosen, notice = select_illustrated_evidence(illustrated_example(QUESTION), [mixed, wrong])
    assert chosen == []
    assert '未找到' in notice


def test_unlabelled_exercise_can_include_a_read_only_observation_after_the_command():
    question = '恢复后 R4 的 OSPF 回显里如何判断接收端的状态？'
    setup = source(1, '恢复后 R4 接收端配置如下。\n\n```cli\n[R4] ip address 10.1.2.4 24\n```')
    blank = source(2, '恢复后在 R4 接收端查看。\n\n```cli\n<R4> display ospf peer brief\n```')
    read = source(3, '恢复后 R4 接收端读回如下。\n\n```cli\n<R4> display ospf peer brief\nNeighbor 10.1.2.3 Full\n```')
    wrong = source(4, '恢复后在 R4 接收端查看。\n\n```cli\n<R8> display ospf peer brief\nNeighbor 10.1.2.3 Full\n```')
    chosen, notice = select_illustrated_evidence(illustrated_example(question), [setup, blank, wrong, read])
    assert chosen == [read]
    assert '实际读回' not in notice


def test_a_negotiated_timer_table_cannot_establish_the_measured_recovery_time():
    question = 'BFD 图中 R4 协商后的收发间隔和检测倍数是多少？能确定业务恢复的耗时吗？'
    timer = source(3, 'BFD 协商后图表：\n\n| 设备 | TX/RX/DM |\n| --- | --- |\n| R4 | 15 ms / 30 ms / 2 |'
                   '\n\n业务恢复还需要独立计时。', title='BFD 图示')
    chosen, notice = select_illustrated_evidence(illustrated_example(question), [timer])
    assert chosen == [timer]
    available, missing = notice.split('尚缺', 1)
    assert '发送间隔' in available and '检测倍数' in available
    assert '实际业务恢复耗时' in missing
    assert '发送间隔' not in missing and '检测倍数' not in missing
    assert '判定所需条件' not in missing


def test_named_peers_are_not_field_names_or_universally_readback_owners():
    question = '图中 FW_A 和 FW_B 互联后，FW_A 的 PIM 回显中的上游是哪一端？'
    query = illustrated_example(question)
    assert query.devices == {'fw_a', 'fw_b'}
    assert query.observed_devices == {'fw_a'}
    assert query.literals == set()
    actual = source(3, '本例 FW_A 与 FW_B 相连。\n\nFW_A 的 PIM 回显显示上游为端口 2。', title='PIM 组网')
    wrong = source(4, '本例 FW_A 与 FW_B 相连。\n\nFW_B 的 PIM 回显显示上游为端口 1。', title='PIM 组网')
    assert select_illustrated_evidence(query, [wrong, actual]) == ([actual], '')


def test_verified_experiment_heading_can_join_the_topology_and_its_readback():
    query = illustrated_example('图中 OSPF 的 R4 与 R7 同组，R4 的回显里记录了什么？')
    location = {'source_experiment_key': 'verified-heading-1', 'edition_version': 'edition-A'}
    topology = {**source(3, '本实验中 R4 与 R7 相连。'), **location}
    readback = {**source(4, 'R4 的回显显示邻居为 Full。'), **location}
    other = {**source(5, 'R4 的回显显示邻居为 Down。'), **location, 'source_experiment_key': 'verified-heading-2'}
    assert select_illustrated_evidence(query, [topology, other, readback]) == ([readback], '')
    assert not select_illustrated_evidence(query, [topology, other])[0]


def test_reused_labels_in_two_headings_of_one_book_need_disambiguation():
    query = illustrated_example('图中 OSPF 的 R4 与 R7 同组，R4 的回显里记录了什么？')
    body = '该实验中 R4 与 R7 相连。\n\nR4 的回显显示邻居为 Full。'
    hints = [{**source(page, body), 'source_experiment_key': f'verified-heading-{page}'} for page in (3, 4)]
    selected, notice = select_illustrated_evidence(query, hints)
    assert not selected and '多处' in notice


def test_same_excerpt_identifier_does_not_attach_another_phase():
    query = illustrated_example('图中 OSPF 的 R4 恢复后的回显里，邻居是什么状态？')
    expected = source(3, '恢复后，R4 的回显显示邻居为 Full。')
    other = {**source(4, '恢复前，R4 的回显显示邻居为 Down。'), 'source_id': expected['source_id']}
    assert select_illustrated_evidence(query, [other, expected]) == ([expected], '')


def test_an_original_phase_cannot_borrow_participants_from_another_step():
    query = illustrated_example('图中 OSPF 的 R4 与 R7 同组，R4 的回显里记录了什么？')
    case = {'source_experiment_key': 'case-A'}
    topology = {**source(1, '本实验中 R4 与 R7 相连。'), **case, 'source_phase_key': 'case-A-step-1'}
    readback = {**source(2, 'R4 的回显显示邻居为 Full。'), **case, 'source_phase_key': 'case-A-step-2'}
    chosen, notice = select_illustrated_evidence(query, [topology, readback])
    assert not chosen and '未找到' in notice


def test_joint_protocol_experiment_requires_both_protocols_in_its_source():
    question = 'OSPF 与 BFD 这次实验图中，R4 恢复后的回显状态是什么？'
    query = illustrated_example(question)
    assert query.protocols == {'ospf', 'bfd'}
    only_ospf = source(1, 'R4 恢复后回显显示邻居 Full。')
    supported = source(2, 'R4 恢复后回显显示 Full。', title='OSPF 和 BFD 联动实验')
    assert select_illustrated_evidence(query, [only_ospf, supported]) == ([supported], '')


def test_distinct_named_readbacks_can_show_different_states_in_the_same_experiment():
    query = illustrated_example('图中 OSPF 的 R4 回显和 R7 回显分别是什么？')
    example = '本例 R4 与 R7 相连。\n\n'
    left = source(3, example + 'R4 回显显示邻居为 Full。')
    right = source(4, example + 'R7 回显显示邻居为 Down。')
    assert query.observed_devices == {'r4', 'r7'}
    assert select_illustrated_evidence(query, [left, right]) == ([left, right], '')
    inconsistent = source(5, example + 'R4 回显显示邻居为 Down。')
    selected, notice = select_illustrated_evidence(query, [left, right, inconsistent])
    assert selected == []
    assert '多处' in notice


def test_packet_headers_and_learned_origin_require_the_right_evidence():
    question = '图中 VXLAN 的 R4 与 R7 实验，哪些表项是从远端学到的？抓包的内层与外层字段能读出什么？'
    query = illustrated_example(question)
    observed = source(3, 'VXLAN 的 R4 与 R7 实验。\n\nR4 从远端 R7 学到了对方的 MAC 地址。', title='VXLAN 实验')
    capture = source(4, 'VXLAN 的 R4 与 R7 实验。\n\n抓包显示报文外层地址为 192.0.2.5，内层地址为 198.51.100.3。', title='VXLAN 实验')
    wrong = source(2, 'VXLAN 的 R4 与 R7 在其他实验。\n\nR4 读回显示会话 Up。', title='VXLAN 实验', document='other-example')
    diagram = source(1, 'VXLAN 的 R4 与 R7 示意图。\n\n原图给出内层与外层地址的书写次序。', title='VXLAN 示意图', document='diagram')
    assert select_illustrated_evidence(query, [wrong, diagram, observed, capture]) == ([observed, capture], '')


def test_proof_boundary_keeps_packet_capture_and_table_reading_separate():
    query = illustrated_example('图中 OSPF 的 R4 和 R7 同组，抓包和表中记录能否证明完整通信？')
    case = 'R4 与 R7 相连。\n\n'
    assert query.witnesses == {'报文捕获', '表格读数'}
    capture = source(3, case + '抓包显示收到 Hello 报文。')
    table = source(4, case + 'R4 回显如下。\n\n| 邻居 | 状态 |\n| --- | --- |\n| R7 | Full |'
                    '\n\n仍需核对两侧同一时点的转发记录。')
    different_read = source(5, case + 'R4 回显显示接收数为 3。', document='other-example')
    assert select_illustrated_evidence(query, [different_read, capture, table]) == ([capture, table], '')


def test_unrecognized_device_like_alias_alone_is_not_an_exhibit_key():
    assert illustrated_example('图中 ALPHA_7 与 BRAVO_B 连起来，表中回显里的上游是哪端？') is None


def test_generic_compound_alias_and_mode_identify_the_same_exhibit():
    question = '分布式网关实验中 Edge_A 和 Edge_B 相连，Edge_A 的 EVPN 回显里下一跳是谁？'
    query = illustrated_example(question)
    assert query.devices == {'edge_a', 'edge_b'}
    assert query.observed_devices == {'edge_a'}
    assert query.literals == set()
    actual = source(3, 'Edge_A 与 Edge_B 互联。\n\nEdge_A 的 EVPN 回显显示下一跳为 192.0.2.2。',
                    title='EVPN 分布式网关')
    other_mode = source(4, 'Edge_A 与 Edge_B 互联。\n\nEdge_A 的 EVPN 回显显示下一跳为 192.0.2.6。',
                        title='EVPN 集中式网关', document='experiment-b')
    assert select_illustrated_evidence(query, [other_mode, actual]) == ([actual], '')


def test_previous_question_about_an_interface_does_not_make_a_field_a_device():
    question = 'R2 的 BGP 回显里实际出接口叫什么？AS_PATH 变空后会发生什么？'
    query = illustrated_example(question)
    assert query.devices == {'r2'}
    assert query.literals == {'as_path'}


def test_explicit_mode_comparison_keeps_separate_readouts_and_reports_a_missing_side():
    question = '图中对比 EVPN 的集中式网关和分布式网关，Edge_A 回显里的下一跳分别是什么？'
    query = illustrated_example(question)
    centralized = source(3, 'Edge_A 的 EVPN 回显显示下一跳为 192.0.2.2。', title='EVPN 集中式网关')
    distributed = source(4, 'Edge_A 的 EVPN 回显显示下一跳为 192.0.2.6。', title='EVPN 分布式网关', document='experiment-b')
    unnamed = source(5, 'Edge_A 的 EVPN 回显显示下一跳为 192.0.2.9。', title='EVPN 基础', document='other')
    selected, notice = select_illustrated_evidence(query, [unnamed, centralized, distributed])
    assert selected == [centralized, distributed]
    assert not notice
    selected, notice = select_illustrated_evidence(query, [unnamed, centralized])
    assert selected == [centralized]
    assert '分布式' in notice


def test_broader_sources_drop_only_explicitly_conflicting_subjects_and_stages():
    current = source(3, '恢复后，OSPF 回显显示邻居为 Full。')
    earlier = source(2, '恢复前，OSPF 回显显示邻居为 Down。')
    alternative = source(1, 'BGP 的对等体回显显示 Idle。', title='BGP 对等体实验')
    general = source(4, '只读观察的记录时间需要分别核对。', title='记录说明')
    chosen, notice = exclude_conflicting_examples('OSPF 恢复后回显里该怎么看？', [earlier, current, alternative, general])
    assert chosen == [current, general]
    assert not notice
    chosen, notice = exclude_conflicting_examples('OSPF 恢复前后回显有何变化？', [earlier, current])
    assert chosen == [earlier, current]
    assert not notice
    chosen, notice = exclude_conflicting_examples('OSPF 恢复后回显里该怎么看？', [earlier])
    assert chosen == []
    assert '其他阶段' in notice


def test_explicitly_excluded_application_illustration_is_not_extra_background():
    principle = source(2, 'LDP 的两类消息负责不同职责。', title='LDP 的发现过程')
    example = source(3, '本例 OSPF 也会使用 Hello，工作阶段不同。', title='OSPF 应用例')
    question = '请解释 LDP 的发现过程，别拿 OSPF 应用例。'
    assert exclude_conflicting_examples(question, [example, principle]) == ([principle], '')
    # A protocol named on both sides of a comparison remains a positive subject.
    assert exclude_conflicting_examples('对照 LDP 和 OSPF 的发现方法。', [example, principle]) == ([example, principle], '')
