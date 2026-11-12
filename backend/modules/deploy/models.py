"""配置下发模块数据模型"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Enum as SAEnum, Index, JSON
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum
from core.database import Base
from core.legacy_types import LegacyReadableEnum


class DeployStatus(str, enum.Enum):
    """下发任务状态。

    已删除从未被赋值的 VALIDATING（P2-06）：V6.0 的校验发生在创建任务时
    （`VRPValidator.assess`），不存在独立的"校验中"阶段，保留只会让前端显示
    一个永远不会出现的状态。旧数据库已存的 validating 仅通过列类型兼容读取，
    不重新加入现行状态转换。
    """

    PENDING = "pending"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CONFIRMED = "confirmed"
    DEPLOYING = "deploying"
    VERIFYING = "verifying"
    SUCCESS = "success"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"


class ChangeLevel(str, enum.Enum):
    EMERGENCY = "emergency"
    DAILY = "daily"
    HIGH_RISK = "high_risk"


class DeployBatch(Base):
    __tablename__ = "deploy_batch"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    source = Column(String(32), nullable=False, default="manual")
    planned_at = Column(DateTime, nullable=True)
    operator_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class DeployTask(Base):
    __tablename__ = "deploy_task"
    __table_args__ = (
        Index("ix_deploy_device", "device_id"),
        Index("ix_deploy_transaction", "transaction_id"),
        Index("ix_deploy_status", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(Integer, ForeignKey("deploy_batch.id"), nullable=True, index=True)
    transaction_id = Column(String(64), nullable=True, index=True)
    device_id = Column(Integer, ForeignKey("device.id"), nullable=False)
    template_id = Column(Integer, ForeignKey("config_template.id"), nullable=True)
    config_content = Column(Text, nullable=False)
    # 本次下发所依据的配置快照（形如 config_version:12/v3），仅作溯源用；
    # 由 DeployService.create_pending_tasks 写入（P2-06）。
    config_watermark = Column(String(256), nullable=True)
    status = Column(LegacyReadableEnum(DeployStatus, legacy_values=("validating",)), default=DeployStatus.PENDING, nullable=False)
    engine = Column(String(16), default="netmiko")
    change_level = Column(SAEnum(ChangeLevel, values_callable=lambda x: [e.value for e in x]), default=ChangeLevel.DAILY)
    result_output = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    backup_config = Column(Text, nullable=True)
    rollback_output = Column(Text, nullable=True)
    verified = Column(Boolean, default=False)
    verify_diff = Column(Text, nullable=True)
    operator_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    confirmed_by = Column(Integer, ForeignKey("user.id"), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    risk_confirmed_by = Column(Integer, ForeignKey("user.id"), nullable=True)
    risk_confirmed_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    # V7-A A-07：执行那一刻的模式记录（simulated/real）。历史任务为空 = 未记录，
    # 不能再用当前 DEPLOY_SIMULATE_ONLY 反推过去的行为。
    execution_mode = Column(String(16), nullable=True)
    # ── V6.1 预留字段（只落表，V6.0 不参与逻辑）──
    city_id = Column(Integer, nullable=True)
    node_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    device = relationship("Device", back_populates="deploy_tasks")
    batch = relationship("DeployBatch")
    template = relationship("ConfigTemplate")
    operator = relationship("User", foreign_keys=[operator_id])


class DeviceWriteLock(Base):
    """设备写锁：同一设备同一时间只允许一个配置写任务（设计 §15.3）。

    记录内容：任务ID（→ 操作者由 `DeployTask.operator_id` 表达）、操作类型 `lock_type`、
    创建时间、过期时间 `expire_at`（超过后由调度器清理**未进入执行**的锁）。

    与设计 §15.3 的差异（有意）：**释放原因记在审计日志**（`device_write_lock_released`
    的 `result` 字段：released / success / released_cancelled / released_not_allowlisted / failed），
    而不是本表 —— 释放走"删行"语义（互斥判定的唯一依据是"行是否存在"，避免软删除漏过滤
    导致设备被永久锁死），删掉的行无法携带原因。
    """

    __tablename__ = "device_write_lock"

    device_id = Column(Integer, ForeignKey("device.id"), primary_key=True)
    # BF-03：终端/部署/训练写路径共用同一权威占用；终端没有 DeployTask。
    task_id = Column(Integer, ForeignKey("deploy_task.id"), nullable=True)
    owner_type = Column(String(16), nullable=False, default="deploy")  # deploy|terminal|training
    owner_id = Column(Integer, nullable=True)
    # BF2-04：终端实例唯一令牌；旧会话延迟释放不能删除同用户新会话的锁。
    owner_token = Column(String(64), nullable=True)
    # BF4-01：终端实例状态持久化，不能用时间过期/内存标记代替活动状态。
    state = Column(String(16), nullable=True)  # active|closing|closed|orphaned|unknown
    last_seen_at = Column(DateTime, nullable=True)
    release_state = Column(String(16), nullable=True)  # none|failed|recovered
    release_error = Column(String(256), nullable=True)
    owner_instance_id = Column(String(64), nullable=True)
    # M1: deploy=confirmed/legacy; executing/ready/verifying distinguish active
    # device I/O from a finished execution waiting for verification, without an enum migration.
    lock_type = Column(String(32), nullable=False, default="deploy")
    expire_at = Column(DateTime, nullable=True)  # 超过后可被调度器清理（仅限未进入执行的锁）
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class ConfigTemplate(Base):
    __tablename__ = "config_template"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    content = Column(Text, nullable=False)
    variables = Column(JSON, nullable=True)
    category = Column(String(64), nullable=True)
    is_active = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("user.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class ConfigVersion(Base):
    __tablename__ = "config_version"
    __table_args__ = (
        Index("ix_configver_device", "device_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("device.id"), nullable=False)
    deploy_task_id = Column(Integer, ForeignKey("deploy_task.id"), nullable=True)
    version_number = Column(Integer, nullable=False)
    config_snapshot = Column(Text, nullable=False)
    source = Column(String(32), nullable=False, default="post_readback")
    change_description = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("user.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    device = relationship("Device", back_populates="config_versions")


class ServiceInstance(Base):
    """BF5：单机服务实例心跳/进程身份；用于跨进程判断旧终端持有者是否已结束。"""
    __tablename__ = "service_instance"
    instance_id = Column(String(64), primary_key=True)
    pid = Column(Integer, nullable=False)
    process_started_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    last_heartbeat_at = Column(DateTime, nullable=True)
