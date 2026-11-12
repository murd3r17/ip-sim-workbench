"""监控模块数据模型"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey, Enum as SAEnum, Index, BigInteger, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum
from core.database import Base
from core.legacy_types import LegacyReadableEnum


# SQLite 只把 INTEGER PRIMARY KEY 当作 rowid 别名并自动递增；BIGINT PRIMARY KEY 不会。
# 最小模式（DB_BACKEND=sqlite）下这两张表如果不做变体，插入时不带 id 会直接
# NOT NULL constraint failed —— 监控采集与聚合整条链路在最小模式下全废。
_BIGINT_PK = BigInteger().with_variant(Integer, "sqlite")


class AggLevel(str, enum.Enum):
    HOURLY = "hourly"
    DAILY = "daily"


class MetricType(str, enum.Enum):
    """V6.0 只保留 SSH 采集能真正产出的指标（`docs/guides/监控方案变更说明.md`）。

    历史遗留的 interface_in_bps / interface_out_bps 已删除：那是退役的 SNMP 轮询方案
    产物，而 V6.0 的 `display interface brief` 只给 InUti/OutUti 百分比，没有 bps
    数据源，保留等于死字段（审计 P2-10）。旧数据库中已存的 bps 值由列类型
    兼容读取，保留历史记录，不重新启用这些指标的采集。
    """

    CPU_USAGE = "cpu_usage"
    MEMORY_USAGE = "memory_usage"
    INTERFACE_UP = "interface_up"
    INTERFACE_DOWN = "interface_down"
    OSPF_NEIGHBOR_COUNT = "ospf_neighbor_count"
    TEMPERATURE = "temperature"


class AlarmStatus(str, enum.Enum):
    FIRED = "fired"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    CLOSED = "closed"


class MonitorJobType(str, enum.Enum):
    COLLECTION = "collection"
    INSPECTION = "inspection"


class MonitorTriggerMode(str, enum.Enum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"


class MonitorJobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class MetricRecord(Base):
    __tablename__ = "metric_record"
    __table_args__ = (
        Index("ix_metric_device_time", "device_id", "collected_at"),
        Index("ix_metric_type", "metric_type"),
    )

    id = Column(_BIGINT_PK, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("device.id"), nullable=False)
    metric_type = Column(LegacyReadableEnum(MetricType, legacy_values=("interface_in_bps", "interface_out_bps")), nullable=False)
    metric_name = Column(String(128), nullable=True)
    value = Column(Float, nullable=False)
    unit = Column(String(32), nullable=True)
    collected_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    device = relationship("Device", back_populates="metric_records")


class MetricAggregated(Base):
    __tablename__ = "metric_aggregated"
    __table_args__ = (
        # 同一设备/指标/粒度/周期只允许一行：否则重复聚合会重复累计，
        # aggregate_daily 还会把重复行再 sum 一次。
        UniqueConstraint("device_id", "metric_type", "agg_level", "period_start", name="uq_agg_device_metric_period"),
        Index("ix_agg_device_metric_time", "device_id", "metric_type", "agg_level", "period_start"),
        Index("ix_agg_period", "agg_level", "period_start"),
    )

    id = Column(_BIGINT_PK, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("device.id"), nullable=False)
    metric_type = Column(LegacyReadableEnum(MetricType, legacy_values=("interface_in_bps", "interface_out_bps")), nullable=False)
    agg_level = Column(SAEnum(AggLevel, values_callable=lambda x: [e.value for e in x]), nullable=False)
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    min_value = Column(Float, nullable=False)
    max_value = Column(Float, nullable=False)
    avg_value = Column(Float, nullable=False)
    sample_count = Column(Integer, nullable=False)
    unit = Column(String(32), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Alarm(Base):
    __tablename__ = "alarm"
    __table_args__ = (
        Index("ix_alarm_device", "device_id"),
        Index("ix_alarm_status", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("device.id"), nullable=False)
    alarm_type = Column(String(64), nullable=False)
    severity = Column(String(16), nullable=False)
    message = Column(Text, nullable=False)
    metric_value = Column(Float, nullable=True)
    threshold = Column(Float, nullable=True)
    status = Column(SAEnum(AlarmStatus, values_callable=lambda x: [e.value for e in x]), default=AlarmStatus.FIRED, nullable=False)
    fired_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    acknowledged_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    device = relationship("Device", back_populates="alarms")


class MonitorJob(Base):
    __tablename__ = "monitor_job"
    __table_args__ = (
        Index("ix_monitor_job_topology", "topology_id"),
        Index("ix_monitor_job_kind", "job_type"),
        Index("ix_monitor_job_status", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    topology_id = Column(Integer, ForeignKey("topology.id"), nullable=False)
    job_type = Column(SAEnum(MonitorJobType, values_callable=lambda x: [e.value for e in x]), nullable=False)
    trigger_mode = Column(SAEnum(MonitorTriggerMode, values_callable=lambda x: [e.value for e in x]), nullable=False)
    status = Column(SAEnum(MonitorJobStatus, values_callable=lambda x: [e.value for e in x]), nullable=False, default=MonitorJobStatus.PENDING)
    triggered_by = Column(Integer, ForeignKey("user.id"), nullable=True)
    device_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    failure_count = Column(Integer, default=0)
    summary_json = Column(Text, nullable=True)
    report_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    topology = relationship("Topology")
