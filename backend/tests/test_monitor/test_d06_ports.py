from datetime import datetime, timedelta, timezone
import json
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from modules.monitor.ports import (parse_ports, assess_ports, policy_payload, sample_fresh, PortPolicyWrite)
from modules.monitor.port_service import get_port_state, save_port_policy, evaluate_port_alarms
from modules.monitor.service import AlarmService, MetricCollector, MonitorService
from modules.monitor.models import Alarm, AlarmStatus, MonitorJob, MonitorJobStatus, MonitorJobType, MonitorTriggerMode
from modules.device.models import Device, Topology, DeviceType, DeviceStatus
from core.config import get_settings

TABLE='Interface PHY Protocol InUti OutUti\nGE0/0/0 up up 0% 0%\nGE0/0/1 *down down 0% 0%\nGE0/0/2 down down 0% 0%\nNULL0 up up(s) 0% 0%'
def policy(ports): return policy_payload(1, ports)
def p(name, purpose, enabled): return {'name':name,'purpose':purpose,'expected_enabled':enabled}


@pytest.fixture
def simulated_collection(monkeypatch):
    monkeypatch.setenv("DEVICE_MODE", "sim")
    get_settings.cache_clear()


def test_admin_state_unknown_is_not_inferred_enabled_and_suffix_is_preserved():
    result=parse_ports(TABLE)
    assert result['complete']
    assert result['ports'][0]['admin_state']=='unknown'
    assert result['ports'][1]['admin_state']=='disabled'
    assert result['ports'][3]['protocol']=='up(s)'


@pytest.mark.parametrize('text',['','Error: Unrecognized command',TABLE+'\n---- More ----',
                                'Interface PHY Protocol\nGE0/0/1 unknown down',
                                'Interface PHY Protocol\nGE0/0/1 up',TABLE+'\nGE0/0/0 up up'])
def test_incomplete_never_certifies_recovery(text):
    assert not parse_ports(text)['complete']


def test_unknown_idle_expected_and_missing_ports_are_separate():
    output=assess_ports(parse_ports(TABLE),policy([p('GigabitEthernet0/0/1','management',True),p('GE0/0/2','unused',False),p('GE0/0/99','uplink',True)]))
    assert output['expected_down']==1
    assert output['missing_expected_ports']==['GE0/0/99']
    assert output['ports'][1]['assessment']=='expected_down'
    assert output['ports'][2]['assessment']=='expected_inactive'
    assert output['review_count']==1
    unknown=assess_ports(parse_ports(TABLE),policy([]))
    assert unknown['expected_down']==0 and unknown['review_count']==2


def test_policy_validation_no_alias_duplicates_or_implicit_boolean():
    for rows in [[p('GE0/0/0','unused',True)], [p('GE0/0/0','uplink',1)],
                 [p('GE0/0/0','business',True),p('GigabitEthernet0/0/0','business',True)],
                 [p('GE0/0/0\nshutdown','unused',False)]]:
        with pytest.raises(ValidationError): PortPolicyWrite(base_revision='',ports=rows)


def test_freshness_includes_policy_mode_timestamp():
    s={'version':'ports-d06.1','mode':'sim','policy_revision':'x','observed_at':datetime.now(timezone.utc).isoformat()}
    assert sample_fresh(s,'sim','x')
    assert not sample_fresh(s,'ssh','x') and not sample_fresh(s,'sim','y')
    s['observed_at']=(datetime.now(timezone.utc)-timedelta(seconds=301)).isoformat()
    assert not sample_fresh(s,'sim','x') and not sample_fresh({},'sim','x')


async def device(db):
    t=Topology(name='D06 isolated');db.add(t);await db.flush()
    d=Device(hostname='D06-R1',mgmt_ip='198.18.96.1',topology_id=t.id,device_type=DeviceType.ROUTER,status=DeviceStatus.ONLINE)
    db.add(d);await db.commit();return d


@pytest.mark.asyncio
async def test_raw_twenty_down_warning_and_old_critical_not_auto_resolved(test_session_factory):
    async with test_session_factory() as db:
        d=await device(db)
        old=Alarm(device_id=d.id,alarm_type='interface_down_high',severity='critical',message='historical',status=AlarmStatus.FIRED)
        db.add(old);await db.commit()
        warning=await AlarmService.evaluate_and_alarm(db,d,'interface_down',20)
        assert warning.severity=='warning' and warning.alarm_type=='interface_review'
        await AlarmService.evaluate_and_alarm(db,d,'interface_down',0)
        await db.refresh(old)
        assert old.status==AlarmStatus.FIRED and old.severity=='critical' and old.message=='historical'


@pytest.mark.asyncio
async def test_expected_down_fires_and_only_full_matching_sample_resolves(test_session_factory):
    async with test_session_factory() as db:
        d=await device(db)
        pol=policy([p('GE0/0/1','uplink',True),p('GE0/0/2','unused',False)])
        s=assess_ports(parse_ports(TABLE),pol)|{'observed_at':datetime.now(timezone.utc).isoformat()}
        fired=await evaluate_port_alarms(db,d,s);await db.flush()
        alarm=next(a for a in fired if a.alarm_type=='interface_expected_down')
        assert alarm.severity=='major' and alarm.metric_value==1
        incomplete=assess_ports(parse_ports('Interface PHY Protocol\nGE0/0/1 up up\nunknown'),pol)|{'observed_at':s['observed_at']}
        await evaluate_port_alarms(db,d,incomplete)
        assert alarm.status==AlarmStatus.FIRED
        changed=policy([p('GE0/0/1','unused',False),p('GE0/0/2','unused',False)])
        await evaluate_port_alarms(db,d,assess_ports(parse_ports(TABLE),changed)|{'observed_at':s['observed_at']})
        assert alarm.status==AlarmStatus.FIRED  # reclassification does not prove recovery
        complete=assess_ports(parse_ports(TABLE.replace('*down down','up up')),pol)|{'observed_at':s['observed_at']}
        await evaluate_port_alarms(db,d,complete)
        assert alarm.status==AlarmStatus.RESOLVED


@pytest.mark.asyncio
async def test_policy_revision_conflict_and_latest_failed_attempt_does_not_reuse_success(test_session_factory):
    from fastapi import HTTPException
    from modules.monitor.ports import load_policy
    async with test_session_factory() as db:
        d=await device(db); old=await load_policy(db,d.id)
        from modules.auth.models import User
        u=User(username='d06-audit',hashed_password='unused-test-hash');db.add(u);await db.commit()
        body=PortPolicyWrite(base_revision=old['revision'],ports=[p('GE0/0/1','unused',False)])
        saved=await save_port_policy(db,d.id,body,{'user_id':u.id,'username':'test'})
        with pytest.raises(HTTPException) as conflict: await save_port_policy(db,d.id,body,{'user_id':u.id})
        assert conflict.value.status_code==409
        state=await get_port_state(db,d.id)
        assert state['policy']['revision']==saved['revision'] and not state['fresh']
        for data in [{'status':'success','port_observation':{'version':'ports-d06.1','mode':'sim','policy_revision':saved['revision'],'observed_at':datetime.now(timezone.utc).isoformat()}},{'status':'failed','reason':'timeout'}]:
            db.add(MonitorJob(topology_id=d.topology_id,job_type=MonitorJobType.COLLECTION,trigger_mode=MonitorTriggerMode.MANUAL,status=MonitorJobStatus.FAILED,summary_json=json.dumps({'devices':[{'device_id':d.id,**data}]})))
            await db.commit()
        state=await get_port_state(db,d.id)
        assert state['observation'] is None and state['latest_attempt']['reason']=='timeout'


@pytest.mark.asyncio
async def test_actual_collector_persists_port_snapshot_and_raw_counts(client,test_session_factory,simulated_collection):
    async with test_session_factory() as db:
        d=await device(db)
        result=await MonitorService.run_collection(db,d.topology_id)
        sample=result['summary']['devices'][0]
        assert sample['port_observation']['ports']
        assert sample['port_observation']['complete']
        assert any(p['metric_type']=='interface_down' for p in sample['metrics'])
        assert all(a['severity']!='critical' for a in sample['alarms'] if a['alarm_type'].startswith('interface'))
        state=await get_port_state(db,d.id)
        assert state['fresh'] and state['observation']['policy_revision']==state['policy']['revision']


@pytest.mark.asyncio
async def test_normal_user_reads_but_cannot_save(client,test_session_factory):
    from modules.auth.models import User, UserRole
    from core.security import create_access_token
    async with test_session_factory() as db:
        d=await device(db); did=d.id
        admin=User(username='d06-admin',hashed_password='unused-test-hash',role=UserRole.ADMIN)
        user=User(username='d06-reader',hashed_password='unused-test-hash',role=UserRole.USER)
        db.add_all([admin,user]);await db.commit()
        auth_headers={'Authorization':'Bearer '+create_access_token(admin.id,admin.username,'admin')}
        user_headers={'Authorization':'Bearer '+create_access_token(user.id,user.username,'user')}
    read=await client.get(f'/api/v1/monitor/ports/{did}',headers=user_headers)
    assert read.status_code==200
    revision=read.json()['policy']['revision']
    denied=await client.put(f'/api/v1/monitor/ports/{did}/expectations',headers=user_headers,json={'base_revision':revision,'ports':[]})
    assert denied.status_code==403
    allowed=await client.put(f'/api/v1/monitor/ports/{did}/expectations',headers=auth_headers,json={'base_revision':revision,'ports':[p('GE0/0/2','unused',False)]})
    assert allowed.status_code==200


@pytest.mark.asyncio
async def test_corrupt_policy_and_snapshot_never_turn_into_current_match(client,test_session_factory,simulated_collection):
    from modules.system.models import SystemConfig
    async with test_session_factory() as db:
        d=await device(db)
        db.add(SystemConfig(config_key=f'monitor.port_expectations.{d.id}',config_value='{"ports":"broken"}'))
        await db.commit()
        result=await MonitorService.run_collection(db,d.topology_id)
        row=result['summary']['devices'][0]
        assert row['port_observation']['complete'] is False
        assert any(a['alarm_type']=='interface_review' for a in row['alarms'])
        assert (await get_port_state(db,d.id))['policy']['valid'] is False
        job=(await db.execute(select(MonitorJob).where(MonitorJob.id==result['task']['id']))).scalar_one()
        for malformed in [[], {'version':'older','ports':[]}, {'version':'ports-d06.1','ports':None}]:
            job.summary_json=json.dumps({'devices':[{'device_id':d.id,'status':'success','port_observation':malformed}]})
            await db.commit()
            state=await get_port_state(db,d.id)
            assert state['observation'] is None and not state['fresh']


@pytest.mark.asyncio
async def test_saved_device_tool_exposes_port_scope_not_a_new_read(client,test_session_factory,simulated_collection):
    from modules.ai_text.agent_tools import _query_device_detail
    async with test_session_factory() as db:
        d=await device(db)
        await MonitorService.run_collection(db,d.topology_id)
        text=await _query_device_detail(db,{'device_id':d.id})
        assert '已保存端口观察（不新采集、不证明业务可达）' in text
        assert 'review_down' in text and '"fresh": true' in text
