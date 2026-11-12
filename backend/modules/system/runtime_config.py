"""Runtime resolution and safe display; reading this view performs no probes."""
import math
from urllib.parse import urlsplit, urlunsplit
from core.redaction import redact_sensitive


def resolve_value(key, value, fallback):
    meta = {'source': 'process_settings', 'override_status': 'absent'}
    if value is None:
        return fallback, meta
    raw = value.strip()
    if not raw:
        return fallback, {**meta, 'override_status': 'empty_fallback'}
    try:
        if isinstance(fallback, bool):
            if raw.lower() not in {'1','true','yes','on','0','false','no','off'}:
                raise ValueError('boolean')
            parsed = raw.lower() in {'1','true','yes','on'}
        elif isinstance(fallback, int):
            parsed = int(raw)
        elif isinstance(fallback, float):
            parsed = float(raw)
            if not math.isfinite(parsed):
                raise ValueError('nonfinite')
        else:
            parsed = raw
        if key in {'llm.timeout','llm.max_tokens'} and parsed <= 0:
            raise ValueError('positive')
    except (ValueError, TypeError, OverflowError):
        return fallback, {**meta, 'override_status': 'invalid_fallback'}
    return parsed, {'source': 'database', 'override_status': 'applied'}


def safe_value(key, value, secret=False):
    if secret:
        return '已配置' if value not in (None, '') else '未配置'
    if isinstance(value,float) and not math.isfinite(value):
        return '非有限数值（需修正）'
    if not isinstance(value, str):
        return value
    value = redact_sensitive(value)
    if key.endswith(('url', 'base_url')):
        try:
            parts = urlsplit(value)
            if parts.scheme and parts.netloc:
                # Display only. The saved/actual provider URL is never changed.
                host = parts.hostname or ''
                if ':' in host:
                    host = '['+host+']'
                if parts.port:
                    host += ':'+str(parts.port)
                return urlunsplit((parts.scheme,host,parts.path,'','')) + (' [查询/用户信息已隐藏]' if parts.query or parts.fragment or parts.username or parts.password else '')
        except ValueError:
            return 'URL格式有误（内容已隐藏）'
    return value


PROCESS_FIELDS = {
    'llm.vision_model': ('llm_vision_model','vision'),
    'llm.thinking_enabled': ('llm_thinking_enabled','llm'),
    'llm.reasoning_effort': ('llm_reasoning_effort','llm'),
    'knowledge.provider': ('knowledge_provider','knowledge'),
    'knowledge.base_url': ('knowledge_base_url','knowledge'),
    'knowledge.api_key': ('knowledge_api_key','knowledge'),
    'knowledge.workspace_slug': ('knowledge_workspace_slug','knowledge'),
    'knowledge.top_k': ('knowledge_top_k','knowledge'),
    'monitor.scheduler_enabled': ('monitor_scheduler_enabled','monitor'),
    'monitor.collect_interval': ('monitor_collect_interval','monitor'),
    'device.mode': ('device_mode','device'),
    'deploy.simulate_only': ('deploy_simulate_only','deploy'),
    'deploy.allowlist_device_ids': ('deploy_allowlist_device_ids','deploy'),
    'deploy.allowlist_topology_id': ('deploy_allowlist_topology_id','deploy'),
    'deploy.allowlist_baseline_version': ('deploy_allowlist_baseline_version','deploy'),
}


def stored_consumer(key, llm_keys):
    if key in llm_keys:
        return {'consumer':'llm_runtime','activation':'next_provider','note':'后续新请求构造模型provider时读取；在途请求保持原配置。'}
    if key == 'monitor.thresholds':
        return {'consumer':'monitor_thresholds','activation':'next_collection','note':'与内置阈值逐项合并；interface_down旧总数项不控制D06用途告警。'}
    if key.startswith('monitor.port_expectations.'):
        return {'consumer':'port_expectations','activation':'next_collection','note':'用途及预期是本地登记；请从监控页版本化编辑，重新采集后再核对。'}
    if key in PROCESS_FIELDS:
        return {'consumer':'stored_only','activation':'not_applied','note':'此数据库键没有对应覆盖读取器；实际值来自进程启动配置，修改启动环境后按部署流程重启。'}
    return {'consumer':'unregistered','activation':'unknown','note':'未登记运行消费者；保存键值不证明已改变服务行为。'}


async def effective_config(db):
    from datetime import datetime,timezone
    from core.config import Settings,get_settings
    from .service import SystemService,LLM_CONFIG_KEYS
    from modules.monitor.service import load_thresholds
    settings=get_settings();details=await SystemService.get_llm_runtime_details(db)
    runtime,metadata=details['values'],details['fields']
    fields=[]
    for key,attr in LLM_CONFIG_KEYS.items():
        value=runtime[attr];meta=metadata[key].copy();active=True
        if key.startswith('llm.fallback_'):
            active=bool(runtime['llm_fallback_model'])
        if key in {'llm.fallback_base_url','llm.fallback_api_key'} and not value:
            inherited='llm.base_url' if key.endswith('base_url') else 'llm.api_key'
            value=runtime[LLM_CONFIG_KEYS[inherited]];meta.update(source='inherited',inherited_from=inherited)
        if key=='llm.provider':value=str(value).strip().lower().replace('-','_')
        secret=SystemService._is_secret_key(key)
        fields.append({'key':key,'group':'fallback' if key.startswith('llm.fallback_') else 'llm','value':safe_value(key,value,secret),'default_value':safe_value(key,Settings.model_fields[attr].default,secret),'configured':value not in (None,''),'is_secret':secret,'active':active,'activation':'next_provider',**meta})
    for key,(attr,group) in PROCESS_FIELDS.items():
        value=getattr(settings,attr);secret=SystemService._is_secret_key(key)
        fields.append({'key':key,'group':group,'value':safe_value(key,value,secret),'default_value':safe_value(key,Settings.model_fields[attr].default,secret),'configured':value not in (None,''),'is_secret':secret,'active':True,'activation':'restart_backend','source':'process_settings','override_status':'not_supported'})
    stored=await SystemService.list_configs(db)
    def safe_numbers(value):
        if isinstance(value,float) and not math.isfinite(value):return '非有限数值（需修正）'
        if isinstance(value,dict):return {k:safe_numbers(v) for k,v in value.items()}
        return value
    return {'generated_at':datetime.now(timezone.utc).isoformat(),'fields':fields,
            'stored_items':[{'key':x.config_key,**stored_consumer(x.config_key,LLM_CONFIG_KEYS)} for x in stored],
            'known_items':[{'key':key,**stored_consumer(key,LLM_CONFIG_KEYS)} for key in [*LLM_CONFIG_KEYS,*PROCESS_FIELDS,'monitor.thresholds']],
            'monitor_thresholds':safe_numbers(await load_thresholds(db)),
            'source_note':'进程启动配置是环境变量、.env与代码默认值的合并快照；本进程未保存每项精确文件来源。默认值列仅作代码默认参照。',
            'scope':'只读配置快照，未探测模型、知识库或设备；配置完整不等于连通或回答质量通过。',
            'chains':{'dialogue':'主模型及备用参数采用支持的数据库覆盖；备用地址/密钥为空时继承主模型。','vision':'视觉模型名称来自启动设置；不是AnythingLLM嵌入模型。','knowledge':'知识检索provider和workspace来自启动设置；嵌入模型由所用检索服务独立管理。'}}
