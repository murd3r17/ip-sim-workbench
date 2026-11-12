"""D02: server-authored expectations and evidence identity, never keyword grades."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest

from modules.training.step_verification import evaluate_frozen_step


def fixture(kind='ospf_expectations'):
    now = datetime.now(timezone.utc)
    devices = [{'role': 'R1', 'device_id': 11, 'expected_neighbors': ['2.2.2.2'],
                'expected_routes': ['10.2.0.1/32'], 'interfaces': [
                    {'name': 'GE1/0/1', 'address': '10.1.0.1/24', 'purpose': 'link'},
                    {'name': 'LoopBack0', 'address': '10.1.0.2/32', 'purpose': 'loopback'}]}]
    env = {'id': 1, 'version': 'v1', 'content_hash': 'frozen-hash', 'revision': 1,
           'status': 'ready', 'last_preflight_status': 'ready', 'last_preflight_mode': 'sim',
           'devices': devices}
    step = {'id': 3, 'verification': {'kind': kind, 'version': 'd1',
                                    'components': ['neighbors', 'routes']}}
    session = NS(id=20, trainee_id=7, status='in_progress', started_at=now-timedelta(seconds=40),
                 content_version='d1', content_snapshot={'version': 'd1', 'objectives': [step],
                    'environment_spec': {'devices': [{'role': 'R1'}]}},
                 mode_snapshot={'device_mode': 'sim'}, trust_environment_id=1,
                 trust_environment_version='v1', trust_environment_snapshot={
                    'environment': deepcopy(env), 'content_hash': 'frozen-hash'})
    def row(id, action, facts):
        return NS(id=id, device_id=11, created_by=7, action_id=action, command='',
                  source='server_observed', mode='sim', adapter_mode='sim', parser_version='v7b.4',
                  completeness='complete', status='ok', environment_id=1, environment_version='v1',
                  environment_snapshot=deepcopy(env), collected_at=now, facts=facts)
    rows = [row(1, 'ospf_peer', {'peers': [{'neighbor_id': '2.2.2.2', 'state': 'Full'}]}),
            row(2, 'ospf_route', {'routes': [{'destination': '10.2.0.1/32', 'next_hop': '10.1.0.2'}]})]
    return session, env, rows, now


def check(session, env, rows, now, ids=None):
    return evaluate_frozen_step(session, 3, ids or [r.id for r in rows], rows, env,
                                {'user_id': 7, 'role': 'user'}, now=now)


def test_matching_sim_evidence_only_satisfies_scoped_practice_and_never_scores():
    s,e,rows,t=fixture()
    result=check(s,e,rows,t)
    assert result['status']=='satisfied' and result['evaluation_scope']=='practice'
    assert result['skill_passed'] is None and result['score'] is None
    assert result['roles']==['R1'] and result['content_version']=='d1'


def test_long_running_session_accepts_a_fresh_observation_not_only_first_five_minutes():
    s,e,rows,t=fixture()
    s.started_at=t-timedelta(hours=2)
    assert check(s,e,rows,t)['status']=='satisfied'


@pytest.mark.parametrize('defect,reason', [
    ('owner','not_owner'), ('device','target_mismatch'), ('source','untrusted_source'),
    ('parser','unsupported_parser'), ('partial','incomplete'), ('mode','mode_mismatch'),
    ('version','stale_environment_version'), ('hash','stale_environment_content'),
    ('old','stale_evidence'), ('future','future_evidence'), ('before_session','before_session'),
    ('missing','missing_evidence'), ('duplicate','duplicate_evidence'),
])
def test_ineligible_observations_never_pass(defect,reason):
    s,e,rows,t=fixture()
    r=rows[0]; ids=None
    if defect=='owner': r.created_by=8
    elif defect=='device': r.device_id=12
    elif defect=='source': r.source='client_reported'
    elif defect=='parser': r.parser_version='unknown'
    elif defect=='partial': r.completeness='partial'
    elif defect=='mode': r.adapter_mode='real'
    elif defect=='version': r.environment_version='old'
    elif defect=='hash': r.environment_snapshot['content_hash']='other'
    elif defect=='old': r.collected_at=t-timedelta(seconds=301); s.started_at=t-timedelta(hours=1)
    elif defect=='future': r.collected_at=t+timedelta(seconds=61)
    elif defect=='before_session': r.collected_at=t-timedelta(seconds=50)
    elif defect=='missing': ids=[1,2,9]
    elif defect=='duplicate': ids=[1,1,2]
    result=check(s,e,rows,t,ids)
    assert result['status']!='satisfied' and result['rejected_reason']==reason


@pytest.mark.parametrize('defect', ['drift','unready','missing_snapshot','legacy_content','changed_version'])
def test_session_and_environment_contracts_fail_closed(defect):
    s,e,rows,t=fixture()
    if defect=='drift': e['content_hash']='changed'
    elif defect=='unready': e['last_preflight_status']='unknown'
    elif defect=='missing_snapshot': s.trust_environment_snapshot={}
    elif defect=='legacy_content': s.content_snapshot={}
    elif defect=='changed_version': s.content_snapshot['version']='old'
    assert check(s,e,rows,t)['status']!='satisfied'


def test_missing_component_and_known_zero_are_not_confused_with_expected_full():
    s,e,rows,t=fixture()
    assert check(s,e,rows[:1],t)['rejected_reason']=='missing_action'
    rows[0].facts={'peers': [], 'reported_peer_counts': [{'process_id': 1, 'peer_count': 0}]}
    assert check(s,e,rows,t)['status']=='not_matched'
    rows[0].facts={'peers': []}
    assert check(s,e,rows,t)['status']=='insufficient_evidence'


def test_unexpected_neighbor_and_exact_route_prefix_are_not_ignored():
    s,e,rows,t=fixture()
    rows[0].facts['peers'].append({'neighbor_id':'9.9.9.9','state':'Full'})
    assert check(s,e,rows,t)['status']=='not_matched'
    rows[0].facts['peers'].pop()
    rows[1].facts['routes'][0]['destination']='10.2.0.0/24'
    assert check(s,e,rows,t)['status']=='not_matched'


def test_interface_address_prefix_and_both_up_come_from_bound_purposes():
    s,e,rows,t=fixture('interface_expectations')
    rows=rows[:1]; rows[0].action_id='interface_brief'
    rows[0].facts={'interfaces':[{'name':'GigabitEthernet1/0/1','address':'10.1.0.1/24','state':'up'},
                                {'name':'LoopBack0','address':'10.1.0.2/32','state':'up'}]}
    assert check(s,e,rows,t)['status']=='satisfied'
    rows[0].facts['interfaces'][0]['address']='10.1.0.1/25'
    assert check(s,e,rows,t)['status']=='not_matched'
    rows[0].facts['interfaces'][0]['address']='10.1.0.1/24'
    rows[0].facts['interfaces'][1]['state']='unknown'
    assert check(s,e,rows,t)['status']!='satisfied'


def test_advanced_manual_step_does_not_turn_up_or_user_checkmark_into_evidence():
    s,e,rows,t=fixture('manual_review')
    result=check(s,e,rows,t)
    assert result['status']=='manual_review' and result['skill_passed'] is None


@pytest.mark.parametrize('defect',['rule','objectives','requirements','role','devices','mode'])
def test_unsupported_stored_metadata_returns_unknown_instead_of_crashing(defect):
    s,e,rows,t=fixture()
    if defect=='rule': s.content_snapshot['objectives'][0]['verification']='unsupported'
    elif defect=='objectives': s.content_snapshot['objectives']='unsupported'
    elif defect=='requirements': s.content_snapshot['environment_spec']='unsupported'
    elif defect=='role': s.content_snapshot['environment_spec']['devices'][0]['role']=['R1']
    elif defect=='devices': s.trust_environment_snapshot['environment']['devices']=None
    elif defect=='mode': s.mode_snapshot='unsupported'
    assert check(s,e,rows,t)['status']=='insufficient_evidence'


def test_filter_requires_same_target_before_after_and_preserved_control():
    s,e,rows,t=fixture('route_filter_effect')
    step=s.content_snapshot['objectives'][0]
    step['verification']['filter']={'role':'R1','target':'10.2.0.1/32','control':'10.3.0.1/32'}
    before=rows[1]; before.facts={'routes':[{'destination':'10.2.0.1/32'},{'destination':'10.3.0.1/32'}]}
    before.collected_at=t-timedelta(seconds=10)
    after=deepcopy(before); after.id=3; after.collected_at=t
    after.facts={'routes':[{'destination':'10.3.0.1/32'}]}
    assert check(s,e,[before,after],t)['status']=='satisfied'
    after.facts={'routes':[]}
    assert check(s,e,[before,after],t)['status']!='satisfied'
    after.facts={'routes':[{'destination':'10.3.0.1/32'}]}; after.collected_at=before.collected_at
    assert check(s,e,[before,after],t)['status']!='satisfied'
