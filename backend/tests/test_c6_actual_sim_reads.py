"""Regress real offline adapter outputs, not injected evidence-only fixtures."""
import json
import pytest
from engines.device_adapter import SimDeviceAdapter
from modules.ai_text.read_plan import initial_read
from modules.ai_text.trusted_context import ResolvedTaskTargets
from modules.ai_text.context_bundle import prepare_sources

@pytest.mark.asyncio
async def test_actual_sim_ipv4_route_read_contains_fields_instead_of_generic_ack():
    output=await SimDeviceAdapter('R-3').run_command('display ip routing-table')
    assert 'Destination/Mask' in output and 'Direct' in output
    assert 'GE3/0/3' in output and '10.0.23.0/24' in output
    assert 'Info: (sim) 已执行' not in output

@pytest.mark.asyncio
async def test_unimplemented_sim_display_is_an_explicit_error_not_a_successful_read():
    from modules.trust.service import detect_cli_error
    output=await SimDeviceAdapter('R-3').run_command('display definitely-unsupported')
    assert detect_cli_error(output)
    assert '已执行' not in output

@pytest.mark.asyncio
async def test_sim_rejects_configuration_and_unimplemented_filters_without_changing_readback():
    from modules.trust.service import detect_cli_error

    sim = SimDeviceAdapter('R-1')
    original = await sim.run_command('display current-configuration')
    for command in (
        'system-view', 'interface GigabitEthernet0/0/7', 'description UX_SIM_EDIT_CHECK',
        'description display version', 'sysname R-NEW', 'quit', 'return',
        'display current-configuration interface GE0/0/7', 'display bgp peer ipv6',
    ):
        response = await sim.run_command(command)
        assert detect_cli_error(response), command
        assert '未执行' in response, command
    assert await sim.run_command('display current-configuration') == original


@pytest.mark.asyncio
@pytest.mark.parametrize('hostname', ['R-1', 'R-7'])
async def test_sim_help_only_advertises_commands_with_a_readback(hostname):
    from modules.trust.service import detect_cli_error

    sim = SimDeviceAdapter(hostname)
    command_lines = (await sim.run_command('help')).splitlines()[2:]
    assert 'display ip interface brief' in command_lines
    assert 'display current-configuration' in command_lines
    for command in command_lines:
        result = await sim.run_command(command)
        assert command.startswith('display ') and not detect_cli_error(result), command
        assert len(result.strip().splitlines()) > 1, command

@pytest.mark.parametrize('question,command', [
    ('那 R1 的路由表呢？','display ip routing-table'),
    ('R1的OSPF邻居有哪些？','display ospf peer'),
    ('R1的接口摘要呢？','display ip interface brief'),
])
def test_whole_field_followup_uses_resolved_read_without_extra_planning(question,command):
    targets=ResolvedTaskTargets([{'hostname':'R1','device_id':1}],[],[],'now')
    plan=initial_read(question,'live_evidence',targets,['run_display_command'])
    assert plan and json.loads(plan['function']['arguments'])['command']==command

def test_vrrp_review_explicitly_preserves_address_owner_exception_and_zero_priority():
    sources=prepare_sources([{'filename':'14-vrf配置bfd联动与vrrp原理.md',
        'text':'如果优先级低的先启动，优先级高的后启动'}])
    note=sources[0]['reviewed_notes'][0]['content']
    assert '1–254' in note and '255' in note and '不受抢占开关' in note
    assert '0' in note and '退出' in note
