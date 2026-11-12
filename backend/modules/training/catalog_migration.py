"""Explicit D content upgrade. Match entire known managed identities, preserve users."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from sqlalchemy import select
from core.time_utils import iso_utc
from modules.training.builtin_catalog import CATALOG_VERSION, builtin_labs, workflow_demo_lab
from modules.training.models import TrainingLab

FIELDS = ('title','description','objectives','time_limit_minutes','is_sandbox','content_version','environment_spec')
IDENTITIES = Path(__file__).with_name('data') / 'legacy_catalog_identities_20261107.json'


def managed(row):
    value = {key: deepcopy(row.get(key) if isinstance(row, dict) else getattr(row, key)) for key in FIELDS}
    value['is_sandbox'] = bool(value['is_sandbox'])
    return value


def digest(row):
    return hashlib.sha256(json.dumps(managed(row), ensure_ascii=False, sort_keys=True, separators=(',',':')).encode()).hexdigest()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # A previous rollback record is never overwritten by a repeated migration.
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


async def upgrade(db, *, dry_run=True, backup_path=None, fail_after=None):
    known = json.loads(IDENTITIES.read_text(encoding='utf-8'))['known']
    rows = (await db.execute(select(TrainingLab).order_by(TrainingLab.id).with_for_update())).scalars().all()
    report = {'version': CATALOG_VERSION, 'dry_run':dry_run, 'updated':[], 'skipped':[], 'already_current':[]}
    backups = []
    planned = []
    for target in [*builtin_labs(), workflow_demo_lab()]:
        candidates = [r for r in rows if r.title==target['title']]
        if len(candidates)!=1:
            report['skipped'].append({'title':target['title'],'reason':'missing' if not candidates else 'duplicate_title',
                                       'ids':[r.id for r in candidates]})
            continue
        row = candidates[0]
        if digest(row)==digest(target):
            report['already_current'].append(row.id)
            continue
        if digest(row) not in known.get(row.title,[]):
            report['skipped'].append({'id':row.id,'title':row.title,'reason':'modified_or_unknown_managed_identity'})
            continue
        planned.append((row,target))
        report['updated'].append({'id':row.id,'title':row.title,'from_version':row.content_version})
        backups.append({'id':row.id,'created_at':iso_utc(row.created_at) if row.created_at else None,
                        'before':managed(row),'after_digest':digest(target)})
    if not dry_run and planned and not backup_path:
        raise ValueError('写入前必须指定一个新的完整备份文件')
    if backup_path:
        write_new(backup_path, {'kind':'v7d_managed_content_rollback','version':CATALOG_VERSION,
                               'captured_at':datetime.now(timezone.utc).isoformat(), 'rows':backups})
    try:
        if not dry_run:
            for index,(row,target) in enumerate(planned,1):
                for key,value in managed(target).items(): setattr(row,key,value)
                if fail_after and index>=fail_after: raise RuntimeError('injected D migration failure')
            await db.commit()
        else:
            await db.rollback()
    except Exception:
        await db.rollback()
        raise
    return report


async def restore(db, backup_path, *, dry_run=True):
    data = json.loads(Path(backup_path).read_text(encoding='utf-8'))
    if data.get('kind')!='v7d_managed_content_rollback' or not isinstance(data.get('rows'),list):
        raise ValueError('不是D阶段完整内容备份')
    result={'dry_run':dry_run,'restored':[],'skipped':[]}
    try:
        for saved in data['rows']:
            if set(saved.get('before',{})) != set(FIELDS):
                raise ValueError('备份受管字段不完整')
            row = await db.get(TrainingLab,saved['id'],with_for_update=True)
            created = iso_utc(row.created_at) if row and row.created_at else None
            if not row or created!=saved.get('created_at') or digest(row)!=saved.get('after_digest'):
                result['skipped'].append({'id':saved['id'],'reason':'missing_recreated_or_modified_since_upgrade'})
                continue
            if not dry_run:
                for key,value in managed(saved['before']).items(): setattr(row,key,value)
            result['restored'].append(row.id)
        if dry_run: await db.rollback()
        else: await db.commit()
    except Exception:
        await db.rollback()
        raise
    return result
