"""Keep direct and adequately attributed textbook evidence from an existing source list."""
from dataclasses import dataclass
from ipaddress import ip_address, ip_network
import re

from core.markdown_blocks import blocks
from modules.knowledge.evidence_limits import evidence_limit_targets, evidence_limit_witnesses
from modules.knowledge.query_focus import lookup_parts, protocol_names

from modules.ai_text.retrieval import supports_vrrp_mechanism, vrrp_mechanism_queries
from modules.ai_text.source_scope import explicit_physical_scope
from modules.ai_text.example_scope import IllustratedExample, illustrated_example, select_illustrated_evidence


_CIDR = re.compile(r'(?<![\w.:])(?:\d{1,3}(?:\.\d{1,3}){3}|[0-9a-f]*:[0-9a-f:]+)/(?:\d{1,3})(?![\w/])', re.I)
_ADDRESS = r'(?:\d{1,3}(?:\.\d{1,3}){3}|[a-f\d]*:[a-f\d:]+)'
_DEVICE = r'(?<![A-Za-z0-9_-])(?:[A-Za-z]{1,5}-?\d{1,3})(?![A-Za-z0-9_-])'
_TABLE = r'(?:\s*(?:的|上|中|里))?\s*(?:(?:IPv[46]|IP|OSPF(?:v3)?|BGP|IS-?IS|静态)\s*)*(?:路由(?:表|回显|读回)|(?<=\s)表)'
_TABLE_OWNER = re.compile(rf'(?P<owner>{_DEVICE}){_TABLE}', re.I)
_DISPLAY_OWNER = re.compile(rf'(?P<owner>{_DEVICE})\s*的?\s*`?(?:display)\s+(?:ip(?:v6)?\s+routing-table|ospf(?:v3)?\s+routing)', re.I)
_SENTENCE_OWNER = re.compile(rf'^\s*[*\s]*(?P<owner>{_DEVICE})\s*(?:的|指向|收到|到|去往|表中|在)', re.I)
_PHASE = re.compile(r'(汇总|引入|重分发|变更|切换|收敛|故障|恢复|调整)(?:之)?([前后])')
_NEGATED_PHASE = re.compile(r'(?:不引用|不要|不看|只排除|不用)(?:.{0,8}?)?(?:汇总|引入|重分发|变更|切换|收敛|故障|恢复|调整)(?:之)?[前后]')
_CASE_ID = re.compile(r'(?:案例|实验|示例)\s*(\d{1,3})(?!\d)')
_CASE_CAPTION = re.compile(r'\s*(?:\*\*)?(?:案例|实验|示例)\s*\d{1,3}[^。！？\n]{0,48}[。]?(?:\*\*)?\s*\Z')
_RECORD_DEVICE = re.compile(r'(?<![A-Za-z0-9_-])(?:R|AR|PE|CE|NE|FW|SW|S|P|GW|PC|Leaf|Spine)-?\d{1,3}(?![A-Za-z0-9_-])', re.I)
_COMMAND_LITERAL = re.compile(r'(?<![A-Za-z0-9_-])(?:display|show)\s+(?:[A-Za-z0-9_./:-]+[ \t]*){1,10}', re.I)
_TARGET_ARTIFACTS = {
    'setup': re.compile(r'配置(?:步骤|顺序|片段|记录|清单|表|行)|(?:实验|操作)步骤|哪一步|先后顺序', re.I),
    'command': re.compile(r'(?:查看|核对|验证|只读|显示|查询|采集)命令|哪条命令|用什么命令|命令(?:行|是什么)', re.I),
    'readback': re.compile(r'回显|读回|核验结果|实际输出|返回(?:状态|结果|字段)|检验结果', re.I),
    'plan': re.compile(r'规划(?:图|表|稿|方案)|设计(?:图|表|方案)|拓扑图|预期状态', re.I),
}
_MATERIAL_NAMES = {'setup': '配置步骤', 'command': '只读命令示例', 'readback': '设备读回',
                   'plan': '规划内容', 'next_hop': '下一跳', 'cost': '路由代价', 'type': '路由类型'}
_READBACK_LINE = re.compile(r'(?:\b(?:Full|Up|Down|Established)\b|'
                            r'(?:(?:Total|Count|Peer\(s\)|Neighbors?)\s*[:：=]\s*\d+)|'
                            rf'^\s*{_ADDRESS}(?:/\d{{1,3}})?\s+(?:\S+\s+){{1,}}\S+)', re.I)
_READBACK_CLAIM = re.compile(r'(?:回显|读回|实际输出|实际结果)(?:表明|显示|给出|中|为|是|记录到)|'
                             r'(?:邻居状态|接口状态|运行状态|回读结果)\s*[：:]?\s*(?:为|是)?\s*(?:Full|Up|Down|Established)', re.I)
_PLANNED_RECORD = re.compile(r'地址规划|规划(?:为|表|图|设置)|设计(?:图|为|表)|预期(?:拓扑|状态|角色)')
_SETUP_MATERIAL = re.compile(r'#{2,}\s*步骤|配置步骤|以下配置|先配置|\[\w[^\]]{0,64}\]\s*(?:interface|ip |ospf |bgp |isis |vlan )', re.I)
_READBACK_GUIDANCE = re.compile(r'须(?:核对|检查|验证)|请(?:核对|查看)|可查看|之后(?:核对|查看)|未(?:实际|获得|记录)|尚未|'
                                r'没有(?:采集|输出)|预期|建议|\b(?:expected|should)\b', re.I)
_MULTI_TASK = re.compile(r'另外|再(?:看|查|说|问|对照)|还(?:想)?(?:知道|问|查|对照)|两个.{0,7}(?:案例|场景|实验)|'
                         r'(?:前后|分别说|对比|比较).{0,6}(?:场景|案例|实验|阶段)|(?:是否|能否).{0,12}(?:能用|适用|做到|支持)')
_EXTRA_ASK = re.compile(r'还要|同时(?:请)?(?:解释|说明|给出|告诉)|为什么|原因|如果|假设|(?:改|换)(?:成|用)|'
                        r'(?:怎么|如何)(?:配置|修改|操作|计算)|'
                        r'出接口|出口(?:网口|端口)|管理距离|优先级|标志位|标签|标签栈|虚拟路由|(?:两|三|多|\d+)条.{0,6}下一跳')
_UNVERIFIED_PROSE = re.compile(r'规划|计划|拟用|将要|预计|配置(?:为|成)|如果|假设|未(?:能)?(?:找到|显示|记录)|'
                               r'没有(?:找到|记录|显示)|无此(?:条目|路由)|无法核对|可能是')
_CLASSROOM = re.compile(r'教材|课本|课件|教科书|原书|书上|书里|(?:在|这(?:个|一))\s*(?:题设|例题|教学示例)')
_FIELD_CONTEXT = re.compile(r'现场|实机|真机|工单|附件|快照|工作台|最近证据|已(?:经)?保存|正式验收|'
                            r'(?:当前|现在|此刻).{0,8}(?:设备|状态|路由)|(?:这次|最新|刚才).{0,6}(?:采集|读取|读回)')
_COMMAND = re.compile(r'^(?:<([^>]+)>|\[([^\]]+)\])\s*(?:display|show)\s+([^\n]+)', re.I)
_READ_ROUTE_COMMAND = re.compile(r'(?:ip(?:v6)?\s+routing-table|ospf(?:v3)?(?:\s+\d+)?\s+routing|isis\s+route)', re.I)
_TYPE_VALUE = r'(?:O_(?:ASE|NSSA)|E[12]|N[12]|IA|(?:Inter|Intra)[ -]area|Type\s*[12]|ISIS-L[12]|iBGP|eBGP|Direct|Static)'
_FIELDS = {
    'next_hop': (re.compile(r'下一跳|转发下一站|\bnext\s*hop\b', re.I),
                 re.compile(rf'(?:下一跳|\bnext\s*hop\b)[^：。，；\n]{{0,18}}[:：]?\s*`?{_ADDRESS}(?![\w:/])', re.I)),
    'cost': (re.compile(r'开销|代价|\bcost\b', re.I),
             re.compile(r'(?:开销|代价|\bcost\b)[^\d。；\n]{0,12}\d{1,8}(?!\d)', re.I)),
    'type': (re.compile(r'(?:路由)?类型|\btype\b', re.I),
             re.compile(rf'(?<![\w-]){_TYPE_VALUE}(?![\w-])', re.I)),
}
_HEADERS = {'nexthop': 'next_hop', 'next-hop': 'next_hop', 'cost': 'cost', 'type': 'type', 'proto': 'type'}
_ROUTE_HEADER = re.compile(r'(?:Dest(?:ination)?(?:/Mask)?|Prefix)\s+', re.I)
_SHARED_VALUES = re.compile(r'均为|均是|都是|都为|都显示为')
_PREFIX_CONJUNCTION = re.compile(r'[`\s]*(?:、|和|与|及|以及)[`\s]*')
_DIRECT_FIELD_LINK = re.compile(r'[`\s]*(?:的)?\s*\Z')
_SHARED_ROWS = re.compile(r'^\s*(?:这|上述)?([两三])条.{0,30}(?:路由|前缀|表项)')
_DIRECT_VRRP = {
    '监视上行端口': re.compile(r'(?:降低|减小|减少).{0,12}优先级|优先级.{0,12}(?:降低|减小|减少)'),
    '降低优先级': re.compile(r'(?:降低|减小|减少).{0,12}优先级|优先级.{0,12}(?:降低|减小|减少)'),
    '抢占延时': re.compile(r'(?:抢占|回切)(?:延时|延迟)[^。]{0,44}(?:预留|等待|推迟|延后)|'
                           r'(?:预留|等待|推迟|延后)[^。]{0,32}(?:抢占|回切)'),
}
_OTHER_REDUNDANCY = re.compile(r'(?<![a-z0-9])(?:HRP|VGMP)(?![a-z0-9])', re.I)
_REFUTED_VRRP = re.compile(r'(?:不会|不能|不应|无需|未曾|不再)(?:因此|直接|再)?\s*(?:降低|减少|减小|预留|延后|推迟)')
_MECHANISM_PARTS = re.compile(r'[。！？?!，,；;]|以及|另讲|再讲|和|与')
_SOURCE_REQUEST_ONLY = re.compile(r'(?:请)?(?:只讲原理|(?:分别|各自|对应)?(?:给(?:出)?|列出|附)(?:对应)?(?:出处|来源|依据))')
_PORT_RECORD = re.compile(r'(?:端口|接口|(?<![A-Za-z])port)\s*((?:[A-Za-z-]+)?\d+(?:[./:-]\d+)*)(?![A-Za-z\d./:-])', re.I)
_PORT_VALUE = re.compile(r'(?<![A-Za-z])(?:Forwarding|Discarding|Learning|Blocking|Up|Down|Root|Alternate|Designated)'
                         r'(?![A-Za-z])|转发|丢弃|阻塞', re.I)


def textbook_port_lookup(question):
    """Recognize a single port observation without an experiment or device identity."""
    if (not _CLASSROOM.search(question) or not re.search(r'状态|角色|读回|回显', question)
            or _FIELD_CONTEXT.search(question) or _CASE_ID.search(question) or _RECORD_DEVICE.search(question)
            or re.search(r'原理|机制|概念|定义|为什么|如何配置', question)):
        return None
    ports = {match[1].casefold(): match[0] for match in _PORT_RECORD.finditer(question)}
    if len(ports) != 1:
        return None
    return next(iter(ports.items()))


def port_observation_matches(question, hits):
    """Locate records for an otherwise unidentified textbook port."""
    lookup = textbook_port_lookup(question)
    if not lookup:
        return []
    port, _ = lookup
    matched = {}
    for hit in hits:
        if not hit.get('document_id'):
            continue
        for line in re.split(r'[。！？；\n]', hit.get('text') or hit.get('content') or ''):
            for match in _PORT_RECORD.finditer(line):
                if match[1].casefold() != port:
                    continue
                field = re.split(r'端口|接口|(?<![A-Za-z])port', line[match.end():], maxsplit=1, flags=re.I)[0]
                if _UNVERIFIED_PROSE.search(field) or not re.search(r'显示|处于|记录|报告|状态|角色|为|[:：]', field):
                    continue
                if value := _PORT_VALUE.search(field):
                    identity = (hit['document_id'], hit.get('document_version'), hit.get('edition_version'), value[0].casefold())
                    matched.setdefault(identity, hit)
    return list(matched.values())
_MISSING_PROOF = re.compile(r'(?:还|仍|另)(?:差|缺|少|需|要|得)(?:再)?(?:看|查|补|核对|做|测|有)?(?:哪(?:些|种|类)|什么)')
_TEACHING_EXERCISE = re.compile(r'练习|例题|习题')
_SINGLE_RECORD = re.compile(r'(?:只|仅)(?:有|看(?:到|见)?|拿到|找到|给[出了]?|保留).{0,12}(?:一[条份次张个行]|这[条份张个行])')
_BUSINESS = re.compile(r'业务|端到端|数据面|应用|流量|丢包')
_CONTINUOUS = re.compile(r'连贯|连[续通]|一直|全程|整个|中断|没断|不断|持续|无损|无感|丢包')
_ELAPSED = re.compile(r'耗[时费]|时长|用时|用多久|持续时间|完成时间|'
                      r'(?:切换|收敛|恢复|事件).{0,14}(?:毫秒|秒|分钟|时间|\d+(?:ms|s)\b)', re.I)
_CLOCK_COLUMN = re.compile(r'(?<![\w-])(?:time(?:stamp)?|date|last\s+change)(?![\w-])|记录时间|记录时[间刻]|采样时[间刻]|发生时[间刻]', re.I)
_RATE_COLUMN = re.compile(r'(?<![\w-])(?:[kmg]?bps|[kmg]?b/s|speed|(?:bit|link|input|output|rx|tx)[ -]*rate)(?![\w-])|速率|比特率', re.I)
_MEASUREMENT_COLUMN = re.compile(r'(?:开始|起始|结束|完成)时(?:间|刻)|实测(?:时延|耗时|丢包)|丢包率|'
                                 r'(?<![\w-])(?:elapsed|duration|rtt|packet loss)(?![\w-])', re.I)


def _prefixes(text):
    result = set()
    for match in _CIDR.finditer(text):
        try:
            result.add(str(ip_network(match[0], strict=True)))
        except ValueError:
            continue
    return result


@dataclass(frozen=True)
class RouteLookup:
    owner: str
    addresses: frozenset[str]
    fields: frozenset[str]
    protocols: frozenset[str]
    table_protocols: frozenset[str]
    phases: frozenset[tuple[str, str]]
    cases: frozenset[str]


@dataclass(frozen=True)
class ArtifactLookup:
    owners: frozenset[str]
    command: str
    fields: frozenset[str]
    protocols: frozenset[str]
    phases: frozenset[tuple[str, str]]
    cases: frozenset[str]


@dataclass(frozen=True)
class ExampleEvidence:
    sources: list[dict]
    notice: str = ''


def _route_lookup(question):
    tables = list(_TABLE_OWNER.finditer(question))
    owners = {match['owner'].casefold() for match in tables}
    fields = {field for field, (name, _) in _FIELDS.items() if name.search(question)}
    addresses = _prefixes(question)
    phases = set(_PHASE.findall(_NEGATED_PHASE.sub('', question)))
    cases = set(_CASE_ID.findall(question))
    if not owners and (_CLASSROOM.search(question) or phases or cases):
        owners = {match[0].casefold() for match in _RECORD_DEVICE.finditer(question)}
    if len(owners) != 1 or not 1 <= len(addresses) <= 3 or not fields or len(phases) > 1 or len(cases) > 1:
        return None
    return RouteLookup(owners.pop(), frozenset(addresses), frozenset(fields),
                       frozenset(protocol_names(question)), frozenset(protocol_names(' '.join(match[0] for match in tables))),
                       frozenset(phases), frozenset(cases))


def classroom_route_question(question):
    return bool(_CLASSROOM.search(question) and not _FIELD_CONTEXT.search(question) and not _MULTI_TASK.search(question)
                and not _EXTRA_ASK.search(question) and _route_lookup(question))


def _commands(text):
    for match in _COMMAND_LITERAL.finditer(text):
        yield ' '.join(match[0].casefold().split())


def _artifact_lookup(question, *, named_source=False):
    owners = frozenset(match[0].casefold() for match in _RECORD_DEVICE.finditer(question))
    protocols = frozenset(protocol_names(question))
    phases = frozenset(_PHASE.findall(_NEGATED_PHASE.sub('', question)))
    cases = frozenset(_CASE_ID.findall(question))
    fields = {name for name, pattern in _TARGET_ARTIFACTS.items() if pattern.search(question)}
    commands = set(_commands(question))
    if len(owners) > 1 or len(protocols) != 1 or not fields or len(commands) > 1 or len(phases) > 1 or len(cases) > 1:
        return None
    if not (cases or phases or named_source or (owners and commands)) or not (owners or commands):
        return None
    return ArtifactLookup(owners, next(iter(commands), ''), frozenset(fields), protocols, phases, cases)


def _has_readback(text, query):
    """A command to run or a prose suggestion supplies no saved output."""
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith(('```', '~~~'))]
    owner = ''
    for line in lines:
        if line.startswith(('<', '[')):
            match = _COMMAND.match(line)
            call = next(_commands(line), '')
            owner = (match[1] or match[2]).casefold() if match and (not query.command or call == query.command) else ''
        elif (owner and (not query.owners or query.owners == {owner})
              and not _READBACK_GUIDANCE.search(line) and _READBACK_LINE.search(line)):
            return True
    return False


def _artifact_evidence(query, source):
    body = source['content']
    context = str(source.get('title') or '') + '\n' + body
    title_protocols = protocol_names(str(source.get('title') or ''))
    if title_protocols and not title_protocols & query.protocols:
        return set()
    if not _supports_context(query, context):
        return set()
    observed_owners = {match[0].casefold() for match in _RECORD_DEVICE.finditer(body)}
    if not query.owners <= observed_owners:
        return set()
    fields = set()
    blocks_seen = list(blocks(body))
    if _SETUP_MATERIAL.search(body):
        fields.add('setup')
    if _PLANNED_RECORD.search(body):
        fields.add('plan')
    for kind, start, stop in blocks_seen:
        part = body[start:stop]
        owners = {match[0].casefold() for match in _RECORD_DEVICE.finditer(part)}
        if kind == 'fence':
            for line in part.splitlines():
                command = _COMMAND.match(line.strip())
                calls = set(_commands(line))
                if command and (not query.owners or query.owners == {(command[1] or command[2]).casefold()}) and (
                    not query.command or query.command in calls
                ):
                    fields.add('command')
            if _has_readback(part, query):
                fields.add('readback')
        elif kind == 'paragraph' and (not query.owners or query.owners == owners):
            calls = set(_commands(part))
            if calls and (not query.command or query.command in calls):
                fields.add('command')
            if (not _READBACK_GUIDANCE.search(part) and _READBACK_CLAIM.search(part)
              and (not query.command or query.command in set(_commands(part)))):
                fields.add('readback')
    return fields


def explicit_example_lookup(question):
    titles, phrases, pages, _ = lookup_parts(question)
    if (explicit_physical_scope(question) or _FIELD_CONTEXT.search(question) or _MULTI_TASK.search(question)
            or len(question) > 280 or phrases or pages):
        return None
    if not _EXTRA_ASK.search(question):
        if route := _route_lookup(question):
            return route
    return _artifact_lookup(question, named_source=bool(titles))


def example_evidence_query(question, *, allow_explicit=True):
    illustrated = illustrated_example(question)
    if illustrated and illustrated.compared_modes:
        return illustrated
    return (explicit_example_lookup(question) if allow_explicit else None) or illustrated


def prepare_example_evidence(query, sources, limit=6):
    if isinstance(query, IllustratedExample):
        chosen, notice = select_illustrated_evidence(query, sources, limit)
        return ExampleEvidence(chosen, notice)
    if isinstance(query, RouteLookup):
        wanted = {(prefix, field) for prefix in query.addresses for field in query.fields}
        candidates = [(source, _route_evidence(query, source)) for source in sources]
        def label(pair):
            prefix, field = pair
            return f'{prefix} 的{_MATERIAL_NAMES[field]}' if len(query.addresses) > 1 else _MATERIAL_NAMES[field]
    else:
        wanted = query.fields
        candidates = [(source, _artifact_evidence(query, source)) for source in sources]
        label = _MATERIAL_NAMES.__getitem__
    matched = [(source, fields) for source, fields in candidates if fields & wanted]
    chosen = [source for source, _ in matched]
    if not chosen:
        other_materials = [(source, fields) for source, fields in candidates if fields]
        if other_materials and _same_example([source for source, _ in other_materials]):
            available = sorted({label(item) for _, fields in other_materials for item in fields})
            missing = sorted({label(item) for item in wanted})
            return ExampleEvidence([], f'本次只找到同例的{"、".join(available)}，未找到{"、".join(missing)}的对应证据。'
                                       '请补充教材名、章节或 PDF 物理页。')
        return ExampleEvidence([], '本次未找到与所问设备、案例或阶段一致的教材例证。请补充教材名、章节或 PDF 物理页。')
    if not _same_example(chosen):
        return ExampleEvidence([], '本次查到不止一个可能的教材案例或阶段，无法核定所问例子。请补充教材名、章节或 PDF 物理页。')
    chosen = []
    found = set()
    while len(chosen) < limit:
        source, fields = max(matched, key=lambda item: len((item[1] & wanted) - found))
        if not (new := (fields & wanted) - found):
            break
        chosen.append(source)
        found.update(new)
    chosen = [source for source, _ in matched if source in chosen]
    missing = sorted({label(item) for item in wanted - found})
    if not missing:
        return ExampleEvidence(chosen)
    present = sorted({label(item) for item in wanted & found})
    return ExampleEvidence(chosen, f'本次仅核对到同例的{"、".join(present)}，尚未找到{"、".join(missing)}的对应证据。'
                                    '可补充教材名、章节或 PDF 物理页。')


def _supports_context(query, context):
    return (query.phases <= set(_PHASE.findall(context))
            and (not query.cases or query.cases == set(_CASE_ID.findall(context)))
            and query.protocols <= protocol_names(context))


def _supports_table_protocol(query, table):
    declared = protocol_names(table)
    if not declared or not query.protocols:
        return True
    return query.table_protocols <= declared and bool(query.protocols & declared)


def _prose_rows(query, paragraph, heading):
    found = set()
    previous = set()
    for sentence in re.split(r'[。！？；\n]', paragraph):
        prefixes = _prefixes(sentence)
        shared = _SHARED_ROWS.match(sentence)
        carried = bool(not prefixes and shared and len(previous) == {'两': 2, '三': 3}[shared[1]])
        previous, prior = set(), previous
        if not (prefixes or carried) or _UNVERIFIED_PROSE.search(sentence):
            continue
        owner = _SENTENCE_OWNER.match(sentence)
        tables = [match for pattern in (_TABLE_OWNER, _DISPLAY_OWNER) for match in pattern.finditer(sentence)]
        attributed = {match['owner'].casefold() for match in tables}
        if not attributed and owner:
            attributed.add(owner['owner'].casefold())
        if (attributed != {query.owner} and not (carried and not attributed)
                or not _supports_context(query, heading + '\n' + paragraph)):
            continue
        if any(not _supports_table_protocol(query, table[0]) for table in tables):
            continue
        if query.protocols and (named := protocol_names(sentence)) and not query.protocols <= named:
            continue
        previous = prefixes
        mentions = list(_CIDR.finditer(sentence))
        for field in query.fields:
            for claim in _FIELDS[field][1].finditer(sentence):
                if carried:
                    if _SHARED_VALUES.search(claim[0]):
                        found.update((prefix, field) for prefix in prior & query.addresses)
                    continue
                same_list = all(_PREFIX_CONJUNCTION.fullmatch(sentence[earlier.end():later.start()])
                                for earlier, later in zip(mentions, mentions[1:]))
                if len(mentions) == 1 or (all(match.end() < claim.start() for match in mentions)
                                          and (same_list or _SHARED_VALUES.search(claim[0]))):
                    matched = prefixes
                elif before := next((match for match in reversed(mentions) if match.end() < claim.start()), None):
                    matched = (_prefixes(before[0])
                               if _DIRECT_FIELD_LINK.fullmatch(sentence[before.end():claim.start()]) else set())
                else:
                    matched = set()
                found.update((prefix, field) for prefix in matched & query.addresses)
    return found


def _valid_route_value(field, text):
    if field == 'next_hop':
        try:
            ip_address(text)
        except ValueError:
            return False
        return True
    if field == 'cost':
        return text.isascii() and text.isdecimal()
    return bool(re.fullmatch(_TYPE_VALUE, text, re.I))


def _command_rows(query, text, heading):
    found = set()
    owner_matches = False
    headers = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(('<', '[')):
            command = _COMMAND.match(line)
            owner_matches = bool(command and (command[1] or command[2]).casefold() == query.owner
                                 and _READ_ROUTE_COMMAND.search(command[3]) and _supports_table_protocol(query, command[3]))
            command_title = command[3] if command else ''
            headers = []
        elif owner_matches and _ROUTE_HEADER.match(line):
            headers = line.lower().split()
        elif owner_matches and headers:
            values = line.split()
            if len(values) < len(headers) or not (prefixes := _prefixes(values[0]) & query.addresses):
                continue
            fields = {_HEADERS[col] for col, value in zip(headers, values)
                      if col in _HEADERS and _valid_route_value(_HEADERS[col], value)}
            if _supports_context(query, heading + '\n' + command_title + '\n' + line):
                found.update((prefix, name) for prefix in prefixes for name in fields & query.fields)
    return found


def _route_evidence(query, source):
    found = set()
    body = source['content']
    heading = source.get('title') or ''
    caption = ''
    for kind, start, stop in blocks(body):
        part = body[start:stop]
        if kind == 'heading':
            heading = (source.get('title') or '') + '\n' + part
            caption = ''
        elif kind == 'paragraph' and _CASE_CAPTION.fullmatch(part):
            caption = part
        elif kind == 'fence':
            found.update(_command_rows(query, part, heading + caption))
        elif kind == 'paragraph':
            found.update(_prose_rows(query, part, heading + caption))
    return found


def _focused_vrrp(question, sources):
    if re.search(r'\d|回显|哪个字段|示例|案例|配置命令|工单|(?:彼此|相互)影响|之间.{0,6}(?:区别|关系)', question):
        return [], set()
    focuses = vrrp_mechanism_queries(question)
    if len(focuses) < 2:
        return [], set()
    parts = [part.strip() for part in _MECHANISM_PARTS.split(question) if part.strip()]
    if any(not _SOURCE_REQUEST_ONLY.fullmatch(part) and not vrrp_mechanism_queries('VRRP ' + part) for part in parts):
        return [], set()
    wanted = {item.facet for item in focuses}
    selected = []
    for index, source in enumerate(sources):
        content = source['content']
        direct = set()
        for kind, start, stop in blocks(content):
            paragraph = content[start:stop]
            if kind != 'paragraph' or _OTHER_REDUNDANCY.search(paragraph) or _REFUTED_VRRP.search(paragraph):
                continue
            passage = {**source, 'content': paragraph}
            direct.update(facet for facet in wanted if _DIRECT_VRRP[facet].search(paragraph)
                          and supports_vrrp_mechanism(passage, facet))
        if direct:
            selected.append((index, direct))
    return selected, wanted


def _same_example(sources):
    identities = {(source.get('edition_version'), source['document_id'], source['document_version'],
                   source.get('source_experiment_key')) for source in sources}
    case_labels = set().union(*(_CASE_ID.findall(source['content']) for source in sources))
    phases = set().union(*(_PHASE.findall(source['content']) for source in sources))
    return not (len(identities) != 1 or len(case_labels) > 1 or
                any((name, '前') in phases and (name, '后') in phases for name, _ in phases))


def _record_only_limit(question, sources, targets):
    """Bound what one timestamped readback can demonstrate about measurements."""
    if not _SINGLE_RECORD.search(question):
        return None
    needs = []
    for target in targets:
        if _BUSINESS.search(target) and _CONTINUOUS.search(target):
            needs.append('要判断端到端业务是否全程连续，需要同一窗口的连续业务探测或转发采样。')
        elif _ELAPSED.search(target):
            needs.append('要判断事件耗时是否符合要求，需要同次事件的起止记录或直接的耗时测量。')
        else:
            return None
    records = []
    for source in sources:
        body = source['content']
        for kind, start, end in blocks(body):
            if kind != 'fence':
                continue
            # Measurement output in another excerpt warrants review instead of
            # claiming that the readback is all the material for the question.
            if _MEASUREMENT_COLUMN.search(body[start:end]):
                return None
            lines = body[start:end].strip().splitlines()[1:-1]
            owners = [number for number, line in enumerate(lines) if _COMMAND.match(line.strip())]
            if len(owners) != 1 or source.get('truncated'):
                continue
            output = '\n'.join(lines[owners[0] + 1:])
            if _CLOCK_COLUMN.search(output) and _RATE_COLUMN.search(output) and re.search(r'\d', output):
                records.append(source)
    if len(records) != 1:
        return None
    labels = '、'.join(f'「{target}」' for target in targets)
    return records, f'这份教材回显能核对记录时刻和链路速率。它不足以判定{labels}。' + ''.join(dict.fromkeys(needs))


def direct_evidence_limit(question, sources):
    """Keep the direct textbook support for an explicit request to judge a record."""
    if (not (_CLASSROOM.search(question) or _TEACHING_EXERCISE.search(question))
            or _FIELD_CONTEXT.search(question) or _MULTI_TASK.search(question)
            or not _MISSING_PROOF.search(question) or not (targets := evidence_limit_targets(question))):
        return None
    subjects = protocol_names(question)
    candidates = []
    for source in sources:
        body = source['content']
        if (source.get('truncated') or not subjects <= protocol_names(source['title'] + '\n' + body)
                or not (_READBACK_CLAIM.search(body) or _READBACK_LINE.search(body))):
            continue
        if all({'excluded_inference', 'required_observation'} <= set(evidence_limit_witnesses(target, body))
               for target in targets):
            candidates.append(source)
    if len(candidates) != 1:
        return _record_only_limit(question, sources, targets) if not candidates else None
    labels = '、'.join(f'「{target}」' for target in targets)
    notice = f'教材的这个读回不足以判定{labels}。请按所引原文核对还需要的观测。'
    return candidates, notice


def refine_sources(question, sources, edition):
    """Only narrow when every requested direct fact has one coherent example."""
    if (len(sources) < 2 or explicit_physical_scope(question) or _MULTI_TASK.search(question) or _FIELD_CONTEXT.search(question)
            or len(question) > 220 or any(lookup_parts(question)[:3])):
        return sources, 'unchanged_unbounded'
    if any(source.get('edition_version') != edition or not source.get('document_id')
           or not source.get('document_version') or not source.get('section_id')
           or type(source.get('page')) is not int for source in sources):
        return sources, 'unchanged_unverified'
    if (route := _route_lookup(question)) and not _EXTRA_ASK.search(question):
        selected = [(i, facts) for i, source in enumerate(sources) if (facts := _route_evidence(route, source))]
        wanted = {(prefix, field) for prefix in route.addresses for field in route.fields}
        strategy = 'direct_route_record'
    else:
        selected, wanted = _focused_vrrp(question, sources)
        strategy = 'direct_mechanism'
    if not wanted or not selected or not wanted <= set().union(*(facts for _, facts in selected)):
        return sources, 'unchanged_incomplete_proof'
    chosen = [sources[i] for i, _ in selected]
    if not _same_example(chosen):
        return sources, 'unchanged_ambiguous_experiment'
    return (chosen, strategy) if len(chosen) < len(sources) else (sources, 'unchanged_all_direct')
