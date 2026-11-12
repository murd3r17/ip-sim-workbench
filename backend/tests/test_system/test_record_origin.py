import pytest
from core.record_origin import declared_origin,background_origin
from core.security import create_access_token
from modules.auth.models import User,UserRole
from modules.deploy.models import DeployBatch,DeployTask,DeployStatus
from modules.device.models import Device,DeviceType,Topology
from modules.system.models import BackgroundTask,TaskStatus


def test_only_declared_sources_classify_and_function_type_is_not_origin():
    assert declared_origin('test_fixture')=='test'
    assert declared_origin('manual')=='normal'
    for value in [None,'','legacy','TEST','测试任务','simulated']:
        assert declared_origin(value)=='unknown'
    assert background_origin('test')=='test'
    assert background_origin('deploy')=='unknown'


@pytest.mark.asyncio
async def test_origin_metadata_preserves_owner_visibility_and_never_uses_names(client,test_session_factory):
    async with test_session_factory() as db:
        user=User(username='d08-own-origin',role=UserRole.USER,hashed_password='unused')
        other=User(username='d08-other-origin',role=UserRole.USER,hashed_password='unused')
        topology=Topology(name='D08 origin');db.add_all([user,other,topology]);await db.flush()
        device=Device(hostname='D08 metadata',mgmt_ip='198.18.108.1',device_type=DeviceType.ROUTER,topology_id=topology.id)
        db.add(device);await db.flush();uid=user.id
        batches=[DeployBatch(name=name,source=source,operator_id=user.id) for name,source in [('测试名字但手动创建','manual'),('例行维护','test_fixture'),('正常名字但来源未明','legacy')]]
        foreign=DeployBatch(name='other test',source='test_fixture',operator_id=other.id);db.add_all([*batches,foreign]);await db.flush();foreign_id=foreign.id
        tasks=[DeployTask(batch_id=x.id,device_id=device.id,config_content='description authored',operator_id=x.operator_id,status=DeployStatus.PENDING) for x in [*batches,foreign]]
        db.add_all(tasks);await db.commit();foreign_task_id=tasks[-1].id
    headers={'Authorization':'Bearer '+create_access_token(uid,'d08-own-origin','user')}
    response=await client.get('/api/v1/deploy/batches',headers=headers)
    assert response.status_code==200
    rows=response.json();assert len(rows)==3 and foreign_id not in [row['id'] for row in rows]
    assert {row['name']:row['record_origin'] for row in rows}=={'测试名字但手动创建':'normal','例行维护':'test','正常名字但来源未明':'unknown'}
    rows=(await client.get('/api/v1/deploy/tasks',headers=headers)).json()
    assert len(rows)==3 and {row['record_origin'] for row in rows}=={'normal','test','unknown'}
    assert (await client.get(f'/api/v1/deploy/tasks/{foreign_task_id}',headers=headers)).status_code==403
    assert (await client.get(f'/api/v1/deploy/batches/{foreign_id}',headers=headers)).status_code==403


@pytest.mark.asyncio
async def test_background_legacy_origin_unknown_and_explicit_test_preserved(client,test_session_factory):
    async with test_session_factory() as db:
        user=User(username='d08-admin-origin',role=UserRole.ADMIN,hashed_password='unused');db.add(user);await db.flush();uid=user.id
        db.add_all([BackgroundTask(task_name='测试名字',task_type='deploy',status=TaskStatus.PENDING),BackgroundTask(task_name='日常维护',task_type='test_fixture',status=TaskStatus.SUCCESS)])
        await db.commit()
    headers={'Authorization':'Bearer '+create_access_token(uid,'d08-admin-origin','admin')}
    response=await client.get('/api/v1/system/tasks',headers=headers)
    assert response.status_code==200
    values={row['task_name']:row['record_origin'] for row in response.json()['items']}
    assert values['测试名字']=='unknown' and values['日常维护']=='test'
