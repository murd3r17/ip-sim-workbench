"""设备管理模块数据模型"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Float, ForeignKey, Enum as SAEnum, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum
from core.database import Base


class DeviceStatus(str, enum.Enum):
    UNKNOWN = "unknown"
    ONLINE = "online"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"


VALID_TRANSITIONS = {
    # UNKNOWN 必须能转 OFFLINE：新建设备默认 unknown，首次探测离线时
    # 此前会抛"非法状态流转"，导致设备状态永远停在 unknown。
    DeviceStatus.UNKNOWN: [DeviceStatus.ONLINE, DeviceStatus.OFFLINE, DeviceStatus.MAINTENANCE],
    DeviceStatus.ONLINE: [DeviceStatus.OFFLINE, DeviceStatus.MAINTENANCE],
    DeviceStatus.OFFLINE: [DeviceStatus.ONLINE, DeviceStatus.MAINTENANCE],
    DeviceStatus.MAINTENANCE: [DeviceStatus.ONLINE, DeviceStatus.OFFLINE],
}


def validate_status_transition(current: DeviceStatus, target: DeviceStatus) -> bool:
    return target in VALID_TRANSITIONS.get(current, [])


class DeviceType(str, enum.Enum):
    ROUTER = "router"
    SWITCH_L2 = "switch_l2"
    SWITCH_L3 = "switch_l3"
    FIREWALL = "firewall"
    SERVER = "server"
    OTHER = "other"


class DeviceVendor(str, enum.Enum):
    HUAWEI = "huawei"
    H3C = "h3c"
    OTHER = "other"


class TopologyType(str, enum.Enum):
    MAIN = "main"
    LAB = "lab"


class Topology(Base):
    __tablename__ = "topology"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    topology_type = Column(SAEnum(TopologyType, values_callable=lambda x: [e.value for e in x]), nullable=False, default=TopologyType.MAIN)
    parent_id = Column(Integer, ForeignKey("topology.id"), nullable=True)
    owner_id = Column(Integer, ForeignKey("user.id"), nullable=True)
    device_count = Column(Integer, default=0)
    status = Column(String(16), default="active")
    # ── V6.1 预留字段（只落表，V6.0 不参与任何查询/展示/权限逻辑）──
    # 见《扩展方案纲要V6.1》§16 与《详细开发计划V6.0》阶段1.7
    city_id = Column(Integer, nullable=True)
    node_id = Column(Integer, nullable=True)
    topology_source = Column(String(32), nullable=True)  # ensp / inetbox / manual
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    devices = relationship("Device", back_populates="topology")
    links = relationship("TopologyLink", back_populates="topology", foreign_keys="TopologyLink.topology_id")


class Device(Base):
    __tablename__ = "device"
    __table_args__ = (
        Index("ix_device_mgmt_ip", "mgmt_ip"),
        Index("ix_device_topology", "topology_id"),
        Index("ix_device_status", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    hostname = Column(String(128), nullable=False)
    mgmt_ip = Column(String(45), nullable=False)
    ssh_port = Column(Integer, default=22)
    device_type = Column(SAEnum(DeviceType, values_callable=lambda x: [e.value for e in x]), nullable=False)
    vendor = Column(SAEnum(DeviceVendor, values_callable=lambda x: [e.value for e in x]), default=DeviceVendor.HUAWEI)
    model = Column(String(64), nullable=True)
    vrp_version = Column(String(64), nullable=True)

    username_encrypted = Column(String(512), nullable=True)
    password_encrypted = Column(String(512), nullable=True)
    enable_encrypted = Column(String(512), nullable=True)

    status = Column(SAEnum(DeviceStatus, values_callable=lambda x: [e.value for e in x]), default=DeviceStatus.UNKNOWN, nullable=False)
    last_seen_at = Column(DateTime, nullable=True)
    status_changed_at = Column(DateTime, nullable=True)

    topology_id = Column(Integer, ForeignKey("topology.id"), nullable=False)
    network_role = Column(String(32), default="access")
    notes = Column(Text, nullable=True)
    tags = Column(String(512), nullable=True)

    # ── V6.1 预留字段（只落表，V6.0 不参与逻辑）──
    city_id = Column(Integer, nullable=True)
    node_id = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    topology = relationship("Topology", back_populates="devices")
    config_versions = relationship("ConfigVersion", back_populates="device", lazy="noload")
    deploy_tasks = relationship("DeployTask", back_populates="device", lazy="noload")
    metric_records = relationship("MetricRecord", back_populates="device", lazy="noload")
    alarms = relationship("Alarm", back_populates="device", lazy="noload")


class TopologyLink(Base):
    __tablename__ = "topology_link"
    __table_args__ = (Index("ix_link_topology", "topology_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    topology_id = Column(Integer, ForeignKey("topology.id"), nullable=False)
    source_device_id = Column(Integer, ForeignKey("device.id"), nullable=False)
    source_interface = Column(String(64), nullable=False)
    target_device_id = Column(Integer, ForeignKey("device.id"), nullable=False)
    target_interface = Column(String(64), nullable=False)
    link_type = Column(String(32), default="physical")
    bandwidth = Column(String(32), nullable=True)
    status = Column(String(16), default="up")
    discovery_source = Column(String(32), nullable=True)
    source_type = Column(String(32), nullable=False, default="baseline")
    source_ip = Column(String(64), nullable=True)
    target_ip = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    topology = relationship("Topology", back_populates="links")
    source_device = relationship("Device", foreign_keys=[source_device_id])
    target_device = relationship("Device", foreign_keys=[target_device_id])


class TopologyVersion(Base):
    __tablename__ = "topology_version"
    __table_args__ = (
        UniqueConstraint("topology_id", "version", name="uq_topology_version"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    topology_id = Column(Integer, ForeignKey("topology.id"), nullable=False)
    version = Column(Integer, nullable=False)
    batch_id = Column(String(36), nullable=False)
    source_name = Column(String(255), nullable=False)
    source_type = Column(String(32), nullable=False, default="excel")
    snapshot_json = Column(Text, nullable=False)
    summary_json = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("user.id"), nullable=True)
    rollback_of_id = Column(Integer, ForeignKey("topology_version.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class TopologyRuntimeCheck(Base):
    __tablename__ = "topology_runtime_check"
    __table_args__ = (Index("ix_runtime_check_topology", "topology_id", "created_at"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    topology_id = Column(Integer, ForeignKey("topology.id"), nullable=False)
    version_id = Column(Integer, ForeignKey("topology_version.id"), nullable=True)
    # version_id is the baseline compared; promotion records its new version separately.
    confirmed_version_id = Column(Integer, ForeignKey("topology_version.id"), nullable=True)
    baseline_fingerprint = Column(String(64), nullable=True)
    status = Column(String(16), nullable=False)
    ssh_success = Column(Integer, default=0)
    ssh_failed = Column(Integer, default=0)
    observed_links_json = Column(Text, nullable=False)
    diff_json = Column(Text, nullable=False)
    errors_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
