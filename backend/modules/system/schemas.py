"""系统管理模块Schemas"""
from datetime import datetime

from core.time_utils import UtcDatetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator, computed_field


class SystemConfigCreate(BaseModel):
    config_key: str = Field(..., min_length=1, max_length=128)
    config_value: Optional[str] = Field(None, max_length=4096)
    description: Optional[str] = Field(None, max_length=256)


class SystemConfigUpdate(BaseModel):
    config_value: Optional[str] = Field(None, max_length=4096)
    description: Optional[str] = Field(None, max_length=256)


class SystemConfigResponse(BaseModel):
    id: int
    config_key: str
    config_value: Optional[str]
    description: Optional[str]
    updated_by: Optional[str]
    created_at: UtcDatetime
    updated_at: UtcDatetime
    is_secret: bool = False

    model_config = {"from_attributes": True}


class AuditLogResponse(BaseModel):
    id: int
    user_id: int
    username: str
    module: str
    action: str
    resource_type: Optional[str]
    resource_id: Optional[str]
    detail: Optional[str]
    ip_address: Optional[str]
    result: str
    created_at: UtcDatetime

    @field_validator('detail', mode='before')
    @classmethod
    def redact_detail(cls, value):
        from core.redaction import redact_sensitive
        return redact_sensitive(value)

    model_config = {"from_attributes": True}


class AuditLogListResponse(BaseModel):
    items: list[AuditLogResponse]
    total: int
    page: int
    page_size: int


class BackgroundTaskResponse(BaseModel):
    id: int
    task_type: str
    task_name: str
    status: str
    progress: int
    result: Optional[str]
    error_message: Optional[str]
    created_by: Optional[int]
    started_at: Optional[UtcDatetime]
    finished_at: Optional[UtcDatetime]
    created_at: UtcDatetime

    @computed_field
    @property
    def record_origin(self) -> str:
        from core.record_origin import background_origin
        return background_origin(self.task_type)

    model_config = {"from_attributes": True}


class BackgroundTaskListResponse(BaseModel):
    items: list[BackgroundTaskResponse]
    total: int


class SystemInfoResponse(BaseModel):
    app_name: str
    app_version: str
    python_version: str
    database_status: str
    llm_status: str
    llm_provider: str
    llm_model: str
    device_count: int
    user_count: int
    uptime_seconds: float
    log_level: str
    fernet_configured: bool
    jwt_configured: bool = False


class LogFileResponse(BaseModel):
    filename: str
    size_bytes: int
    last_modified: str
    lines: int
