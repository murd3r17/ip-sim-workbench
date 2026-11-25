from modules.knowledge.phase_reference import operation_comparison, operation_phases, record_phases, source_step_boundary, step_phases
from modules.knowledge.ranked_evidence import _plan, _reported_phases


def test_phase_folds_aliases_but_preserves_the_operation_object():
    assert operation_phases('拔掉环回链路以前，接收端的状态为 Full。') == {('断开 环回链路', 'before')}
    assert operation_phases('断开该环回链路以后，接口实际进入 Down。', reported=True) == {('断开 环回链路', 'after')}
    assert operation_phases('断开监控链路以后，接口实际进入 Down。') == {('断开 监控链路', 'after')}


def test_order_words_inside_the_object_are_not_a_phase():
    assert operation_phases('启用第一条前置策略以后，路径恢复。') == {('启用 第一条前置策略', 'after')}
    assert not operation_phases('启用第一条前置策略，保存备用状态。')


def test_reported_phase_excludes_planned_operations_and_unclear_objects():
    assert not operation_phases('预计停用备用链路之后会掉线。', reported=True)
    assert not operation_phases('移除该项之后有什么变化？')


def test_comparison_preserves_user_vocabulary_and_requires_one_operation():
    command = '先看拔下备份跳线前后，R4 的实际回显。'
    label, (start, end) = operation_comparison(command)
    assert label == '拔下备份跳线' and command[start:end] == '拔下备份跳线前后'
    assert not operation_comparison('比较拔下环回链路前后与关闭测试端口前后。')


def test_ranked_question_uses_the_same_operation_binding_as_the_original():
    question = '拔下环回链路前后，R4 的 OSPF 回显分别是什么邻居状态？'
    plan = _plan(question)
    assert plan.compare_phases
    assert [facet.phases for facet in plan.facets] == [{('断开 环回链路', 'before')}, {('断开 环回链路', 'after')}]
    assert ('断开 环回链路', 'after') in _reported_phases('断开环回链路后，R4 的 OSPF 邻居表实际显示 Down。')
    assert not _reported_phases('如果断开环回链路后，应该显示 Down。')


def test_source_step_ordinals_are_distinct_from_phase_ordinals_and_plans():
    assert step_phases('第二步的回显是什么') == step_phases('步骤 2 FIB 核对') == {('步骤2', 'ordinal')}
    assert not step_phases('第二阶段的回显是什么')
    assert not _reported_phases('计划在步骤 2 观察设备')
    assert source_step_boundary('步骤 2') and not source_step_boundary('步骤 2 FIB 核对')


def test_numbered_observations_are_typed_and_separate_from_numbered_steps():
    assert record_phases('首次实际回显显示 Down') == {('第1次读回', 'ordinal')}
    assert record_phases('第二份原始命令输出显示 Full') == {('第2次读回', 'ordinal')}
    assert record_phases('第二次实际抓包中收到哪一条') == {('第2次捕获', 'ordinal')}
    assert not _reported_phases('计划做第二次实际抓包')
    assert not record_phases('第二步中记录设备状态')
    assert _plan('同一实验，R2 第一次回显是什么状态？R2 第二次读回是什么状态？').compare_phases
    assert not _plan('同一实验，R2 第一次回显是什么状态？R2 第二次抓包收到哪个请求？').compare_phases
