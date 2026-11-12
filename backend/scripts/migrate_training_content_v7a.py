# -*- coding: utf-8 -*-
"""V7-A A-02 / AF-05 / AF2-01：把既有库里的 OSPF 系统样例幂等升级到共享参数版本。

安全边界（AF2-01 收紧）：
- 只匹配标题在 ``lab_seed_payloads()`` 里的系统样例；
- 旧值证据分两层：四字段整行指纹（description、时限、is_sandbox、objectives）
  + 迁移还会写入字段的可靠旧值（environment_spec/content_version 必须为空）；
- 同标题多条记录只处理 id 最小的一条，其余视为用户自建/来源未知，保守跳过；
- 用户改过任一受管字段（包括只改环境映射）都跳过，并区分“与旧样例不同”和
  “与目标新内容不同”，不把正常旧内容变化误叫用户修改；
- 全部更新在同一个事务里，任何异常回滚，不留半更新状态；
- ``--backup`` 导出**可恢复的完整受管字段**（不是摘要），可用 ``--restore`` 回写；
- 不删除、不重建实验；历史会话含义由 ``content_source`` 解析，不用新内容冒充旧版本。

用法::

    python scripts/migrate_training_content_v7a.py --dry-run
    python scripts/migrate_training_content_v7a.py --backup backup.json --report result.json
    python scripts/migrate_training_content_v7a.py --restore backup.json --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import modules.auth.models  # noqa: F401,E402
import modules.deploy.models  # noqa: F401,E402
import modules.device.models  # noqa: F401,E402
import modules.monitor.models  # noqa: F401,E402
import modules.training.models  # noqa: F401,E402
import modules.ai_text.models  # noqa: F401,E402

from sqlalchemy import select  # noqa: E402

from core.database import close_db, get_session_factory, init_db  # noqa: E402
from modules.training.lab_content import (  # noqa: E402
    CONTENT_VERSION,
    known_legacy_fingerprints,
    lab_seed_payloads,
    legacy_managed_defaults,
    system_lab_fingerprint,
)
from modules.training.models import TrainingLab  # noqa: E402

MANAGED_FIELDS = (
    "title",
    "description",
    "objectives",
    "time_limit_minutes",
    "is_sandbox",
    "content_version",
    "environment_spec",
)


def _row_fingerprint(lab: TrainingLab) -> str:
    return system_lab_fingerprint(
        description=lab.description,
        time_limit_minutes=lab.time_limit_minutes,
        is_sandbox=lab.is_sandbox,
        objectives=lab.objectives,
    )


def _is_current(lab: TrainingLab, payload: dict) -> bool:
    return (
        lab.content_version == CONTENT_VERSION
        and lab.title == payload["title"]
        and lab.description == payload["description"]
        and lab.objectives == payload["objectives"]
        and lab.time_limit_minutes == payload["time_limit_minutes"]
        and bool(lab.is_sandbox) == bool(payload.get("is_sandbox", False))
        and lab.environment_spec == payload["environment_spec"]
    )


def _field_diffs(lab: TrainingLab, payload: dict) -> list[str]:
    """与目标新内容不同的字段（正常旧样例也会在这里）。"""
    diffs: list[str] = []
    if lab.description != payload["description"]:
        diffs.append("description")
    if lab.time_limit_minutes != payload["time_limit_minutes"]:
        diffs.append("time_limit_minutes")
    if bool(lab.is_sandbox) != bool(payload.get("is_sandbox", False)):
        diffs.append("is_sandbox")
    if lab.objectives != payload["objectives"]:
        diffs.append("objectives")
    if lab.environment_spec != payload["environment_spec"]:
        diffs.append("environment_spec")
    if lab.content_version != payload["content_version"]:
        diffs.append("content_version")
    return diffs


def _legacy_extra_diffs(lab: TrainingLab, defaults: dict) -> list[str]:
    """迁移会写入、但四字段指纹未覆盖的字段与可靠旧值不一致的字段。"""
    diffs = []
    for field, expected in defaults.items():
        if getattr(lab, field) != expected:
            diffs.append(field)
    return diffs


def _row_snapshot(lab: TrainingLab) -> dict:
    """完整受管字段，可直接回写恢复（不是摘要）。"""
    row = {field: getattr(lab, field) for field in MANAGED_FIELDS}
    row["id"] = lab.id
    row["created_at"] = lab.created_at.isoformat() if lab.created_at else None
    return row


def _snapshot_digest(row: dict) -> str:
    raw = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def migrate(dry_run: bool, *, backup_path: str | None = None, fail_after: int | None = None) -> dict:
    """执行/演练迁移。

    ``fail_after`` 仅用于隔离测试：在第 N 条更新后抛错，验证事务回滚与恢复。
    """
    seed = {item["title"]: item for item in lab_seed_payloads()}
    legacy = known_legacy_fingerprints()
    defaults = legacy_managed_defaults()
    _, _ = await init_db()
    factory = get_session_factory()
    report = {
        "content_version": CONTENT_VERSION,
        "dry_run": dry_run,
        "updated": [],
        "skipped_user_modified": [],
        "skipped_same_title": [],
        "skipped_missing": [],
        "already_current": [],
        "backup": None,
        "failure": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    async with factory() as db:
        labs = (await db.execute(select(TrainingLab).order_by(TrainingLab.id))).scalars().all()
        by_title: dict[str, list[TrainingLab]] = {}
        for lab in labs:
            by_title.setdefault(lab.title, []).append(lab)

        if backup_path:
            snapshot = [_row_snapshot(lab) for lab in labs]
            path = Path(backup_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "content_version": CONTENT_VERSION,
                "kind": "restorable_managed_content",
                "fields": list(MANAGED_FIELDS),
                "rows": snapshot,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            report["backup"] = {
                "path": str(path),
                "kind": "restorable_managed_content",
                "restorable": True,
                "row_count": len(snapshot),
                "fields": list(MANAGED_FIELDS),
                "digest": hashlib.sha256(path.read_bytes()).hexdigest(),
            }

        try:
            applied = 0
            for title, payload in seed.items():
                candidates = sorted(by_title.get(title, []), key=lambda item: item.id)
                if not candidates:
                    report["skipped_missing"].append(title)
                    continue
                # 同名多条：只认 id 最小的系统记录，其余是用户自建/来源未知。
                for extra in candidates[1:]:
                    report["skipped_same_title"].append({
                        "id": extra.id,
                        "title": title,
                        "differences_from_target": _field_diffs(extra, payload),
                        "reason_code": "same_title_unknown_origin",
                        "reason": "同标题存在多条记录，仅 id 最小的系统样例可升级；该记录来源未知，不覆盖",
                    })
                lab = candidates[0]
                if _is_current(lab, payload):
                    report["already_current"].append({"id": lab.id, "title": title})
                    continue
                fingerprint = _row_fingerprint(lab)
                extra_diffs = _legacy_extra_diffs(lab, defaults.get(title, {}))
                if fingerprint not in legacy.get(title, set()):
                    report["skipped_user_modified"].append({
                        "id": lab.id,
                        "title": title,
                        "fingerprint": fingerprint,
                        "differences_from_target": _field_diffs(lab, payload),
                        "differences_from_legacy": ["description", "time_limit_minutes", "is_sandbox", "objectives"],
                        "reason_code": "fingerprint_mismatch",
                        "reason": "系统内容指纹与历史样例不一致（用户修改或来源未知），不覆盖",
                    })
                    continue
                if extra_diffs:
                    report["skipped_user_modified"].append({
                        "id": lab.id,
                        "title": title,
                        "fingerprint": fingerprint,
                        "differences_from_target": _field_diffs(lab, payload),
                        "differences_from_legacy": extra_diffs,
                        "reason_code": "legacy_managed_field_mismatch",
                        "reason": (
                            "environment_spec/content_version 与旧系统默认值不一致"
                            "（用户修改或来源未知），不覆盖"
                        ),
                    })
                    continue
                report["updated"].append({
                    "id": lab.id,
                    "title": title,
                    "from_version": lab.content_version,
                    "from_fingerprint": fingerprint,
                    "differences_from_target": _field_diffs(lab, payload),
                })
                if not dry_run:
                    lab.title = payload["title"]
                    lab.description = payload["description"]
                    lab.objectives = payload["objectives"]
                    lab.time_limit_minutes = payload["time_limit_minutes"]
                    lab.is_sandbox = payload.get("is_sandbox", False)
                    lab.content_version = payload["content_version"]
                    lab.environment_spec = payload["environment_spec"]
                    applied += 1
                    if fail_after is not None and applied >= fail_after:
                        raise RuntimeError("injected migration failure (test only)")
            if not dry_run:
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            report["failure"] = {
                "error": f"{type(exc).__name__}: {exc}",
                "rolled_back": True,
                "updated_before_failure": len(report["updated"]),
            }
            report["updated"] = []
            await close_db()
            return report
    await close_db()
    report["updated_count"] = len(report["updated"])
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    return report


async def restore_backup(backup_path: str, *, dry_run: bool = False) -> dict:
    """显式把完整受管字段写回同 id 记录；用于演练/误迁移恢复。"""
    data = json.loads(Path(backup_path).read_text(encoding="utf-8"))
    if data.get("kind") != "restorable_managed_content":
        raise ValueError("备份不是可恢复的受管内容快照（kind 不匹配）")
    rows = data.get("rows") or []
    _, _ = await init_db()
    factory = get_session_factory()
    result = {"restored": [], "missing": [], "dry_run": dry_run}
    async with factory() as db:
        for row in rows:
            lab = await db.get(TrainingLab, row.get("id"))
            if lab is None:
                result["missing"].append({"id": row.get("id"), "title": row.get("title")})
                continue
            for field in MANAGED_FIELDS:
                if field in row:
                    setattr(lab, field, row[field])
            result["restored"].append({"id": lab.id, "title": lab.title})
        if dry_run:
            await db.rollback()
        else:
            await db.commit()
    await close_db()
    result["restored_count"] = len(result["restored"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="幂等升级 OSPF 系统样例到 V7-A 共享参数版本")
    parser.add_argument("--dry-run", action="store_true", help="只报告，不写库")
    parser.add_argument(
        "--backup",
        default="",
        help="迁移前把全部受管字段写成可恢复 JSON（不是摘要；含 environment_spec/content_version）",
    )
    parser.add_argument("--restore", default="", help="从 --backup 生成的可恢复快照回写受管字段")
    parser.add_argument("--report", default="", help="把 JSON 结果写到指定路径")
    args = parser.parse_args()
    if args.restore:
        report = asyncio.run(restore_backup(args.restore, dry_run=args.dry_run))
    else:
        report = asyncio.run(migrate(args.dry_run, backup_path=args.backup or None))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return 1 if report.get("failure") else 0


if __name__ == "__main__":
    raise SystemExit(main())
