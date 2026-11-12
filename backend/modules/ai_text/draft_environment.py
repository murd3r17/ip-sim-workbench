"""Server-owned environment binding for concrete assistant configuration drafts.

Inventory identity is insufficient: mapping/preflight identity must still be
valid. Browser version strings never select a profile. This does not authorize
execution; the existing deployment confirmation remains necessary.
"""
from dataclasses import dataclass

from sqlalchemy import select

from .trusted_context import ResolvedDraftTarget, TrustedPageData
from modules.trust.models import EnvironmentProfile
from modules.trust.service import environment_hash


@dataclass(frozen=True)
class DraftEnvironmentPolicy:
    verified: bool = False
    reason_code: str = 'environment_unbound'
    reason: str = '目标设备还没有可核验的环境映射。'
    device_id: int | None = None
    environment_id: int | None = None
    version: str = ''
    revision: int = 0
    content_hash: str = ''
    mode: str = ''
    checked_at: str = ''

    def as_context(self):
        return {'environment_id':self.environment_id,'version':self.version,'revision':self.revision,
                'mode':self.mode,'checked_at':self.checked_at,'scope':'environment_mapping_preflight_not_current_interface_observation'}


def blocked_draft_policy(policy, reason):
    reason = reason or '无法核验草稿所需的环境。'
    text = (f'本次未生成配置草稿：{reason}\n'
            '尚未读取或修改设备，也未创建下发任务。请先在「设备」确认对象并做只读观察；'
            '环境映射需由管理员完成核验，再请求具体设备的配置草稿。')
    return {**policy,'allow_model':False,'allow_draft':False,'reason':reason,'safe_text':text}


def _contains(row, device_id):
    return any(isinstance(item, dict) and str(item.get('device_id')) == str(device_id)
               for item in (row.devices or []))


def _ready(row):
    return (row.status == 'ready' and row.last_preflight_status == 'ready'
            and row.last_preflight_mode in {'sim', 'real'} and row.last_preflight_at is not None
            and isinstance(row.revision, int) and row.revision > 0
            and bool(row.content_hash) and row.content_hash == environment_hash(row))


async def resolve_draft_environment(db, target, *, page=None):
    if not isinstance(target, ResolvedDraftTarget):
        return DraftEnvironmentPolicy(reason_code='target_unresolved', reason='目标设备尚未唯一核验。')
    if db is None:
        return DraftEnvironmentPolicy(device_id=target.device_id)
    rows = (await db.execute(select(EnvironmentProfile).order_by(EnvironmentProfile.id).limit(1001))).scalars().all()
    if len(rows) > 1000:
        return DraftEnvironmentPolicy(reason_code='scope_exceeded', reason='环境范围过大，无法完成唯一核验。', device_id=target.device_id)
    matches = [row for row in rows if _contains(row, target.device_id)]
    if not matches:
        return DraftEnvironmentPolicy(device_id=target.device_id)
    binding = None
    if (isinstance(page, TrustedPageData) and page.trusted
            and str(page.meta.get('device_id')) == str(target.device_id)
            and page.meta.get('environment_id') is not None):
        binding = page.meta
        matches = [row for row in matches if str(row.id) == str(page.meta['environment_id'])]
    if len(matches) != 1:
        return DraftEnvironmentPolicy(reason_code='environment_ambiguous', reason='设备关联的环境未能唯一确定，请先核对对应环境的只读观察。', device_id=target.device_id)
    row = matches[0]
    if binding and (str(binding.get('environment_revision')) != str(row.revision)
                    or binding.get('environment_version') != row.version):
        return DraftEnvironmentPolicy(reason_code='environment_binding_drift',reason='观察绑定的环境版本或修订已变化，请重新核对。',device_id=target.device_id)
    if not _ready(row):
        return DraftEnvironmentPolicy(reason_code='environment_unverified', reason='环境映射尚未通过核验，或核验后内容已变化。', device_id=target.device_id)
    return DraftEnvironmentPolicy(True, '', '', target.device_id, row.id, row.version, row.revision,
                                  row.content_hash, row.last_preflight_mode, row.last_preflight_at.isoformat())


async def current_draft_environment(db, policy):
    if db is None or not isinstance(policy, DraftEnvironmentPolicy) or not policy.verified:
        return False
    row = await db.get(EnvironmentProfile, policy.environment_id, populate_existing=True)
    return bool(row is not None and _ready(row) and _contains(row, policy.device_id)
                and row.version == policy.version and row.revision == policy.revision
                and row.content_hash == policy.content_hash and row.last_preflight_mode == policy.mode)
