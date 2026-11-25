"""Recognize authored observations in textbook prose and printed exhibits."""

import re
from ipaddress import ip_address

from .local_provider import _query_tokens
from .query_focus import compact_text, passage_concepts, protocol_names


_READ_ARTIFACT = r"(?:回显|读回|日志|记录|状态表|邻居表|路由表|配置表|输出|读数|抓包|报告)"
_EXHIBIT = r"(?:图中|图里|图上|图注|图题|图例|图示|(?:对照|这个|那张|该)表|表中|表上|表里)"
_ASK = re.compile(r"什么|([哪几谁])[一条个项]?|多少|有没有|是否|怎样|怎么(?:写|填|读|标)|有何(?:区别|变化)|"
                  r"(?:各自|分别|实际)(?:是|为|显示|写|记录|取)|(?:是|为)[^，？]{1,18}[吗呢]|用的是|哪边")
_SEEK = re.compile(rf"{_READ_ARTIFACT}|(?:实际|当时|那轮|当下|当次)(?:看|测|查|读|检)到|"
                   r"(?:从中|在那里|在表里)(?:看|读|查|核对)到|(?:先后|各自)(?:拿到|看到|收到了?)")
_REAL_DEVICE = re.compile(r"(?:请|现在|重新|即时|现场)(?:真正|实际|去)?(?:连接|登录|采集|读取)(?:实际|现场)?设备")
_PROCEDURE_ONLY = re.compile(r"(?:哪条|什么|用啥)(?:只读|查看|核对|读取)?命令|(?:怎么|如何)配置(?:这个|该|它)")
_BACKGROUND = re.compile(r"作为.{0,10}(?:例子|比方)|下文|另一个|另一组|另一份|下一(?:页|步)|建议|用于查看|"
                         r"计划|待验证|预期(?:为|将|会)|预计|理论上|假设|(?<!无)若|如果|应该|应当|将会")
_BOUNDARY = re.compile(r"不能|不足以|不代表|不等于|(?:仍|还)需|仅仅说明|只能证明|不宜|没有证据|尚不能")
_READ_ROLE = re.compile(rf"{_READ_ARTIFACT}|(?:从|由)(?:本次|该次)?(?:验证|读取|统计|结果)|实测|实列|实际(?:读到|显示|观测到|结果|记录|看到)")
_ASSERTION = re.compile(r"显示|记录(?:了|为|中)|读到|列(?:了|为|出|在)|实列|看(?:见|出|到)|找(?:到|出)|"
                        r"标(?:注|出|明)|可见|呈现|写(?:了|为|作)|观察(?:到|结果)|捕获(?:到|的)|测得|回显(?:为|中)|"
                        r"(?:角色|状态|(?:源|目的)区域|下一跳|标签|开销|优先级|计数|数目)(?:均|各自)?(?:[:：=]|为|是)|"
                        r"^\s*\*\*?(?:核对|观察|记录)[^\r\n]{2,50}\*\*\s*")
_DEVICE = r"(?:ar|sw|fw|ce|pe|ne|pc|r|s|p|edge|leaf|spine)[-_]?\d{1,4}(?:[-_][a-z0-9]{1,4})?"
_ISSUER = re.compile(rf"(?<![a-z0-9_-])(?P<owner>{_DEVICE})(?![a-z0-9_/-])\s*"
                     rf"(?:(?:上|的|这一侧|侧)[^，。；\n]{{0,14}})?(?:本次|实际)?\s*{_READ_ARTIFACT}", re.I)
_DEVICE_LABEL = re.compile(rf"(?<![a-z0-9_-]){_DEVICE}(?![a-z0-9_/-])", re.I)
_STATE = re.compile(r"(?<![a-z])(?:up|down|full|init|open|normal|established|discarding|forwarding|backup|master)(?![a-z])|"
                    r"阻塞|转发|稳定|未建立|已建立|没有邻居|无邻居|未恢复|进入|回到", re.I)
_ROLE_VALUE = re.compile(r"主用|备用|指定端口|根端口|替代端口|发送端|接收端|发起端|响应端|上游|下游|"
                         r"(?<![a-z])(?:root|designated|alternate|master|backup|active|passive|client|server)(?![a-z])", re.I)
_DIRECTED = re.compile(r"(?:由|从).{1,45}?(?:发出|发送|发起|应答|返回|下发)|(?:发给|发送给|发送到|请求到|指向)"
                        r"\s*\S|(?:收|收到|接收)(?:自|来自)|(?:发送端|接收端|发起端|响应端)\s*(?:是|为|[:：])")
_ADDRESS = re.compile(r"(?<![a-z0-9.-])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])|(?:[0-9a-f]+:){2,}[0-9a-f:]+", re.I)
_FIGURE_VALUE = re.compile(r"标(?:注|出|明|为)|箭头|线条|连接|接到|记作|填(?:写|入)|显示|列出|表示|"
                           r"不同(?:颜色|线型)|位于|示意|选的是|终点|起点|留空|为空")
_FIGURE_ANCHOR = re.compile(r"(?:红|蓝|绿|灰|黄|黑|白|橙)(?:色)?(?:的)?(?:线|箭头|节点|框|区域)|"
                            r"(?:实|虚|点划)(?:线|箭头)|图\s*\d+(?:[-.－]\d+)?")
_NAMED_CASE_HEADING = re.compile(r"^(?:(?:\d+(?:[.．]\d+)*[.．、]?\s+)|(?:实验|案例|场景)\s*\d+\s*[.．、:：]\s*)?"
                                 r"(?P<name>[^#\n:：]{5,34}?)(?:实验|案例|场景|演练)$")
_GENERIC_CASE_HEADING = re.compile(r"(?:网络|本节|本组|配置|协议|端口|交换机|路由器|设备|命令|功能)?"
                                   r"(?:基础|组网|操作|验证|配置|示例|技术|应用|典型|教学|培训|综合){1,3}$")
_PERSPECTIVE_NAMES = {
    'sender': r'发送(?:端|侧|方)|发包(?:端|侧|方)',
    'receiver': r'接收(?:端|侧|方)|收包(?:端|侧|方)',
    'initiator': r'发起(?:端|侧|方)|请求(?:端|侧|方)',
    'responder': r'响应(?:端|侧|方)|应答(?:端|侧|方)',
    'client': r'客户端|client',
    'server': r'服务端|服务器侧|server',
}
_READ_PERSPECTIVES = {key: re.compile(rf"(?:{name})(?:设备)?(?:的|侧的|这一侧)?[^。；，,\n]{{0,12}}?{_READ_ARTIFACT}", re.I)
                      for key, name in _PERSPECTIVE_NAMES.items()}
_SAME_ARTIFACT = re.compile(rf"^\s*(?:该|这(?:份|张|次|段)?|上述|前述|同一)\s*(?:{_READ_ARTIFACT}|表|图)")
_FOLLOW_ON = re.compile(rf"^\s*\**(?:(?:单凭|只看|仅凭|据|根据)\s*)?"
                        rf"(?:该|这(?:份|张|项|段)?|上述|前述)\s*{_READ_ARTIFACT}")
_OTHER_MATERIAL = re.compile(r"另一次|另一个|另一例|另一份|另一个阶段|下一个步骤|下一例|后一个样例")
_ENTRY_COUNT = re.compile(r"(?:合计|共|有|达到|增至|减至|统计(?:为)?)\s*\d+\s*(?:个|条|项)|"
                          r"(?:表项|条目|路由|前缀|记录|数量|总数)\s*(?:数目|个数|数)?\s*(?:为|是|[:：=])\s*\d+|"
                          r"(?<![a-z])total(?:\s+\w+){0,3}\s*[:=]\s*\d+", re.I)
_PREFIX = re.compile(r"(?:\b\d{1,3}(?:\.\d{1,3}){0,3}|[0-9a-f:]*:[0-9a-f:]+)\s*/\s*\d{1,3}(?![\d/])", re.I)
_INTERFACE_VALUE = r'(?:x?ge|gigabitethernet|ethernet|eth-trunk|vlanif|tunnel|loopback|port-channel)\s*\d+(?:/\d+){0,3}(?:\.\d+)?'
_READING = {
    'next_hop': (r'下一跳|next[ _-]*hop', _ADDRESS.pattern),
    'egress_interface': (r'出接口|出口网口|(?:out|egress)[ _-]*interface', _INTERFACE_VALUE),
    'ingress_interface': (r'入接口|入口网口|(?:in|ingress)[ _-]*interface', _INTERFACE_VALUE),
    'run_priority': (r'(?:运行|生效)优先级|priority[ _-]*run', r'\d{1,4}'),
    'configured_priority': (r'配置优先级|priority[ _-]*config', r'\d{1,4}'),
    'preempt_delay': (r'抢占延[时迟]|delay[ _-]*time', r'\d+(?:\.\d+)?\s*(?:ms|s|毫秒|秒|分钟)'),
    'receive_interval': (r'接收间隔|rx[ _-]*interval', r'\d+(?:\.\d+)?\s*(?:ms|s|毫秒|秒|分钟)'),
    'send_interval': (r'发送间隔|tx[ _-]*interval', r'\d+(?:\.\d+)?\s*(?:ms|s|毫秒|秒|分钟)'),
    'detection_multiplier': (r'检测倍数|detect(?:ion)?[ _-]*mult(?:iplier)?', r'\d{1,3}(?:\s*倍)?'),
}
_FIELD_VALUE = {field: re.compile(rf'(?:{name})\s*[` ]*(?:为|是|[=：:])?\s*[` ]*(?P<value>{value})(?![a-z0-9_./-])', re.I)
                for field, (name, value) in _READING.items()}
_CONFIGURATION_WORDS = re.compile(r'安排为|建议值|将.*配[成置为]|设[置为]|改成|规划|缺省配置|默认值|模板中')
_EXPLANATION_TASKS = (
    (re.compile(r'为什么|什么原因|原因是什么|为何|为什么要|基于什么|根据什么'),
     re.compile(r'因为|由于|所以|因此|从而|导致|取决于|依赖于|原因是|基于|依据')),
    (re.compile(r'(?:有什么|起什么|起到什么|用来做什么|做什么用|什么)作用|用来干什么|用途是什么'),
     re.compile(r'负责|用于|用来|目的在于|作用是|用以|能让|以便|为的是')),
    (re.compile(r'是什么|指的是|说的是|(?:什么|哪个)含义|什么意思|如何理解'),
     re.compile(r'是指|指的是|称为|表示|意味着|体现为|指代|定义为|是一种')),
    (re.compile(r'(?:谁|哪一?(?:侧|端|边|台|方))(?:来|先|负责|主动)?\s*(?:发|收|响应|选择|维护|建立|生成)'),
     re.compile(r'(?:负责|主动|先|由|只由)[^。；，,]{0,30}(?:发送|接收|响应|选择|维护|建立|生成)|'
                r'(?:发送|接收|响应|选择|维护|建立|生成)[^。；，,]{1,32}(?:发往|提供给|来自|分别由|交给)')),
)
_EXPLANATION_FILLER = re.compile(r"(?:(?:这一|这个|那个|本|该)?(?:教材|实验|案例|过程|设备|操作|结果|内容|现象|变化|具体|"
                                  r"机制|原理|情况下|可以|什么|为什么|作用|根据|怎么|如何|实际|显示|发生|状态|角色|"
                                  r"说明|解释|确认|这里|分别|会|呢|吗|一下|然后|再看|多少|哪一个))+|\s+")
_EXPLANATION_OBSERVATION = re.compile(r'哪(?:条|一行|一列)|(?:回显|表中|图中|实际)\s*(?:显示|看到|读出|写|记录)')
_LONG_WORD = re.compile(r'[\u4e00-\u9fff]{4,}|[a-z][a-z0-9_./-]{3,}', re.I)
_AUTHORED_READOUT = re.compile(r'回显|读回|实测|观察到|显示为|读取结果|记录了|记录为|报出')
_UNPERFORMED_READ = re.compile(r'尚未|未曾|未采集|未(?:查|读|做|显示|记录|观测)|没有(?:采集|看到|进行)|'
                              r'(?:可|可以|应|应该|待|需|请|先)(?:再|通过|由|用)?(?:查看|查询|读取|观察|核对)|仅供参考|示例格式')


def readback_request(text: str) -> str:
    """Recognize an explicit request for a printed artifact result or its label."""
    if (not _ASK.search(text) or _REAL_DEVICE.search(text) or _PROCEDURE_ONLY.search(text)):
        return ''
    if _SEEK.search(text):
        return 'readback'
    return 'diagram' if re.search(_EXHIBIT, text) else ''


def authored_readout_clauses(text: str):
    """Keep completed readout clauses for additional same-step context."""
    for clause in re.split(r'[。；！？\n]', text):
        if _BACKGROUND.search(clause) or _BOUNDARY.search(clause) or _UNPERFORMED_READ.search(clause):
            continue
        if (record := _AUTHORED_READOUT.search(clause)) and len(compact_text(clause[record.end():])) >= 3:
            yield clause


def _axis_observed(axis: str, text: str) -> bool:
    if axis in {'role', 'roles', 'port_role'}:
        return bool(_ROLE_VALUE.search(text))
    if axis in {'state', 'status', 'port_state'}:
        return bool(_STATE.search(text))
    if axis in {'direction', 'sender', 'receiver'}:
        return bool(_DIRECTED.search(text))
    if axis in {'prefix', 'address', 'next_hop'}:
        return bool(_ADDRESS.search(text))
    if axis in {'count', 'number', 'entries'}:
        return bool(_ENTRY_COUNT.search(text))
    if axis == 'prefixes':
        return bool(_PREFIX.search(text) or _ADDRESS.search(text) and re.search(r'前缀|网段|掩码|prefix', text, re.I))
    return False


def _figure_anchors(text: str) -> set[str]:
    return {compact_text(re.sub(r'色的?|的', '', item)) for item in _FIGURE_ANCHOR.findall(text)}


def _asked_named_case(text: str, path: tuple) -> bool:
    question = compact_text(text)
    return any(not _GENERIC_CASE_HEADING.fullmatch(title['name']) and compact_text(title['name']) in question
               for _, heading, _ in path if (title := _NAMED_CASE_HEADING.fullmatch(heading)))


def linked_observation_note(original: str, note: str) -> bool:
    """Recognize an adjacent author's explanation of the immediately preceding record."""
    if not (_READ_ROLE.search(original) and _ASSERTION.search(original) and _FOLLOW_ON.match(note)):
        return False
    if _BACKGROUND.search(original) or _OTHER_MATERIAL.search(note) or not (_BOUNDARY.search(note) or _ASSERTION.search(note)):
        return False
    issuers = {match['owner'].casefold() for match in _ISSUER.finditer(original)}
    new_issuers = {match['owner'].casefold() for match in _ISSUER.finditer(note)}
    subjects = protocol_names(original)
    new_subjects = protocol_names(note)
    return not (new_issuers - issuers or subjects and new_subjects and subjects.isdisjoint(new_subjects))


def _has_field_value(field: str, text: str) -> bool:
    if field not in _FIELD_VALUE:
        return False
    matching = tuple(_FIELD_VALUE[field].finditer(text))
    if len(matching) != 1:
        return False
    if field == 'next_hop':
        try:
            ip_address(matching[0]['value'])
        except ValueError:
            return False
    return True


def observed_prose_witness(facet, text: str, path: tuple) -> bool:
    """Require an attributed assertion, with scope and phase checked by the caller."""
    kind = facet.kind
    if kind not in {'readback', 'diagram'}:
        return False
    requested = set(_query_tokens(facet.text))
    requested_concepts = set(facet.concepts)
    heading = '\n'.join(row[1] for row in path)
    figure = kind == 'diagram'
    anchors = _figure_anchors(facet.text) if figure else set()
    perspectives = {key for key, witness in _READ_PERSPECTIVES.items() if witness.search(facet.text)}
    owners = frozenset({facet.observation_owner}) if facet.observation_owner else facet.devices
    if not (owners or facet.subjects or facet.labels or anchors or _asked_named_case(facet.text, path)):
        # Generic terms such as "readback" and "status" occur in unrelated labs.
        # A candidate can still be discovered, but cannot become a direct proof.
        return False
    protocols = protocol_names(text + '\n' + heading)
    if facet.subjects and protocols and facet.subjects.isdisjoint(protocols):
        return False
    for paragraph in re.split(r'\n\s*\n', text):
        previous_issuer = frozenset()
        for clause in re.split(r'[。！？；\n]', paragraph):
            if not clause.strip():
                continue
            if _BACKGROUND.search(clause) or _BOUNDARY.search(clause):
                previous_issuer = frozenset()
                continue
            replaces_issuer = frozenset(match['owner'].casefold() for match in _ISSUER.finditer(clause))
            inherited_issuer = previous_issuer if _SAME_ARTIFACT.match(clause) else frozenset()
            previous_issuer = replaces_issuer if len(replaces_issuer) == 1 else frozenset()
            issuer = replaces_issuer or inherited_issuer
            if figure:
                if not re.search(_EXHIBIT, clause) or not _FIGURE_VALUE.search(clause):
                    continue
                if anchors and not anchors <= _figure_anchors(clause):
                    continue
            elif not ((_READ_ROLE.search(clause) or inherited_issuer) and _ASSERTION.search(clause)):
                continue
            if perspectives:
                declared = {side: witness.search(clause) for side, witness in _READ_PERSPECTIVES.items() if witness.search(clause)}
                if declared.keys() != perspectives or any(not _ASSERTION.search(clause[match.end():]) for match in declared.values()):
                    continue
            if owners:
                observed = {owner.casefold() for owner in _DEVICE_LABEL.findall(clause)}
                if not owners <= observed | issuer or issuer and not owners <= issuer:
                    continue
            if facet.output_fields:
                if (_CONFIGURATION_WORDS.search(clause)
                        or not all(_has_field_value(field, clause) for field in facet.output_fields)):
                    continue
            literal_overlap = len(requested & set(_query_tokens(clause)))
            if literal_overlap < (2 if owners else 3):
                continue
            represented = requested_concepts & passage_concepts(clause)
            has_field = any(compact_text(field) in compact_text(clause) for field in facet.fields)
            axes = facet.observation_axes
            if axes and not all(_axis_observed(axis, clause) for axis in axes):
                continue
            if (represented or has_field or facet.output_fields or axes or owners and (_STATE.search(clause) or _DIRECTED.search(clause))
                    or figure and literal_overlap >= 4):
                return True
    return False


def original_explanation_witness(facet, text: str, path: tuple, *, require_named_case: bool = False) -> bool:
    """Match explicit authored relations using the subject of the user's question."""
    if facet.kind not in {'concept', 'mechanism'} or _EXPLANATION_OBSERVATION.search(facet.text):
        return False
    relations = tuple(written for requested, written in _EXPLANATION_TASKS if requested.search(facet.text))
    if not relations:
        return False
    subject = _EXPLANATION_FILLER.sub(' ', facet.text)
    wanted = set(_query_tokens(subject))
    anchors = set()
    for word in _LONG_WORD.findall(subject):
        if word.isascii():
            anchors.add(word.casefold())
        else:
            anchors.update(word[i:i + 4] for i in range(len(word) - 3))
    named_case = _asked_named_case(facet.text, path)
    if require_named_case and not named_case:
        return False
    if not anchors and not (named_case or facet.subjects and wanted or facet.labels):
        return False
    for clause in re.split(r'[。！？；\n]', text):
        if _BACKGROUND.search(clause) or _BOUNDARY.search(clause) or not any(pattern.search(clause) for pattern in relations):
            continue
        material = compact_text(clause)
        phrase_matches = {label for label in anchors if label in material}
        shared = wanted & set(_query_tokens(clause))
        if (phrase_matches and len(shared) >= 3 or named_case and len(shared) >= 2
                or facet.subjects and len(shared) >= 3 and facet.subjects <= protocol_names(clause)):
            return True
    return False
