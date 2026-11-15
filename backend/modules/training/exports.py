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


def render_learning_record(data: dict) -> str:
    """Readable view of the same redacted, saved records as the JSON export."""
    session, workspace = data["session"], data["workspace"]
    title = " ".join(str(session.get("title") or "实训").splitlines())
    status = {
        "in_progress": "进行中", "completed": "已结束", "abandoned": "已放弃", "pending": "待开始",
    }.get(session["status"], "状态未记录")
    steps = {str(item.get("id")): item.get("status") for item in workspace["steps"] if isinstance(item, dict)}
    objectives = [item for item in session["objectives"] if isinstance(item, dict)]
    logged = sum(steps.get(str(item.get("id"))) == "done" for item in objectives)
    logs = data["logs"]
    lines = [
        f"# {title} · 学习记录", "",
        f"- 会话 #{session['id']} · {status}",
        f"- 课程版本 {session.get('content_version') or '未记录'}",
        f"- 学员记录 {logged}/{len(objectives)} 步",
        "- 技能未验证。会话状态和步骤标记仅用于记录学习进度。",
        f"- 保存的操作记录 {len(logs)} 条",
        "", "## 已保存笔记", "",
    ]
    notes = str(workspace.get("notes") or "没有已保存的笔记。")
    lines.extend("> " + line for line in notes.splitlines())
    lines.extend(["", "## 步骤记录", ""])
    for item in objectives:
        name = " ".join(str(item.get("name") or item.get("goal") or "步骤").splitlines())
        marked = "已标记完成" if steps.get(str(item.get("id"))) == "done" else "待记录"
        lines.append(f"- {name} · {marked}")
    if not objectives:
        lines.append("没有可核对的课程步骤。")
    if logs:
        lines.extend(["", "## 保存的观察与操作", ""])
        for log in logs:
            event = " ".join(str(log.get("command") or log.get("action") or "记录").splitlines())
            result = " ".join(str(log.get("result") or "未保存输出").splitlines())
            lines.append(f"- {log.get('timestamp') or '时间未记录'} · {event} · {result}")
    report = data.get("report")
    lines.extend(["", "## AI 复盘", ""])
    if report:
        lines.append(f"已保存版本 v{report['version']}。以下为建议与解释。")
        lines.append("")
        lines.extend("> " + line for line in (report.get("report_text") or report.get("summary") or "").splitlines())
    else:
        lines.append("本会话暂无已保存的 AI 复盘。")
    return "\n".join(lines) + "\n"
