"""实训模块数据模型"""
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Text, Boolean, ForeignKey,
    Enum as SAEnum, Index, JSON, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum
from core.database import Base


class LabStatus(str, enum.Enum):
    DRAFT = "draft"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class FaultType(str, enum.Enum):
    INTERFACE_SHUTDOWN = "interface_shutdown"
    OSPF_NEIGHBOR_DOWN = "ospf_neighbor_down"
    VLAN_MISMATCH = "vlan_mismatch"
    ACL_BLOCK = "acl_block"
    ROUTE_BLACKHOLE = "route_blackhole"
    MTU_MISMATCH = "mtu_mismatch"
    DNS_FAULT = "dns_fault"


class TrainingLab(Base):
    __tablename__ = "training_lab"
    __table_args__ = (Index("ix_lab_status", "status"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    topology_id = Column(Integer, ForeignKey("topology.id"), nullable=False)
    instructor_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    status = Column(SAEnum(LabStatus), default=LabStatus.DRAFT)
    objectives = Column(JSON, nullable=True)
    scoring_rules = Column(JSON, nullable=True)
    time_limit_minutes = Column(Integer, default=60)
    is_sandbox = Column(Boolean, default=False, nullable=False)
    # V7-A A-02: 实验内容版本与现场环境要求。历史记录没有版本时为空，
    # 不能把空值当成“已核对内容”。
    content_version = Column(String(32), nullable=True)
    environment_spec = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    topology = relationship("Topology")
    sessions = relationship("TrainingSession", back_populates="lab")
    operation_logs = relationship("OperationLog", back_populates="lab")


class TrainingSession(Base):
    __tablename__ = "training_session"
    __table_args__ = (Index("ix_session_lab", "lab_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    lab_id = Column(Integer, ForeignKey("training_lab.id"), nullable=False)
    trainee_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    time_spent_seconds = Column(Integer, nullable=True)
    score = Column(Float, nullable=True)
    score_detail = Column(JSON, nullable=True)
    passed = Column(Boolean, nullable=True)
    command_log = Column(Text, nullable=True)
    status = Column(String(16), default="pending")
    # V7-A A-02: 会话开始时固定实验版本与步骤快照，内容更新不能悄悄改变历史任务。
    content_version = Column(String(32), nullable=True)
    content_snapshot = Column(JSON, nullable=True)
    # A-fix AF-04：会话开始时的设备连接/下发/绑定事实，历史显示不随当前设置翻转。
    mode_snapshot = Column(JSON, nullable=True)
    # V7-B B-10：实训内连续任务视图（笔记/步骤状态），刷新恢复；已结束只读。
    workspace = Column(JSON, nullable=True)
    # BF-04：独立 revision 列，PUT 用原子 CAS 更新，避免并发读-改-写丢稿。
    workspace_revision = Column(Integer, nullable=False, default=0)
    # BF-01：会话绑定采集时 trust 环境版本/快照；环境改版后旧会话不漂移。
    trust_environment_id = Column(Integer, ForeignKey("environment_profile.id"), nullable=True)
    trust_environment_version = Column(String(32), nullable=True)
    trust_environment_snapshot = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    lab = relationship("TrainingLab", back_populates="sessions")
    faults = relationship("FaultInjection", back_populates="session")
    operation_logs = relationship("OperationLog", back_populates="session")


class FaultInjection(Base):
    __tablename__ = "fault_injection"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("training_session.id"), nullable=False)
    device_id = Column(Integer, ForeignKey("device.id"), nullable=False)
    fault_type = Column(SAEnum(FaultType), nullable=False)
    fault_config = Column(JSON, nullable=True)
    injected_commands = Column(Text, nullable=True)
    rollback_commands = Column(Text, nullable=True)
    injected_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime, nullable=True)
    resolved_correctly = Column(Boolean, nullable=True)

    session = relationship("TrainingSession", back_populates="faults")


class OperationLog(Base):
    """JSON Lines格式操作日志"""
    __tablename__ = "operation_log"
    __table_args__ = (Index("ix_oplog_session", "session_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("training_session.id"), nullable=False)
    lab_id = Column(Integer, ForeignKey("training_lab.id"), nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    action = Column(String(64), nullable=False)
    target_device = Column(String(128), nullable=True)
    command = Column(Text, nullable=True)
    result = Column(Text, nullable=True)
    success = Column(Boolean, default=True)
    meta = Column(JSON, nullable=True)

    session = relationship("TrainingSession", back_populates="operation_logs")
    lab = relationship("TrainingLab", back_populates="operation_logs")


class TrainingReport(Base):
    """V7-A A-05：持久化复盘报告版本。

    - ``status=ready``：一次成功生成的不可变版本；
    - ``status=failed``：一次失败尝试，只保留错误原因，不覆盖旧的 ready 版本；
    - ``input_hash``：生成输入（会话/实验版本/证据摘要）的指纹，用于判断“证据有没有变”；
    - ``prompt_version``/``model``：便于回溯当时使用的生成契约。
    """
    __tablename__ = "training_report"
    __table_args__ = (
        UniqueConstraint("session_id", "version", name="uq_training_report_session_version"),
        UniqueConstraint("session_id", "idempotency_key", name="uq_training_report_idempotency"),
        Index("ix_training_report_session", "session_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("training_session.id"), nullable=False)
    version = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False, default="ready")
    title = Column(String(256), nullable=True)
    summary = Column(Text, nullable=True)
    key_findings = Column(JSON, nullable=True)
    root_causes = Column(JSON, nullable=True)
    impact_analysis = Column(JSON, nullable=True)
    recommendations = Column(JSON, nullable=True)
    report_text = Column(Text, nullable=True)
    sources = Column(JSON, nullable=True)
    input_hash = Column(String(64), nullable=True)
    input_summary = Column(JSON, nullable=True)
    model = Column(String(64), nullable=True)
    prompt_version = Column(String(32), nullable=True)
    error = Column(Text, nullable=True)
    idempotency_key = Column(String(64), nullable=True)
    generated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    session = relationship("TrainingSession")
