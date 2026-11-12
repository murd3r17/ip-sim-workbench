"""A scoped, explicit zero is a fact; absent or incomplete output is not."""
import pytest
from modules.trust.service import parse_ospf_peer

HEADER='OSPF Process 1 with Router ID 10.0.0.2\n'

def test_explicit_zero_keeps_process_scope_without_inventing_peer_rows():
    facts=parse_ospf_peer(HEADER+'Total Peer(s): 0\n')
    assert facts['peers']==[]
    assert facts['reported_peer_counts']==[{'process_id':1,'router_id':'10.0.0.2','peer_count':0}]
    assert any(facts.values())  # existing collector recognizes a nonempty fact

@pytest.mark.parametrize('output',[
 '', '  ', HEADER, 'Total Peer(s): 0\n',
 HEADER+'Total Peer(s): 0\n---- More ----',
 HEADER+'Error: command unavailable\nTotal Peer(s): 0\n',
 HEADER+'Total Peer(s): 0\nTotal Peer(s): 2\n',
 HEADER+'Total Peer(s): 0\nOSPF Process 2 with Router ID 10.0.0.3\nTotal Peer(s): 0\n',
])
def test_missing_ambiguous_paged_or_error_output_does_not_become_a_complete_zero(output):
    facts=parse_ospf_peer(output)
    assert not facts.get('reported_peer_counts')

def test_zero_summary_does_not_override_actual_neighbor_row():
    facts=parse_ospf_peer(HEADER+'Router ID: 10.0.0.1\nState: Full\nTotal Peer(s): 0\n')
    assert facts['peers']==[{'neighbor_id':'10.0.0.1','state':'Full'}]
    assert not facts.get('reported_peer_counts')


@pytest.mark.asyncio
@pytest.mark.parametrize('output,status,completeness',[
    (HEADER+'Total Peer(s): 0\n','ok','complete'),
    ('','empty','empty'),
    (HEADER+'Total Peer(s): 0\n---- More ----','partial','partial'),
])
async def test_real_observation_route_keeps_zero_blank_and_paged_results_distinct(
        client,test_session_factory,monkeypatch,output,status,completeness):
    from unittest.mock import AsyncMock
    from tests.test_trust.test_v7b_trust import _device, _admin_token, auth_header
    from modules.trust.service import PARSER_VERSION
    token=await _admin_token(test_session_factory)
    device_id=await _device(test_session_factory,hostname='ZERO-R2')
    adapter=type('Adapter',(),{'run_command':AsyncMock(return_value=output),'close':AsyncMock()})()
    monkeypatch.setattr('engines.device_adapter.get_device_adapter',AsyncMock(return_value=adapter))
    monkeypatch.setattr('engines.device_adapter.get_device_mode',lambda:'sim')
    response=await client.post('/api/v1/trust/observations',headers=auth_header(token),
        json={'device_id':device_id,'action_id':'ospf_peer'})
    assert response.status_code==200
    body=response.json()
    assert body['status']==status and body['completeness']==completeness
    assert body['parser_version']==PARSER_VERSION
    assert bool(body['facts'].get('reported_peer_counts'))==(status=='ok')
    adapter.run_command.assert_awaited_once_with('display ospf peer')
