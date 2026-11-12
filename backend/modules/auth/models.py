"""认证模块数据模型"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum
from core.database import Base


class UserRole(str, enum.Enum):
    ADMIN = "admin"  # 与数据库enum('admin','user')匹配
    USER = "user"


class User(Base):
    __tablename__ = "user"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    hashed_password = Column(String(256), nullable=False)
    display_name = Column(String(128), nullable=True)
    role = Column(SAEnum(UserRole, values_callable=lambda x: [e.value for e in x]), nullable=False, default=UserRole.USER)
    is_active = Column(Boolean, default=True)
    token_version = Column(Integer, nullable=False, default=0, server_default="0")
    last_login_at = Column(DateTime, nullable=True)
    # ── V6.1 预留字段（只落表，V6.0 不参与任何权限判定）──
    # data_scope 预留给"按地市/节点隔离数据范围"，V6.0 仍是两级角色（admin/user）
    data_scope = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    audit_logs = relationship("AuditLog", back_populates="user")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    username = Column(String(64), nullable=False)
    module = Column(String(32), nullable=False)
    action = Column(String(64), nullable=False)
    resource_type = Column(String(64), nullable=True)
    resource_id = Column(String(64), nullable=True)
    detail = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    result = Column(String(16), nullable=False, default="success")
    # ── V6.1 预留字段（审计的地市/节点归属，V6.0 不参与逻辑）──
    city_id = Column(Integer, nullable=True)
    node_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="audit_logs")
