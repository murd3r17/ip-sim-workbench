"""BF 回归：由协调者 B 反例适配到正式测试；隔离 SQLite，不连真实网络/模型。"""
import asyncio,json
from pathlib import Path
from datetime import datetime,timedelta,timezone
from unittest.mock import AsyncMock
import pytest
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from modules.trust import service
from modules.trust.models import ReadOnlyObservation
from tests.test_training.test_v7a_state_and_reports import _admin_token,_lab,_session,auth_header
from tests.test_trust.test_v7b_trust import _device,_environment

def evidence(name,data):
    # 正式回归：断言已经覆盖；不把夹具结果写成产品证据。
    return None

@pytest.mark.asyncio
async def test_wrong_environment_is_not_ready(client,test_session_factory,monkeypatch):
    token=await _admin_token(test_session_factory)
    did=await _device(test_session_factory,hostname='REVIEW-ENV')
    eid=await _environment(client,token,did)
    adapter=AsyncMock()
    monkeypatch.setattr('engines.device_adapter.get_device_adapter',adapter)
    update=await client.put(f'/api/v1/trust/environments/{eid}',headers=auth_header(token),json={
        'devices':[{'device_id':did,'role':'R1','mgmt_ip':'203.0.113.250','vendor':'wrong-vendor',
                    'interfaces':[{'name':'NONEXISTENT-999','address':'203.0.113.199/24'}]}],
        'protections':[{}],
    })
    assert update.status_code==200
    result=await client.post(f'/api/v1/trust/environments/{eid}/preflight',json={},headers=auth_header(token))
    evidence('probe-preflight',{'wrong_mapping':update.json(),'preflight':result.json(),'adapter_calls':adapter.call_count})
    assert result.json()['status']!='ready','Wrong address/interface/vendor and empty protection accepted without observation'

@pytest.mark.asyncio
async def test_sim_evidence_is_distinguished(client,test_session_factory,monkeypatch):
    monkeypatch.setenv('DEVICE_MODE','sim')
    from core.config import get_settings
    get_settings.cache_clear()
    token=await _admin_token(test_session_factory)
    did=await _device(test_session_factory,hostname='REVIEW-SIM')
    result=await client.post('/api/v1/trust/observations',headers=auth_header(token),json={'device_id':did,'action_id':'interface_brief'})
    assert result.status_code==200
    data=result.json()
    evidence('probe-sim-provenance',data)
    assert data['source'] in {'demonstration','simulation','simulated'} or data['mode'] in {'sim','simulation','simulated'},'SimDeviceAdapter presented as server_observed/read_only without sim marker'

@pytest.mark.asyncio
@pytest.mark.parametrize('source,parser',[('client_reported','v7b.1'),('demonstration','v7b.1'),('server_observed','unsupported-99')])
async def test_rule_rejects_untrusted_provenance(client,test_session_factory,source,parser):
    token=await _admin_token(test_session_factory)
    did=await _device(test_session_factory,hostname='REVIEW-PROVENANCE')
    async with test_session_factory() as db:
        row=ReadOnlyObservation(device_id=did,action_id='ospf_peer',command='display ospf peer',
            source=source,mode='read_only',completeness='complete',parser_version=parser,
            facts={'peers':[{'neighbor_id':'10.0.0.2','state':'Full'}]},status='ok')
        db.add(row);await db.commit();oid=row.id
    result=await client.post('/api/v1/trust/rules/ospf/evaluate',headers=auth_header(token),json={'observation_id':oid,'expected_neighbors':['10.0.0.2']})
    evidence('probe-rule-'+source+'-'+parser,result.json())
    assert result.json()['status']!='satisfied'

@pytest.mark.asyncio
async def test_rule_rejects_mixed_devices_and_environment(client,test_session_factory):
    token=await _admin_token(test_session_factory)
    ids=[]
    for i in (1,2):
        did=await _device(test_session_factory,hostname=f'REVIEW-MIX-{i}')
        eid=await _environment(client,token,did)
        async with test_session_factory() as db:
            row=ReadOnlyObservation(environment_id=eid,device_id=did,action_id='ospf_peer',
                command='display ospf peer',source='server_observed',mode='read_only',completeness='complete',
                parser_version='v7b.1',facts={'peers':[{'neighbor_id':f'10.0.0.{i+1}','state':'Full'}]},status='ok')
            db.add(row);await db.commit();ids.append(row.id)
    result=await client.post('/api/v1/trust/rules/ospf/evaluate',headers=auth_header(token),json={
        'observation_ids':ids,'expected_neighbors':['10.0.0.2','10.0.0.3'],
        'environment_id':eid,'device_id':did})
    evidence('probe-mixed-targets',{'requested_target':{'environment_id':eid,'device_id':did},'actual':result.json()})
    assert result.json()['status']!='satisfied','Union of unrelated device/environment facts accepted'

@pytest.mark.asyncio
async def test_truncated_output_not_complete(client,test_session_factory,monkeypatch):
    token=await _admin_token(test_session_factory)
    did=await _device(test_session_factory,hostname='REVIEW-PARTIAL')
    class Adapter:
        async def run_command(self,cmd):
            return '10.0.0.2  1  Full/ -  00:00:12\n---- More ----'
        async def close(self):pass
    monkeypatch.setattr('engines.device_adapter.get_device_adapter',AsyncMock(return_value=Adapter()))
    response=await client.post('/api/v1/trust/observations',headers=auth_header(token),json={'device_id':did,'action_id':'ospf_peer'})
    row=response.json()
    rule=await client.post('/api/v1/trust/rules/ospf/evaluate',headers=auth_header(token),json={'observation_id':row['id'],'expected_neighbors':['10.0.0.2']})
    evidence('probe-partial-output',{'observation':row,'rule':rule.json(),'fixture':'synthetic pagination marker; no real device'})
    assert row['completeness']!='complete' and rule.json()['status']!='satisfied'

@pytest.mark.asyncio
async def test_environment_version_is_bound_to_evidence(client,test_session_factory,monkeypatch):
    monkeypatch.setenv('DEVICE_MODE','sim')
    from core.config import get_settings
    get_settings.cache_clear()
    token=await _admin_token(test_session_factory)
    did=await _device(test_session_factory,hostname='REVIEW-VERSION')
    eid=await _environment(client,token,did)
    observed=await client.post('/api/v1/trust/observations',headers=auth_header(token),json={
        'device_id':did,'action_id':'interface_brief','environment_id':eid})
    before=observed.json()
    updated=await client.put(f'/api/v1/trust/environments/{eid}',headers=auth_header(token),json={
        'version':'v2','devices':[{'device_id':did,'role':'R9','interfaces':[{'name':'CHANGED','address':'10.99.1.1/24'}]}]})
    after=(await client.get(f"/api/v1/trust/observations/{before['id']}",headers=auth_header(token))).json()
    async with test_session_factory() as db:
        row=await db.get(ReadOnlyObservation,before['id'])
        stored={col.name:getattr(row,col.name) for col in row.__table__.columns if 'environment' in col.name or 'version' in col.name}
    evidence('probe-environment-version',{'before':before,'environment_after':updated.json(),'after':after,'stored_binding_fields':stored})
    assert any('v1'==v for k,v in stored.items() if k!='parser_version') or after.get('environment_snapshot',{}).get('version')=='v1','Environment row overwritten; evidence has no captured environment version/snapshot'

@pytest.mark.asyncio
async def test_route_parser_uses_actual_next_hop():
    text='Destination        Cost  Type       NextHop         AdvRouter       Area\n10.0.0.2/32        1     Stub       10.0.123.2      10.0.0.2        0.0.0.0'
    result=service.parse_ospf_routes(text)
    evidence('probe-route-next-hop',{'input':text,'result':result,'origin':'same table columns as repository SimDeviceAdapter routing response'})
    assert result['routes'][0]['next_hop']=='10.0.123.2'

@pytest.mark.asyncio
async def test_workspace_actual_concurrency_is_conflict(client,monkeypatch,tmp_path):
    from main import app
    from core.database import Base,get_async_session
    import importlib
    import core.database as database
    tr=importlib.import_module('modules.training.router')
    engine=create_async_engine('sqlite+aiosqlite:///'+(tmp_path/'race.sqlite3').as_posix())
    factory=async_sessionmaker(engine,expire_on_commit=False)
    monkeypatch.setattr(database,'_session_factory',factory)
    async with engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
    async def override():
        async with factory() as db:yield db
    previous=app.dependency_overrides[get_async_session]
    app.dependency_overrides[get_async_session]=override
    try:
        token=await _admin_token(factory);lab=await _lab(client,token);sid=await _session(client,token,lab)
        original=tr._require_session_owner
        both=asyncio.Event();arrivals=0
        async def barrier(*args,**kwargs):
            nonlocal arrivals
            row=await original(*args,**kwargs)
            arrivals+=1
            if arrivals==2:both.set()
            await asyncio.wait_for(both.wait(),3)
            return row
        monkeypatch.setattr(tr,'_require_session_owner',barrier)
        responses=await asyncio.gather(*[
            client.put(f'/api/v1/training/sessions/{sid}/workspace',headers=auth_header(token),json={'notes':note,'steps':[],'revision':0})
            for note in ('first independent edit','second independent edit')])
        monkeypatch.setattr(tr,'_require_session_owner',original)
        saved=await client.get(f'/api/v1/training/sessions/{sid}/workspace',headers=auth_header(token))
        evidence('probe-workspace-concurrent',{'responses':[{'status':r.status_code,'body':r.json()} for r in responses],'saved':saved.json(),'store':'isolated file SQLite, two requests meet after separate reads'})
        assert sorted(r.status_code for r in responses)==[200,409],'Concurrent editors both accepted same revision'
    finally:
        app.dependency_overrides[get_async_session]=previous
        await engine.dispose()

@pytest.mark.asyncio
async def test_capability_actions_are_complete_and_callable(client,test_session_factory):
    token=await _admin_token(test_session_factory)
    pages=(await client.get('/api/v1/trust/pages',headers=auth_header(token))).json()
    actions=(await client.get('/api/v1/trust/actions',headers=auth_header(token))).json()
    defined={x['action_id'] for x in actions}
    missing=sorted({a for p in pages for a in p['actions'] if a not in defined})
    did=await _device(test_session_factory,hostname='REVIEW-CATALOG')
    action=next(a for a in actions if a['action_id']=='observe_interfaces')
    called=await client.post(action['path'],headers=auth_header(token),json={'action_id':action['action_id'],'device_id':did})
    evidence('probe-capability-catalog',{'undefined_page_actions':missing,'declared_action':action,'call_status':called.status_code,'call_result':called.json()})
    assert not missing and called.status_code==200

@pytest.mark.asyncio
async def test_active_terminal_blocks_deploy_confirmation(client,test_session_factory,monkeypatch):
    import importlib
    from types import SimpleNamespace
    from core.dependencies import authenticate_token
    from modules.deploy.models import DeployTask,DeployStatus,DeviceWriteLock,ChangeLevel
    from modules.deploy.service import DeployService
    wr=importlib.import_module('modules.webssh.router')
    ds=importlib.import_module('modules.deploy.service')
    token=await _admin_token(test_session_factory)
    did=await _device(test_session_factory,hostname='REVIEW-LOCK')
    async with test_session_factory() as db: actor=await authenticate_token(token,db)
    started=asyncio.Event();release=asyncio.Event()
    class Proxy:
        def __init__(self,**kwargs):pass
        async def start(self):
            started.set()
            await release.wait()
    monkeypatch.setattr(wr,'SSHProxySession',Proxy)
    monkeypatch.setattr(wr.DeviceService,'get_device_credentials',AsyncMock(return_value={'username':'isolated','password':''}))
    monkeypatch.setattr(ds.VRPValidator,'assess',lambda *a,**kw:{'requires_confirmation':False})
    ws=SimpleNamespace(headers={},accept=AsyncMock(),close=AsyncMock(),send_text=AsyncMock())
    task=asyncio.create_task(wr.webssh_websocket(ws,did,token))
    try:
        await asyncio.wait_for(started.wait(),3)
        async with test_session_factory() as db:
            before=await db.get(DeviceWriteLock,did)
            row=DeployTask(device_id=did,config_content='sysname REVIEW',operator_id=actor['user_id'],
                status=DeployStatus.AWAITING_CONFIRMATION,change_level=ChangeLevel.DAILY)
            db.add(row);await db.commit();tid=row.id
            error=None
            try: await DeployService.confirm_task(db,tid,actor,False)
            except Exception as exc:error=type(exc).__name__+': '+str(exc)
            await db.refresh(row)
            lock=await db.get(DeviceWriteLock,did)
            evidence('probe-terminal-first-lock',{'fixture':'fake live proxy, isolated DB, no SSH or deploy execution',
                'terminal_active':not task.done(),'lock_before_confirmation':bool(before),
                'confirmation_error':error,'deploy_status':row.status.value,'lock_after_confirmation':bool(lock)})
            assert error is not None and row.status!=DeployStatus.CONFIRMED,'Active terminal and confirmed deployment coexist'
    finally:
        release.set()
        await task
