"""Bounded evidence selection from admitted passages in one textbook edition."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, replace
from hashlib import sha256
from ipaddress import ip_network
import re
from typing import Any

from core.source_outline import append_heading, authored_step_title, heading_paths
from core.source_units import reading_units
from .actor_comparison import actor_comparison_request, choose_actor_evidence
from .device_alias_facets import device_aliases
from .edition import _page_texts, _source_excerpt
from .evidence_anchors import output_field_names
from .evidence_limits import evidence_limit_target, evidence_limit_witnesses
from .facet_evidence import FacetEvidence, FacetEvidenceRef
from .local_provider import _NETWORK_LABEL, _network_labels, _passage_role, _query_tokens
from .page_evidence import completed_readout_phases
from .phase_reference import operation_comparison, operation_phases, record_phases, same_ordered_record_type, source_step_boundary, step_phases
from .phase_state_readbacks import page_witnesses as phase_state_witnesses, requests as phase_state_requests
from .principle_evidence import direct_principle, multiple_principle_requests, principle_request
from .printed_exhibits import complete_exhibit_attribution, complete_printed_exhibit, exhibit_attribution_request, printed_exhibit_request
from .printed_routes import complete_printed_routes, printed_routes_request
from .query_focus import compact_text, passage_concepts, passage_query, protocol_names
from .question_roles import has_requested_visual_marks, natural_question_role, visual_marks
from .reader import DocumentReadError
from .record_sequence import case_title, record_sequence_request, sequence_witnesses
from .reported_readbacks import repeated_readback_field, reported_readback_witness
from .reviewed_source_notes import notes_for_excerpt
from .source_claims import authored_readout_clauses, linked_observation_note, observed_prose_witness, original_explanation_witness, readback_request
from .section_discovery import section_discovery_hits
from .short_observations import original_observation, short_record_request
from .source_completion import additional_document_hits
from .source_output_status import planned_output, planned_unit


_SEPARATORS = re.compile(r"[。；;？?！!\n]+|[,，]\s*(?=另外|再(?:看|问|核对|说明)|以及|还(?:有|想)|同时核对|"
                         r"(?:能|能否|能不能|可以|是否能)(?:单独|直接|据此)?(?:当|作为|证明|认定|确认)|"
                         r"还(?:缺|差|要看|需查|得补)(?:什么|哪(?:类|些|种|一项|项)))")
_ASK_FRAME = re.compile(r"谁|哪个|哪一|哪些|哪种|哪类|多少|几(?:个|股|条|位|项|次)|什么|有何|是否|能否|(?:[吗么]|呢)$")
_QUESTION_CHOICE = re.compile(r"^(?:或(?:者)?|还是|以及|和|与|包括|例如|比如|若|如果|即|也就是)")
_CITATION_INSTRUCTION = re.compile(
    r"(?:(?:请|并|另|还要)?(?:只)?(?:给出?|附|标明|补充)(?:具体)?"
    r"(?:出处|(?:教材|原书)?页码|物理页|引用|(?:图表|图中|表中)文字)(?:即可|就好)?"
    r"|(?:我)?(?:只|仅)(?:问|看)(?:教材|原书|课本)(?:的)?(?:原理|内容|材料)?"
    r"|(?:我)?(?:只|仅)(?:依据|根据|参考|使用)(?:本地)?(?:教材|原书|课本)(?:材料|资料)?(?:回答|作答)?"
    r"|(?:只|仅)(?:作|做)(?:教材|原书|课本)(?:对比|比较)"
    r"|(?:仅限|只用)(?:教材|原书|课本)(?:资料|内容)?"
    r"|(?:不要|不用|无需|别)(?:去)?(?:查看|登录|操作|连接)(?:任何|实际|真实)?设备"
    r"|(?:请)?看(?:真实|实际)?(?:回显|读回|输出)"
    r"|(?:请)?(?:把|将)同一(?:项|次|份)?(?:观察|回显|输出)(?:的)?(?:说明|解释)(?:也)?(?:带上|附上|保留)"
    r"|(?:要|请)?(?:使用|保留|给出)?同一(?:次|份)(?:回显|输出|读回)(?:和|与|及)(?:其)?(?:说明|解释))"
)
_RESPONSE_CONSTRAINT = re.compile(
    r"(?:本题|这题|这次)?\s*(?:请|就)?\s*(?:"
    r"(?:只|仅|完全)(?:按|根据|依据|看|从|查)\s*(?:给定的|已有的|本地的|本地|现有的|这份|这本)?\s*"
    r"(?:教材|课件|讲义|原书|工单样例)(?:里的|中的|的)?(?:原文|正文|内容|资料|记录|证据|观察结果)?"
    r"|(?:请)?(?:不要|无需|不必|不用|不)\s*(?:真的|实际|现场|直接|再)?\s*"
    r"(?:(?:登录|接入|连接|访问|读取|查询|操作|去碰)(?:任何|真实|实时|现场|实际)?设备"
    r"|执行(?:任何|配置)?命令|下发(?:任何)?配置|提供(?:任何|实操|配置)?命令)"
    r"|(?:只|仅)(?:讲|谈|说明|讨论|做|作)(?:教材|原书)?(?:原理|文字分析|教材对照|证据判断)"
    r"|(?:都|仍|继续)?(?:按|用|看|在)?同一(?:个)?(?:教材|原书)?(?:实验|案例|场景|例子)(?:里|内|中)?"
    r")\s*(?:分析|回答|核对|解释|作答|即可|就好)?"
)
_NAME = r"(?:[A-Za-z][A-Za-z0-9_]*(?:[- ][A-Za-z0-9]+){0,3}|[\u3400-\u9fff]{2,12}?)"
_PAIR = re.compile(rf"^(?:(?:请|对比|比较)\s*)*[‘“`\"]?(?P<a>{_NAME})[’”`\"]?\s*(?:和|与|vs\.?)\s*"
                   rf"[‘“`\"]?(?P<b>{_NAME})[’”`\"]?(?=\s*(?:分别|各自|有何|有什么|的区别|怎么|如何|两者|差别|[:：,，]))", re.I)
_DEVICE = r"(?:ar|ce|fw|ne|pe|pc|sw|p|r|s)[0-9]+|(?:ar|ce|fw|ne|pe|pc|sw|leaf|spine|edge|acc|router)[0-9]*[-_][a-z0-9]{1,4}"
_DEVICES = re.compile(rf"(?<![a-z0-9_-])(?:{_DEVICE})(?![a-z0-9_/-])", re.I)
_BINDING = r"(?:\s*`?(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?`?)?"
_UI_DIRECTION = re.compile(rf"(?<![a-z0-9_-])(?P<a>{_DEVICE}){_BINDING}\s*(?:→|->|向|到|至|发给|测到)\s*(?P<b>{_DEVICE})(?![a-z0-9_/-])", re.I)
_OBSERVATION_OWNER = re.compile(rf"(?<![a-z0-9_-])(?P<device>{_DEVICE})(?![a-z0-9_/-])\s*"
                                r"(?:(?:的|上)[^，。；？！\n]{0,16}?)?(?:回显|读回|输出|状态表|邻接表|路由表)", re.I)
_DATA_OBSERVER = re.compile(rf"(?<![A-Za-z0-9_/-])(?P<device>{_DEVICE})(?![A-Za-z0-9_/-])\s*"
                            r"(?:的\s*(?:路由|转发|表项|前缀|条目)|(?:(?:实际|能|所)\s*)?(?:看到|读到|查到)的?)", re.I)
_JOINT_OBSERVATION_OWNER = re.compile(rf"(?<![a-z0-9_-])(?:{_DEVICE})\s*(?:和|与|及|、)\s*(?:{_DEVICE})\s*的"
                                      r"[^，。；？！\n]{0,16}?(?:回显|读回|输出|状态表|邻接表|路由表)", re.I)
_GROUP_DIRECTION = re.compile(rf"(?<![a-z0-9_-])(?P<a>{_DEVICE}){_BINDING}\s*(?:、|和|与|以及)\s*(?P<b>{_DEVICE}){_BINDING}"
                              rf"\s*(?:各自|分别|均)?\s*(?:→|->|向|到|至)\s*(?P<target>{_DEVICE})(?![a-z0-9_/-])", re.I)
_RECIPROCAL = re.compile(rf"(?<![a-z0-9_-])(?P<a>{_DEVICE}){_BINDING}\s*(?:和|与|、)\s*(?P<b>{_DEVICE}){_BINDING}"
                         r"\s*(?:做|进行)?\s*双向(?:互测|探测|测试)", re.I)
_NAMED_ROLE = r"客户端|服务端|发送端|接收端|发起端|响应端|上游|下游|主设备|备设备|主根桥|备份根桥|根端口|指定端口|备用端口"
_ROLES = re.compile(rf"{_NAMED_ROLE}|服务器|\bclient\b|\bserver\b|\bmaster\b|\bbackup\b", re.I)
_ROLE_OWNER = re.compile(rf"(?<![a-z0-9_-])(?P<device>{_DEVICE})\s*(?:作为|是|为|担任|成为|充当)\s*(?:本例|该组)?\s*(?P<role>{_NAMED_ROLE})", re.I)
_MODE = re.compile(r"分布式网关|集中式网关|透明模式|路由模式|主备模式|负载分担模式|传输模式|隧道模式|主动模式|被动模式|"
                   r"(?<![a-z0-9_-])(?:active[- ]standby|load sharing)(?![a-z0-9_-])|(?:配置)?方式\s*[一二三四1-4A-D]", re.I)
_PHASE_ACTION = r"故障|切换|重选|恢复|调整|配置|引入|重分发|汇总|聚合|重启"
_PHASE = re.compile(rf"(?P<action>{_PHASE_ACTION})(?:之前|之后|发生前|发生后|完成后|前|后)")
_PHASE_RANGE = re.compile(rf"(?P<action>{_PHASE_ACTION})(?:前后|(?:之前|前)\s*(?:和|与|及|、)\s*(?:(?P=action))?(?:之后|后))")
_RELATIVE_STAGE = re.compile(r"^(?:而|然后|再)?\s*(?:之后|以后)[，,、\s]*")
_QUALIFIED_ADJUSTMENT = re.compile(r"(?:调整|修改|变更)(?P<object>[\u3400-\u9fffA-Za-z_-]{2,12}?)(?P<time>之前|之后)")
_PRINTED_ADJUSTMENT = re.compile(r"(?:调|调整)(?P<time>前|后)\s*(?:表|回显|结果|输出)")
_STEP = re.compile(r"(?:第|阶段\s*)[一二三四五六1-6]\s*阶段|阶段\s*[一二三四五六1-6]")
_SCOPE = re.compile(r"^(?:(?:第\s*)?[0-9一二三四五六]+(?:[.、 ]+|\s*))?(?:实验|案例|方案|场景)\s*(?:[0-9一二三四五六A-D]|[:：、]).{0,140}$", re.I)
_FIELD = re.compile(r"(?<![A-Za-z0-9_/-])(?:[A-Z][A-Z0-9_-]{1,18}|[A-Z][a-z]{2,20}(?:[ \t]+[A-Za-z][a-z]{2,18}){1,3})(?![A-Za-z0-9_/-])")
_FIELD_REFERENT = re.compile(r"^(?:(?:请|再)?(?:说说|说明)?(?:这|该)(?:个|一)?(?:字段|列))(?:的(?:含义|作用)|(?:说明|表示|描述|反映|代表))")
_NEXT_EVIDENCE_ASK = re.compile(r"^(?:那|那么|另外)?\s*(?:还|再|另)(?:(?:需|缺|差|要|得)(?:再)?)?"
                                 r"(?:查|看|核对|补充?|提供)?\s*(?:什么|哪(?:类|种|些|项|一项))"
                                 r"(?:证据|资料|材料|记录|观测|观察|回显)?(?:才(?:能|可以)?(?:说得准|下结论|填这项))?$")
_NAMED_READBACK_FIELD = re.compile(rf"(?<![A-Za-z0-9_-])(?:{_DEVICE})\s*的\s*[`“\"]?"
                                  r"(?P<field>[A-Za-z][A-Za-z0-9_/-]*(?:[ \t]+[A-Za-z0-9][A-Za-z0-9_/-]*){0,7})"
                                  r"\s*[`”\"]?\s*(?=(?:回显|读回)(?!里面|里|中|内)|(?:也|又)(?:是|为)?(?:多少|哪|什么)|呢$)", re.I)
_OBSERVATION_CONTEXT_PREFIX = re.compile(r"^[^，。；]{1,150}(?:回显|读回|输出)(?:里面|里|中|内)?[，,、]\s*")
_NAMED_ARTIFACT = re.compile(r"(?<![A-Za-z0-9_-])([A-Z][A-Z0-9_-]{1,16})\s*(?:回显|读回|输出)")
_ELLIPTIC_READBACK = re.compile(r"(?:也|又)(?:是|为)?(?:多少|哪|什么)|呢$")
_FIELD_COUNT = re.compile(r"哪\s*([一二三四五六七八九1-9])\s*(?:个|条|项)\s*(?:地址|条目|记录|数值)")
_COUNT_DIGITS = str.maketrans("一二三四五六七八九", "123456789")
_READ = re.compile(r"回显|读回|日志|实际(?:结果|显示|探测|测得)|(?:表|输出)(?:中|里|内)|字段(?:值|里)|实测|几(?:个|次)回复|互测|确认.*(?:状态|结果)")
_ASKED_DISPLAY = re.compile(r"(?:显示|列出|读到|查到|写着|测到)(?:了|的)?(?:是|为)?\s*(?:哪|什么|多少|几)")
_OPERATION_BEFORE = re.compile(r"(?:动手|操作|做这一步|执行这(?:一)?步)(?:之前|以前|前)")
_OPERATION_AFTER = re.compile(r"(?:动手|操作|做完这(?:一)?步|执行完这(?:一)?步)(?:之后|以后|后)")
_OBSERVATION_ASK = re.compile(r"什么|有何|谁|哪|几(?:个|位|次)|多少|怎样|如何|怎么|呢$")
_OBSERVATION_ROLE = re.compile(r"(?:端口|接口|设备|两端|两台|各自)(?:的)?角色|角色(?:各是|是|分别是|是什么)|"
                               r"(?:什么|哪(?:种|一?类|一?个))角色")
_OBSERVATION_STATE = re.compile(r"(?:邻接|邻居|端口|接口|链路|会话|对等体)(?:的)?状态|状态(?:各是|是|分别是|是什么)|"
                                r"(?:什么|哪(?:种|一?类|一?个))状态")
_ROLE_VALUE = re.compile(r"(?:根端口|指定端口|备用端口|主设备|备设备)|\b(?:root(?: port)?|desi(?:gnated)?|alte(?:rnate)?|backup|master)\b", re.I)
_STATE_VALUE = re.compile(r"(?:阻塞|转发|未建立|已建立)|\b(?:up|down|discarding|forwarding|full|established)\b", re.I)
_ACTUAL_PROSE = re.compile(r"(?:实际(?:读回|回显|输出|探测|显示|记录|结果)|(?:回显|读回|日志|记录)(?:中|里|显示|列出|的?结果)|观察到|实测|命令输出)")
_PROSE_ASSIGNMENT = re.compile(r"(?:角色|状态|结果|字段)|(?:均|已)?(?:为|回到|转入|恢复为|达到|列出|进入)")
_EXPECTED_ONLY = re.compile(r"预期|预计|计划|规划|建议|应当|应该|目标是|拟用|将会|如果|假设|用于查看")
_FIGURE_ID = re.compile(r"图\s*([0-9]+(?:\s*[-—.–－]\s*[0-9]+)*)")
_DIAGRAM = re.compile(r"图中|图上|图题|图注|图例|图示|拓扑图|箭头|从图|图表|图\s*[0-9]")
_CONFIG = re.compile(r"如何配置|怎么配置|(?:配置|设置|启用|禁用)(?:在哪|什么|哪些|哪一)|用什么命令|配置步骤")
_MECHANISM = re.compile(r"为什么|如何(?:工作|处理|影响|传|收|选)|(?:谁|哪一端)(?:发|收|建立|负责)|方向|动作|工作流程|触发|根据什么")
_MECHANISM_TITLE = re.compile(r"^\s*\*\*([^*\r\n]{2,100})\*\*")
_TITLE_COMPARISON = re.compile(r"[A-Za-z][A-Za-z0-9_-]+\s*(?:和|与|或|vs\.?|/)\s*[A-Za-z][A-Za-z0-9_-]+", re.I)
_ROLE_DESTINATION = re.compile(r"(?:向|到|至|发给)(?:集中)?(?P<role>服务端|服务器|客户端|接收端|发送端)")
_FIELD_EXPLANATION = re.compile(r"为什么|什么(?:含义|意思|作用)|(?:有什么|何种)作用")
_CAUSAL_PROOF = re.compile(r"依赖|因此|导致|所以|代表|表示|意味着|用于|负责")
_EXPERIMENT_WORDS = re.compile(r"同一(?:次|轮|组|实验|案例)|本(?:次|轮|例)|这(?:次|轮|一例|个实验)|该(?:回显|页|表|实验)|实验中的")
_SAME_CASE = re.compile(r"同一(?:个)?(?:次|轮|组|实验|案例|场景|方案|拓扑|组设备|台设备)|同一个?例子")
_SAME_CASE_UNCERTAIN = re.compile(r"(?:是否|能否|不是|并非|不要求|不能当作|是不是).{0,8}(?:同一|同个)")
_INDEPENDENT_CASES = re.compile(r"(?:不同的?|独立的?|互相独立的?|另一个|另一组)(?:实验|案例|场景|方案|拓扑)|"
                                r"(?:比较|对比|分别看).{0,12}(?:两个|两组|两种)(?:不同的?)?(?:实验|案例|场景|方案|拓扑)")
_SWITCH_SCOPE = re.compile(r"^(?:然后|之后|接着|另外|还)?\s*(?:再看|另看|再核对|再问)")
_SOURCE_PHASE = re.compile(r"^步骤\s*[0-9一二三四五六七八九十]+[.、：:\-\s]+\s*(?P<title>\S.*)$")
_NUMBERED_CASE = re.compile(r"^\d+(?:\.\d+)+\s+(?P<title>(?=\S).*?(?:案例|实验|场景|方案).*)$")
_CASE_COMPONENT = re.compile(r"^(?P<number>\d+(?:[.．]\d+)+)\s+实验(?P<part>介绍|目的|目标|任务|规划|步骤)(?:与.*)?$")
_GENERIC_SCOPE = re.compile(r"^(?:实验|案例|场景|方案)?(?:组网介绍|配置步骤|配置|结果|验证|介绍|概述|说明|小结|目标|目的|任务|"
                            r"准备|背景|列表|概览)$")
_SCOPE_EXCLUSION = re.compile(r"不(?:是|用|查|看|要|考虑)|别(?:用|查|看)|排除|除外|除了")
_TITLE_NUMBERING = re.compile(r"^(?:\d+(?:[.．]\d+)*\s+)?(?:(?:实验|案例|场景|方案)[0-9一二三四五六七八九十A-D]+[:：、\s]+)?")
_OBSERVED = re.compile(r"显示|回显|日志|返回|收到|测得|观察到|(?<!\d)\d+\s*发\s*\d+\s*收|\b(?:established|full|discarding|forwarding)\b", re.I)
_OBSERVED_VALUE = re.compile(r"\d|\b(?:up|down|full|normal|established|discarding|forwarding|backup|master)\b|为空|留空|未建立|无回显", re.I)
_LOOK_ONLY = re.compile(r"(?:需要|建议|应该|应当)(?:再次|先|另行)?(?:参见|查看|读回|核对|观察)|用于(?:查看|读取|验证)|目录|下(?:一)?页(?:展示|显示)")
_OBSERVATION_CLAUSE = re.compile(r"[。；;,，\n]")
_DIRECTED_RESULT = re.compile(r"(?<!\d)\d+\s*发\s*\d+\s*收|\b(?:is|state\s*[:=])\s*(?:up|down|full|normal|discarding|forwarding)\b", re.I)
_ALL_OBSERVATIONS = re.compile(r"(?:均(?:为|是|返回|收到)?|都是|各自.{0,16}(?:为|收到|返回)|皆为)\s*[:：]?\s*$")
_UNOBSERVED = re.compile(r"预期|预计|理论上|应当|应该|可能|建议|用于|若|如果|将会|目标是|下(?:一)?页|未执行|未观察到|无回显")
_READ_COMMAND = re.compile(r"^\s*(?:<[^>]+>|\[[^]\s]+\])?\s*(?:display|show)\s+", re.I)
_CONFIGURATION_VALUE = re.compile(r"(?:当前|生效|已保存|实际)配置|配置(?:读回|回显|输出)")
_PROMPT = re.compile(r"^\s*(?:<[^>]+>|\[[^]\s]+\])\s*\S+")
_COMMAND_DEVICE = re.compile(r"^\s*(?:<([^>]+)>|\[([^]\s]+)\])")
_AFTER_CAPTION = re.compile(r"(?:如下|见下(?:表|图)|如(?:下表|下图)所示|输出如下|回显如下)[：:。\s]*$")
_BEFORE_CAPTION = re.compile(r"^(?:由|从)?(?:上表|上图|上述(?:命令)?(?:输出|回显)|(?:该|此)(?:表|图|回显|输出))(?:中|可见|显示|记录|给出|说|的)")
_OUTPUT_EXPLANATION = re.compile(r"^(?:由|从|据)(?:该|这份|上述)?(?:命令)?(?:输出|回显|读回)(?:信息)?(?:中)?(?:可以|可|能够)?(?:看到|看出|发现|得知|说明)")
_AFTER_RECORD_NOTE = re.compile(r"^\s*\**(?:原页|原书|本页)(?:的)?[^，。；\n]{0,10}(?:表|回显|输出)(?:中|里|仍|显示|列出|所)")
_CHECK_AGAIN = re.compile(r"^(?:再次|重新|再)(?:查看|读取|观察|核对|执行)")
_RECORDED_CHANGE = re.compile(r"(?:修改|调整|改为|配置|设置|变为).{0,20}\S")
_SENTENCE_END = re.compile(r"[。？！!?；;.!\]）][”’）》)*`\s]*$")
_CONTINUED_WORD = re.compile(r"^[\u3400-\u9fff]{1,3}[。；]")
_FIELD_RELATION = re.compile(r"描述|表示|反映|代表|用于|指的是|对应")
_FIGURE_EXPLANATION = re.compile(r"^(?:(?:由|从)?(?:该图|此图|本图|上图|图中|图内)|(?:该|此)?图(?:题|例|注))")
_OTHER_PAGE_FIGURE = re.compile(r"(?:图题|图注|图例|图)\s*(?:见|详见|在|移至)\s*(?:下一页|上一页|(?:PDF\s*)?(?:第|物理)\s*[0-9])")
_ACTION = re.compile(r"发送|发起|发布|收到|接收|响应|转发|返回|丢弃|替换|保留|封装|请求|注册|设置|协商|建立|加密|转换|允许|校验|等待|拒绝|变成|改写|通过")
_DEFINITION = re.compile(r"指(?:的是)?|是(?:一种|一种用来|指)|用于|表示|作用是|负责|由.{1,32}(?:产生|发布|发送|组成)|作用范围")
_CONFIG_PROOF = re.compile(r"(?m)^[ \t]*(?:\[[^]\s]+\]\s*)?(?:interface|ip route-static|peer|router-id|vlan|bridge-domain|network|undo|ospf|isis|bgp|enable)\s", re.I)
_NAVIGATION = re.compile(r"^(?:\*\*)?(?:目录|学习目标|练习|本章小结|本节将|接下来介绍)(?:[:：。]|\*\*|\s|$)")
_PHYSICAL_HEADING = re.compile(r"^PDF\s*第\s*[0-9]+\s*页")
_HEADING_MARK = re.compile(r"^(#{1,6})\s+(\S.*?)\s*$")
_STAGE_SUFFIX = re.compile(r"(?:之前|发生前|前)$")
_FIELD_STOP = frozenset({"pdf", "cli", "ip", "ipv4", "ipv6"})
_COLUMN_SPLIT = re.compile(r" {2,}|\t+")
_RECORD_ROW_KEY = frozenset({"port", "interface", "接口", "端口", "destination", "network", "prefix", "目的地址", "前缀"})
_SEPARATE_ROWS = re.compile(r"分别|各自|各(?:是|为|表示|对应)")
_OUTPUT_RECORD_LABEL = re.compile(r"^(?:[A-Za-z][A-Za-z0-9.\-]*\s+){0,5}(?:entry information|record details)\s+(?:of|for)\s+", re.I)
_MULTIPLE_RECORDS = re.compile(r"除了|之外|以外|其他(?:条目|记录|对端|邻居|接口)|(?:所有|全部|每一)(?:行|条|入口|接口|邻居|记录)|"
                               r"(?:共|总共|一共)(?:有|应有)?(?:几|多少)|另(?:一|两|三)(?:条|行|个邻居)")
_OTHER_EVIDENCE = frozenset({"required_observation", "separate_observation"})
_DIRECT_LIMIT = frozenset({"excluded_inference", "separate_observation"})
_ROLE_COLUMNS = frozenset({"role", "portrole", "角色", "端口角色"})
_STATE_COLUMNS = frozenset({"state", "portstate", "stpstate", "状态", "端口状态", "转发状态"})
_PRINCIPLE_KINDS = frozenset({"principle_definition", "principle_purpose"})
_SUMMARY_ARTIFACT = re.compile(r"路由表|转发表|表项|路由条目")
_SUMMARY_PREFIX = re.compile(r"前缀|子网(?:地址)?")
_SUMMARY_AMOUNT = re.compile(r"(?:有|共(?:有|计)?|为)\s*(?:[0-9]+|[一二三四五六七八九十]+)\s*条|(?:条目|表项)(?:总)?(?:数|数量)\s*(?:为|是)\s*\d+")
_SUMMARY_CHANGE = re.compile(r"由\s*\d+\s*(?:条)?\s*(?:变为|改为|变成|增至|减至|降至|升至)\s*\d+")
_SUMMARY_APPLIED = re.compile(rf"(?:已实施|实施|完成|执行|进行了)(?:[^。；！？]{{0,32}}?)(?P<action>{_PHASE_ACTION})")
_SUMMARY_ROUTE_ASSERTION = re.compile(r"指向|列出|读到|看到|包含|显示|出现|有\s*`?[0-9a-f]", re.I)
_SUMMARY_ROUTE_MERGED = re.compile(r"(?:合并|汇总|聚合)(?:成|为)|(?:为|变成)\s*`?[0-9a-f:.]+/\d+", re.I)
_SUMMARY_PREFIX_VALUE = re.compile(r"(?<![0-9a-f:.])(?:\d{1,3}(?:\.\d{1,3}){3}|[0-9a-f:]*:[0-9a-f.]+)/(?:\d{1,3})(?![\d/])", re.I)
_SUMMARY_SHARED_AMOUNT = re.compile(rf"(?<![A-Za-z0-9_/-])(?P<owners>(?:{_DEVICE})(?:\s*(?:、|和|与|及)\s*(?:{_DEVICE}))+)(?![A-Za-z0-9_/-])\s*各自的"
                                    r"[^，。；]{0,28}(?:表|输出)[，,]?\s*均有\s*\d+\s*条", re.I)
_ORIGINAL_NUMBER = re.compile(r"^(\d+(?:[.．]\d+)+)\s+\S")


@dataclass(frozen=True)
class _Facet:
    number: int
    text: str
    kind: str
    topic: str
    subjects: frozenset[str]
    labels: frozenset[str]
    devices: frozenset[str]
    directions: frozenset[tuple[str, str]]
    roles: frozenset[str]
    owners: frozenset[tuple[str, str]]
    phases: frozenset[tuple[str, str]]
    modes: frozenset[str]
    fields: frozenset[str]
    concepts: frozenset[str]
    limit_target: str
    figures: frozenset[str]
    observation_owner: str
    readback_label: str = ""
    observation_axes: frozenset[str] = frozenset()
    asks_for_other_evidence: bool = False
    output_fields: frozenset[str] = frozenset()
    phase_object: str = ""
    artifact_label: str = ""


@dataclass(frozen=True)
class _Plan:
    facets: tuple[_Facet, ...]
    same_experiment: bool
    compare_phases: bool = False


@dataclass(frozen=True)
class PreciseCase:
    scope: tuple[str, ...]
    matches: tuple[tuple[int, FacetEvidenceRef], ...]
    directions: tuple[tuple[int, tuple[tuple[str, str], ...]], ...]


@dataclass(frozen=True)
class VerifiedEvidenceBundle:
    scope: tuple[str, ...]
    matches: tuple[tuple[int, FacetEvidenceRef], ...]


@dataclass(frozen=True)
class RankedEvidence:
    query_sha256: str
    edition_version: str
    facets: tuple[tuple[int, str, str], ...]
    matches: tuple[tuple[int, FacetEvidenceRef], ...]
    missing: tuple[int, ...]
    precise_case: PreciseCase | None = None
    ambiguous_precise_case: bool = False
    observation_facets: tuple[int, ...] = ()
    verified_observation: tuple[tuple[int, FacetEvidenceRef], ...] = ()
    ambiguous_observation_facets: tuple[int, ...] = ()
    verified_explanation: tuple[tuple[int, FacetEvidenceRef], ...] = ()
    comparison_topics: tuple[tuple[int, str], ...] = ()
    verified_bundle: VerifiedEvidenceBundle | None = None
    ambiguous_verified_bundle: bool = False
    same_experiment: bool = False
    compare_phases: bool = False
    explicit_same_experiment: bool = False
    phase_facets: tuple[int, ...] = ()
    original_scope_locations: tuple[dict[str, Any], ...] = ()
    same_step_readouts: tuple[tuple[int, FacetEvidenceRef], ...] = ()

    def select_hits(self, query: str, pool: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        return self._select(query, pool, self.matches)

    def select_precise_hits(self, query: str, pool: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        if self.precise_case is None or self.ambiguous_precise_case:
            return None
        return self._select(query, pool, self.precise_case.matches)

    def select_verified_observations(self, query: str, pool: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        return self._select(query, pool, self.verified_observation)

    def select_verified_explanations(self, query: str, pool: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        return self._select(query, pool, self.verified_explanation)

    def select_verified_bundle(self, query: str, pool: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        if self.verified_bundle is None or self.ambiguous_verified_bundle:
            return None
        return self._select(query, pool, self.verified_bundle.matches)

    def _select(self, query, pool, matches):
        if sha256(query.encode("utf-8")).hexdigest() != self.query_sha256:
            return None
        ordered = tuple(dict.fromkeys(ref for _, ref in matches))
        found = {FacetEvidenceRef.from_hit(hit): hit for hit in pool if hit.get("edition_version") == self.edition_version}
        if not ordered or any(ref not in found for ref in ordered):
            return None
        return [found[ref] for ref in ordered]


@dataclass(frozen=True)
class EvidenceSearchResult:
    hits: list[dict[str, Any]]
    facet_evidence: FacetEvidence | None
    pool: list[dict[str, Any]]
    ranked: RankedEvidence | None


def _subjects(text):
    return frozenset(protocol_names(text))


def _devices(text):
    plain = _DEVICES.findall(text.casefold())
    return frozenset(name for name in plain if "_" not in name and "-" not in name) | device_aliases(text)


def _directions(text):
    directed = {(item["a"].casefold(), item["b"].casefold()) for item in _UI_DIRECTION.finditer(text)}
    for match in _GROUP_DIRECTION.finditer(text):
        directed.update((side.casefold(), match["target"].casefold()) for side in (match["a"], match["b"]))
    for match in _RECIPROCAL.finditer(text):
        start, end = match["a"].casefold(), match["b"].casefold()
        directed.update(((start, end), (end, start)))
    return frozenset(directed)


def _observed_directions(text):
    observed = set()
    for clause in _OBSERVATION_CLAUSE.split(text):
        if _UNOBSERVED.search(clause) or _EXPECTED_ONLY.search(clause):
            continue
        start = 0
        for result in _DIRECTED_RESULT.finditer(clause):
            claim = clause[start:result.start()]
            start = result.end()
            directions = _directions(claim)
            if len(directions) == 1 or directions and _ALL_OBSERVATIONS.search(claim):
                observed.update(directions)
    return frozenset(observed)


def _phases(text, *, reported=False):
    stages = {(match["action"], "before" if _STAGE_SUFFIX.search(match[0]) else "after") for match in _PHASE.finditer(text)}
    stages.update((compact_text(value), "ordinal") for value in _STEP.findall(text))
    if _OPERATION_BEFORE.search(text):
        stages.add(("操作", "before"))
    if _OPERATION_AFTER.search(text):
        stages.add(("操作", "after"))
    stages.update(("调整", "before" if match["time"].endswith("前") else "after")
                  for pattern in (_QUALIFIED_ADJUSTMENT, _PRINTED_ADJUSTMENT) for match in pattern.finditer(text))
    return (frozenset(stages) | operation_phases(text, reported=reported) | step_phases(text, reported=reported)
            | record_phases(text, reported=reported))


def _markers(text):
    return frozenset(compact_text(value) for value in _MODE.findall(text))


def _roles(text):
    normalized = {"client": "客户端", "server": "服务端", "服务器": "服务端", "master": "主设备", "backup": "备设备"}
    return frozenset(normalized.get(token.casefold(), token.casefold()) for token in _ROLES.findall(text))


def _owners(text):
    return frozenset((m["device"].casefold(), m["role"]) for m in _ROLE_OWNER.finditer(text))


def _kind(text):
    for marker, kind in ((_CONFIG, "configuration"), (_READ, "readback"), (_DIAGRAM, "diagram"),
                         (_ASKED_DISPLAY, "readback")):
        if marker.search(text):
            return kind
    if explicit := readback_request(text):
        return explicit
    if natural := natural_question_role(text):
        return natural.kind
    return "mechanism" if _MECHANISM.search(text) else "concept"


def _fields(text):
    text = _NETWORK_LABEL.sub(" ", text)
    return frozenset(compact_text(token) for token in _FIELD.findall(text)) - _subjects(text) - _devices(text) - _FIELD_STOP


def _observation_owner(text):
    if _JOINT_OBSERVATION_OWNER.search(text):
        return ""
    owners = {match['device'].casefold() for match in _OBSERVATION_OWNER.finditer(text)}
    if not owners:
        owners = {match['device'].casefold() for match in _DATA_OBSERVER.finditer(text)}
    return next(iter(owners)) if len(owners) == 1 else ""


def _figures(text):
    return frozenset(compact_text(value).translate(str.maketrans("—.–－", "----")) for value in _FIGURE_ID.findall(text))


def _explicit_same_case(text):
    return bool(_SAME_CASE.search(text) and not _SAME_CASE_UNCERTAIN.search(text))


def _reference_domains(facet):
    families = set()
    for label in facet.labels:
        try:
            ip_network(label, strict=False)
        except ValueError:
            if re.fullmatch(r"[a-z]+[0-9]+", label):
                families.add(label.rstrip("0123456789"))
        else:
            families.add("network-address")
    return families


def _independent_cases(text, facets):
    if len(facets) < 2 or _explicit_same_case(text):
        return False
    if _INDEPENDENT_CASES.search(text):
        return True
    for previous, following in zip(facets, facets[1:]):
        if not _SWITCH_SCOPE.match(following.text):
            continue
        if previous.modes and following.modes and previous.modes.isdisjoint(following.modes):
            return True
        if previous.devices and following.devices and previous.devices.isdisjoint(following.devices):
            if previous.subjects and following.subjects and previous.subjects.isdisjoint(following.subjects):
                return True
            left, right = _reference_domains(previous), _reference_domains(following)
            if left and right and left.isdisjoint(right) and not (previous.subjects & following.subjects):
                return True
    return False


def _compares_phases(facets):
    if any(len(facet.phases) > 1 for facet in facets):
        return False
    requested = set().union(*(facet.phases for facet in facets))
    if len(requested) != 2:
        return False
    (first, when), (second, other) = requested
    return (first == second and {when, other} == {"before", "after"}
            or first != second and when == other == "ordinal" and same_ordered_record_type(first, second))


def _question_clauses(terms):
    for span in _SEPARATORS.split(terms):
        current = ""
        for part in re.split(r"([，,、])", span):
            candidate = part.strip()
            if (len(candidate) >= 2 and _ASK_FRAME.search(candidate) and _ASK_FRAME.search(current)
                    and not _QUESTION_CHOICE.match(candidate)):
                yield current.strip(" ，,、：:")
                current = part
            else:
                current += part
        clause = current.strip(" ，,、：:")
        if len(clause) >= 2:
            yield clause


def _evidence_question_clauses(terms):
    questions = []
    for clause in _question_clauses(terms):
        pieces = re.split(r'([，,])', clause)
        left, right = 0, len(pieces)
        while left < right and _RESPONSE_CONSTRAINT.fullmatch(pieces[left].strip()):
            left += 2
        while left < right and (_RESPONSE_CONSTRAINT.fullmatch(pieces[right - 1].strip())
                                or _CITATION_INSTRUCTION.fullmatch(pieces[right - 1].strip())):
            right -= 2
        question = ''.join(pieces[left:right]).strip()
        if question:
            questions.append(question)
    return tuple(questions)


def _observation_axes(text):
    axes = set()
    if _SUMMARY_ARTIFACT.search(text) and (not _SUMMARY_PREFIX.search(text) or re.search(r"表项|条目|几条|多少条|数量", text)):
        axes.add("entries")
    if _SUMMARY_PREFIX.search(text):
        axes.add("prefixes")
    return frozenset(axes)


def _staged_readbacks(text):
    ranges = [(match["action"], match.span()) for match in _PHASE_RANGE.finditer(text)]
    named = operation_comparison(text)
    if named:
        action, (start, end) = named
        ranges = [(label, (left, right)) for label, (left, right) in ranges if not start <= left < right <= end]
        ranges.append((action, (start, end)))
    if (len(ranges) != 1 or not _ASK_FRAME.search(text)
            or not (_READ.search(text) or _devices(text) and (_OBSERVATION_ROLE.search(text) or _OBSERVATION_STATE.search(text)
                                                               or _observation_axes(text) and _observation_owner(text)))):
        return (text,)
    (action, (start, end)), = ranges
    if _phases(text[:start] + text[end:]):
        return (text,)
    return tuple(text[:start] + action + when + text[end:] for when in ("前", "后"))


def _plan(terms):
    terms = terms.strip()
    if not terms or len(terms) > 1600:
        return None
    clauses = [part for clause in _evidence_question_clauses(terms) for part in _staged_readbacks(clause)]
    if not clauses or len(clauses) > 12:
        return None
    substantive = "。".join(clauses)
    pair = _PAIR.match(clauses[0])
    case = bool(_EXPERIMENT_WORDS.search(terms) or _devices(substantive) or _phases(substantive))
    bindings = [(part, "") for part in clauses]
    if pair and not case:
        remainder = clauses[0][pair.end():].strip(" ，,：:")
        bindings = [(f"{pair[side]} {remainder}", pair[side].strip()) for side in ("a", "b")] + bindings[1:]
    common_subjects = _subjects(substantive)
    common_modes = _markers(substantive)
    facets = []
    for index, (text, topic) in enumerate(bindings, 1):
        subjects = _subjects(text) or (common_subjects if len(common_subjects) == 1 else frozenset())
        modes = _markers(text) or (common_modes if len(common_modes) == 1 else frozenset())
        limit_target = evidence_limit_target(text)
        asks_for_other_evidence = bool(_NEXT_EVIDENCE_ASK.fullmatch(text))
        if asks_for_other_evidence and not limit_target and facets and facets[-1].limit_target:
            limit_target = facets[-1].limit_target
        kind = "evidence_limit" if limit_target else _kind(text)
        devices, labels = _devices(text), frozenset(_network_labels(text))
        phases = _phases(text)
        repeated = repeated_readback_field(text) if not limit_target and not (devices or labels) else ""
        if repeated and facets and facets[-1].kind == "readback" and len(facets[-1].devices) >= 2:
            previous = facets[-1]
            kind, devices, labels, subjects, modes, phases = (
                "readback", previous.devices, previous.labels, previous.subjects, previous.modes, previous.phases)
        else:
            repeated = ""
        if (not phases and facets and _RELATIVE_STAGE.match(text) and len(facets[-1].phases) == 1):
            (action, when), = facets[-1].phases
            if when == "before" and _ASK_FRAME.search(text):
                phases = frozenset({(action, "after")})
        axes = _observation_axes(text) if phases and _observation_owner(text) else frozenset()
        if (kind in {"concept", "mechanism"} and phases and _devices(text) and _ASK_FRAME.search(text)
                and (_OBSERVATION_ROLE.search(text) or _OBSERVATION_STATE.search(text) or axes)):
            kind = "readback"
        if kind == "readback" and not axes and (natural := natural_question_role(text)) and natural.kind == "readback":
            axes = natural.axes
        record_context = _OBSERVATION_CONTEXT_PREFIX.match(text) if kind == "readback" else None
        field_words = text[record_context.end():] if record_context else text
        named_artifact = _NAMED_ARTIFACT.search(record_context[0]) if record_context else None
        label = _NAMED_READBACK_FIELD.search(field_words)
        explicit_label = repeated or (label["field"] if label else "")
        if (kind == "concept" and explicit_label and facets and _ELLIPTIC_READBACK.search(text)
                and facets[-1].kind == "readback" and compact_text(explicit_label) == compact_text(facets[-1].readback_label)):
            kind = "readback"
        if (not limit_target and _FIELD_REFERENT.match(text) and facets
                and (earlier := facets[-1]).kind == "readback" and len(earlier.fields) == 1
                and not (_devices(text) or any(_network_labels(text)))):
            facets.append(_Facet(index, text, "output_interpretation", "", earlier.subjects, earlier.labels,
                                 earlier.devices, earlier.directions, frozenset(), frozenset(), earlier.phases,
                                 earlier.modes, earlier.fields, frozenset(), "", earlier.figures, earlier.observation_owner,
                                 earlier.readback_label))
            continue
        if kind != "readback":
            explicit_label = ""
        facets.append(_Facet(index, text, kind, topic, subjects, labels,
                             devices, _directions(text), _roles(text), _owners(text), phases, modes,
                             frozenset({compact_text(explicit_label)}) if explicit_label else _fields(field_words),
                             frozenset(passage_concepts(text)), limit_target, _figures(text),
                             _observation_owner(text) if kind == "readback" else "", explicit_label, axes,
                             asks_for_other_evidence and bool(limit_target),
                             output_field_names(text) if kind == "readback" and not explicit_label else frozenset(),
                             adjustment["object"] if (adjustment := _QUALIFIED_ADJUSTMENT.search(text)) else "",
                             named_artifact[1] if named_artifact else ""))
    if len(facets) == 1 and not case and facets[0].kind in {"concept", "mechanism"}:
        if request := principle_request(facets[0].text):
            kind, topic = request
            facets[0] = replace(facets[0], kind=kind, topic=topic)
    scoped = case or any(f.kind in {"configuration", "readback", "diagram"} for f in facets)
    same_experiment = scoped and not _independent_cases(terms, facets)
    return _Plan(tuple(facets), same_experiment, same_experiment and _compares_phases(facets))


def _independent_principles(terms, plan):
    if not plan or plan.same_experiment or any(facet.topic or facet.kind not in {"concept", "mechanism"} for facet in plan.facets):
        return None
    requests = multiple_principle_requests(terms, tuple(facet.text for facet in plan.facets))
    if not requests:
        return None
    return replace(plan, facets=tuple(replace(facet, kind=kind, topic=topic)
                                      for facet, (kind, topic) in zip(plan.facets, requests, strict=True)))


def _heading_paths(reading):
    return heading_paths(reading["sections"])


def _case_root_lines(reading):
    parts = defaultdict(set)
    for section in reading["sections"]:
        if match := _CASE_COMPONENT.match(section["title"]):
            parts[match["number"].replace("．", ".").rsplit(".", 1)[0]].add(match["part"])
    cases = {number for number, labels in parts.items() if labels & {"介绍", "目的", "目标"} and labels & {"任务", "规划", "步骤"}}
    return frozenset(section["line"] for section in reading["sections"]
                     if (number := _ORIGINAL_NUMBER.match(section["title"])) and number[1].replace("．", ".") in cases)


def _heading_key(hit, row):
    return f"{hit['document_id']}@{hit['document_version']}:{row[2]}"


def _mentioned_source_titles(query, hit):
    if not query or _SCOPE_EXCLUSION.search(query):
        return frozenset()
    query = compact_text(query)
    names = set()
    for title in (hit.get("title", ""), *hit.get("source_heading_path", ())):
        if _SOURCE_PHASE.match(title):
            continue
        name = _TITLE_NUMBERING.sub("", title).strip()
        if name.endswith("实验"):
            name = name.removesuffix("实验").rstrip()
        term = compact_text(name)
        if 5 <= len(term) <= 40 and not _GENERIC_SCOPE.fullmatch(name) and term in query:
            names.add(term)
    return frozenset(names)


def _source_metadata(hit, path, case_roots=()):
    context = {"source_heading_path": tuple(row[1] for row in path)}
    if path:
        context["source_heading_key"] = _heading_key(hit, path[-1])
    step = _current_source_step(path)
    experiment = next((row for row in reversed(path) if row[2] in case_roots or _SCOPE.match(row[1]) or (
        (match := _NUMBERED_CASE.match(row[1])) and not _CASE_COMPONENT.match(row[1])
        and not _GENERIC_SCOPE.fullmatch(match["title"]))), None)
    if experiment:
        context["source_experiment_key"] = _heading_key(hit, experiment)
    if step:
        if (phase := _SOURCE_PHASE.match(step[1])) and not _GENERIC_SCOPE.fullmatch(phase["title"]):
            context["source_phase_key"] = _heading_key(hit, step)
        else:
            context["source_step_boundary_key"] = _heading_key(hit, step)
    return context


def _current_source_step(path):
    return next((row for row in reversed(path) if _SOURCE_PHASE.match(row[1]) or source_step_boundary(row[1])), None)


def _source_step_phases(path):
    step = _current_source_step(path)
    return _phases(step[1]) if step else frozenset()


def _adjacent_caption(kind, text, other, *, preceding):
    other = other.strip("* \t")
    if kind in {"fence", "table"}:
        if kind == "fence" and not preceding and _OUTPUT_EXPLANATION.match(other) and _FIELD_RELATION.search(other):
            return True
        if kind == "fence" and not preceding and _record_note_matches(text, other):
            return True
        return bool((_AFTER_CAPTION if preceding else _BEFORE_CAPTION).search(other))
    if not preceding and linked_observation_note(text, other):
        return True
    figures = _figures(text)
    nearby = _figures(other)
    return (len(figures) == 1 and not (_OTHER_PAGE_FIGURE.search(text) or _OTHER_PAGE_FIGURE.search(other))
            and (nearby == figures if nearby else not preceding and bool(_FIGURE_EXPLANATION.match(other))))


def _record_note_matches(fence, note):
    if not _AFTER_RECORD_NOTE.match(note):
        return False
    units = reading_units(fence)
    if len(units) != 1 or units[0].kind != "fence":
        return False
    records = [record for record in units[0].commands if record.kind == "observation" and record.output]
    if len(records) != 1 or {records[0].owner} != _devices(note):
        return False
    labels = frozenset(_network_labels(note))
    return bool(labels and labels <= frozenset(_network_labels(fence[slice(*records[0].output)])))


def _units(body, parent, page_line):
    path = list(parent)
    first_line = body.splitlines()[0]
    units = []
    for source in reading_units(body):
        kind = "paragraph" if source.kind == "list" else source.kind
        start, end = source.start, source.end
        text = body[start:end].strip()
        if kind == "heading":
            match = _HEADING_MARK.fullmatch(text)
            if match and not _PHYSICAL_HEADING.match(match[2]):
                level = len(match[1])
                path = append_heading(path, level, match[2], page_line + body[:start].count("\n"))
            continue
        if kind == "paragraph" and (title := authored_step_title(text)):
            path = append_heading(path, 4, title, page_line + body[:start].count("\n"))
        if first_line != text:
            location = tuple(path)
            caption = ""
            if units and kind in {"fence", "table", "paragraph"}:
                previous_kind, _, previous_end, previous_text, previous_path = units[-1]
                if previous_kind.removeprefix("planned_") == "paragraph" and previous_path == location and not body[previous_end:start].strip():
                    caption = previous_text
            if kind in {"fence", "table", "paragraph"} and planned_output(location, caption):
                kind = "planned_" + kind
            units.append((kind, start, end, text, location))
    for kind, start, end, text, path in units:
        yield kind, text, path, None

    for index, (kind, start, end, text, path) in enumerate(units):
        if kind not in {"fence", "table", "paragraph"}:
            continue
        neighbors = []
        if index:
            before = units[index - 1]
            if _adjacent_caption(kind, text, before[3], preceding=True) and not body[before[2]:start].strip():
                neighbors.append((before, before[1], end))
        if index + 1 < len(units):
            after = units[index + 1]
            if _adjacent_caption(kind, text, after[3], preceding=False) and not body[end:after[1]].strip():
                beginning, extent = start, after[2]
                if kind == "fence" and index >= 2 and _record_note_matches(text, after[3]):
                    action, cue = units[index - 2:index]
                    if (action[0] == cue[0] == "paragraph" and action[4] == cue[4] == path
                            and len(action[3]) + len(cue[3]) <= 260 and _RECORDED_CHANGE.search(action[3])
                            and _CHECK_AGAIN.match(cue[3]) and _devices(cue[3]) == _devices(after[3])
                            and not body[action[2]:cue[1]].strip() and not body[cue[2]:start].strip()):
                        beginning = action[1]
                if kind == "fence" and index + 2 < len(units) and not _SENTENCE_END.search(after[3]):
                    continuation = units[index + 2]
                    if (continuation[0] == "paragraph" and continuation[4] == path and len(continuation[3]) <= 240
                            and _CONTINUED_WORD.match(continuation[3]) and not body[extent:continuation[1]].strip()):
                        extent = continuation[2]
                neighbors.append((after, beginning, extent))
        for neighbor, span_start, span_end in neighbors:
            if neighbor[0] == "paragraph" and neighbor[4] == path and 8 <= len(neighbor[3]) <= 320:
                yield kind, body[span_start:span_end].strip(), path, text


def _excerpt_location(original, excerpt, units):
    exact = {location for _, unit, location, _ in units if _source_excerpt(excerpt, unit)}
    if exact:
        return next(iter(exact)) if len(exact) == 1 else ()
    # A normal search result can carry the physical heading and several source
    # blocks. Recover a scope only while all touched original units agree.
    start = original.find(excerpt)
    if start < 0 or original.find(excerpt, start + 1) >= 0:
        return ()
    end = start + len(excerpt)
    touched = set()
    for _, text, path, core in units:
        if core:
            continue
        offset = original.find(text)
        if offset < 0 or original.find(text, offset + 1) >= 0:
            if _source_excerpt(text, excerpt):
                return ()
            continue
        if offset < end and offset + len(text) > start:
            touched.add(path)
    return next(iter(touched)) if len(touched) == 1 else ()


def _evidence_type(kind, text, requested):
    out, _, values, visual, interpretation = _passage_role(text)
    if out or _NAVIGATION.match(text):
        return False
    if requested == "readback":
        if kind == "fence":
            rows = [line for line in text.splitlines()[1:-1] if line.strip()]
            return bool(len(rows) >= 2 and _READ_COMMAND.match(rows[0])
                        and not any(_PROMPT.match(line) for line in rows[1:])
                        and any(_OBSERVED_VALUE.search(line) for line in rows[1:]))
        if kind == "table":
            return values or bool(_OBSERVED_VALUE.search(text.splitlines()[-1]))
        return any(not (_LOOK_ONLY.search(sentence) or _EXPECTED_ONLY.search(sentence)) and (
            (_OBSERVED.search(sentence) and _OBSERVED_VALUE.search(sentence)) or (
                _ACTUAL_PROSE.search(sentence) and _PROSE_ASSIGNMENT.search(sentence)
                and (_ROLE_VALUE.search(sentence) or _STATE_VALUE.search(sentence) or _OBSERVED_VALUE.search(sentence))))
                   for sentence in re.split(r"[。；\n]", text))
    if requested == "configuration":
        return bool(_CONFIG_PROOF.search(text) if kind == "fence" else re.search(r"(?:配置|设置|启用|绑定).{2,48}(?:`|为|到|向|使用|在)", text))
    if requested == "diagram":
        return kind != "fence" and bool(visual and (_ACTION.search(text) or (values and _DIAGRAM.search(text))))
    if kind == "fence":
        return False
    if requested == "mechanism":
        return bool(_ACTION.search(text) and (_DEFINITION.search(text) or _roles(text) or _directions(text)
                                             or re.search(r"当|若|如果|由于|随后|再|从.{1,18}到|必须", text)))
    return bool(interpretation and _ACTION.search(text) or _DEFINITION.search(text))


def _topic_in_text(topic, text):
    return compact_text(topic) in compact_text(text) if topic else True


def _title_scopes_action(facet, text):
    lead = _MECHANISM_TITLE.match(text)
    destination = _ROLE_DESTINATION.search(facet.text)
    if not facet.topic or not lead or not destination or _TITLE_COMPARISON.search(lead[1]):
        return False
    if not compact_text(lead[1]).startswith(compact_text(facet.topic)):
        return False
    if facet.topic.isascii() and not re.search(rf"(?<![a-z0-9_-]){re.escape(facet.topic)}(?![a-z0-9_-])", lead[1], re.I):
        return False
    role = destination["role"]
    role_names = r"(?:服务端|服务器)" if role in {"服务端", "服务器"} else re.escape(role)
    relation = re.compile(rf"(?:向|到|至|发给|请求)\s*(?:集中)?(?:的)?{role_names}")
    return any(_ACTION.search(clause) and relation.search(clause) and not _EXPECTED_ONLY.search(clause)
               for clause in re.split(r"[。；\n]", text[lead.end():]))


def _field_explanation(facet, text):
    if facet.topic or not facet.fields or not facet.subjects or not _FIELD_EXPLANATION.search(facet.text):
        return False
    fields = [re.escape(term.replace("-", "_")) for term in facet.fields]
    for clause in re.split(r"[。；\n]", text):
        if _CAUSAL_PROOF.search(clause) and not _EXPECTED_ONLY.search(clause):
            lexemes = compact_text(clause).replace("-", "_")
            if all(re.search(rf"(?<![a-z0-9_]){field}(?![a-z0-9_])", lexemes) for field in fields):
                return True
    return False


def _mechanism_witness(facet, kind, text):
    return kind == "paragraph" and facet.kind == "mechanism" and not _NAVIGATION.match(text) and (
        _title_scopes_action(facet, text) or _field_explanation(facet, text))


def _matched_fields(expected, text):
    matched = expected & _fields(text)
    for field in expected - matched:
        if "_" in field or "-" in field:
            spelling = r"[-_]".join(map(re.escape, re.split(r"[-_]", field)))
            if re.search(rf"(?<![A-Za-z0-9_-]){spelling}(?![A-Za-z0-9_-])", text, re.I):
                matched |= {field}
    return matched


def _requested_fields(facet, text):
    if facet.readback_label:
        words = r"[ \t]+".join(map(re.escape, facet.readback_label.replace("-", "_").split()))
        return (facet.fields if re.search(rf"(?<![A-Za-z0-9_/]){words}(?![A-Za-z0-9_/])", text.replace("-", "_"), re.I)
                else frozenset())
    return _matched_fields(facet.fields, text)


def _record_labels(rows):
    headings = [row for row in rows if _OUTPUT_RECORD_LABEL.match(row)]
    if len(headings) != 1:
        return frozenset()
    identifiers = frozenset(_network_labels(headings[0]))
    return identifiers if len(identifiers) == 1 else frozenset()


def _output_interpretation(facet, kind, text, core):
    if (facet.kind not in {"output_interpretation", "mechanism"} or kind != "fence" or not core
            or not _evidence_type(kind, core, "readback")):
        return False
    rows = [row.strip() for row in core.splitlines()[1:-1] if row.strip()]
    owner = _COMMAND_DEVICE.match(rows[0])
    owners = {facet.observation_owner} if facet.observation_owner else facet.devices
    if owners and (not owner or owners != {(owner[1] or owner[2]).casefold()}):
        return False
    explanation = text.partition(core)[2].lstrip("* \r\n\t")
    if not _OUTPUT_EXPLANATION.match(explanation) or _EXPECTED_ONLY.search(explanation):
        return False
    if facet.kind == "mechanism" and not _field_explanation(facet, explanation):
        return False
    record_labels = _record_labels(rows[1:])
    return (any(_FIELD_RELATION.search(clause) and _requested_fields(facet, clause) == facet.fields
                for clause in re.split(r"[。；\n]", explanation))
            and any(_readback_value(facet, row) and facet.labels <= record_labels | frozenset(_network_labels(row))
                    and facet.devices - owners <= _devices(row) for row in rows[1:]))


def _readback_value(facet, row):
    if _OBSERVATION_ROLE.search(facet.text):
        if not _ROLE_VALUE.search(row):
            return False
    elif _OBSERVATION_STATE.search(facet.text):
        if not _STATE_VALUE.search(row):
            return False
    elif not facet.fields:
        return False
    if facet.fields:
        columns = re.split(r"\s*[:：]\s*| {2,}", row.strip(), maxsplit=1)
        if len(columns) != 2 and len(facet.fields) == 1 and any("_" in field or "-" in field for field in facet.fields):
            columns = row.strip().split(maxsplit=1)
        if len(columns) != 2 or not columns[1] or _requested_fields(facet, columns[0]) != facet.fields:
            return False
        if facet.readback_label and compact_text(columns[0]).replace("-", "_") != compact_text(facet.readback_label).replace("-", "_"):
            return False
    return True


def _observed_column_row(facet, rows, peers):
    if len(rows) < 2:
        return None
    columns = _COLUMN_SPLIT.split(rows[0].strip())
    if any(_NETWORK_LABEL.fullmatch(column) for column in columns):
        return None
    headers = tuple(map(compact_text, columns))
    names = set(headers)
    field_columns = tuple(output_field_names(column) for column in columns)
    if len(headers) < 2 or not (names & (_ROLE_COLUMNS | _STATE_COLUMNS | facet.fields)
                               or any(facet.output_fields & fields for fields in field_columns)):
        return None
    if (_MULTIPLE_RECORDS.search(facet.text) or not (facet.labels or peers)
            or len(names) != len(headers) or not facet.fields <= names):
        return False
    required = []
    for ask, labels, values in ((_OBSERVATION_ROLE, _ROLE_COLUMNS, _ROLE_VALUE),
                                (_OBSERVATION_STATE, _STATE_COLUMNS, _STATE_VALUE)):
        if ask.search(facet.text):
            columns = [index for index, name in enumerate(headers) if name in labels]
            if len(columns) != 1:
                return False
            required.append((columns[0], values))
    for field in facet.output_fields:
        positions = [index for index, fields in enumerate(field_columns) if field in fields]
        if len(positions) != 1:
            return False
        required.append((positions[0], re.compile(r"\S.*")))
    if not (required or facet.fields):
        return False
    separated = len(facet.labels) >= 2 and bool(_SEPARATE_ROWS.search(facet.text))
    identities = [index for index, label in enumerate(headers) if label in _RECORD_ROW_KEY] if separated else []
    if separated and len(identities) != 1:
        return False
    by_label = defaultdict(list)
    matches = []
    for row in rows[1:]:
        if re.fullmatch(r"[-=\s]+", row):
            continue
        cells = _COLUMN_SPLIT.split(row.strip())
        if len(cells) != len(headers) or _EXPECTED_ONLY.search(row):
            return False
        if not peers <= _devices(row):
            continue
        if separated:
            key = frozenset(_network_labels(cells[identities[0]]))
            if len(key) == 1 and (label := next(iter(key))) in facet.labels:
                by_label[label].append(cells)
        elif facet.labels <= frozenset(_network_labels(row)):
            matches.append(cells)
    if separated:
        return all(len(by_label[label]) == 1 and all(pattern.fullmatch(by_label[label][0][index]) for index, pattern in required)
                   for label in facet.labels)
    return len(matches) == 1 and all(pattern.fullmatch(matches[0][index]) is not None for index, pattern in required)


def _record_witness(facet, rows, peers):
    if (table_witness := _observed_column_row(facet, rows, peers)) is not None:
        return table_witness
    record_labels = _record_labels(rows)
    if facet.output_fields:
        return bool(_keyed_field_values(facet, rows, peers, record_labels))
    matched = [row for row in rows if not _EXPECTED_ONLY.search(row) and _readback_value(facet, row)
               and peers <= _devices(row) and facet.labels <= record_labels | frozenset(_network_labels(row))]
    if facet.fields and (count := _FIELD_COUNT.search(facet.text)):
        return len(matched) == len(set(matched)) == int(count[1].translate(_COUNT_DIGITS))
    return len(matched) == 1


def _keyed_field_values(facet, rows, peers, record_labels):
    values = defaultdict(list)
    for row in rows:
        key, separator, value = row.partition(":")
        if (separator and value.strip() and not _EXPECTED_ONLY.search(row) and peers <= _devices(row)
                and facet.labels <= record_labels | frozenset(_network_labels(row))):
            for field in facet.output_fields & output_field_names(key):
                values[field].append(" ".join(value.split()))
    return (tuple((field, values[field][0]) for field in sorted(facet.output_fields))
            if all(len(values.get(field, ())) == 1 for field in facet.output_fields) else ())


def _reported_phases(text):
    phases = _phases(text, reported=True)
    if not _EXPECTED_ONLY.search(text) and _SUMMARY_CHANGE.search(text):
        phases |= frozenset((match["action"], "after") for match in _SUMMARY_APPLIED.finditer(text))
    return phases


def _has_original_prefix(text):
    for match in _SUMMARY_PREFIX_VALUE.finditer(text):
        try:
            ip_network(match[0], strict=False)
        except ValueError:
            continue
        return True
    return False


def _summary_witness(facet, text):
    if (not facet.observation_axes or not facet.phases or not facet.observation_owner
            or not _SUMMARY_ARTIFACT.search(text) or _EXPECTED_ONLY.search(text)
            or not facet.phases <= _reported_phases(text)):
        return False
    owner = facet.observation_owner
    axes = set()
    for clause in re.split(r"[。；\n]", text):
        devices = list(_DEVICES.finditer(clause))
        for index, marker in enumerate(devices):
            if marker[0].casefold() != owner:
                continue
            next_device = devices[index + 1].start() if index + 1 < len(devices) else len(clause)
            own = clause[marker.end():next_device]
            if _SUMMARY_ARTIFACT.search(own) and (_SUMMARY_AMOUNT.search(own) or _SUMMARY_CHANGE.search(own)):
                axes.add("entries")
            if _SUMMARY_ROUTE_ASSERTION.search(own) and _has_original_prefix(own):
                axes.add("prefixes")
            # An explicit merged prefix followed immediately by this measured
            # change is an assertion about the result, not the input plan.
            if _SUMMARY_ARTIFACT.search(own) and _SUMMARY_CHANGE.search(own):
                prefix = re.split(r"[,，]", clause[:marker.start()].rstrip().rstrip(",，"))[-1]
                if _SUMMARY_ROUTE_MERGED.search(prefix) and _has_original_prefix(prefix):
                    axes.add("prefixes")
        if any(owner in _devices(match["owners"]) for match in _SUMMARY_SHARED_AMOUNT.finditer(clause)):
            axes.add("entries")
    return facet.observation_axes <= axes


def _completed_phases(text):
    return frozenset((event, "after" if when == "后" else "before") for event, when in completed_readout_phases(text))


def _matching_fence_outputs(facet, text, owners, peers, phase_context):
    units = reading_units(text)
    if len(units) != 1 or units[0].kind != "fence":
        return []
    matched = []
    for command in units[0].commands:
        if not command.output or owners != {command.owner}:
            continue
        if facet.artifact_label and not re.search(rf"(?<![A-Za-z0-9_-]){re.escape(facet.artifact_label)}(?![A-Za-z0-9_-])", command.command, re.I):
            continue
        if command.kind != "observation" and not (command.kind == "configuration_read" and _CONFIGURATION_VALUE.search(facet.text)):
            continue
        start, end = command.output
        output = text[start:end]
        if not facet.phases <= phase_context | _phases(output) | _completed_phases(output):
            continue
        rows = [row.strip() for row in output.splitlines() if row.strip()]
        if _record_witness(facet, rows, peers):
            matched.append(rows)
    return matched


def _structure_for_observer(facet, text, path, core):
    owners = {facet.observation_owner} if facet.observation_owner else facet.devices
    peers = facet.devices - owners
    actual = core or text
    phases = _source_step_phases(path) | (_phases(text) - _phases(actual))
    outputs = _matching_fence_outputs(facet, actual, owners, peers, phases)
    if len(outputs) != 1:
        return False, ()
    rows, = outputs
    return True, _keyed_field_values(facet, rows, peers, _record_labels(rows)) if facet.output_fields else ()


def _has_observation_witness(facet, kind, text, path, core):
    if facet.kind != "readback" or planned_unit(kind):
        return False
    actual = core or text
    phase_context = _source_step_phases(path)
    if facet.directions:
        for clause in re.split(r"[。；\n]", actual):
            if (facet.directions <= _observed_directions(clause) and facet.phases <= (_phases(clause) | phase_context)
                    and facet.labels <= frozenset(_network_labels(clause))):
                if not (facet.fields or _OBSERVATION_ROLE.search(facet.text) or _OBSERVATION_STATE.search(facet.text)):
                    return True
                if _readback_value(facet, clause):
                    return True
        return False
    if kind == "paragraph" and observed_prose_witness(facet, actual, path):
        return True
    if facet.output_fields and kind != "fence":
        return False
    if kind == "paragraph" and reported_readback_witness(facet, text):
        return True
    if not facet.devices or not _OBSERVATION_ASK.search(facet.text):
        return False
    owners = {facet.observation_owner} if facet.observation_owner else facet.devices
    peers = facet.devices - owners
    if kind == "fence":
        return _structure_for_observer(facet, text, path, core)[0]
    if kind != "paragraph":
        # A table without its read-only prompt can also be an address plan.
        return False
    if _summary_witness(facet, text):
        return True
    for clause in re.split(r"[。；\n]", actual):
        if (_ACTUAL_PROSE.search(clause) and not _EXPECTED_ONLY.search(clause) and facet.devices == _devices(clause)
                and (not peers or _observation_owner(clause) == facet.observation_owner)
                and facet.labels <= frozenset(_network_labels(clause))
                and facet.phases <= (_phases(clause) | phase_context) and _readback_value(facet, clause)):
            return True
    return False


def _limit_witnesses(facet, text):
    witnesses = evidence_limit_witnesses(facet.limit_target, text)
    if facet.asks_for_other_evidence:
        return tuple(witness for witness in witnesses if witness in _OTHER_EVIDENCE)
    return witnesses


def _linked_limit_witness(facet, kind, text, core):
    if not core or not facet.limit_target:
        return False
    note = text.partition(core)[2].strip()
    attached = (_record_note_matches(core, note) if kind == "fence"
                else kind == "paragraph" and linked_observation_note(core, note))
    return attached and bool(_limit_witnesses(facet, note))


def _grade(facet, kind, text, path, core=None):
    if planned_unit(kind):
        if facet.kind in {"readback", "output_interpretation"}:
            return None
        kind = kind.removeprefix("planned_")
    if facet.kind in _PRINCIPLE_KINDS:
        proof = kind == "paragraph" and direct_principle(text, facet.kind, facet.topic) == text
        return (0, 0, 0, 0) if proof else None
    if facet.kind == "diagram" and (marks := visual_marks(facet.text)) and not has_requested_visual_marks(marks, text):
        return None
    linked_limit = _linked_limit_witness(facet, kind, text, core)
    linked = _output_interpretation(facet, kind, text, core) or linked_limit
    if core and not linked and facet.kind not in {"readback", "diagram", "output_interpretation"}:
        return None
    mechanism_witness = _mechanism_witness(facet, kind, text)
    observed_summary = kind == "paragraph" and facet.kind == "readback" and _summary_witness(facet, text)
    native_claim = kind == "paragraph" and (reported_readback_witness(facet, text) or observed_prose_witness(facet, text, path))
    explained = kind == "paragraph" and not _NAVIGATION.match(text) and original_explanation_witness(facet, text, path)
    if facet.kind == "output_interpretation" and not linked:
        return None
    if facet.limit_target:
        if not linked_limit and (kind != "paragraph" or _NAVIGATION.match(text) or not _limit_witnesses(facet, text)):
            return None
    elif not (mechanism_witness or linked or observed_summary or native_claim or explained) and not _evidence_type(kind, core if core and facet.kind == "readback" else text, facet.kind):
        if kind != "fence" or not _has_observation_witness(facet, kind, text, path, core):
            return None
    context = "\n".join(row[1] for row in path[-2:]) + "\n" + text
    if not _topic_in_text(facet.topic, text) or not facet.subjects <= _subjects(context) or not facet.figures <= _figures(text):
        return None
    if facet.phase_object and compact_text(facet.phase_object) not in compact_text(context):
        return None
    if not facet.labels <= frozenset(_network_labels(text)) or not facet.devices <= _devices(text):
        return None
    if not facet.directions <= _directions(text) or not facet.roles <= _roles(text) or not facet.owners <= _owners(text):
        return None
    modes, stages = _markers(context), _phases(context) | (_reported_phases(text) if observed_summary else frozenset())
    if kind == "fence":
        stages |= _completed_phases(core or text)
    if facet.modes and (not facet.modes <= modes or modes - facet.modes):
        # An ordinary contrast can state both modes in one complete paragraph.
        # Use just the actual sentence that binds this arm, keeping the source intact.
        same_arm = (sentence for sentence in re.split(r"[。；\n]", text) if _markers(sentence) == facet.modes)
        if not facet.topic or not any(_topic_in_text(facet.topic, sentence) and _ACTION.search(sentence) for sentence in same_arm):
            return None
    if not facet.phases <= stages or any(action == target and when != wanted for action, when in stages for target, wanted in facet.phases):
        return None
    field_hits = _requested_fields(facet, text)
    if field_hits != facet.fields and not (mechanism_witness and _field_explanation(facet, text)):
        return None
    if facet.limit_target or linked or observed_summary or native_claim or explained:
        return (len(facet.directions), len(facet.owners), len(field_hits), 0)
    if facet.topic and not mechanism_witness and not any(_topic_in_text(facet.topic, clause) and _evidence_type(kind, clause, facet.kind)
                               for clause in re.split(r"[。；\n]", text) if clause.strip()):
        return None
    concept_hits = facet.concepts & (passage_concepts(text) | output_field_names(text))
    if facet.concepts and not concept_hits:
        return None
    shared = set(_query_tokens(passage_query(facet.text))) & set(_query_tokens(text))
    if len(shared) < (1 if facet.topic or facet.subjects else 2) and not (facet.directions or field_hits or concept_hits):
        return None
    return (len(facet.directions), len(facet.owners), len(concept_hits) + len(field_hits), len(shared))


def _principle_units(units, facets):
    for kind, text, location, core in units:
        if kind != "paragraph" or core or _NAVIGATION.match(text):
            continue
        statements = dict.fromkeys(direct_principle(text, facet.kind, facet.topic, separate_heading=len(facets) > 1)
                                   for facet in facets)
        for statement in statements:
            if statement and not (_devices(statement) or any(_network_labels(statement))):
                yield kind, statement, location, None


class _Passages:
    def __init__(self, edition, *, reusable=None):
        self.edition = edition
        self.documents = reusable.documents if reusable else {}
        self.case_roots = reusable.case_roots if reusable else {}
        self.pages_seen = set()
        self.units = reusable.units if reusable else {}
        self.pool = {}
        self.by_facet = defaultdict(list)
        self.ambiguous = set()
        self.scoped_claims = {}
        self.original_scope_locations = ()

    def add(self, hits, plan):
        reported_facets = tuple(facet for facet in plan.facets if facet.kind == "readback")
        for rank, hit in enumerate(hits, 1):
            ref = FacetEvidenceRef.from_hit(hit)
            if ref is None or ref.edition_version != self.edition.version:
                continue
            key = ref.document_id, ref.document_version
            if key not in self.documents:
                try:
                    reading = self.edition.read(*key, include_original_status=False)
                    self.documents[key] = (_page_texts(reading), _heading_paths(reading),
                                           {section["id"]: section["line"] for section in reading["sections"]})
                    self.case_roots[key] = _case_root_lines(reading)
                except (DocumentReadError, KeyError, OSError, ValueError):
                    self.documents[key] = ({}, {}, {})
            pages, contexts, lines = self.documents[key]
            mapped = pages.get(ref.page)
            if not mapped or mapped[0] != ref.section_id:
                continue
            excerpt = _source_excerpt(hit["text"], mapped[1])
            if not excerpt:
                continue
            page_key = key, ref.page
            if page_key not in self.units:
                self.units[page_key] = tuple(_units(mapped[1], contexts.get(ref.section_id, ()), lines[ref.section_id]))
            units = self.units[page_key]
            location = _excerpt_location(mapped[1], excerpt, units)
            case_roots = self.case_roots.get(key, ())
            self.pool.setdefault(ref, {**hit, **_source_metadata(hit, location, case_roots), "facet_ids": ()})
            if not plan.facets or page_key in self.pages_seen:
                continue
            self.pages_seen.add(page_key)
            if plan.facets[0].kind in _PRINCIPLE_KINDS:
                units = _principle_units(units, plan.facets)
            for kind, text, location, core in units:
                if len(text) > 2450:
                    continue
                if (len(text) < 18 and plan.facets[0].kind not in _PRINCIPLE_KINDS
                        and (kind != "paragraph" or not any(_limit_witnesses(facet, text)
                             or original_explanation_witness(facet, text, location, require_named_case=True) for facet in plan.facets))):
                    continue
                linked_output = bool(core and any(_output_interpretation(facet, kind, text, core)
                                                  or _linked_limit_witness(facet, kind, text, core) for facet in plan.facets))
                matches = [(facet.number, grade) for facet in plan.facets
                           if (grade := _grade(facet, kind, text, location, core)) is not None
                           and (not core or linked_output or _grade(facet, kind, core, location) is None)
                           and (len(text) <= 1080 or _has_observation_witness(facet, kind, text, location, core))]
                if not matches:
                    continue
                candidate = {**hit, **_source_metadata(hit, location, case_roots), "text": text,
                             "facet_ids": tuple(number for number, _ in matches)}
                witnesses = tuple((facet.number, witness) for facet in plan.facets
                                  if facet.number in candidate["facet_ids"] and facet.limit_target
                                  for witness in _limit_witnesses(facet, text))
                if witnesses:
                    candidate["facet_witnesses"] = witnesses
                explicitly_requested = {facet.number for facet in plan.facets if facet.asks_for_other_evidence}
                linked_limits = {facet.number for facet in plan.facets if _linked_limit_witness(facet, kind, text, core)}
                limit_ids = {number for number, witness in witnesses
                             if witness in _DIRECT_LIMIT or number in explicitly_requested or number in linked_limits}
                if (witnesses and kind == "paragraph" and not core and len(reported_facets) >= 2
                        and all(facet.number in candidate["facet_ids"] and reported_readback_witness(facet, text)
                                for facet in reported_facets)):
                    limit_ids.update(number for number, witness in witnesses if witness == "required_observation")
                explanation = tuple(facet.number for facet in plan.facets if facet.number in candidate["facet_ids"]
                                    and (facet.number in limit_ids or _mechanism_witness(facet, kind, text)
                                         or _output_interpretation(facet, kind, text, core)
                                         or facet.kind == "diagram" and kind == "paragraph" and observed_prose_witness(facet, text, location)
                                         or kind == "paragraph" and original_explanation_witness(facet, text, location, require_named_case=True)
                                         or facet.kind in _PRINCIPLE_KINDS))
                if explanation:
                    candidate["facet_explanation_ids"] = explanation
                observation_witnesses = tuple(facet.number for facet in plan.facets if facet.number in candidate["facet_ids"]
                                              and _has_observation_witness(facet, kind, text, location, core))
                if observation_witnesses:
                    candidate["facet_readback_ids"] = observation_witnesses
                if kind == "fence":
                    values = tuple((facet.number, datum) for facet in plan.facets
                                   if facet.output_fields and facet.number in observation_witnesses
                                   and (datum := _structure_for_observer(facet, text, location, core)[1]))
                    if values:
                        candidate["facet_record_values"] = values
                if plan.compare_phases:
                    explicit_stages = (_reported_phases(text) if kind == "paragraph" else _phases(text)) | _source_step_phases(location)
                    if kind == "fence":
                        explicit_stages |= _completed_phases(core or text)
                    candidate["facet_phase_ids"] = tuple(facet.number for facet in plan.facets
                                                         if facet.number in candidate["facet_ids"] and facet.phases <= explicit_stages)
                passage_ref = FacetEvidenceRef.from_hit(candidate)
                if passage_ref is None:
                    continue
                self.scoped_claims[(self._scope(candidate, passage_ref), passage_ref)] = candidate
                old = self.pool.get(passage_ref)
                if old and old["facet_ids"] and old.get("source_heading_key") != candidate.get("source_heading_key"):
                    self.ambiguous.add(passage_ref)
                    self.pool[passage_ref] = {**candidate, "facet_ids": ()}
                    self.pool[passage_ref].pop("source_experiment_key", None)
                    self.pool[passage_ref].pop("source_phase_key", None)
                    continue
                if passage_ref in self.ambiguous:
                    continue
                self.pool[passage_ref] = candidate
                for number, score in matches:
                    self.by_facet[number].append(((*score, -rank), passage_ref))

    def _feasible_groups(self, plan):
        claims = {number: [(score, ref) for score, ref in matches if ref not in self.ambiguous]
                  for number, matches in self.by_facet.items()}
        if not plan.same_experiment or len(plan.facets) == 1:
            return [claims]
        groups = defaultdict(lambda: defaultdict(list))
        for number, matches in claims.items():
            for score, ref in matches:
                source = self.pool[ref]
                if plan.compare_phases and number not in source.get("facet_phase_ids", ()):
                    continue
                # Two separately numbered pages only share a case by an explicit
                # original heading, never by name overlap, book or page distance.
                group = self._claim_scope(plan, number, source, ref)
                groups[group][number].append((score, ref))
        return list(groups.values())

    @staticmethod
    def _scope(source, ref):
        if phase := source.get("source_phase_key"):
            return "phase", phase
        if experiment := source.get("source_experiment_key"):
            return "experiment", experiment
        return "page", ref.document_id, ref.document_version, str(ref.page), ref.section_id

    def _claim_scope(self, plan, facet_id, source, ref):
        if plan.compare_phases and facet_id in source.get("facet_phase_ids", ()):
            if experiment := source.get("source_experiment_key"):
                return "experiment", experiment
        return self._scope(source, ref)

    def same_step_readouts(self, plan, initial_hits):
        """Find intact authored readouts already present in the first retrieval pool."""
        requests = {}
        for facet in plan.facets:
            if (facet.kind not in {"concept", "readback"} or not facet.devices or facet.output_fields or facet.fields
                    or facet.directions or not _OBSERVATION_ASK.search(facet.text)):
                continue
            owners = frozenset({facet.observation_owner}) if facet.observation_owner else facet.devices
            if len(owners) == 1:
                words = set(_query_tokens(passage_query(facet.text)))
                requests[facet.number] = facet, owners, {word for word in words if not any(word != other and word in other for other in words)}
        if not requests:
            return ()
        choices = defaultdict(dict)
        seen = set()
        for hit in initial_hits:
            if not (ref := FacetEvidenceRef.from_hit(hit)) or ref.edition_version != self.edition.version:
                continue
            key = ref.document_id, ref.document_version
            for kind, text, path, core in self.units.get((key, ref.page), ()):
                identity = key, ref.page, text
                if (kind != "paragraph" or core or identity in seen or not 18 <= len(text) <= 900
                        or _EXPECTED_ONLY.search(text) or _NAVIGATION.match(text) or not _source_excerpt(text, hit["text"])):
                    continue
                seen.add(identity)
                context = _source_metadata(hit, path, self.case_roots[key])
                if not context.get("source_experiment_key") or not context.get("source_phase_key"):
                    continue
                clauses = tuple(authored_readout_clauses(text))
                if not clauses:
                    continue
                known = _subjects("\n".join((*context["source_heading_path"], text)))
                actual_steps = _source_step_phases(path) | _reported_phases(text)
                for number, (facet, owners, words) in requests.items():
                    if not facet.subjects <= known or not facet.phases <= actual_steps:
                        continue
                    span_words = words & set(_query_tokens(passage_query(text)))
                    if len(span_words) < 4:
                        continue
                    overlaps = [len(words & set(_query_tokens(passage_query(clause)))) for clause in clauses
                                if owners <= _devices(clause) and _observation_owner(clause) in ("", *owners)]
                    if not overlaps or max(overlaps) < 2:
                        continue
                    source = {**hit, **context, "text": text, "facet_ids": (number,)}
                    if bound := FacetEvidenceRef.from_hit(source):
                        choices[number][bound] = (max(overlaps), len(span_words)), source
        found = []
        for number, matches in choices.items():
            _, (best_score, _) = max(matches.items(), key=lambda item: item[1][0])
            near = [(ref, source) for ref, (score, source) in matches.items()
                    if all(value + 1 >= best for value, best in zip(score, best_score, strict=True))]
            if len(near) == 1:
                ((bound, source),) = near
                self.pool.setdefault(bound, source)
                found.append((number, bound))
        return tuple(found)

    def _record_observation(self, choices, key, ref, *, equivalent_for=None):
        if key not in choices:
            choices[key] = ref
            return
        existing = choices[key]
        if existing is None or existing == ref:
            return
        same_page = (existing.document_id, existing.document_version, existing.page, existing.section_id) == (
            ref.document_id, ref.document_version, ref.page, ref.section_id)
        if same_page:
            previous = compact_text(self.pool[existing]["text"])
            arrival = compact_text(self.pool[ref]["text"])
            if previous in arrival or arrival in previous:
                if len(arrival) > len(previous):
                    choices[key] = ref
                return
        if equivalent_for is not None:
            previous, arrival = self.pool[existing], self.pool[ref]
            known = dict(previous.get("facet_record_values", ())).get(equivalent_for)
            if known and known == dict(arrival.get("facet_record_values", ())).get(equivalent_for):
                def corroboration(source):
                    return len(set(source.get("facet_readback_ids", ())) | set(source.get("facet_explanation_ids", ())))

                if corroboration(arrival) > corroboration(previous):
                    choices[key] = ref
                return
        choices[key] = None

    def verified_sources(self, plan, capacity, witness_key):
        if witness_key == "facet_explanation_ids" and plan.facets and plan.facets[0].kind in _PRINCIPLE_KINDS:
            witnesses = []
            for facet in plan.facets:
                referents = [(ref, compact_text(hit["text"]).rstrip("。；;")) for ref, hit in self.pool.items()
                             if ref not in self.ambiguous and facet.number in hit.get(witness_key, ())]
                if len({statement for _, statement in referents}) != 1:
                    return (), ()
                witnesses.append((facet.number, referents[0][0]))
            return (tuple(witnesses) if len({ref for _, ref in witnesses}) <= capacity else ()), ()
        claims = defaultdict(dict)
        for (_, ref), source in self.scoped_claims.items():
            if ref in self.ambiguous:
                continue
            for number in source.get(witness_key, ()):
                if not plan.compare_phases or number in source.get("facet_phase_ids", ()):
                    scope = self._claim_scope(plan, number, source, ref)
                    self._record_observation(claims[number], scope, ref)
        ambiguous = tuple(sorted(number for number, choices in claims.items() if len(choices) > 1 or None in choices.values()))
        if plan.same_experiment and len({scope for alternatives in claims.values() for scope in alternatives}) != 1:
            return (), ambiguous
        witnesses = []
        seen = set()
        for facet in plan.facets:
            choices = claims.get(facet.number, {})
            if len(choices) == 1:
                ref = next(iter(choices.values()))
                if ref is not None and (ref in seen or len(seen) < capacity):
                    seen.add(ref)
                    witnesses.append((facet.number, ref))
        return tuple(witnesses), ambiguous

    def verified_bundle(self, plan, capacity, *, query=""):
        if not plan.same_experiment or not 2 <= len(plan.facets) <= 6:
            return None, False
        required = {facet.number for facet in plan.facets}
        limits = {facet.number for facet in plan.facets if facet.limit_target}
        groups = defaultdict(dict)
        named = defaultdict(lambda: defaultdict(set))
        for (_, ref), source in self.scoped_claims.items():
            if ref in self.ambiguous:
                continue
            numbers = set(source.get("facet_readback_ids", ())) | set(source.get("facet_explanation_ids", ()))
            if plan.compare_phases:
                numbers.intersection_update(source.get("facet_phase_ids", ()))
            titles = _mentioned_source_titles(query, source) if numbers else frozenset()
            for number in numbers:
                scope = self._claim_scope(plan, number, source, ref)
                if scope[0] == "page":
                    # A physical page alone does not prove that adjacent original
                    # statements belong to the same case.
                    scope = (*scope, ref.text_sha256)
                roles = tuple(witness for facet, witness in source.get("facet_witnesses", ()) if facet == number)
                for role in roles if number in limits else ("direct",):
                    self._record_observation(groups[scope], (number, role), ref,
                                             equivalent_for=number if number in source.get("facet_readback_ids", ()) else None)
                if titles:
                    named[scope][number].update(titles)

        complete = [(scope, found) for scope, found in groups.items() if required <= {number for number, _ in found}]
        if named:
            # An explicitly named original title applies to the whole example.
            # A different complete experiment cannot answer a missing named one.
            complete = [(scope, found) for scope, found in complete
                        if set.intersection(*(named[scope][number] for number in required))]
        if len(complete) != 1:
            return None, len(complete) > 1
        scope, found = complete[0]
        if any(ref is None for ref in found.values()):
            return None, True
        if len(set(found.values())) > capacity:
            return None, False
        ordered = tuple(dict.fromkeys((facet.number, ref) for facet in plan.facets
                                      for (number, _), ref in found.items() if facet.number == number))
        return VerifiedEvidenceBundle(scope, ordered), False

    def precise_case(self, plan, capacity):
        if not plan.same_experiment or any(facet.kind != "readback" or not facet.directions for facet in plan.facets):
            return None, False
        claims = defaultdict(dict)
        for (_, ref), source in self.scoped_claims.items():
            directions = _observed_directions(source["text"])
            for facet in plan.facets:
                if (facet.number in source["facet_ids"] and facet.directions <= directions
                        and (not plan.compare_phases or facet.number in source.get("facet_phase_ids", ()))):
                    scope = self._claim_scope(plan, facet.number, source, ref)
                    # Without a labeled case, one contiguous passage must
                    # witness the entire readback; a page can contain two cases.
                    key = scope, ref if scope[0] == "page" else None
                    self._record_observation(claims[key], facet.number, ref)
        # Candidate rank can order alternatives inside one scope, but cannot
        # determine which of two fully witnessed experiments the reader meant.
        complete = [(scope, found) for (scope, _), found in claims.items()
                    if len(found) == len(plan.facets) and len(set(found.values())) <= capacity]
        if len(complete) != 1:
            return None, len(complete) > 1
        scope, found = complete[0]
        if any(ref is None or ref in self.ambiguous for ref in found.values()):
            return None, True
        ordered = tuple((facet.number, found[facet.number]) for facet in plan.facets)
        directions = tuple((facet.number, tuple(sorted(facet.directions))) for facet in plan.facets)
        return PreciseCase(scope, ordered, directions), False

    @staticmethod
    def _first_pass(facets, groups, capacity):
        selected = []
        covered = []
        scores = []
        by_facet = {}
        for facet in facets:
            alternatives = groups.get(facet.number, ())
            if not alternatives:
                continue
            score, ref = max(alternatives, key=lambda item: item[0])
            already = next(((value, old) for value, old in alternatives if old in selected), None)
            if already is not None:
                score, ref = already
            elif len(selected) == capacity:
                continue
            else:
                selected.append(ref)
            covered.append(facet.number)
            scores.append(score)
            by_facet[facet.number] = ref
        return (len(covered), tuple(sorted(scores, reverse=True)), -len(selected)), selected, by_facet

    def select(self, plan, limit):
        choices = [self._first_pass(plan.facets, group, limit) for group in self._feasible_groups(plan)]
        if not choices:
            return [], {}
        score, refs, matches = max(choices, key=lambda option: option[0])
        if plan.same_experiment and len({tuple(items) for grade, items, _ in choices if grade == score}) > 1:
            # A tie between two source-local experiments is not a verified match.
            return [], {}
        return refs, matches

    def ordered_pool(self, chosen):
        order = list(chosen)
        seen = set(order)
        for matches in self.by_facet.values():
            alternatives = sorted(matches, key=lambda item: item[0], reverse=True)
            used_pages = set()
            for _, ref in alternatives:
                key = ref.document_id, ref.page
                if key in used_pages or ref in seen or ref in self.ambiguous:
                    continue
                seen.add(ref)
                used_pages.add(key)
                order.append(ref)
                if len(used_pages) == 4:
                    break
        order.extend(ref for ref in self.pool if ref not in seen)
        return [self.pool[ref] for ref in order[:48]]

    def short_observation(self, request):
        """Resolve one scalar from original units on pages already verified for this request."""
        visited, matches = set(), {}
        for ref, hit in self.pool.items():
            key = ref.document_id, ref.document_version
            locator = key, ref.page
            if locator in visited or ref in self.ambiguous:
                continue
            visited.add(locator)
            for kind, text, path, core in self.units[locator]:
                if (kind != "paragraph" or core or len(text) > 1300 or _NAVIGATION.match(text)
                        or not original_observation(request, text, (hit.get("title", ""),))):
                    continue
                metadata = _source_metadata(hit, path, self.case_roots[key])
                candidate = {**hit, **metadata, "text": text, "facet_ids": (1,), "facet_readback_ids": (1,)}
                bound = FacetEvidenceRef.from_hit(candidate)
                if bound and bound not in self.ambiguous:
                    matches[bound] = candidate
                if len(matches) > 1:
                    return None
        return next(iter(matches.items())) if matches else None

    def verified_record_sequence(self, request, capacity):
        """Keep authored stages separate and keep the first two when review was never observed."""
        seen, by_case = set(), defaultdict(lambda: defaultdict(dict))
        for ref, hit in self.pool.items():
            key = ref.document_id, ref.document_version
            locator = key, ref.page
            if locator in seen or ref in self.ambiguous:
                continue
            seen.add(locator)
            section, body = self.documents[key][0][ref.page]
            units = self.units[locator]
            for number, original, display in sequence_witnesses(request, body):
                paths = {path for kind, text, path, core in units if kind == "paragraph" and not core and text == original}
                if len(paths) != 1:
                    continue
                path, = paths
                case = next((row for row in reversed(path) if case_title(row[1]) == request.scope), None)
                step = _current_source_step(path)
                context = _source_metadata(hit, path, self.case_roots[key])
                if (not case or not step or step[2] <= case[2] or not context.get("source_phase_key")
                        or context.get("source_experiment_key") != _heading_key(hit, case)):
                    continue
                source = self.edition._bound_hit({"retriever": "edition_local"}, self.edition.documents[ref.document_id],
                                                 display, section, ref.page)
                source.update(context, facet_ids=(number,), facet_phase_ids=(number,))
                if bound := FacetEvidenceRef.from_hit(source):
                    by_case[context["source_experiment_key"]][number][bound] = step[2], source
        if len(by_case) != 1:
            return None
        scope, claims = next(iter(by_case.items()))
        if len(claims[1]) != 1 or len(claims[2]) != 1:
            return None
        first, second = (next(iter(claims[number].items())) for number in (1, 2))
        if first[1][0] >= second[1][0]:
            return None
        proven = [(1, first), (2, second)]
        if capacity >= 3 and len(claims[3]) == 1:
            third = next(iter(claims[3].items()))
            if second[1][0] < third[1][0]:
                proven.append((3, third))
        return scope, tuple((number, ref) for number, (ref, _) in proven), [info[1] for _, (_, info) in proven]

    def phase_state_observations(self, requests):
        """Return both independently scoped original observations from one experiment step."""
        seen, matches = set(), {}
        for ref, hit in self.pool.items():
            key = ref.document_id, ref.document_version
            locator = key, ref.page
            if locator in seen or ref in self.ambiguous:
                continue
            seen.add(locator)
            section, body = self.documents[key][0][ref.page]
            units = reading_units(body)
            for number, request in enumerate(requests, 1):
                for _, text in phase_state_witnesses(request, body, units=units):
                    paths = {path for kind, part, path, core in self.units[locator] if kind == "paragraph" and not core
                             and len(part) >= 10 and _source_excerpt(part, text)}
                    if len(paths) != 1:
                        continue
                    context = _source_metadata(hit, next(iter(paths)), self.case_roots[key])
                    if not context.get("source_experiment_key") or not context.get("source_phase_key"):
                        continue
                    source = self.edition._bound_hit({"retriever": "edition_local"}, self.edition.documents[ref.document_id], text, section, ref.page)
                    source.update(context, facet_ids=(number,), facet_readback_ids=(number,), facet_phase_ids=(number,))
                    bound = FacetEvidenceRef.from_hit(source)
                    if bound and bound not in self.ambiguous:
                        matches[number, bound] = source
                    if len(matches) > 2:
                        return None
        if len(matches) != 2:
            return None
        first, second = sorted(matches, key=lambda match: match[0])
        left, right = matches[first], matches[second]
        same_keys = ("document_id", "document_version", "source_experiment_key", "source_phase_key")
        if first[0] != 1 or second[0] != 2 or left["page"] == right["page"] or any(left[key] != right[key] for key in same_keys):
            return None
        return (first, second), (left, right)


async def _rank_actor_comparison(edition, workspace, query, request, initial_hits, passages):
    keyword = edition.keyword_index
    focuses = [(topic, f"{topic} {task.text} {task.target}") for topic in request.topics for task in request.tasks]
    lanes = await asyncio.gather(*(keyword.search_pages(focus, 16, phrases=(topic,)) for topic, focus in focuses))
    bound = list(initial_hits)
    for (_, hits), (_, focus) in zip(lanes, focuses, strict=True):
        bound.extend(await asyncio.to_thread(edition.resolve_hits, hits, keyword, workspace, query=focus))
    await asyncio.to_thread(passages.add, bound, _Plan((), False))
    original = []
    visited = set()
    for ref, seed in passages.pool.items():
        key = ref.document_id, ref.document_version
        locator = key, ref.page
        if locator in visited:
            continue
        visited.add(locator)
        for kind, text, path, core in passages.units[locator]:
            if kind != "paragraph" or core or not 20 <= len(text) <= 550 or _NAVIGATION.match(text):
                continue
            context = _source_metadata(seed, path, passages.case_roots.get(key, ()))
            if (not context.get("source_experiment_key")
                    and not notes_for_excerpt(seed.get("filename", ""), text, ref.document_version)):
                candidate = {**seed, **context, "text": text}
                candidate.pop("source_experiment_key", None)
                if "source_phase_key" not in context:
                    candidate.pop("source_phase_key", None)
                original.append(candidate)
    pair = await asyncio.to_thread(choose_actor_evidence, request, original)
    if not pair:
        return None
    refs = tuple((index, FacetEvidenceRef.from_hit(hit)) for index, hit in enumerate(pair, 1))
    facets = tuple((index, task.text, "mechanism") for index, task in enumerate(request.tasks, 1))
    ranked = RankedEvidence(sha256(query.encode("utf-8")).hexdigest(), edition.version, facets, refs, (), verified_explanation=refs)
    remaining = [hit for ref, hit in passages.pool.items() if ref not in {reference for _, reference in refs}]
    return [*pair, *remaining][:48], ranked


def _rank_printed_span(edition, query, request, complete, facets, initial_hits, passages):
    passages.add(initial_hits, _Plan((), False))
    requires_observed = any(kind == "readback" for _, _, kind in facets)
    visited = set()
    claims = []
    for ref, hit in passages.pool.items():
        key = ref.document_id, ref.document_version
        locator = key, ref.page
        if locator in visited:
            continue
        visited.add(locator)
        _, page = passages.documents[key][0][ref.page]
        statement = complete(page, request)
        if statement and _source_excerpt(statement, page):
            if requires_observed and any(planned_unit(kind) and (_source_excerpt(statement, unit) or _source_excerpt(unit, statement))
                                        for kind, unit, _, _ in passages.units[locator]):
                continue
            claims.append({**hit, "text": statement})
    if len(claims) != 1:
        return None
    claim, = claims
    bound = FacetEvidenceRef.from_hit(claim)
    if not bound:
        return None
    matches = tuple((number, bound) for number, _, _ in facets)
    observation = tuple((number, bound) for number, _, kind in facets if kind == "readback")
    observed_ids = tuple(number for number, _ in observation)
    explanation = tuple((number, bound) for number, _, kind in facets if kind != "readback")
    ranked = RankedEvidence(sha256(query.encode("utf-8")).hexdigest(), edition.version, facets, matches, (),
                            observation_facets=observed_ids, verified_observation=observation, verified_explanation=explanation)
    return [claim, *(hit for ref, hit in passages.pool.items() if ref != bound)][:48], ranked


async def _rank_passages(edition, workspace, terms, initial_hits, plan, capacity, passages):
    await asyncio.to_thread(passages.add, initial_hits, plan)
    chosen, matches = passages.select(plan, capacity)
    if plan.same_experiment and 2 <= len(plan.facets) <= 6 and not passages.verified_bundle(plan, capacity, query=terms)[0]:
        additional = await asyncio.to_thread(additional_document_hits, edition, plan, initial_hits, passages.documents)
        if additional:
            await asyncio.to_thread(passages.add, additional, plan)
            chosen, matches = passages.select(plan, capacity)
        if not passages.verified_bundle(plan, capacity, query=terms)[0]:
            def source_scope(hit, path):
                key = hit['document_id'], hit['document_version']
                metadata = _source_metadata(hit, path, passages.case_roots.get(key, ()))
                return metadata.get('source_experiment_key') or metadata.get('source_heading_key')

            discovered = await asyncio.to_thread(section_discovery_hits, edition, plan, [*initial_hits, *additional],
                                                  passages.documents, iter_units=_units, scope_for=source_scope)
            if discovered:
                await asyncio.to_thread(passages.add, discovered, plan)
                chosen, matches = passages.select(plan, capacity)
        if not passages.verified_bundle(plan, capacity, query=terms)[0]:
            clauses = list(enumerate(_evidence_question_clauses(terms), 1))
            original_scopes = await asyncio.to_thread(edition.original_scope_index.discover, clauses,
                                                       subjects=protocol_names(terms))
            if original_scopes:
                passages.original_scope_locations = tuple(original_scopes)
                await asyncio.to_thread(passages.add, original_scopes, plan)
                chosen, matches = passages.select(plan, capacity)
    missing = [facet for facet in plan.facets if facet.number not in matches]
    if missing:
        keyword = edition.keyword_index
        # Never do another identical corpus query. A separate focus may recover
        # a source missed by the original broad pool; the physical gate still applies.
        focuses = [facet for facet in missing if compact_text(facet.text) != compact_text(terms)][:3]
        lanes = await asyncio.gather(*(keyword.search_pages(facet.text, 16, phrases=(facet.topic,) if facet.topic else ())
                                     for facet in focuses))
        newly_bound = []
        original_candidates = []
        for (_, raw), facet in zip(lanes, focuses, strict=True):
            newly_bound.extend(await asyncio.to_thread(edition.resolve_hits, raw, keyword, workspace, query=facet.text,
                                                       original_candidates=original_candidates))
        if newly_bound:
            await asyncio.to_thread(passages.add, [*newly_bound, *original_candidates], plan)
            chosen, matches = passages.select(plan, capacity)
    return chosen, matches


async def rank_edition_evidence(edition, workspace, query, terms, initial_hits, *, top_k, preserve_selection=False):
    """Select at most six verified references; unresolved facets stay explicit."""
    capacity = min(max(top_k, 1), 6)
    passages = _Passages(edition)
    if not preserve_selection:
        clauses = _evidence_question_clauses(terms)
        exhibit = printed_exhibit_request(clauses)
        attribution = exhibit_attribution_request(clauses)
        request = exhibit or attribution or printed_routes_request(clauses)
        if request:
            if attribution:
                facets = tuple((number, clause, "diagram" if number == 1 else "readback")
                               for number, clause in enumerate(attribution.questions, 1))
                complete = complete_exhibit_attribution
            else:
                facets = tuple((number, clause, "diagram" if exhibit else "readback") for number, clause in enumerate(clauses, 1))
                complete = complete_printed_exhibit if exhibit else complete_printed_routes
            composed = await asyncio.to_thread(_rank_printed_span, edition, query, request, complete, facets, initial_hits, passages)
            if composed:
                return composed
            passages = _Passages(edition, reusable=passages)
    if not preserve_selection and capacity >= 2 and (comparison := actor_comparison_request(terms)):
        composed = await _rank_actor_comparison(edition, workspace, query, comparison, initial_hits, passages)
        if composed:
            return composed
        passages = _Passages(edition, reusable=passages)
    plan = _plan(terms) if not preserve_selection else None
    if plan and len(plan.facets) == 1:
        facet = plan.facets[0]
        if (facet.kind in {"concept", "mechanism"} and not (facet.directions or facet.owners or (facet.fields and facet.devices))
                or facet.kind == "evidence_limit" and not (facet.subjects or facet.labels or facet.devices)):
            plan = None
    principle_plan = _independent_principles(terms, plan)
    plan = plan or _Plan((), False)
    chosen, matches = await _rank_passages(edition, workspace, terms, initial_hits, principle_plan or plan, capacity, passages)
    if principle_plan:
        complete, _ = passages.verified_sources(principle_plan, capacity, "facet_explanation_ids")
        if complete:
            plan = principle_plan
        else:
            # Preserve the old selection contract when one named claim is absent or contested.
            # The second pass reuses documents and source units already verified by physical page.
            passages = _Passages(edition, reusable=passages)
            chosen, matches = await _rank_passages(edition, workspace, terms, initial_hits, plan, capacity, passages)
    precise, ambiguous = await asyncio.to_thread(passages.precise_case, plan, capacity)
    bundle, ambiguous_bundle = passages.verified_bundle(plan, capacity, query=terms)
    precise_refs = tuple(ref for _, ref in precise.matches) if precise else ()
    observation_ids = tuple(facet.number for facet in plan.facets if facet.kind == "readback")
    verified, ambiguous_observations = passages.verified_sources(plan, capacity, "facet_readback_ids")
    explanations, _ = passages.verified_sources(plan, capacity, "facet_explanation_ids")
    if (not preserve_selection and capacity >= 2 and len(plan.facets) == 3
            and not (bundle or ambiguous_bundle or precise or ambiguous or ambiguous_observations or explanations)
            and not edition.has_search_scope(query) and (sequence := record_sequence_request(query, clauses))):
        if selected := await asyncio.to_thread(passages.verified_record_sequence, sequence, capacity):
            scope, sequence_matches, sources = selected
            proposed = dict(zip((number for number, _ in sequence_matches), sources, strict=True))
            lookup = ("document_id", "document_version", "page", "section_id")
            if all(number in proposed and all(getattr(ref, field) == proposed[number][field] for field in lookup)
                   and _source_excerpt(passages.pool[ref]["text"], proposed[number]["text"]) for number, ref in verified):
                facets = tuple((number, clause, "configuration" if number == 1 else "readback")
                               for number, clause in enumerate(clauses, 1))
                recorded = tuple((number, ref) for number, ref in sequence_matches if number != 1)
                ranked = RankedEvidence(sha256(query.encode("utf-8")).hexdigest(), edition.version, facets, sequence_matches,
                                        () if 3 in proposed else (3,), same_experiment=True, explicit_same_experiment=True,
                                        observation_facets=(2, 3), verified_observation=recorded,
                                        verified_bundle=VerifiedEvidenceBundle(("experiment", scope), sequence_matches),
                                        original_scope_locations=passages.original_scope_locations)
                references = {ref for _, ref in sequence_matches}
                remaining = (hit for hit in passages.ordered_pool(chosen) if FacetEvidenceRef.from_hit(hit) not in references)
                return [*sources, *remaining][:48], ranked
    if (not preserve_selection and capacity >= 2 and plan.same_experiment and len(plan.facets) == 2
            and not (bundle or ambiguous_bundle or precise or ambiguous or ambiguous_observations or explanations)
            and not edition.has_search_scope(query) and (requests := phase_state_requests(query, clauses))):
        if phase_state := await asyncio.to_thread(passages.phase_state_observations, requests):
            phase_matches, sources = phase_state
            lookup = ("document_id", "document_version", "page", "section_id")
            if all(all(getattr(ref, field) == sources[number - 1][field] for field in lookup)
                   and _source_excerpt(passages.pool[ref]["text"], sources[number - 1]["text"]) for number, ref in verified):
                scope = ("experiment", sources[0]["source_experiment_key"])
                facets = tuple((number, clause, "readback") for number, clause in enumerate(clauses, 1))
                ranked = RankedEvidence(sha256(query.encode("utf-8")).hexdigest(), edition.version, facets, phase_matches, (),
                                        same_experiment=True, explicit_same_experiment=True, compare_phases=True,
                                        observation_facets=(1, 2), verified_observation=phase_matches, phase_facets=(1, 2),
                                        verified_bundle=VerifiedEvidenceBundle(scope, phase_matches),
                                        original_scope_locations=passages.original_scope_locations)
                proposed = {reference for _, reference in phase_matches}
                remaining = (hit for hit in passages.ordered_pool(chosen) if FacetEvidenceRef.from_hit(hit) not in proposed)
                return [*sources, *remaining][:48], ranked
    if (not preserve_selection and len(clauses) == 1 and len(plan.facets) <= 1
            and not (bundle or ambiguous_bundle or precise or ambiguous or verified or ambiguous_observations or explanations)
            and not edition.has_search_scope(query) and (request := short_record_request(query))):
        if short := await asyncio.to_thread(passages.short_observation, request):
            reference, source = short
            matches = ((1, reference),)
            scope = ("page", reference.document_id, reference.document_version, str(reference.page), reference.section_id)
            ranked = RankedEvidence(sha256(query.encode("utf-8")).hexdigest(), edition.version,
                                    ((1, clauses[0], "readback"),), matches, (), observation_facets=(1,),
                                    verified_observation=matches, verified_bundle=VerifiedEvidenceBundle(scope, matches))
            remaining = (hit for hit in passages.ordered_pool(chosen) if FacetEvidenceRef.from_hit(hit) != reference)
            return [source, *remaining][:48], ranked
    bundle_matches = bundle.matches if bundle else ()
    proofs = tuple(ref for _, ref in (*bundle_matches, *verified, *explanations))
    same_step = ()
    if (not preserve_selection and plan.same_experiment and not plan.compare_phases and len(plan.facets) >= 2
            and not (bundle or precise or ambiguous_bundle or ambiguous or ambiguous_observations)
            and not edition.has_search_scope(query)):
        same_step = await asyncio.to_thread(passages.same_step_readouts, plan, initial_hits)
    pool = passages.ordered_pool(dict.fromkeys((*precise_refs, *proofs, *(ref for _, ref in same_step), *chosen)))
    if (not matches and precise is None and not ambiguous and not observation_ids
            and not explanations and not ambiguous_bundle and not passages.original_scope_locations and not same_step):
        return pool, None
    ranked = RankedEvidence(sha256(query.encode("utf-8")).hexdigest(), edition.version,
                            tuple((facet.number, facet.text, facet.kind) for facet in plan.facets),
                            tuple(matches.items()), tuple(facet.number for facet in plan.facets if facet.number not in matches),
                            precise_case=precise, ambiguous_precise_case=ambiguous,
                            observation_facets=observation_ids, verified_observation=verified,
                            ambiguous_observation_facets=ambiguous_observations, verified_explanation=explanations,
                            comparison_topics=tuple((facet.number, facet.topic) for facet in plan.facets if facet.topic),
                            verified_bundle=bundle, ambiguous_verified_bundle=ambiguous_bundle,
                            same_experiment=plan.same_experiment, compare_phases=plan.compare_phases,
                            explicit_same_experiment=_explicit_same_case(terms),
                            phase_facets=tuple(facet.number for facet in plan.facets if facet.phases),
                            original_scope_locations=passages.original_scope_locations, same_step_readouts=same_step)
    return pool, ranked
