from types import SimpleNamespace

import pytest

from modules.knowledge.source_claims import observed_prose_witness, original_explanation_witness, readback_request


@pytest.mark.parametrize(('question', 'kind'), [
    ('从 R4 这次 PIM 邻居表实际读到什么状态？', 'readback'),
    ('在步骤三那张图里，蓝色箭头的终点是哪台设备？', 'diagram'),
    ('两端先后看到哪些路由前缀？', 'readback'),
    ('现在连接设备看看实际回显是什么', ''),
    ('要看 PIM 邻居，可以用哪条只读命令？', ''),
    ('PIM 邻居为什么会老化？', ''),
])
def test_readback_requests_distinguish_exhibits_and_instructions(question, kind):
    assert readback_request(question) == kind


def _request(text, *, kind='readback', owner='r4', axes=(), fields=(), labels=(), output_fields=()):
    return SimpleNamespace(text=text, kind=kind, observation_owner=owner,
                           devices=frozenset({owner}) if owner else frozenset(),
                           subjects=frozenset({'pim'}) if owner else frozenset(),
                           concepts=frozenset(), observation_axes=axes, fields=fields, labels=labels,
                           output_fields=output_fields)


def test_observed_table_prose_requires_the_named_issuer_and_actual_claim():
    facet = _request('从 R4 的 PIM 邻居表实际读到多少条表项和哪些路由前缀？', axes=('entries', 'prefixes'))
    assert observed_prose_witness(facet, 'R4 的 PIM 邻居表。该表显示合计 2 条表项，其中前缀为 10.20.0.0/16。', ())
    assert not observed_prose_witness(facet, 'R4 的 PIM 邻居表。\n\n该表显示合计 2 条表项，其中前缀为 10.20.0.0/16。', ())
    assert not observed_prose_witness(facet, 'R3 的 PIM 邻居表显示与 R4 互通，合计 2 条表项，其中前缀为 10.20.0.0/16。', ())
    assert not observed_prose_witness(facet, 'R4 的 PIM 邻居表预计会显示 2 条表项，其中前缀应当为 10.20.0.0/16。', ())
    assert not observed_prose_witness(facet, 'R4 的 OSPF 邻居表显示合计 2 条表项，其中前缀为 10.20.0.0/16。', ())
    assert not observed_prose_witness(facet, 'R4 的 PIM 邻居表合计 2 条表项，未提供所问路由前缀。', ())


def test_exhibit_claim_needs_a_label_value_instead_of_a_setup_instruction():
    facet = _request('图中蓝色箭头的终点是哪台设备？', kind='diagram', owner='')
    assert observed_prose_witness(facet, '图中蓝色箭头的终点标为边界交换机。', ())
    assert not observed_prose_witness(facet, '图中蓝色箭头的终点预计会标为边界交换机。', ())
    assert not observed_prose_witness(facet, '另一个实验的图中蓝色箭头的终点标为边界交换机。', ())
    assert not observed_prose_witness(facet, '图中红色箭头的终点标为边界交换机。', ())


def test_shared_observation_words_do_not_identify_an_experiment():
    facet = _request('教材这次实际回显，邻居表有多少条表项和哪些路由前缀？',
                     owner='', axes=('entries', 'prefixes'))
    assert not observed_prose_witness(facet, '邻居表显示合计 2 条表项，其中路由前缀为 10.20.0.0/16。', ())


def test_named_original_case_can_anchor_a_readback_without_device_labels():
    facet = _request('并行双环链路收敛实验的邻居表有多少条表项和哪些路由前缀？',
                     owner='', axes=('entries', 'prefixes'))
    observation = '邻居表显示合计 2 条表项，其中路由前缀为 10.20.0.0/16。'
    assert observed_prose_witness(facet, observation, ((3, '2.1 并行双环链路收敛实验', 8),))
    assert not observed_prose_witness(facet, observation, ((3, '2.1 并行双环链路选路实验', 8),))


def test_recognized_prose_observation_is_attributed_to_the_requested_perspective():
    facet = _request('并行双环链路收敛实验的发送侧回显有多少条路由表项？', owner='', axes=('entries',))
    scope = ((3, '2.1 并行双环链路收敛实验', 8),)
    assert observed_prose_witness(facet, '发送端的回显显示合计 2 条路由表项。', scope)
    assert not observed_prose_witness(facet, '接收侧回显显示合计 2 条路由表项，发送侧仅启用了记录。', scope)
    assert not observed_prose_witness(facet, '发送侧打开回显，接收侧回显显示合计 2 条路由表项。', scope)


def test_textbook_prose_can_prove_fields_when_each_actual_value_is_attributed():
    text = 'R4 的 PIM 回显中，下一跳和出接口各是什么？'
    facet = _request(text, output_fields=('next_hop', 'egress_interface'))
    source = 'R4 的 PIM 回显显示下一跳为 198.51.100.4，出接口为 GE0/0/3。'
    assert observed_prose_witness(facet, source, ())
    assert not observed_prose_witness(facet, source.replace('198', '999'), ())
    assert not observed_prose_witness(facet, source.replace('，出接口', '。R5 的 PIM 回显显示出接口'), ())
    assert not observed_prose_witness(facet, source.replace('显示下一跳', '显示配置模板中安排下一跳'), ())
    assert not observed_prose_witness(facet, source.replace('，出接口', '，下一跳为 198.51.100.5，出接口'), ())


def test_original_explanation_needs_a_requested_relation_and_its_subject():
    facet = _request('备用网关的状态通告为什么增加发送间隔？', kind='mechanism', owner='')
    assert original_explanation_witness(facet, '备用网关增加状态通告发送间隔，是因为同一时段内的重复通告不携带新增状态。', ())
    assert not original_explanation_witness(facet, '备用网关增加状态通告发送间隔。', ())
    assert not original_explanation_witness(facet, '备用网关增加采样间隔，预计这样能减少采集流量。', ())
    assert not original_explanation_witness(facet, '状态通告经管理平台汇总，目的是生成趋势曲线。', ())


def test_original_scope_keeps_explanation_distinct_from_observed_results():
    path = ((2, '7.5 时隙分配与收敛实验', 20),)
    explanation = '集中节点负责发送时隙分配通告。'
    facet = _request('在时隙分配与收敛实验，谁负责发送时隙分配通告？', kind='mechanism', owner='')
    assert original_explanation_witness(facet, explanation, path)
    observed = _request('时隙分配与收敛实验的实际回显显示哪个设备发送了通告？', kind='readback', owner='')
    assert not original_explanation_witness(observed, explanation, path)
