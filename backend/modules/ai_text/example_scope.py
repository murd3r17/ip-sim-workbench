"""Select evidence from a described experiment without treating it as live data."""

from dataclasses import dataclass, replace
import re

from core.markdown_blocks import blocks
from modules.knowledge.device_alias_facets import device_aliases
from modules.knowledge.phase_reference import operation_comparison, operation_phases, step_phases
from modules.knowledge.query_focus import passage_concepts, protocol_names


_CASE_REFERENCE = re.compile(
    r'(?:[这那该本同]个?(?:实验|案例|场景|例子)|实验(?:中|里)|案例(?:中|里)|题设|'
    r'(?:截图|回显|读回|结果|表格|拓扑图|抓包|配置表)(?:中|上|内|里)|图(?:中|上|内|里)|表(?:中|上|内|里)|'
    r'(?:那次|同一次|这次|那轮|同一轮)(?:实验|验证|读回|抓包|观察))'
)
_RESULT_REQUEST = re.compile(r'回显|读回|(?:抓包|报文)(?:中|里|结果|显示|能否)|(?:实测|验证|观察)(?:结果|数据)|字段')
_ACTUAL_RESULT = re.compile(r'回显(?:中|里|显示|为|表明|给出)|读回(?:显示|为|结果)|(?:抓包|报文)(?:显示|中|结果)|'
                            r'(?:实际|实测|观察到的)(?:输出|结果|邻居|状态|读回|回显)', re.I)
_PACKET_CAPTURE = re.compile(r'(?:抓包|捕获|采集)(?:[的到]{0,2}报文|结果|.{0,8}(?:显示|可见|读到|记录了))|'
                             r'(?:Wireshark|pcap).{0,12}(?:显示|记录了|捕获到)', re.I)
_LEARNING_ORIGIN = re.compile(r'(?:从|通过|经)[^，。；\n]{1,26}(?:学习到|学到了?|习得)|'
                              r'(?<![a-z])learn(?:ed|t)\s+(?:from|via)\s+\S', re.I)
_OUTPUT_VALUE = re.compile(r'\b(?:Full|Established|Active|Passive|Up|Down)\b|\d+\.\d+\.\d+\.\d+', re.I)
_READOUT_STATE = re.compile(r'(?<![A-Za-z0-9_-])(?:Full|Established|Active|Passive|Up|Down)(?![A-Za-z0-9_-])', re.I)
_READ_COMMAND = re.compile(r'^\s*(?:<[^>]+>|\[[^\]]+\])\s*(?:display|show)\s+\S[^\n]*$', re.I | re.M)
_TABLE_CAPTION = re.compile(r'(?:保留|按|下表|原图).{0,36}(?:回显|读回|原图指令)|回显.{0,12}(?:表|如下)|\b(?:display|show)\s+\S+', re.I | re.S)
_TABLE_VALUES = re.compile(r'(?:表内|表中|表里|表项|表格|读表).{0,12}(?:显示|读数|记录|读到|为)')
_FIGURE_VALUE = re.compile(r'(?:原图|图中|图上|从表中)(?:标|显示|给出|以|的表|记录)|图示(?:状态|内容|结果)')
_UNOBSERVED = re.compile(r'(?:未|尚无|没有)(?:实际|记录|保存|见到|找到|采集|给出).{0,12}(?:输出|记录|回显|读回|抓包)|预期|建议(?:查看|采集)')
_PLAN = re.compile(r'地址规划|规划(?:图|表|值|的是)|设计(?:图|表)|预期(?:状态|角色|路径)|待(?:核对|验证)')
_LIMIT_REQUEST = re.compile(r'(?:能否|能不能|足以|足够|够不够|可以|能|还要|为何不能|为什么不能).{0,8}'
                            r'(?:证明|确认|判断|推出|代表|当作|视为|认定)|(?:是不是|是否).{0,8}就能|'
                            r'(?:能|可否|足以).{0,16}(?:业务恢复|业务中断).{0,5}(?:计时|时长|耗时)')
_LIMIT = re.compile(r'(?:还需|仍需|需同时|需另|须|应)\s*(?:对照|核对|检查|比较|同时|独立|结合)|'
                    r'(?:需|须|只有)(?:相同|同一|同步).{0,14}(?:时点|时间|两侧|双方)|'
                    r'(?:应|须|要)分别(?:判读|判断|验证)|(?:需要|需|须|要)(?:另行|另外|独立)(?:测量|计时)|'
                    r'(?:无法|不能|不足以|不代表|未(?:记录|采到|验证|能证明))')
_MEASUREMENT = re.compile(r'(业务恢复|业务中断|转发恢复|数据面恢复).{0,8}(?:计时|时长|耗时|时间|多久)')
_MEASURED_DURATION = re.compile(r'(?:实测|实际|测得).{0,22}(业务恢复|业务中断|转发恢复|数据面恢复).{0,12}'
                               r'\d+(?:\.\d+)?\s*(?:ms|s\b|毫秒|秒|分钟)', re.I)
_DEVICE_LABEL = r'(?:AR|PE|CE|NE|FW|SW|GW|PC|LEAF|SPINE|R|S|P)(?:[-_]\d{1,3}|\d{1,3}(?:[-_][A-Z]{1,3})?|[-_][A-Z]{1,3}\d{0,3})'
_DEVICE = re.compile(rf'(?<![A-Za-z0-9_-]){_DEVICE_LABEL}(?![A-Za-z0-9_-])', re.I)
_COMPOUND_LABEL = r'[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+){1,3}'
_COMPOUND_ENTITY = re.compile(rf'(?<![A-Za-z0-9_-])(?P<device>{_COMPOUND_LABEL})(?![A-Za-z0-9_-])', re.I)
_ENTITY_SUFFIX = re.compile(r'[-_](?:[A-Z]\d{0,3}|\d{1,4})\Z', re.I)
_LABEL_BEFORE = re.compile(r'(?:设备|节点|对端|路由器|交换机|防火墙|网关)\s*\Z')
_LABEL_AFTER = re.compile(r'^\s*(?:的)?(?:设备|节点|主机|交换机|路由器|防火墙|网关|对端|端口|接口|'
                          r'作为|向|连接|互联|一端|一侧|角色)')
_FIELD_BEFORE = re.compile(r'(?:字段|属性|表头|标志位)\s*\Z')
_FIELD_AFTER = re.compile(r'^\s*(?:字段|属性|一列|计数|值为|标志位)')
_READ_SUBJECT = re.compile(rf'(?<![A-Za-z0-9_-])(?P<device>{_DEVICE_LABEL}|{_COMPOUND_LABEL})(?![A-Za-z0-9_-])\s*'
                           r'(?:(?:的|上|里|在)[^，。；！？\n]{0,32}?)?'
                           r'(?:回显|读回|实际输出|表中|表内|执行\s*(?:display|show))', re.I)
_EXAMPLE_PROTOCOL = re.compile(r'(?<![A-Za-z0-9])(?:PIM|IGMP|MLD|NDP|GRE|VXLAN|EVPN|SRv6|IPsec|'
                               r'ICMPv?[46]?|DHCPv[46]|LACP|802\.1X|OSPFv2|RIPng|EIGRP)(?![A-Za-z0-9])', re.I)
_PHASE_ACTION = r'汇总|引入|重分发|变更|切换|回切|收敛|故障|恢复|调整|重选|过滤|迁移|启用|撤销|协商'
_PHASE = re.compile(rf'({_PHASE_ACTION})(?:完(?:成)?|发生)?(?:之|以)?([前后])')
_BOTH_PHASES = re.compile(rf'({_PHASE_ACTION})(?:之)?前后')
_MODE = re.compile(r'(集中式|分布式|单活|双活|主备|负载分担|二层|三层|静态|动态|透明|路由|'
                   r'单跳|多跳|异步|查询|主动|被动|独立|有序)(?:\s*(?:模式|网关|组网|配置|接入|转发|部署|实验|检测))')
_MODE_PAIRS = tuple(map(frozenset, (
    ('集中式', '分布式'), ('单活', '双活'), ('主备', '负载分担'), ('二层', '三层'),
    ('单跳', '多跳'), ('异步', '查询'), ('静态', '动态'), ('独立', '有序'),
    ('透明', '路由'), ('主动', '被动'),
)))
_MODE_COMPARISON = re.compile(r'对比|比较|分别|各自|两个.{0,8}(?:模式|网关|实验|场景)')
_ROLE = re.compile(r'上游|下游|发送(?:端|侧|方)|接收(?:端|侧|方)|入口|出口|主用|备用|主动(?:方|端|角色)|被动(?:方|端|角色)|'
                   r'\b(?:Master|Backup|Active|Passive|Upstream|Downstream)\b', re.I)
_ROLE_ALIASES = {'发送侧': '发送端', '发送方': '发送端', '接收侧': '接收端', '接收方': '接收端',
                 'upstream': '上游', 'downstream': '下游'}
_NAMED_FIELD = re.compile(r'(?<![A-Za-z0-9])(?:[A-Za-z]{2,}_[A-Za-z0-9_]+|[A-Z][a-z]{2,}[A-Z][A-Za-z]+)(?![A-Za-z0-9])')
_FIELD_WRITING = re.compile(r'(?<![A-Za-z0-9])(?:as-path)(?![A-Za-z0-9])', re.I)
_ADDRESS = re.compile(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?(?![\w.])')
_CASE_ID = re.compile(r'(?:案例|实验|示例)\s*([0-9]+[.\-][0-9]+|[0-9]+)')
_NONLOCAL = re.compile(r'我(?:们的?|这边)|现场|实机|真机|工单|附件|快照|工作台|最新|刚才|'
                       r'请(?:你)?(?:实际|现在|立刻).{0,7}(?:读|查|跑|执行)|读一下设备')
_SEPARATE = re.compile(r'另(?:一个|一本)|(?:不同|两[个份]).{0,5}(?:实验|案例)|分别(?:看|解释|说明).{0,7}(?:两个|两份)')
_NEW_ARTIFACT = re.compile(r'[。？！；，,!?;]\s*(?:再看|另看|另查|另外核对|接着看)')
_SAME_EXAMPLE = re.compile(r'同一(?:次|轮|组|实验|案例)|同个(?:实验|案例)|这(?:次|一轮)实验')
_ONLY_PRINCIPLE = re.compile(r'(?:只|仅)(?:想|需|需要|要)?(?:讲|看|查|谈|解释|讨论|问|比较|弄清)(?:教材的?|协议的?)?'
                             r'(?:原理|机制|概念|定义|区别)')
_CASE_HEADING = re.compile(r'应用例|例题|案例|实操|实训|演练|具体例子|(?:验证|配置|组网|操作)(?:实验|步骤|示例)|'
                           r'实验(?:任务|步骤|结果|配置)')
_CONCRETE_EXERCISE = re.compile(r'(?m)^(?:以[^。；\n]{2,60}为例|在(?:下图|图中|本例)|'
                                r'(?:如|见)图\s*[\d-]+[^。；\n]{0,12}[，,：:]|(?:下面|接下来)以[^。；\n]{2,50}为例)')
_COMPARE_CHANGE = re.compile(r'(?:(?:从[^。！？；\n]{1,45})?(?:更改|调整|变更|改|换)(?:为|成|到)[^。！？；\n]{1,45}后|'
                             r'(?:变更|改动|调整)[前后]|(?:改|换)(?:完|好|了)(?:之|以)?后)')
_ASK_FOR_PROOF = re.compile(r'核证|核对|验收|拿什么(?:来)?(?:证实|证明)|以什么为据|依据什么|观察什么|对照')
_OBSERVATION_ONLY = re.compile(r'实际(?:观察|读回|回显|状态|输出|记录)|实测|回显|读回|抓包')
_CLI_PROMPT = re.compile(r'^[ \t]*(?:<([^>\s]+)>|\[([^\]\s]+)\])[ \t]*(?:display|show)\s+\S', re.I | re.M)
_OMIT = r'(?:请)?(?:别|不要|不用|不必|无需|不想|不需要)(?:再)?'
_EXCLUDED_EXAMPLE = re.compile(
    rf'^\s*{_OMIT}(?:把|拿|用|引用|借用|混用|参考|套用|套|采用|带入|展开|讲|举|混进|带上)\s*'
    r'(?P<material>[^，。！？；,!?;\n]{0,44}?(?:应用例|例子|案例|场景|实验|示例|实例|实训|演练|题目|配置过程))'
    r'(?:作为.{1,14}|来.{1,14}|里的.{1,24}|.{0,8}举例|混进来|带进来|展开(?:讲)?|混入?(?:讨论|原理)?)?\s*$'
)
_OMIT_EXAMPLES = re.compile(rf'^\s*{_OMIT}(?:再)?(?:举例|举具体例子|展开(?:具体)?(?:案例|演练|实验)|讲具体操作)\s*$')
_MATERIAL_TRAILER = re.compile(r'(?:的?(?:应用例|例子|案例|场景|实验|示例|实例|实训|演练|题目|配置过程))$')
_UNNAMED_MATERIAL = re.compile(r'^(?:(?:这个|那个|那套|某个|该|这|一个|具体|完整|教材里的?|课堂的?)(?:的)?)*$')
_NO_DEVICE_ACCESS = re.compile(rf'^\s*(?:{_OMIT}|不)(?:现在|实际|真正|现场)?(?:连接|登录|接入|读取|访问|操作)(?:真实|实时|实际|现场)?设备\s*$')
_EXCLUDED_REPORTER = re.compile(
    rf'^\s*{_OMIT}(?:把[^，。；\n]{{1,18}}(?:替换|切换|写|说|错看|换|当)(?:成|作|为)|'
    rf'(?:引用|使用|拿|套用|用))\s*(?P<device>{_DEVICE_LABEL})\s*'
    r'(?:那(?:个|台|份)?|的)?(?:\s*(?:设备|例子|回显|读回|实验|记录))?(?:来.{1,12})?\s*$', re.I,
)
_EXCLUDED_VALUE = re.compile(
    rf'^\s*{_OMIT}(?:答|写|说|看|换|当)(?:成|作|为)\s*[「“`"]?'
    r'(?P<target>[A-Za-z0-9_.:/-]{3,48})[」”`"]?\s*(?:的|那)?(?:一)?(?:条|项|份|个)?'
    r'(?:前缀|回显|读回|记录|地址|数据)?\s*$', re.I,
)
_EXCLUDED_DEFAULT = re.compile(rf'^\s*{_OMIT}(?:答成|说成|换成|写成|拿|用|引用)\s*(?:那(?:条|个)?)?'
                               r'(?:默认|缺省)(?:的)?(?:路由|表项|项|那条|那项)(?:[^，。？；\n]{0,12})\s*$')
_RECORD_STAGE = re.compile(r'(?:比对|核对|读回|回显|切换|变更|调整|操作|修改|配置|引入|发布|采集|测试|实验)'
                           r'(?:发生|完成)?(?:之|以)?([前后])|(?:原有|原先|先前|初始)(?:配置|读回|记录|路由)|'
                           r'(?:新|后续|第二次)(?:配置|读回|记录|路由)')
_DEFAULT_PREFIX = re.compile(r'(?<![\d.])0\.0\.0\.0/0\b|默认路由|缺省路由')
_CONCEPT_LABELS = {
    'next_hop': '下一跳', 'egress_interface': '出接口', 'ingress_interface': '入接口',
    'session_table': '会话表', 'session_state': '会话状态', 'received_prefixes': '收到的前缀数',
    'source_address': '源地址', 'destination_address': '目的地址', 'private_network': '私网',
    'public_network': '公网', 'route_leaking': '路由渗透', 'load_sharing': '流量分担',
    'link_failure': '链路故障', 'identity_authentication': '身份校验',
    'send_interval': '发送间隔', 'receive_interval': '接收间隔', 'detection_multiplier': '检测倍数',
    'label_pair': '入标签与出标签',
    'tunnel_state': '隧道或会话状态', 'learning_origin': '表项的学习来源',
    'packet_headers': '报文封装的内外层字段',
}
_EXHIBIT_COLUMNS = re.compile(
    r'\b(?:(?P<egress_interface>out|exit|egress)|(?P<ingress_interface>in|ingress))[-_ ]?interface\b|'
    r'(?P<send_interval>发送(?:时间|间隔)|(?<![\w-])TX(?![\w-]))|'
    r'(?P<receive_interval>接收(?:时间|间隔)|(?<![\w-])RX(?![\w-]))|'
    r'(?P<detection_multiplier>检测倍数|(?<![\w-])DM(?![\w-]))|'
    r'(?P<label_pair>入\s*(?:出|和出|/出)\s*标签|In\s*/\s*Out\s*Label)', re.I,
)


def _matches(pattern, text):
    return frozenset(match[0].casefold() for match in pattern.finditer(text))


def _roles(text):
    return frozenset(_ROLE_ALIASES.get(role, role) for role in _matches(_ROLE, text))


def _devices(text):
    devices = set(_matches(_DEVICE, text) | device_aliases(text))
    for match in _COMPOUND_ENTITY.finditer(text):
        before = text[max(0, match.start() - 12):match.start()]
        after = text[match.end():match.end() + 15]
        if _FIELD_BEFORE.search(before) or _FIELD_AFTER.search(after):
            continue
        label = match['device']
        if _ENTITY_SUFFIX.search(label) or _LABEL_BEFORE.search(before) or _LABEL_AFTER.search(after):
            devices.add(label.casefold())
    return frozenset(devices)


def _literals(text):
    return (_matches(_NAMED_FIELD, _FIELD_WRITING.sub(lambda match: match[0].replace('-', '_'), text))
            - _devices(text)) | _matches(_ADDRESS, text)


def _observing_devices(text):
    labels = _matches(_DEVICE, text) | device_aliases(text)
    return labels & {match['device'].casefold() for match in _READ_SUBJECT.finditer(text)}


def _protocols(text):
    return protocol_names(text) | _matches(_EXAMPLE_PROTOCOL, text)


def _concepts(text):
    fields = _CONCEPT_LABELS.keys() & (passage_concepts(text) | {match.lastgroup for match in _EXHIBIT_COLUMNS.finditer(text)})
    if '检测倍数' in text and '收发' in text:
        fields.update({'send_interval', 'receive_interval'})
    if re.search(r'隧道.{0,7}(?:状态|Up/|Down/)|会话.{0,5}(?:是否建立|有无建立)', text, re.I):
        fields.add('tunnel_state')
    if ((_LEARNING_ORIGIN.search(text) or re.search(r'哪.{0,6}(?:学到|学习到)|学(?:到|习).{0,10}(?:从|来源|本地|远端)', text))
            and re.search(r'表项|地址|条目|路由|MAC|邻居', text, re.I)):
        fields.add('learning_origin')
    if ('内层' in text and '外层' in text and re.search(r'头部|报头|地址|字段|报文|封装', text)):
        fields.add('packet_headers')
    return fields


def _phases(text):
    phases = set(_PHASE.findall(text))
    for name in _BOTH_PHASES.findall(text):
        phases.update({(name, '前'), (name, '后')})
    return frozenset(phases)


def _source_filters_phases(question):
    phases = set(_phases(question))
    phases.update((action, '前' if when == 'before' else '后') for action, when in operation_phases(question))
    phases.update(step_phases(question))
    if contrast := operation_comparison(question):
        action, (start, stop) = contrast
        for marker in ('前', '后'):
            normalized = question[:start] + action + marker + question[stop:]
            phases.update((event, marker) for event, _ in operation_phases(normalized))
    return phases


def _independent_artifacts(question):
    first, *others = _NEW_ARTIFACT.split(question)
    if not others or _SAME_EXAMPLE.search(question):
        return False
    owners = _devices(first)
    subjects = _protocols(first)
    return any(owners and (other_owners := _devices(other)) and owners.isdisjoint(other_owners)
               and (other_subjects := _protocols(other)) and subjects.isdisjoint(other_subjects)
               for other in others)


@dataclass(frozen=True)
class IllustratedExample:
    protocols: frozenset[str]
    devices: frozenset[str]
    observed_devices: frozenset[str]
    literals: frozenset[str]
    phases: frozenset[tuple[str, str]]
    modes: tuple[str, ...]
    compared_modes: tuple[str, ...]
    roles: frozenset[str]
    concepts: frozenset[str]
    case_ids: frozenset[str]
    witnesses: frozenset[str]
    needs_result: bool
    needs_limit: bool
    measurement: str = ''


def illustrated_example(question: str) -> IllustratedExample | None:
    if _NONLOCAL.search(question):
        return None
    protocols = frozenset(_protocols(question))
    devices = _devices(question)
    observed_devices = _observing_devices(question)
    literals = _literals(question) - protocols
    phases = _phases(question)
    modes = tuple(dict.fromkeys(_MODE.findall(question)))
    mode_set = set(modes)
    conflicting_modes = [pair for pair in _MODE_PAIRS if pair <= mode_set]
    compared_modes = tuple(mode for mode in modes if mode in conflicting_modes[0]) if conflicting_modes else ()
    roles = _roles(question)
    concepts = frozenset(_concepts(question))
    measurement = _MEASUREMENT.search(question)
    if measurement:
        concepts -= {'link_failure'}
    case_ids = frozenset(_CASE_ID.findall(question))
    needs_result = bool(_RESULT_REQUEST.search(question))
    needs_limit = bool(_LIMIT_REQUEST.search(question))
    witnesses = frozenset({'报文捕获', '表格读数'}) if (
        needs_limit and re.search(r'抓包|捕获|报文采集', question) and re.search(r'表|读数', question)
    ) else frozenset()
    if (len(protocols) > 3 or len(case_ids) > 1 or len(conflicting_modes) > 1
            or (compared_modes and not _MODE_COMPARISON.search(question))
            or (not compared_modes and (_SEPARATE.search(question) or _independent_artifacts(question)))):
        return None
    if not (_CASE_REFERENCE.search(question) or (devices and phases and needs_result and (roles or literals or concepts))):
        return None
    # A reference to an exhibit alone is also common in concept explanations.
    # Several named participants plus a requested observation also constrain
    # the example when the question has no standard field name.
    anchored_observation = len(devices) > 1 and (needs_result or needs_limit)
    if not ((protocols or _ADDRESS.search(question) or (observed_devices and literals)) and (devices or literals or case_ids)
            and (phases or modes or roles or concepts or literals or case_ids or anchored_observation)):
        return None
    return IllustratedExample(protocols, devices, observed_devices, literals, phases, modes, compared_modes,
                              roles, concepts, case_ids, witnesses, needs_result or anchored_observation, needs_limit,
                              measurement[1] if measurement else '')


def _source_headings(source):
    body = source['content']
    headings = (body[start:end].strip() for kind, start, end in blocks(body) if kind == 'heading')
    return '\n'.join((source.get('title') or '', *source.get('source_heading_path', ()), *headings))


def _case_scope(source):
    return (source.get('edition_version'), source['document_id'], source['document_version'],
            source.get('source_experiment_key'))


def _linked_scope(source):
    return (*_case_scope(source), source.get('source_phase_key'))


def _evidence(query: IllustratedExample, source, *, linked=False):
    body = source['content']
    title = _source_headings(source)
    context = title + '\n' + body
    subjects = _protocols(title)
    if subjects and query.protocols and subjects.isdisjoint(query.protocols):
        return set()
    participants = _devices(body + '\n' + title)
    if not query.protocols <= _protocols(context):
        return set()
    if not query.devices <= participants and not (linked and query.devices & participants):
        return set()
    if query.case_ids and query.case_ids != set(_CASE_ID.findall(context)):
        return set()
    if query.modes and not set(query.modes) <= set(_MODE.findall(context)):
        return set()
    requested_phases = {name for name, _ in query.phases}
    if any(name in requested_phases and (name, side) not in query.phases for name, side in _phases(context)):
        return set()
    literals = query.literals & _literals(body)
    if query.literals and not literals:
        return set()
    fields = set()
    preceding = ''
    heading_phase = {(name, side) for name, side in _phases(title) if name in requested_phases}
    for kind, start, end in blocks(body):
        part = body[start:end]
        caption = preceding
        preceding = part if kind == 'paragraph' and len(part) <= 400 else ''
        if kind == 'heading':
            phase = {(name, side) for name, side in _phases(part) if name in requested_phases}
            if phase:
                heading_phase = phase
        if kind in {'heading', 'rule'} or _PLAN.search(part) or _UNOBSERVED.search(part):
            continue
        phase = {(name, side) for name, side in _phases(caption + '\n' + part) if name in requested_phases}
        block_phase = phase or heading_phase
        if query.phases and (not block_phase or not block_phase <= query.phases):
            if query.needs_limit and query.measurement and query.measurement in part and _LIMIT.search(part):
                fields.add('判定所需条件')
            continue
        block_fields = set()
        read = _READ_COMMAND.search(part) if kind == 'fence' else None
        owners = _devices(read[0] if read else part)
        sourced_table = kind == 'table' and _TABLE_CAPTION.search(caption) and not (_PLAN.search(caption) or _UNOBSERVED.search(caption))
        if sourced_table:
            owners |= _devices(caption)
        if read and _devices(caption) <= owners and not (_PLAN.search(caption) or _UNOBSERVED.search(caption)):
            part = caption + '\n' + part
        roles = query.roles & _roles(part)
        names = query.concepts & _concepts(part)
        regular = names - {'packet_headers', 'learning_origin'}
        part_literals = literals & _literals(part)
        observed = (query.observed_devices or query.devices) & owners
        actual = (not query.devices or bool(observed)) and bool(
            _ACTUAL_RESULT.search(part) or sourced_table or _FIGURE_VALUE.search(part)
            or (read and _OUTPUT_VALUE.search(body[start + read.end():end]))
        )
        if not query.needs_result or actual:
            block_fields.update('角色 ' + role for role in roles)
            block_fields.update(_CONCEPT_LABELS[name] for name in regular)
            block_fields.update('字段 ' + literal for literal in part_literals)
        descriptive = set()
        capture = _PACKET_CAPTURE.search(caption + '\n' + part)
        if 'packet_headers' in names and capture:
            descriptive.add('packet_headers')
        if 'learning_origin' in names and _LEARNING_ORIGIN.search(part):
            descriptive.add('learning_origin')
        block_fields.update(_CONCEPT_LABELS[name] for name in descriptive)
        witnesses = set()
        if capture:
            witnesses.add('报文捕获')
        if sourced_table or (actual and _TABLE_VALUES.search(part)):
            witnesses.add('表格读数')
        matched_witnesses = query.witnesses & witnesses
        block_fields.update(matched_witnesses)
        evidence_match = roles or regular or part_literals or not (query.roles or query.concepts or query.literals or query.witnesses)
        if query.needs_result and (descriptive or matched_witnesses or (actual and evidence_match)):
            block_fields.add('实际读回')
            if actual:
                block_fields.update('设备 ' + owner + ' 的读回' for owner in observed & query.observed_devices)
        if query.needs_limit and _LIMIT.search(part):
            block_fields.add('判定所需条件')
        if query.measurement and query.measurement in _MEASURED_DURATION.findall(part):
            block_fields.add('实际' + query.measurement + '耗时')
        if block_fields:
            block_fields.update(name + side + '的证据' for name, side in query.phases & block_phase)
            fields.update(block_fields)
    return fields


def _select_one_example(query, sources, limit):
    linked_scopes = {_linked_scope(source) for source in sources
                     if query.devices and source.get('source_experiment_key')
                     and query.devices <= _devices(_source_headings(source) + '\n' + source['content'])}
    candidates = [(source, fields) for source in sources
                  if (fields := _evidence(query, source, linked=_linked_scope(source) in linked_scopes))]
    if not candidates:
        return [], '本次未找到能同时对应所问实验及其字段或阶段的教材证据。可补充章节、图表编号或 PDF 物理页。'
    identity_for = _case_scope if len(query.phases) > 1 else _linked_scope
    scopes = {identity_for(source) for source, _ in candidates}
    if len(scopes) > 1 and query.needs_limit and (query.roles or len(query.concepts) >= 2):
        # A readout with matching labels may be repeated. Scope it only when a
        # single document also addresses the requested roles and evidence limit.
        scope = {'角色 ' + role for role in query.roles} or {_CONCEPT_LABELS[name] for name in query.concepts}
        roles_and_limit = {'判定所需条件'} | scope
        scoped = {identity for identity in scopes if roles_and_limit <= set().union(*(
            fields for source, fields in candidates if identity_for(source) == identity
        ))}
        if len(scoped) == 1:
            candidates = [(source, fields) for source, fields in candidates
                          if identity_for(source) in scoped]
            scopes = scoped
    cases = set().union(*(set(_CASE_ID.findall(source['content'])) for source, _ in candidates))
    states_by_owner = {}
    for source, fields in candidates:
        if '实际读回' not in fields or not (states := _matches(_READOUT_STATE, source['content'])):
            continue
        owners = [owner for owner in query.observed_devices if '设备 ' + owner + ' 的读回' in fields]
        # Different statuses on different named readbacks are normal. Repeated
        # alternatives for the same readback still need a source location.
        for owner in owners or [None]:
            states_by_owner.setdefault(owner, set()).add(states)
    different_readbacks = len(query.phases) < 2 and any(len(states) > 1 for states in states_by_owner.values())
    if len(scopes) > 1 or len(cases) > 1 or different_readbacks:
        return [], '找到多处具有相同线索的教材内容，当前无法确定所问实验。可补充章节、图表编号或 PDF 物理页。'
    chosen = []
    covered = set()
    while len(chosen) < limit:
        source, fields = max(candidates, key=lambda item: len(item[1] - covered))
        if not fields - covered:
            break
        chosen.append(source)
        covered.update(fields)
    missing = [name + side + '的证据' for name, side in sorted(query.phases) if name + side + '的证据' not in covered]
    missing.extend('字段 ' + value for value in sorted(query.literals) if '字段 ' + value not in covered)
    missing.extend('角色 ' + role for role in sorted(query.roles) if '角色 ' + role not in covered)
    missing.extend('设备 ' + owner + ' 的读回' for owner in sorted(query.observed_devices)
                   if '设备 ' + owner + ' 的读回' not in covered)
    missing.extend(label for label in sorted(_CONCEPT_LABELS[name] for name in query.concepts) if label not in covered)
    missing.extend(sorted(query.witnesses - covered))
    if query.measurement and (measurement := '实际' + query.measurement + '耗时') not in covered:
        missing.append(measurement)
    missing.extend(name for wanted, name in ((query.needs_result, '实际读回'), (query.needs_limit, '判定所需条件'))
                   if wanted and name not in covered)
    notice = ''
    if missing:
        known = sorted(covered - {'实际读回', '判定所需条件'})
        found = '本次同例材料可核对' + '、'.join(known) + '。' if known else ''
        notice = found + '尚缺' + '、'.join(missing) + '，请补充对应的章节、图表编号或 PDF 物理页。'
    return [source for source in sources if source in chosen], notice


def select_illustrated_evidence(query: IllustratedExample, sources, limit=6):
    """Keep distinct evidence, checking each explicitly compared mode independently."""
    if not query.compared_modes:
        return _select_one_example(query, sources, limit)
    selected = []
    notices = []
    compared_modes = set(query.compared_modes)
    common_modes = tuple(mode for mode in query.modes if mode not in compared_modes)
    for index, mode in enumerate(query.compared_modes):
        in_mode = [source for source in sources if set(_MODE.findall(_source_headings(source) + '\n' + source['content']))
                   & compared_modes == {mode}]
        reserved = len(query.compared_modes) - index
        capacity = (limit - len(selected)) // reserved
        evidence, notice = _select_one_example(replace(query, modes=(*common_modes, mode), compared_modes=()), in_mode, capacity)
        selected.extend(evidence)
        if notice:
            notices.append(f'「{mode}」：{notice}')
    return selected, ' '.join(notices)


def _comparison_at_prefix(sources, prefixes):
    evidence = []
    covered = set()
    for source in sources:
        body = source['content']
        context = _source_headings(source) + '\n' + body
        if not prefixes <= _matches(_ADDRESS, body):
            continue
        if source.get('truncated') or not (_CLI_PROMPT.search(body) or _ACTUAL_RESULT.search(body)):
            continue
        stages = {match[1] or ('后' if match[0].startswith(('新', '后续', '第二次')) else '前')
                  for match in _RECORD_STAGE.finditer(context)}
        if stages:
            evidence.append(source)
            covered.update(stages)
    # A repeated prefix alone does not identify an experiment.
    if covered != {'前', '后'} or len({_case_scope(source) for source in evidence}) != 1:
        return None
    return evidence


def exclude_conflicting_examples(question, sources):
    """Discard explicitly incompatible subjects and stages before broader prompting."""
    if not sources:
        return sources, ''
    clues = re.split(r'[，。！？；,!?;\n]', question)
    excluded = set()
    excluded_reporters = set()
    excluded_values = set()
    excluded_titles = set()
    exclude_default = False
    omit_examples = False
    positive = []
    for clue in clues:
        if match := _EXCLUDED_REPORTER.fullmatch(clue):
            excluded_reporters.add(match['device'].casefold())
        elif _EXCLUDED_DEFAULT.fullmatch(clue):
            exclude_default = True
        elif match := _EXCLUDED_VALUE.fullmatch(clue):
            excluded_values.add(match['target'].casefold())
        elif match := _EXCLUDED_EXAMPLE.fullmatch(clue):
            named = _protocols(match['material'])
            excluded.update(named)
            title = _MATERIAL_TRAILER.sub('', match['material']).strip(' 「」『』“”《》')
            title = re.sub(r'^(?:书上|书里的?|该书里|课件里|教材里|教材中的?|那套|那次|那个)(?:的)?', '', title)
            if len(title) >= 4 and not (_UNNAMED_MATERIAL.fullmatch(title) or named and re.fullmatch(r'[A-Za-z0-9.-]+', title)):
                excluded_titles.add(title.casefold())
            else:
                omit_examples |= not named and not _devices(match['material'])
        elif _OMIT_EXAMPLES.fullmatch(clue):
            omit_examples = True
        elif not _NO_DEVICE_ACCESS.fullmatch(clue):
            positive.append(clue)
    question = '。'.join(positive)
    if _NONLOCAL.search(question) or _SEPARATE.search(question):
        return sources, ''
    protocols = _protocols(question)
    excluded -= protocols
    if excluded or excluded_titles:
        previous = sources
        sources = [source for source in previous if not (
            ((declared := _protocols(source.get('title') or '')) and declared <= excluded)
            or any(title in _source_headings(source).casefold() for title in excluded_titles)
        )]
        if not sources:
            return sources, '本次未找到符合所问主题的教材依据。可补充章节或 PDF 物理页。'
    phases = _source_filters_phases(question)
    modes = set(_MODE.findall(question))
    case_ids = set(_CASE_ID.findall(question))
    change_comparison = bool(_COMPARE_CHANGE.search(question) and _ASK_FOR_PROOF.search(question))
    has_source_context = bool(_CASE_REFERENCE.search(question) or _RESULT_REQUEST.search(question) or change_comparison)
    observation = bool(_OBSERVATION_ONLY.search(question))
    observers = _observing_devices(question)
    requested_values = _literals(question) - protocols
    requested_prefixes = {value for value in _matches(_ADDRESS, question) if '/' in value}
    principles = bool((_ONLY_PRINCIPLE.search(question) or omit_examples) and not has_source_context and not observation)
    if not principles and not has_source_context:
        return sources, ''
    wanted_actions = {name for name, _ in phases}
    queried_steps = {name for name, side in phases if side == 'ordinal'}
    contains_subject = protocols and any(protocols <= _protocols((source.get('title') or '') + '\n' + source['content'])
                                        for source in sources)
    retained = []
    for source in sources:
        title = _source_headings(source)
        declared = _protocols(title)
        context = title + '\n' + source['content']
        if len(protocols) == 1 and contains_subject and declared and not protocols & _protocols(context):
            continue
        declared_steps = {name for name, _ in step_phases(title)} if queried_steps else set()
        if declared_steps and queried_steps.isdisjoint(declared_steps):
            continue
        exhibited = {(name, side) for name, side in _source_filters_phases(context) if name in wanted_actions and side != 'ordinal'}
        if exhibited and not exhibited & phases:
            continue
        if len(case_ids) == 1 and (source_cases := set(_CASE_ID.findall(title))) and source_cases.isdisjoint(case_ids):
            continue
        found_modes = set(_MODE.findall(title))
        if any(len(modes & pair) == len(found_modes & pair) == 1 and modes.isdisjoint(found_modes & pair)
               for pair in _MODE_PAIRS):
            continue
        if principles and (_CASE_HEADING.search(title) or source.get('source_experiment_key')
                           or omit_examples and _CONCRETE_EXERCISE.search(source['content'])
                           and (_ACTUAL_RESULT.search(source['content']) or _CLI_PROMPT.search(source['content']))):
            continue
        command_owners = {(m[1] or m[2]).casefold() for m in _CLI_PROMPT.finditer(source['content'])}
        stated_owners = command_owners | _observing_devices(source['content'])
        if ((observation or change_comparison) and excluded_reporters & stated_owners
                and (not observers or stated_owners.isdisjoint(observers))):
            continue
        if change_comparison and excluded_values and requested_values:
            source_values = _literals(context)
            if excluded_values & source_values and not requested_values & source_values:
                continue
        if change_comparison and exclude_default and requested_prefixes and not _DEFAULT_PREFIX.search(question):
            if _DEFAULT_PREFIX.search(context) and not requested_prefixes & _matches(_ADDRESS, context):
                continue
        if (len(observers) == 1 and command_owners and observers.isdisjoint(command_owners)
                and observers.isdisjoint(stated_owners)):
            continue
        if (observation and _PLAN.search(title) and not command_owners and not _ACTUAL_RESULT.search(source['content'])
                and not (_LIMIT_REQUEST.search(question) and _LIMIT.search(source['content']))):
            continue
        retained.append(source)
    if change_comparison and requested_prefixes and re.search('前后|之前.{0,40}之后|切换前.{0,40}切换后', question):
        if focused := _comparison_at_prefix(retained, requested_prefixes):
            return focused, ''
    if not retained and phases:
        return [], '本次检索到的教材例证处于其他阶段，未找到与问题阶段相符的材料。可补充章节或 PDF 物理页。'
    if not retained and sources:
        return [], '本次未找到符合指定教材范围的证据。可补充章节、设备角色或 PDF 物理页。'
    return retained if len(retained) < len(sources) else sources, ''
