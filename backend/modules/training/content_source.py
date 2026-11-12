"""V7-A AF-05/AF-06：会话有效实验内容解析。

报告、摘要、指纹、教练提示必须使用同一来源：

- ``session_snapshot``：会话开始时保存的步骤/版本，可信；
- ``legacy_unversioned``：旧会话且实验尚未版本化——按当前内容展示，但明确标注
  “无法证明当时版本”，不得写成已核验 v7a；
- ``legacy_unknown``：旧会话且实验已被版本化更新——无法知道当时步骤，不再把当前
  教材内容当作历史任务指导。
"""
from __future__ import annotations


def resolve_session_content(session, lab) -> dict:
    snapshot = getattr(session, "content_snapshot", None)
    if isinstance(snapshot, dict) and isinstance(snapshot.get("objectives"), list) and snapshot["objectives"]:
        return {
            "source": "session_snapshot",
            "objectives": snapshot["objectives"],
            "title": snapshot.get("title") or getattr(lab, "title", "") or "",
            "version": snapshot.get("version") or getattr(session, "content_version", None),
            "warning": "",
            "can_guide": True,
            "environment_spec": snapshot.get('environment_spec'),
        }
    lab_version = getattr(lab, "content_version", None)
    if not lab_version:
        return {
            "source": "legacy_unversioned",
            "objectives": list(getattr(lab, "objectives", None) or []),
            "title": getattr(lab, "title", "") or "",
            "version": None,
            "warning": "该会话早于内容版本管理；按当前实验内容展示，不能证明当时使用的版本。",
            "can_guide": True,
        }
    return {
        "source": "legacy_unknown",
        "objectives": [],
        "title": (snapshot or {}).get("title") or getattr(lab, "title", "") or "",
        "version": None,
        "warning": "该会话早于内容版本记录，且实验内容已被版本化更新；无法证明当时步骤，已停止按当前教材生成现场指导。",
        "can_guide": False,
    }


def content_brief(resolved: dict) -> str:
    labels = [str(item.get("name") or item.get("goal") or "").strip() for item in resolved.get("objectives") or [] if isinstance(item, dict)]
    labels = [label for label in labels if label]
    return "；".join(labels) or "未设置"
