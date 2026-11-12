"""首页运维指挥中心响应契约。"""
from datetime import datetime

from core.time_utils import UtcDatetime

from pydantic import BaseModel, ConfigDict, Field


class DeviceSummary(BaseModel):
    total: int
    online: int
    ssh_reachable: int
    offline: int
    maintenance: int
    unknown: int


class TopologyNode(BaseModel):
    id: int
    hostname: str
    status: str
    device_type: str
    network_role: str


class TopologyEdge(BaseModel):
    id: int
    source_device_id: int
    source_interface: str
    target_device_id: int
    target_interface: str
    status: str


class TopologySummary(BaseModel):
    id: int
    name: str
    status: str
    device_count: int
    link_count: int
    nodes: list[TopologyNode]
    links: list[TopologyEdge]
    published_positions: dict[str, dict[str, float]] = Field(default_factory=dict)


class TaskItem(BaseModel):
    id: int
    kind: str
    name: str
    status: str
    progress: int
    device_name: str | None = None
    high_risk: bool = False
    has_diff: bool = False
    created_at: UtcDatetime


class TaskSummary(BaseModel):
    active: int
    pending: int
    failed: int
    with_diff: int
    items: list[TaskItem]


class AlarmItem(BaseModel):
    id: int
    device_id: int
    device_name: str
    severity: str
    message: str
    status: str
    fired_at: UtcDatetime


class AlarmTrendPoint(BaseModel):
    """近 7 天每天的告警条数（首页告警趋势图）。"""

    date: str
    count: int


class AlarmSummary(BaseModel):
    active: int
    critical: int
    items: list[AlarmItem]
    # 注意：response_model 会把未声明的字段全部裁掉 —— A7 新增字段必须在这里登记，
    # 否则 service 里算好的 trend/approvals/reports 到不了前端（曾因此静默失效）。
    trend: list[AlarmTrendPoint] = Field(default_factory=list)


class ApprovalItem(BaseModel):
    """待确认/待执行的下发任务（首页"审批状态"面板）。"""

    id: int
    device_name: str
    status: str
    high_risk: bool
    change_level: str | None = None
    created_at: UtcDatetime


class ReportItem(BaseModel):
    """最近巡检/采集任务（首页"巡检 / 验证报告"入口）。"""

    id: int
    job_type: str
    status: str
    trigger_mode: str
    device_count: int | None = None
    success_count: int | None = None
    failure_count: int | None = None
    alarm_count: int | None = None
    created_at: UtcDatetime


class ServiceState(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: str
    provider: str | None = None
    model: str | None = None
    config_source: str | None = None


class ServicesSummary(BaseModel):
    database: ServiceState
    llm: ServiceState
    knowledge: ServiceState


class RiskItem(BaseModel):
    level: str
    title: str
    detail: str
    recommendation: str
    route: str


class RiskSummary(BaseModel):
    pending_approval: int
    items: list[RiskItem]


class ActivityItem(BaseModel):
    id: int
    module: str
    action: str
    result: str
    created_at: UtcDatetime


class TrainingSummary(BaseModel):
    active: int = 0
    total: int = 0


class DashboardSummary(BaseModel):
    generated_at: UtcDatetime
    environment_name: str
    environment_status: str
    devices: DeviceSummary
    topology: TopologySummary | None
    tasks: TaskSummary
    alarms: AlarmSummary
    services: ServicesSummary
    risks: RiskSummary
    approvals: list[ApprovalItem] = Field(default_factory=list)
    reports: list[ReportItem] = Field(default_factory=list)
    activity: list[ActivityItem]
    monitor_scheduler_enabled: bool = False
    training: TrainingSummary = Field(default_factory=TrainingSummary)
