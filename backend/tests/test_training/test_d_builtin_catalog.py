"""D01: preserve current labs while making prerequisites and proof scope explicit."""
import copy

from modules.training.builtin_catalog import CATALOG_VERSION, builtin_labs, workflow_demo_lab
from modules.training.lab_content import ENVIRONMENT_SPEC


def test_existing_seven_labs_keep_steps_and_all_have_versioned_requirements():
    labs = builtin_labs()
    assert len(labs) == 7
    assert sum(len(lab['objectives']) for lab in labs) == 27
    assert len({lab['title'] for lab in labs}) == 7
    for lab in labs:
        assert lab['content_version'] == CATALOG_VERSION
        requirements = lab['environment_spec']
        assert requirements['requires_binding'] is True
        assert requirements['binding_status'] == 'unverified'
        assert requirements['prerequisites'] and requirements['sources']
        ids = [step['id'] for step in lab['objectives']]
        assert len(ids) == len(set(ids))
        for step in lab['objectives']:
            verification = step['verification']
            assert verification['kind'] in {'interface_expectations', 'ospf_expectations', 'route_filter_effect', 'manual_review'}
            assert verification['scope'] and verification['limitations']


def test_catalog_returns_detached_content_and_keeps_legacy_reference_immutable():
    before = copy.deepcopy(ENVIRONMENT_SPEC)
    first = builtin_labs()
    first[0]['objectives'][0]['goal'] = 'edited outside catalogue'
    first[0]['environment_spec']['devices'].clear()
    assert builtin_labs()[0]['objectives'][0]['goal'] != 'edited outside catalogue'
    assert builtin_labs()[0]['environment_spec']['devices']
    assert ENVIRONMENT_SPEC == before


def test_filtering_requires_real_abr_and_preserves_an_allowed_control_prefix():
    lab = next(l for l in builtin_labs() if '路由过滤' in l['title'])
    assert lab['environment_spec']['minimum_areas'] == 2
    assert lab['environment_spec']['requires_abr_binding'] is True
    rule = lab['objectives'][1]['verification']
    assert rule['kind'] == 'route_filter_effect'
    assert rule['requires_before_after'] and rule['requires_allowed_control']
    assert 'single_area_not_ready' in lab['environment_spec']['unready_reasons']
    assert '区域视图' in lab['objectives'][0]['config_hint']


def test_bfd_timing_and_ldp_withdrawal_need_actual_evidence_not_up_words():
    bfd = next(l for l in builtin_labs() if 'BFD' in l['title'])
    assert bfd['objectives'][1]['verification']['kind'] == 'manual_review'
    assert '1 秒内收敛' not in bfd['objectives'][1]['goal']
    assert '计时' in bfd['objectives'][1]['expected']
    ldp = next(l for l in builtin_labs() if 'MPLS' in l['title'])
    assert '目标会话和相关LSP' in ldp['objectives'][3]['expected']
    assert '不要求或声称整个标签转发表清空' in ldp['objectives'][3]['expected']
    assert all(s['verification']['kind'] == 'manual_review' for s in ldp['objectives'])


def test_bgp_reference_declares_own_prefix_lengths_instead_of_reusing_ospf_24():
    bgp = next(l for l in builtin_labs() if 'BGP' in l['title'])
    assert all(d['loopback_address'].endswith('/32') for d in bgp['environment_spec']['devices'])
    assert '精确' in bgp['objectives'][2]['goal']
    assert 'GigabitEthernet3/0/4' in bgp['objectives'][3]['config_hint']
    assert bgp['objectives'][1]['verification']['kind'] == 'manual_review'


def test_existing_workflow_demo_has_structured_version_and_no_fake_fault_repair_grade():
    demo = workflow_demo_lab()
    assert len(demo['objectives'])==3 and demo['content_version']==CATALOG_VERSION
    assert demo['environment_spec']['supports_binding'] is False
    assert all(s['verification']['kind']=='manual_review' for s in demo['objectives'])
    assert '不连SSH、不改设备' in demo['objectives'][1]['config_hint']
