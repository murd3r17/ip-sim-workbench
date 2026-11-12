"""配置下发模块Schema"""
from pydantic import BaseModel, ConfigDict, field_serializer, field_validator, computed_field
from typing import Optional, List
from datetime import datetime

from core.time_utils import UtcDatetime

MAX_DEVICE_IDS = 50


class DeployRequest(BaseModel):
    device_ids: List[int]
    config_content: str
    template_id: Optional[int] = None
    change_level: str = "daily"
    engine: str = "netmiko"

    @field_validator("device_ids")
    @classmethod
    def validate_device_ids(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("device_ids不能为空")
        if len(v) > MAX_DEVICE_IDS:
            raise ValueError(f"单次下发设备数不能超过{MAX_DEVICE_IDS}台")
        if any(did <= 0 for did in v):
            raise ValueError("device_id必须为正整数")
        return v

    @field_validator("config_content")
    @classmethod
    def validate_config_content(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("config_content不能为空")
        if len(v) > 100_000:
            raise ValueError("config_content不能超过100KB")
        return v

    @field_validator("engine")
    @classmethod
    def validate_engine(cls, v: str) -> str:
        if (v or "netmiko").strip().lower() != "netmiko":
            raise ValueError("仅支持 netmiko 引擎（Ansible 未接入）")
        return "netmiko"


class DeployResponse(BaseModel):
    transaction_id: str
    total: int
    success: int
    failed: int
    rolled_back: int
    details: list


class DeployBatchItemRequest(BaseModel):
    device_id: int
    config_content: str
    template_id: Optional[int] = None

    @field_validator("device_id")
    @classmethod
    def validate_device_id(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("device_id必须为正整数")
        return value

    @field_validator("config_content")
    @classmethod
    def validate_item_config(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("config_content不能为空")
        if len(value) > 100_000:
            raise ValueError("config_content不能超过100KB")
        return value


class DeployBatchCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    source: str = "manual"
    planned_at: Optional[UtcDatetime] = None
    engine: str = "netmiko"
    items: List[DeployBatchItemRequest]

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("任务名称不能为空")
        if len(value) > 128:
            raise ValueError("任务名称不能超过128字符")
        return value.strip()

    @field_validator("items")
    @classmethod
    def validate_items(cls, value: list[DeployBatchItemRequest]) -> list[DeployBatchItemRequest]:
        if not value:
            raise ValueError("items不能为空")
        if len(value) > MAX_DEVICE_IDS:
            raise ValueError(f"单次下发设备数不能超过{MAX_DEVICE_IDS}台")
        if len({item.device_id for item in value}) != len(value):
            raise ValueError("同一设备只能有一个任务项")
        return value

    @field_validator("engine")
    @classmethod
    def validate_batch_engine(cls, v: str) -> str:
        if (v or "netmiko").strip().lower() != "netmiko":
            raise ValueError("仅支持 netmiko 引擎（Ansible 未接入）")
        return "netmiko"


class DeployConfirmRequest(BaseModel):
    risk_confirm: bool = False


class ExecuteResponse(BaseModel):
    task_id: int
    device_id: int
    mode: str
    steps: list[str] | None = None
    error_category: str | None = None


class TemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    content: str
    variables: Optional[dict] = None
    category: Optional[str] = None


class TemplateResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    content: str
    category: Optional[str]
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class ConfigVersionResponse(BaseModel):
    id: int
    device_id: int
    deploy_task_id: Optional[int] = None
    version_number: int
    config_snapshot: str
    source: Optional[str] = None
    change_description: Optional[str]
    created_at: UtcDatetime

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def record_origin(self) -> str:
        from core.record_origin import declared_origin
        return declared_origin(self.source)

    @field_serializer("config_snapshot")
    def _redact_snapshot(self, value: str) -> str:
        """配置快照出参前脱敏：运行配置可能含 password cipher / SNMP community / PSK。"""
        if not value:
            return value
        from modules.ai_text.llm_service import redact_sensitive
        return redact_sensitive(value)


class SnapshotCaptureRequest(BaseModel):
    device_ids: List[int]

    @field_validator("device_ids")
    @classmethod
    def validate_capture_devices(cls, value: list[int]) -> list[int]:
        if not value or len(value) > MAX_DEVICE_IDS or any(device_id <= 0 for device_id in value):
            raise ValueError("device_ids必须为1至50个正整数")
        return value


class VerifyBatchRequest(BaseModel):
    task_ids: List[int]


class TemplateRenderRequest(BaseModel):
    content: str
    variables: Optional[dict] = None
    declarations: Optional[dict] = None


class TemplateValidateRequest(BaseModel):
    content: str


class ConfigValidateRequest(BaseModel):
    config_content: str
    device_model: Optional[str] = "NE40E"

    @field_validator("config_content")
    @classmethod
    def validate_config_content(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("config_content不能为空")
        if len(v) > 100_000:
            raise ValueError("config_content不能超过100KB")
        return v
