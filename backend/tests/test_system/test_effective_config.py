import json
import pytest
from core.config import Settings
from core.security import create_access_token
from modules.auth.models import User,UserRole
from modules.system.models import SystemConfig
from modules.system.service import SystemService
from modules.system.runtime_config import resolve_value


@pytest.fixture
def configured(monkeypatch):
    import core.config as core
    import modules.system.service as service
    settings=Settings(_env_file=None,llm_provider='openai-compatible',llm_model='authored-main',llm_api_key='AUTHORED_ENV_KEY',llm_temperature=0.3,llm_fallback_model='authored-secondary',llm_fallback_api_key='',llm_fallback_base_url='',knowledge_provider='local')
    monkeypatch.setattr(core,'get_settings',lambda:settings)
    monkeypatch.setattr(service,'get_settings',lambda:settings)
    return settings


def test_invalid_empty_and_nonfinite_overrides_resolve_to_real_fallback():
    for key,value,fallback in [('llm.timeout','x',120),('llm.timeout','0',120),('llm.max_tokens','-1',8192),('llm.temperature','NaN',0.3),('llm.temperature','inf',0.3),('llm.model','  ','main')]:
        parsed,meta=resolve_value(key,value,fallback)
        assert parsed==fallback and meta['source']=='process_settings'
    parsed,meta=resolve_value('llm.temperature','0',0.3)
    assert parsed==0 and meta['source']=='database'
    assert resolve_value('bool','false',True)[0] is False


@pytest.mark.asyncio
async def test_effective_view_matches_llm_runtime_and_does_not_probe(client,test_session_factory,configured,monkeypatch):
    import core.llm_provider as provider
    monkeypatch.setattr(provider,'create_llm_provider',lambda *a,**k:pytest.fail('No provider may be constructed'))
    async with test_session_factory() as db:
        user=User(username='d08-owner',role=UserRole.ADMIN,hashed_password='unused');db.add(user);await db.flush();uid=user.id
        rows=[('llm.model','authored-db'),('llm.temperature','NaN'),('llm.timeout',''),('llm.fallback_api_key',None),('knowledge.provider','anythingllm'),('app.custom_flag','stored-value')]
        db.add_all([SystemConfig(config_key=k,config_value=v) for k,v in rows]);await db.commit()
        actual=await SystemService.get_llm_runtime_config(db)
        assert actual['llm_model']=='authored-db' and actual['llm_temperature']==0.3 and actual['llm_timeout']==configured.llm_timeout
        assert await SystemService.get_llm_config_source(db)=='system_config'
    auth={'Authorization':'Bearer '+create_access_token(uid,'d08-owner','admin')}
    response=await client.get('/api/v1/system/effective-config',headers=auth)
    assert response.status_code==200 and 'AUTHORED_ENV_KEY' not in response.text
    data=response.json();fields={f['key']:f for f in data['fields']};stored={f['key']:f for f in data['stored_items']}
    assert fields['llm.model']['value']==actual['llm_model'] and fields['llm.model']['source']=='database'
    assert fields['llm.temperature']['source']=='process_settings' and fields['llm.temperature']['override_status']=='invalid_fallback'
    assert fields['llm.fallback_api_key']['source']=='inherited' and fields['llm.fallback_api_key']['value']=='已配置'
    assert fields['knowledge.provider']['value']=='local' and stored['knowledge.provider']['activation']=='not_applied'
    assert stored['app.custom_flag']['consumer']=='unregistered'
    assert fields['deploy.simulate_only']['activation']=='restart_backend'
    assert '未探测' in data['scope'] and '精确文件来源' in data['source_note']


@pytest.mark.asyncio
async def test_empty_invalid_rows_do_not_claim_database_source(test_session_factory,configured):
    async with test_session_factory() as db:
        db.add_all([SystemConfig(config_key='llm.model',config_value=' '),SystemConfig(config_key='llm.timeout',config_value='invalid')]);await db.commit()
        assert await SystemService.get_llm_config_source(db)=='env'


@pytest.mark.asyncio
async def test_url_credentials_redacted_and_edit_uses_preserve_semantics(client,test_session_factory,configured):
    secret='D08_URL_PRIVATE'
    original=f'https://reader:{secret}@example.invalid/v1?token={secret}'
    async with test_session_factory() as db:
        user=User(username='d08-url',role=UserRole.ADMIN,hashed_password='unused');db.add(user);await db.flush()
        row=SystemConfig(config_key='llm.base_url',config_value=original);db.add(row);await db.commit();uid=user.id;rid=row.id
    headers={'Authorization':'Bearer '+create_access_token(uid,'d08-url','admin')}
    for endpoint in ['/api/v1/system/config','/api/v1/system/effective-config']:
        response=await client.get(endpoint,headers=headers);assert response.status_code==200 and secret not in response.text
        if endpoint.endswith('/config'):
            record=next(i for i in response.json() if i['config_key']=='llm.base_url')
            assert record['is_secret'] and record['config_value']=='******'
    response=await client.put('/api/v1/system/config/llm.base_url',headers=headers,json={'description':'preserve URL','config_value':None})
    assert response.status_code==200
    async with test_session_factory() as db:assert (await db.get(SystemConfig,rid)).config_value==original


@pytest.mark.asyncio
async def test_effective_configuration_requires_admin(client,test_session_factory,configured):
    async with test_session_factory() as db:
        user=User(username='d08-normal',role=UserRole.USER,hashed_password='unused');db.add(user);await db.commit();uid=user.id
    headers={'Authorization':'Bearer '+create_access_token(uid,'d08-normal','user')}
    assert (await client.get('/api/v1/system/effective-config',headers=headers)).status_code==403
    assert (await client.post('/api/v1/system/llm-health',headers=headers)).status_code==403


@pytest.mark.asyncio
async def test_model_connectivity_only_probes_llm_and_audits(client,test_session_factory,configured,monkeypatch):
    from unittest.mock import AsyncMock
    import core.health as health
    from modules.auth.models import AuditLog
    from sqlalchemy import select
    probe=AsyncMock(return_value={'status':'healthy','provider':'openai_compatible','model':'authored-main','config_source':'env'})
    monkeypatch.setattr(health,'_probe_llm',probe)
    monkeypatch.setattr(health,'get_health_status',AsyncMock(side_effect=AssertionError('Do not probe unrelated dependencies')))
    async with test_session_factory() as db:
        user=User(username='d08-probe',role=UserRole.ADMIN,hashed_password='unused');db.add(user);await db.commit();uid=user.id
    headers={'Authorization':'Bearer '+create_access_token(uid,'d08-probe','admin')}
    response=await client.post('/api/v1/system/llm-health',headers=headers)
    assert response.status_code==200 and '缓存' in response.json()['scope'] and response.json()['generated_at']
    probe.assert_awaited_once()
    async with test_session_factory() as db:
        rows=(await db.execute(select(AuditLog).where(AuditLog.action=='llm_test'))).scalars().all()
        assert rows and 'AUTHORED_ENV_KEY' not in json.dumps([row.detail for row in rows])
