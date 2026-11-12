"""Read-only, version-specific exports; stored evidence is never rewritten."""
from copy import deepcopy
import hashlib
from datetime import datetime, timezone

from fastapi import HTTPException
from core.redaction import redact_payload
from core.time_utils import iso_utc
from modules.training import reports
from modules.training.content_source import resolve_session_content


def select_report(versions, version=None):
    if version is not None and version <= 0:
        raise HTTPException(status_code=422, detail='报告版本须为正整数')
    ready = [row for row in versions if row.status == reports.REPORT_STATUS_READY]
    if version is None:
        return max(ready, key=lambda row: row.version, default=None)
    selected = next((row for row in ready if row.version == version), None)
    if selected is None:
        raise HTTPException(status_code=404, detail='所选报告版本不存在或未成功保存，请重新读取版本列表')
    return selected


def build_export(snapshot, workspace, versions, version=None):
    session=snapshot['session']
    resolved=resolve_session_content(session,snapshot['lab'])
    selected=select_report(versions,version)
    report=deepcopy(reports.serialize_report(selected)) if selected is not None else None
    if report:
        for source in report['sources']:
            if not isinstance(source,dict):
                continue
            content=source.get('content')
            if isinstance(content,str):
                exported=redact_payload(content)
                source['export_content_redacted']=exported!=content
                source['export_content_sha256']=hashlib.sha256(exported.encode()).hexdigest()
    return redact_payload({
        'format':'ip-workbench.training-export.v1',
        'exported_at':iso_utc(datetime.now(timezone.utc)),
        'session':{'id':session.id,'lab_id':session.lab_id,'status':session.status,
                   'started_at':iso_utc(session.started_at),'completed_at':iso_utc(session.completed_at),
                   'content_version':resolved['version'],'content_source':resolved['source'],
                   'content_warning':resolved['warning'],'title':resolved['title'],
                   'objectives':deepcopy(resolved['objectives']),
                   'environment_id':getattr(session,'trust_environment_id',None),
                   'environment_version':getattr(session,'trust_environment_version',None),
                   'mode_snapshot':deepcopy(session.mode_snapshot)},
        'workspace':deepcopy(workspace),
        'logs':deepcopy(snapshot['logs']),
        'report':report,
        'scope':{
            'workspace':'当前已保存的笔记/步骤修订，不含浏览器未保存草稿；与报告生成输入相互独立',
            'report':'所选成功保存版本；来源片段为生成时快照，不重新检索或生成',
            'hashes':'input_hash、prompt_sha256等原指纹保留其生成时语义；export_content_sha256对应本次脱敏片段',
            'redaction':'仅导出副本遮蔽识别到的凭据字段/配置行，原记录不变',
        },
    })
