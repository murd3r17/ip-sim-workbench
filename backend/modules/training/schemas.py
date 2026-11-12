"""实训模块Schema"""
import re
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List

from modules.training.models import LabStatus


class LabCreate(BaseModel):
    title: str = Field(max_length=256)
    description: Optional[str] = Field(default=None, max_length=10000)
    topology_id: int
    objectives: Optional[list] = None
    scoring_rules: Optional[dict] = None
    time_limit_minutes: Optional[int] = 60
    is_sandbox: Optional[bool] = False

    @field_validator("time_limit_minutes")
    @classmethod
    def validate_time_limit(cls, v: int) -> int:
        if v < 5 or v > 480:
            raise ValueError("时间限制必须在5-480分钟之间")
        return v


class LabUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=256)
    description: Optional[str] = Field(default=None, max_length=10000)
    status: Optional[LabStatus] = None
    objectives: Optional[list] = None
    scoring_rules: Optional[dict] = None
    time_limit_minutes: Optional[int] = None
    is_sandbox: Optional[bool] = None


class SessionCreate(BaseModel):
    lab_id: int


class LabEnvironmentBinding(BaseModel):
    model_config = {"extra": "forbid"}
    environment_id: Optional[int] = Field(..., gt=0)


class StepVerificationRequest(BaseModel):
    model_config = {"extra": "forbid"}
    observation_ids: list[int] = Field(default_factory=list, max_length=24)

    @field_validator('observation_ids')
    @classmethod
    def positive_observation_ids(cls, values):
        if any(v <= 0 for v in values):
            raise ValueError('观察ID必须为正整数')
        return values


# ── 故障注入配置值白名单正则 ──────────────────────────────────────────
_FAULT_VALUE_PATTERNS = {
    "interface": re.compile(r"^[A-Za-z0-9/]+$"),
    "process_id": re.compile(r"^\d{1,4}$"),
    "area_id": re.compile(r"^\d{1,4}$"),
    "acl_number": re.compile(r"^\d{1,5}$"),
    "wrong_vlan": re.compile(r"^\d{1,4}$"),
    "correct_vlan": re.compile(r"^\d{1,4}$"),
    "dest_network": re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"),
    "dest_mask": re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"),
    "blackhole_nexthop": re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"),
    "correct_nexthop": re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"),
    "wrong_mtu": re.compile(r"^\d{3,5}$"),
    "correct_mtu": re.compile(r"^\d{3,5}$"),
    "wrong_dns": re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"),
    "correct_dns": re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"),
}


class FaultItem(BaseModel):
    """单个故障注入项，带严格输入校验"""
    device_id: int
    fault_type: str
    config: Optional[dict] = None

    @field_validator("fault_type")
    @classmethod
    def validate_fault_type(cls, v: str) -> str:
        from modules.training.models import FaultType
        valid = {ft.value for ft in FaultType}
        if v not in valid:
            raise ValueError(f"无效的故障类型: {v}，可选: {', '.join(sorted(valid))}")
        return v

    @field_validator("config")
    @classmethod
    def validate_config(cls, v: dict | None) -> dict | None:
        if v is None:
            return v
        for key, value in v.items():
            if not isinstance(value, str):
                raise ValueError(f"配置值必须是字符串: {key}")
            if len(value) > 64:
                raise ValueError(f"配置值过长(最大64字符): {key}")
            if "\n" in value or "\r" in value:
                raise ValueError(f"配置值不能包含换行符: {key}")
            pattern = _FAULT_VALUE_PATTERNS.get(key)
            if pattern and not pattern.match(value):
                raise ValueError(f"配置值格式无效: {key}={value}")
        return v


class FaultInjectRequest(BaseModel):
    fault_scenario: List[FaultItem]


class ScoreRequest(BaseModel):
    session_id: int


class ScoreResponse(BaseModel):
    session_id: int
    score: Optional[float] = Field(default=None, description="技能成绩；无可信验证证据时为null")
    passed: Optional[bool] = Field(default=None, description="技能通过判定；未验证时为null")
    detail: dict = Field(default_factory=dict, description="冻结的复盘参考明细，不代表技能达标")


class OperationLogCreate(BaseModel):
    session_id: int = Field(default=0, description="从session派生,客户端可忽略(路由路径已含session_id)")
    lab_id: int = Field(default=0, description="从session派生,客户端可忽略")
    action: str = Field(max_length=64)
    target_device: Optional[str] = Field(default=None, max_length=128)
    command: Optional[str] = Field(default=None, max_length=10000)
    result: Optional[str] = Field(default=None, max_length=10000)
    success: Optional[bool] = True
    meta: Optional[dict] = None


class SandboxStartRequest(BaseModel):
    lab_id: int
    fault_types: Optional[List[str]] = None

    @field_validator("fault_types")
    @classmethod
    def validate_fault_types(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        if len(v) > 10:
            raise ValueError("一次最多注入10种故障类型")
        from modules.training.models import FaultType
        valid = {ft.value for ft in FaultType}
        for ft in v:
            if ft not in valid:
                raise ValueError(f"无效的故障类型: {ft}，可选: {', '.join(sorted(valid))}")
        return v


class LabResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    title: str
    description: Optional[str]
    topology_id: int
    instructor_id: int
    status: str
    objectives: Optional[list]
    scoring_rules: Optional[dict]
    time_limit_minutes: int
    is_sandbox: bool
    created_at: Optional[str]


class SessionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    lab_id: int
    trainee_id: int
    status: str
    score: Optional[float]
    score_detail: Optional[dict]
    passed: Optional[bool]
    started_at: Optional[str]
    completed_at: Optional[str]
    time_spent_seconds: Optional[int]


class TrainingHintResponse(BaseModel):
    session_id: int
    lab_id: int
    goal: str
    summary: str
    next_steps: list[str] = Field(default_factory=list)
    corrections: list[str] = Field(default_factory=list)
    explanations: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    coach_text: str
    sources: list[dict] = Field(default_factory=list)
    degraded: bool = False
    knowledge_status: str = "ok"
    environment_status: str = "unknown"
    content_source: str = "unknown"
    config_blocked: bool = False
    blocked_reason: str = ""


class TrainingWorkspaceUpdate(BaseModel):
    notes: str = Field("", max_length=8000)
    steps: list[dict] = Field(default_factory=list)
    revision: int = Field(..., ge=0)


class TrainingWorkspaceResponse(BaseModel):
    session_id: int
    notes: str = ""
    steps: list[dict] = Field(default_factory=list)
    revision: int = 0
    updated_at: str = ""
    read_only: bool = False


class TrainingReportResponse(BaseModel):
    session_id: int
    lab_id: int
    title: str
    summary: str
    key_findings: list[str] = Field(default_factory=list)
    root_causes: list[str] = Field(default_factory=list)
    impact_analysis: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    timeline: list[dict] = Field(default_factory=list)
    faults: list[dict] = Field(default_factory=list)
    report_text: str
    sources: list[dict] = Field(default_factory=list)
    degraded: bool = False
    knowledge_status: str = "ok"


class TrainingReportGenerate(BaseModel):
    """显式生成/重生成复盘报告。

    - 不传 ``regenerate`` 时，若证据指纹未变则复用已有 ready 版本（不调用模型）；
    - ``regenerate=True`` 一定产生新版本，旧版本永久保留；
    - ``idempotency_key`` 由前端在双击/重试时复用，服务端据此返回同一次生成结果。
    """
    regenerate: bool = False
    idempotency_key: Optional[str] = Field(default=None, max_length=64)


class TrainingReportVersion(BaseModel):
    version: int
    status: str
    input_hash: Optional[str] = None
    generated_at: Optional[str] = None
    model: Optional[str] = None


class TrainingReportEnvelope(BaseModel):
    """读取与生成共用返回：``status=none`` 表示还没有任何成功版本。"""
    session_id: int
    lab_id: int
    status: str
    report: Optional[dict] = None
    versions: list[TrainingReportVersion] = Field(default_factory=list)
    last_failure: Optional[dict] = None
    reused: bool = False
