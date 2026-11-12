"""AI模块Schema"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class CLIRequest(BaseModel):
    natural_language: str = Field(..., min_length=1, max_length=5000, description="自然语言描述的运维需求")
    device_model: Optional[str] = Field(None, max_length=64, description="设备型号，如NE40E")


class CLIResponse(BaseModel):
    commands: list[str]
    explanation: str
    warnings: list[str]


class ReviewIssue(BaseModel):
    severity: str
    description: str
    suggestion: str


class ReviewRequest(BaseModel):
    config_text: str = Field(..., min_length=1, max_length=50000, description="VRP设备配置内容")
    device_model: Optional[str] = Field(None, max_length=64, description="设备型号")


class ReviewResponse(BaseModel):
    issues: list[ReviewIssue]
    summary: str
    risk_level: Optional[str] = None
    validation_suggestions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=5000, description="知识库问答问题")
    kb_id: Optional[str] = Field(None, max_length=64, description="知识库ID")
    top_k: int = Field(5, ge=1, le=50, description="返回结果数量")


class CopilotContext(BaseModel):
    """前端工作台当前上下文（只读感知，不用于代操作）"""
    route: str = Field("", max_length=256)
    page_name: str = Field("", max_length=128)
    selection: str = Field("", max_length=2000, description="当前选中设备/拓扑节点/告警等摘要")
    notes: str = Field("", max_length=4000, description="页面补充说明")


class CopilotAttachment(BaseModel):
    """AI 助手附件（图片：data URL / 外链 URL）"""
    contentString: str = Field(..., min_length=1, max_length=30000000, description="data:image/...;base64,xxx 或 https:// 图片 URL")
    mime: Optional[str] = Field(None, max_length=64, description="如 image/png")


class CopilotChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=20)
    context: Optional[CopilotContext] = None
    want_draft: bool = Field(
        False,
        description="为 True 时尝试生成可填入下发表单的 CLI 草稿（仍不执行）",
    )
    device_model: str = Field("NE40E", max_length=64)
    top_k: int = Field(6, ge=1, le=30)
    page_data: str = Field(
        "",
        max_length=20000,
        description="前端采集的当前页面实时数据快照（设备/告警/任务等），供回答参考",
    )
    attachments: list[CopilotAttachment] = Field(
        default_factory=list,
        max_length=4,
        description="图片附件（截图/拓扑图/告警图等）；由视觉模型理解",
    )
    lab_steps: list[dict] = Field(
        default_factory=list,
        max_length=30,
        description="实训实验步骤（进行实训时传入；AI 按实验教练角色引导+工具验证）",
    )
    lab_id: Optional[int] = Field(
        None, description="实训实验 ID；用于判断当前环境是否已核验、能否生成可执行草稿",
    )
    lab_session_id: Optional[int] = Field(
        None, description="实训会话 ID；已结束会话只能回看，不绑定教练/终端",
    )
    request_id: Optional[str] = Field(
        None, max_length=64, description="本次请求 ID；用于取消与丢弃迟到事件",
    )


class CopilotChatResponse(BaseModel):
    answer: str
    sources: list[dict] = Field(default_factory=list)
    draft_commands: list[str] = Field(default_factory=list)
    draft_explanation: str = ""
    draft_refused_reason: str = ""
    draft_target: Optional[dict] = None
    request_id: str = ""
    replayed: bool = False
    historical: bool = False
    assist_only: bool = True
    status: str = "ok"
    provider: str = "anythingllm"
    knowledge_status: str = "unknown"
    tier: str = "standard"
    trace: dict = Field(default_factory=dict)


class GenerateValidateRequest(BaseModel):
    """配置生成闭环请求：自然语言→CLI→校验→预览"""
    natural_language: str = Field(..., min_length=1, max_length=5000, description="自然语言描述的运维需求")
    device_model: str = Field("NE40E", max_length=64, description="设备型号")


class ValidationResult(BaseModel):
    """单条命令校验结果"""
    level: str
    command: str
    passed: bool
    message: str


class GenerateValidateResponse(BaseModel):
    """配置生成闭环响应"""
    commands: list[str]
    explanation: str
    warnings: list[str]
    validation_results: list[ValidationResult]
    all_passed: bool
    high_risk_commands: list[str]
    risk_level: Optional[str] = None
    validation_suggestions: list[str] = Field(default_factory=list)


class ConfigPlanDevice(BaseModel):
    device_id: int = Field(..., gt=0)
    hostname: str = Field(..., min_length=1, max_length=128)
    role: str = Field("unknown", max_length=64)


class ConfigPlanRequest(BaseModel):
    natural_language: str = Field(..., min_length=1, max_length=5000)
    devices: list[ConfigPlanDevice] = Field(..., min_length=1, max_length=50)


class ConfigPlanItem(BaseModel):
    device_id: int
    config_content: str


class ConfigPlanResponse(BaseModel):
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    order: list[int] = Field(default_factory=list)
    items: list[ConfigPlanItem]


class ReportRequest(BaseModel):
    """AI报告助手请求"""
    title: str = Field(..., min_length=1, max_length=200, description="报告标题")
    source_text: str = Field(..., min_length=1, max_length=20000, description="日志、差异或事件原文")
    context: Optional[str] = Field(None, max_length=5000, description="附加上下文")


class ReportResponse(BaseModel):
    """AI报告助手响应"""
    title: str
    summary: str
    key_findings: list[str] = Field(default_factory=list)
    root_causes: list[str] = Field(default_factory=list)
    impact_analysis: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    report_text: str


class CoachRequest(BaseModel):
    """AI实训教练请求"""
    goal: str = Field(..., min_length=1, max_length=200, description="训练目标")
    scenario: str = Field(..., min_length=1, max_length=20000, description="训练场景或当前状态")
    current_step: Optional[str] = Field(None, max_length=5000, description="当前操作步骤")
    history: Optional[str] = Field(None, max_length=10000, description="历史操作记录")


class InspectionSummaryRequest(BaseModel):
    """B5：巡检/采集任务的 AI 归因总结请求"""
    job_id: int = Field(..., ge=1, description="巡检或采集任务 ID（monitor 任务）")


class DiffExplanationRequest(BaseModel):
    """B5：配置差异 AI 说明请求"""
    version_id_a: int = Field(..., ge=1, description="基准配置版本 ID")
    version_id_b: int = Field(..., ge=1, description="对比配置版本 ID")


class CoachResponse(BaseModel):
    """AI实训教练响应"""
    goal: str
    summary: str
    next_steps: list[str] = Field(default_factory=list)
    corrections: list[str] = Field(default_factory=list)
    explanations: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    coach_text: str
    degraded: bool = False


class FeedbackRequest(BaseModel):
    """AI交互反馈"""
    feedback: Literal["good", "bad"]


class CopilotSessionSave(BaseModel):
    """全量消息快照；更新已有会话必须提供读取时的revision。"""
    title: str = Field("新对话", max_length=256)
    messages: list[dict] = Field(default_factory=list, max_length=200)
    revision: int | None = Field(default=None, ge=0, strict=True)


class AILogResponse(BaseModel):
    """AI日志条目"""
    model_config = {"from_attributes": True}

    id: int
    user_id: int
    request_type: str
    prompt: str
    response: Optional[str] = None
    model_used: Optional[str] = None
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None
    latency_ms: Optional[int] = None
    feedback: Optional[str] = None
    created_at: Optional[datetime] = None


class AILogListResponse(BaseModel):
    """AI日志分页列表"""
    items: list[AILogResponse]
    total: int
    page: int
    page_size: int
