# -*- coding: utf-8 -*-
"""V7-B 可信基础：版本化环境与只读观察证据。

环境映射是“接收方现场”的版本化对象，不是把 R1/R2/R3 写死为全局默认。
证据只记录服务端实际观察到的只读结果；客户端上报与演示数据必须用 source 区分。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text

from core.database import Base


class EnvironmentProfile(Base):
    __tablename__ = "environment_profile"
    __table_args__ = (Index("ix_environment_status", "status"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    version = Column(String(32), nullable=False, default="v1")
    site = Column(String(128), nullable=True)
    status = Column(String(16), nullable=False, default="draft")
    # [{device_id, role, mgmt_ip, interfaces: [{name, address, peer}], vendor, os_version}]
    devices = Column(JSON, nullable=True)
    # [{kind, target, note}]：管理口/上联/不可操作项等保护项
    protections = Column(JSON, nullable=True)
    # BF-01：管理员只改映射；status 由服务端 preflight 写入，不接受手填 ready。
    revision = Column(Integer, nullable=False, default=1)
    content_hash = Column(String(64), nullable=True)
    expected = Column(JSON, nullable=True)  # {neighbors:[], routes:[]}，来自环境/任务规则版本
    last_preflight_status = Column(String(16), nullable=True)
    last_preflight_mode = Column(String(16), nullable=True)
    last_preflight_at = Column(DateTime, nullable=True)
    source = Column(String(32), nullable=False, default="manual")
    created_by = Column(Integer, ForeignKey("user.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class ReadOnlyObservation(Base):
    __tablename__ = "read_only_observation"
    __table_args__ = (
        Index("ix_observation_device_time", "device_id", "collected_at"),
        Index("ix_observation_environment", "environment_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    environment_id = Column(Integer, ForeignKey("environment_profile.id"), nullable=True)
    # BF-01/02：采集时冻结环境版本与内容摘要；之后环境改版不回写历史证据。
    environment_version = Column(String(32), nullable=True)
    environment_snapshot = Column(JSON, nullable=True)
    device_id = Column(Integer, ForeignKey("device.id"), nullable=False)
    action_id = Column(String(64), nullable=False)
    command = Column(Text, nullable=False)
    collected_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    source = Column(String(32), nullable=False, default="server_observed")
    # BF-02：mode 记录实际 adapter 维度（real/sim/unknown），read_only 是访问权限维度。
    mode = Column(String(16), nullable=False, default="unknown")
    adapter_mode = Column(String(16), nullable=False, default="unknown")
    completeness = Column(String(16), nullable=False, default="error")  # complete|partial|empty|error
    parser_version = Column(String(32), nullable=False, default="v7b.1")
    facts = Column(JSON, nullable=True)
    raw_excerpt = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default="error")  # ok|error|unsupported
    error_message = Column(String(512), nullable=True)
    created_by = Column(Integer, ForeignKey("user.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
