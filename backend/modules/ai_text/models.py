"""AI模块数据模型"""
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Index, JSON

from core.database import Base


class AILog(Base):
    __tablename__ = "ai_log"
    __table_args__ = (
        Index("ix_ai_user", "user_id"),
        Index("ix_ai_created", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    request_type = Column(String(32), nullable=False)
    prompt = Column(Text, nullable=False)
    response = Column(Text, nullable=True)
    model_used = Column(String(64), nullable=True)
    tokens_input = Column(Integer, nullable=True)
    tokens_output = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    feedback = Column(String(16), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"<AILog(id={self.id}, type={self.request_type}, user={self.user_id})>"


class CopilotConversation(Base):
    """AI 助手会话持久化（跨浏览器/清缓存不丢历史）。

    id 沿用前端生成的会话 id；messages 为 JSON 数组（含附件，已由前端裁剪）。
    """

    __tablename__ = "copilot_conversation"
    __table_args__ = (
        Index("ix_copilot_user", "user_id"),
        Index("ix_copilot_updated", "updated_at"),
    )

    id = Column(String(48), primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False, default=0)
    title = Column(String(256), nullable=False, default="新对话")
    messages = Column(JSON, nullable=False, default=list)
    revision = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"<CopilotConversation(id={self.id}, user={self.user_id}, msgs={len(self.messages or [])})>"


class CopilotRequest(Base):
    """Durable once-per-ID reservation; terminal IDs are never reused."""
    __tablename__ = "copilot_request"
    user_id = Column(Integer, ForeignKey("user.id"), primary_key=True)
    request_id = Column(String(64), primary_key=True)
    input_hash = Column(String(64), nullable=False)
    authorization_scope = Column(String(64), nullable=False)
    owner_token = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False)
    response = Column(JSON, nullable=True)
    http_status = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
