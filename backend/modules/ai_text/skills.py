# -*- coding: utf-8 -*-
"""CF-02：按需加载的运维技能（六类）。

技能是服务端选择的“回答框架 + 工具白名单”，不是给模型自由发挥的新权限：
- 选择是确定性的，可测试；
- 技能只影响提示与允许的工具子集，最终权限仍由工具层/角色校验；
- 简单问题走短路径，不强制先做工具规划。
"""
from __future__ import annotations

import re
import json
from dataclasses import dataclass, field
from .trusted_context import DEVICE_LABEL_PATTERN
from .read_plan import explicit_status_question

# 仅声明“建议使用”的工具；实际执行仍由 agent_tools 的权限与参数校验决定。
SKILLS: dict[str, dict] = {
    "page_help": {
        "label": "页面与功能说明",
        "prompt": "围绕用户当前页面回答：按真实控件给出最相关的两三个操作、作用及必要边界。用户未询问其他模块时，不展开完整审批/下发流程。遵守字数限制，不重复问题，不附无关结语；不要编造不存在的按钮或开关。",
        "tools": [],
    },
    "live_evidence": {
        "label": "现场证据核对",
        "prompt": "先核对目标与证据。若服务端已核验的本次观察足以回答，就解释这份原始证据，不重复采集、不假称刚做了新读取；标明原采集时间、对象与来源。无足够可信观察时，先用 query_devices 确认对象，再按需读取接口/邻居/路由；证据为空、过期或不足就说明缺口，不用教材补现场。",
        "tools": ["query_devices", "query_device_detail", "run_display_command", "query_monitor_stats", "query_alarms", "query_topology", "query_deploy_tasks", "query_config_versions"],
    },
    "knowledge_answer": {
        "label": "知识库问答",
        "prompt": "直接回答问题，优先遵守用户字数限制，不重复题目、不附多余结语。概念解释不额外展开配置、排查、参数或重启建议；用户只问某状态能否证明另一故障时，说明能证明什么、不能证明什么即可。引用前核对来源讨论的是同一协议、同一对象及同一状态；相同词语不代表相同含义。每个 [n] 紧跟它实际支持的论断；没有匹配依据就明确片段不足，不借不相关材料作证。通用知识补充须与教材依据区分。表格按列标题解读，实验操作不扩展成协议必要条件、唯一触发条件或无例外保证。",
        "tools": [],  # 检索已在入口完成，不再让模型重复规划工具
    },
    "config_draft": {
        "label": "配置草稿",
        "prompt": "只生成草稿并标注未执行；保护口（管理口）不得生成写命令。正文简洁解释必要前提，配置由系统统一展示，不另写CLI。只有有可提供草稿且用户询问后续时才简要给出校验/下发入口；保护限制不引导解除，不声称已执行。",
        "tools": [],
    },
    "troubleshooting": {
        "label": "故障排查",
        "prompt": "先确认现象与范围。服务端已解析的设备 ID 可直接用于只读工具，不重复查询清单或详情来获取相同标识；未解析或重名则先澄清。双端问题先以最少读取核对相关两端接口，再根据实际结果选择邻居/路由等下一步，有足够依据就结束。目的业务地址、源地址或路径未知时说明缺口，不能拿管理地址代替目标流量。单个接口 up/up 只说明该接口字段，不证明整个出口、路由或业务正常；单处异常也不证明唯一根因。回答简洁给已知、未知和最有用的下一步，只读排查不附未经请求的写命令。",
        "tools": ["query_devices", "query_device_detail", "run_display_command", "query_alarms", "query_topology"],
    },
    "lab_coach": {
        "label": "实训教练",
        "prompt": "按实训步骤引导，先讲目标与验证命令；不代替学员执行写操作，不跳过验证。",
        "tools": ["query_devices", "query_device_detail", "run_display_command"],
    },
}

TROUBLE = re.compile(r"不通|故障|排障|排查|丢包|链路中断|\bdown\b|\btimeout\b|超时|访问不了|ping\s*不通", re.I)
PAGE = re.compile(r"这个页面|本页|页.*(做什么|怎么用|能做什么|用途)|按钮|菜单|入口(?!\s*(?:LSR|路由器|标签|节点))", re.I)
KNOW = re.compile(r"原理|是什么|区别|有哪些|类型|默认|参数|机制|为什么", re.I)
CONCEPT = re.compile(r"原理|机制|区别|有哪些|是什么|是什么意思|如何工作|职责|分工|分别负责", re.I)
GENERAL_METHOD = re.compile(r"一般|通常|通用|基本流程|什么顺序|哪些方法", re.I)
LIVE = re.compile(r"这些数字|这个告警|这台|这条链路|当前.*(状态|设备|告警|任务)|查看|查询|核对|" + DEVICE_LABEL_PATTERN, re.I)
EXPLICIT_KNOWLEDGE = re.compile(r"教材|知识库|原理|概念|机制|区别|参考资料|文档依据", re.I)
LAB = re.compile(r"下一步|这一步|本实验|这个实验|实训|步骤|做完|验证结果", re.I)
SKILL_VERSION = "v7-d1.11"
CONTEXT_REQUIREMENTS = {
    "page_help": ["authenticated_role", "route_catalog"],
    "knowledge_answer": ["retrieval_sources"],
    "live_evidence": ["target", "verified_snapshot_or_tool_results"],
    "troubleshooting": ["target", "symptom", "tool_feedback"],
    "config_draft": ["target", "environment_policy", "protected_interfaces", "retrieval_sources"],
    "lab_coach": ["lab_steps", "target", "verified_snapshot_or_tool_results"],
}

# Literal product actions, scoped by their module rather than generic words
# such as "read"/"save" alone. Keep synchronized with the actual Vue pages and
# WORKBENCH_GUIDE; these labels classify explanations, never grant operations.
WORKBENCH_CONTROLS = {
    '工作台': ('刷新状态', '去设备', '进入实训', '完整拓扑'),
    '设备': ('健康检查', '只读观察', '添加设备', '重试设备列表', '重试拓扑列表', '重试环境列表', '最近证据'),
    '环境映射': ('新建环境', '预检', '核查恢复', '保存'),
    '拓扑': ('适应画布', '缩小画布', '放大画布', '接口标签', '链路详情', '运行态校验', '查看采集覆盖与差异', '发布到总览', '保存草稿', '版本记录', '重试版本记录', '恢复已发布布局', '确认 LLDP 基线', '导入 Excel 基线'),
    '终端': ('连接', '断开', '重新连接', '重试设备列表'),
    '知识库': ('刷新资料状态', '资料目录', '教材分组', '阅读全文', '检索资料', '检索', '片段详情', '阅读当前全文', '删除文档'),
    '监控': ('触发采集', '触发巡检', '刷新数据', '重试拓扑列表', '查看端口观察', '刷新观察', '登记用途与预期', '保存本地期望', '采集', '刷新'),
    '实训': ('更多操作', '自由练习', '新开会话', '删除实验', '查看复盘', '已保存复盘版本', '导出记录', '操作日志（JSONL）', '已保存笔记与复盘（JSON）', '重新生成复盘报告', '生成复盘报告', '结束实训', '记录操作', '核对本步', '采集当前观察', '保存环境绑定', '重试拓扑列表', '重试设备列表'),
    '配置版本': ('采集并保存配置', '选择采集设备', '比对快照', '本地 A / B 文件比对', '比对本地文件', '仅看差异及相邻行', '忽略空白与注释', '导出可见差异', '比对', '导出', '回滚', '重试设备列表', '重试快照列表'),
    '配置下发': ('AI 辅助', '静态校验', '校验配置', '创建任务', '验证报告', '查看结果', '取消任务', '重试设备列表', '重试任务列表', '重试模板列表'),
    '告警': ('确认', '关闭', '详情', '重试设备列表'),
    '变更审批': ('确认', '高风险确认', '执行', '取消', '查看结果', '记录来源筛选'),
    '系统信息': ('重试', '系统配置', '审计日志'),
    '系统配置': ('刷新配置快照', '查看逐项有效值', '查看监控有效阈值', '测试模型连通性', '新增配置', '编辑', '删除', '保存'),
    '审计日志': ('刷新', '查看', '审计记录详情'),
    '后台任务': ('刷新', '记录来源筛选', '下发任务管理', '采集与巡检', '实训会话'),
    '日志文件': ('刷新', '查看', '重试读取', '返回列表'),
    '助手': ('新建', '历史', '来源', '引用', '查询原回答', '专注展开', '收起'),
}


@dataclass
class SkillChoice:
    id: str
    label: str
    prompt: str
    tools: list[str] = field(default_factory=list)
    reason: str = ""
    version: str = SKILL_VERSION
    needs_knowledge: bool = True
    context_requirements: list[str] = field(default_factory=list)

    def as_meta(self) -> dict:
        return {"id": self.id, "label": self.label, "tools": self.tools, "reason": self.reason,
                "version": self.version, "needs_knowledge": self.needs_knowledge,
                "context_requirements": self.context_requirements}


def dashboard_summary_question(message: str, route: str | None) -> bool:
    """Explain current dashboard counters, without silently diagnosing devices."""
    return (route in {"/", "/dashboard"} and not TROUBLE.search(message or "")
            and bool(re.search(r"数字|指标|卡片|总数|统计", message or ""))
            and bool(re.search(r"什么意思|含义|表示|解释|怎么看|代表", message or "")))


def _workbench_question(text: str) -> bool:
    """Named product controls and assistant write capability are page help.

    A protocol comparison or an actual display request remains independent of
    incidental navigation. This changes prompt/retrieval selection, not rights.
    """
    feature = re.search(r'系统(?:的)?(?:私有)?(?:配置|管理|信息)|系统(?:模型)?(?:密钥|凭据)|环境映射|配置(?:下发|版本|模板)|变更审批|审计日志|后台任务|日志文件|(?:知识库|实训|设备|监控|告警|终端)(?:页|页面|中心)', text)
    control = re.search(r'哪里|在哪|入口|按钮|预检|保存|回滚|权限|管理员|普通用户|确认|操作|页面|怎么用|审批|静态校验|AI\s*辅助|弹窗', text, re.I)
    capability = re.search(r'(?:你|助手|AI).{0,12}(?:能|可以|会).{0,24}(?:写入|写进|下发|(?:执行|修改|更改).{0,8}配置|改配置)', text, re.I)
    document_authority = re.search(r'(?:文档|资料|教材|页面|附件|输出).{0,35}(?:忽略|绕过).{0,16}(?:安全|限制|确认).{0,40}(?:执行|照做|下发)', text)
    explanation = re.search(r'区别|会不会|是否|是不是|哪个|怎么用|如何使用|可以|对吗|代表|什么意思|有什么用|作用|范围|会做什么|一样吗|吗[？?]?', text)
    compact_text = re.sub(r'\s+', '', text)
    named_action = explanation and any(
        (module in compact_text or (module == '工作台' and any(alias in compact_text for alias in ('首页', '总览'))))
        and any(re.sub(r'\s+', '', label) in compact_text for label in labels)
        for module, labels in WORKBENCH_CONTROLS.items()
    )
    terminal_mode = (re.search(r'WebSSH|终端', text, re.I)
                     and re.search(r'模拟下发|DEPLOY_SIMULATE_ONLY', text, re.I)
                     and re.search(r'只读|改设备|开关|作用|范围|影响', text))
    return bool((feature and control) or capability or document_authority or named_action or terminal_mode)


def _description_without_reference(text: str) -> bool:
    """A bounded annotation edit does not need unrelated protocol examples.

    This changes retrieval only, never allowed operations. Complex requests,
    uncertain language and explicit textbook questions keep normal retrieval.
    """
    if EXPLICIT_KNOWLEDGE.search(text):
        return False
    positive = re.sub(r'(?:不修改|不更改|不调整|不动|不要修改|不要更改|别修改)(?:(?!但是|而是|但|然后|同时|并|。|；|;|\n).)*', '', text)
    return (bool(re.search(r'(?:添加|设置|修改|更改|调整|更新).{0,20}(?:描述|description)', positive, re.I))
            and bool(re.search(r'接口|LoopBack\s*\d+|(?:GE|Ethernet|Vlanif)\s*\d', positive, re.I))
            and not re.search(r'(?<![A-Za-z0-9_-])(?:IP|IPv6|OSPF|BGP|VLAN\d*|ACL|SSH|MTU|shutdown)(?![A-Za-z0-9_-])|路由|地址|账号|速率|启用|关闭|开启|删除', positive, re.I))


def _explains_observation(text: str, page_data: str | None, trusted: bool) -> bool:
    """Conservative fast path for explaining an already verified observation.

    The caller owns `trusted`; a browser source label never grants this path.
    New reads, comparisons and diagnoses retain the feedback/tool loop.
    """
    if re.search(r'(?:不是|并非).{0,4}(?:不要|不必|不再)|不能不|不得不|不要不', text):
        return False
    # Negated rereads do not request fresh evidence. Remove only the action
    # phrase, so another positive read/comparison/diagnosis still blocks this
    # shortcut. All trusted-source, target and observation checks stay below.
    positive = re.sub(r'(?:不要|无需|禁止|别|不必|不)(?:再|重新)?(?:采集|读取|查询|查看|调用)(?:一次)?', '', text)
    if not trusted or TROUBLE.search(positive) or re.search(r"重新|刷新|再采集|最新|实时|对比|比较|原因|为什么|原理|配置", positive):
        return False
    if not re.search(r"刚采集|刚才|本次|这份|这条|已有|这次", text) or not re.search(r"解释|解读|核对|说明|看懂|什么意思", text):
        return False
    try:
        data = json.loads(page_data or "")
    except (TypeError, ValueError):
        return False
    if not isinstance(data, dict) or not data.get("evidence_id") or not data.get("facts"):
        return False
    if data.get("completeness") not in {"complete", "partial"} or data.get("status") not in {"ok", "partial"}:
        return False
    if any(name.lower() != str(data.get("device", "")).lower() for name in re.findall(DEVICE_LABEL_PATTERN, text, re.I)):
        return False
    command = data.get("command", "")
    for term, expected in (("接口", "display ip interface brief"), ("邻居", "display ospf peer"), ("路由", "display ospf routing")):
        if term in text and command != expected:
            return False
    return True


def _observation_provenance_question(text: str) -> bool:
    return bool(re.search(r'这(?:个|份|条|次)|刚才|本次|当前', text)
                and re.search(r'数据|观察|证据|采集|输出', text)
                and re.search(r'真实|真机|模拟|来源|什么时候采|何时采', text)
                and not re.search(r'重新采|刷新|排查|原理|机制', text))


def _separate_knowledge_question(text: str) -> bool:
    """An incidental navigation clause must not erase a textbook question.

    Only the generic PAGE fallback is affected. Named workbench controls,
    permissions, current observations and explicit tool requests keep their
    earlier selection. A question about the entry/button itself stays page help.
    """
    if not EXPLICIT_KNOWLEDGE.search(text):
        return False
    return any(
        re.search(r'是什么|是什么意思|代表什么|表示什么|含义|原理|机制|如何工作|区别', clause)
        and not PAGE.search(clause) and not _workbench_question(clause)
        for clause in re.split(r'[。？！?!；;\n]', text)
    )


def _history_recap(text: str, history: list | None) -> bool:
    if not history or re.search(r'重新(?:采|读|查)|刷新|原理|机制|生成|下发|写入', text):
        return False
    recap = re.search(r'^\s*(?:请)?重新回答|两次结论.*对比|两个结论.*互相证明|没查到.*列|'
                      r'总结.*刚才|刚才.*过程|刚才说的.*作数|^现在还能用吗|'
                      r'(?:比较|对比).{0,12}(?:这|那)两次(?:读取|观察|结果|记录)|'
                      r'(?:这|那)两次(?:读取|观察|结果|记录).{0,20}(?:比较|对比|证明|可达)', text)
    observation_followup = (re.search(r'刚才|之前|此前|已有|那条|原记录', text)
                            and re.search(r'观察|接口|状态|证据|(?<![A-Za-z])(?:down|up)(?![A-Za-z])|邻居|路由', text, re.I)
                            and re.search(r'推翻|证明|恢复|还.*代表|仍.*有效|现在.*状态|直接.*好', text))
    # User intent may select a recap role; historical assistant claims do not
    # become verified evidence, object identity or permission as a result.
    user_goals = [str(item.get('content') or '') for item in history[-12:]
                  if isinstance(item, dict) and item.get('role') == 'user']
    return bool((recap or observation_followup) and any(LIVE.search(goal) or TROUBLE.search(goal)
                             or _observation_provenance_question(goal) for goal in user_goals))


def _lab_explanation(text: str) -> str | None:
    """Assessing evidence sufficiency is distinct from requesting new validation.

    Only used with server-resolved owned lab steps; text never binds a session.
    """
    positive = re.sub(r'(?:不要|无需|禁止|别|不)(?:再|重新)?(?:采集|读取|查询|执行|验证|核对|操作)', '', text)
    positive = re.sub(r'没有(?:实际)?(?:执行|操作|采集|读取)(?:记录|回显|证据)', '', positive)
    if EXPLICIT_KNOWLEDGE.search(text) or re.search(r'读取|采集|查询|核对|执行|验证命令|验证(?:这个|当前|本次)', positive):
        return None
    if re.search(r'(?:实训|实验).{0,18}(?:通过|达标|完成)|(?:通过|达标).{0,10}(?:实训|实验)', text):
        return 'verified_lab_assessment_explanation'
    if (re.search(r'步骤|两步|各步|第一步|第二步|这一步|下一步', text)
            and re.search(r'做什么|记录什么|要记录|解释|说明|需要什么', text)):
        return 'verified_lab_step_explanation'
    return None


def select_skill(
    message: str,
    *,
    want_draft: bool = False,
    lab_steps: list | None = None,
    page_data: str | None = None,
    page_data_trusted: bool = False,
    route: str | None = None,
    history: list | None = None,
) -> SkillChoice:
    text = message or ""
    if want_draft:
        key, reason = "config_draft", "want_draft"
    elif lab_steps and (lab_explanation := _lab_explanation(text)):
        key, reason = 'lab_coach', lab_explanation
    elif lab_steps and LAB.search(text):
        step_help = bool(re.search(r'第一步|这一步|下一步|做什么', text)) and not re.search(r'验证|核对|检查|读取|采集|设备状态', text)
        key, reason = 'lab_coach', 'verified_lab_step_explanation' if step_help else 'lab_followup'
    elif _history_recap(text, history):
        key, reason = 'live_evidence', 'operational_history_recap'
    elif _observation_provenance_question(text):
        key, reason = 'live_evidence', 'observation_provenance_explanation'
    elif _explains_observation(text, page_data, page_data_trusted):
        key, reason = "live_evidence", "verified_observation_explanation"
    elif _workbench_question(text):
        key, reason = "page_help", "workbench_controls_or_capability"
    elif TROUBLE.search(text) and not ((CONCEPT.search(text) or GENERAL_METHOD.search(text)) and not LIVE.search(text)):
        key, reason = "troubleshooting", "troubleshooting_keywords"
    elif dashboard_summary_question(text, route):
        key, reason = "page_help", "dashboard_summary_explanation"
    elif PAGE.search(text) and not _separate_knowledge_question(text):
        key, reason = "page_help", "page_question"
    elif LIVE.search(text):
        key, reason = "live_evidence", "explicit_live_question"
    elif KNOW.search(text):
        key, reason = "knowledge_answer", "knowledge_keywords"
    else:
        key, reason = "knowledge_answer", "default"
    skill = SKILLS[key]
    explanation_only = reason in {'verified_observation_explanation','observation_provenance_explanation',
                                  'operational_history_recap','verified_lab_step_explanation',
                                  'verified_lab_assessment_explanation'}
    needs_knowledge=(key != "page_help" and not explanation_only
                     and (key != "troubleshooting" or bool(EXPLICIT_KNOWLEDGE.search(text)))
                     and (key != "live_evidence" or (bool(KNOW.search(text)) and not explicit_status_question(text)))
                     and (key != "config_draft" or not _description_without_reference(text)))
    requirements=list(CONTEXT_REQUIREMENTS[key])
    if key == 'config_draft' and not needs_knowledge:
        requirements.remove('retrieval_sources')
    return SkillChoice(
        id=key,
        label=skill["label"],
        prompt=skill["prompt"],
        tools=[] if explanation_only else list(skill["tools"]),
        reason=reason,
        needs_knowledge=needs_knowledge,
        context_requirements=requirements,
    )
