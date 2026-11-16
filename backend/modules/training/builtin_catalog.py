"""Versioned current builtins; retain V7-A parameters and historical migrator.

Catalogue requirements describe a task, never grant execution permission.
Runtime checks must resolve the recipient's actual bound environment.
"""
from __future__ import annotations

CATALOG_VERSION = 'v7ux.2026-11-16'
CORPUS = 'knowledge/corpus/huawei-ip/'
OSPF_SOURCE = CORPUS + 'HCIP-Datacom-Core-Lab/01-11-ospf-单区域.md'
IGP_SOURCE = CORPUS + 'HCIP-Datacom-Advanced-RS-Lab/01-1-igp-高级特性实验.md'
BGP_SOURCE = CORPUS + 'HCIP-Datacom-Core-Lab/06-3-bgp-实验.md'
MPLS_SOURCE = CORPUS + 'HCIP-Datacom-Advanced-RS-Training/06-风暴控制dhcp与mpls基础.md'
ORIGINAL_REFERENCES = {
    OSPF_SOURCE: ('corpus-dad972b897a7249a0d24b1a3', 'Core 实验手册 · OSPF 单区域'),
    IGP_SOURCE: ('corpus-33eafbf98e019daab8b9d2ca', 'Advanced RS 实验手册 · IGP 高级特性'),
    BGP_SOURCE: ('corpus-385b7ab61e01e6a7f8fa17d9', 'Core 实验手册 · BGP 基础实验'),
    MPLS_SOURCE: ('corpus-447bfc3dfc040f77058cc721', 'Advanced RS 培训教材 · MPLS LDP'),
}


def _verification(kind='manual_review', **extra):
    return {
        'kind': kind, 'version': CATALOG_VERSION,
        'scope': '当前绑定角色、原步骤和受支持服务端观察；不是整网或业务验收',
        'limitations': ('没有确定性解析/计时或业务证据时由教员复核，不按关键词或AI结论判通过'
                        if kind == 'manual_review' else '错对象、旧版本、空/截断/不支持或未绑定均不能判通过'),
        'expected_from': 'frozen_session_environment', **extra,
    }


def _step(number, name, goal, hint, command, expected, kind='manual_review', **extra):
    return {'id': number, 'name': name, 'goal': goal, 'config_hint': hint,
            'verify_command': command, 'verify_contains': [], 'expected': expected,
            'verification': _verification(kind, **extra)}


def _requirements(roles, prerequisites, sources, **extra):
    return {
        'kind': 'bound_course', 'requires_binding': True, 'binding_status': 'unverified',
        'devices': [{'role': role} for role in roles],
        'prerequisites': prerequisites, 'sources': sources, **extra,
    }


def _finish(title, description, steps, minutes, requirements, sandbox=False, *, source_pages=()):
    if source_pages:
        document_id, source_title = ORIGINAL_REFERENCES[requirements['sources'][0]]
        for step, pages in zip(steps, source_pages, strict=True):
            step['original_sources'] = [
                {'document_id': document_id, 'title': source_title, 'page': page} for page in pages
            ]
    return {'title': title, 'description': description, 'objectives': steps,
            'time_limit_minutes': minutes, 'is_sandbox': sandbox,
            'content_version': CATALOG_VERSION, 'environment_spec': requirements}


def _ospf_courses() -> list[dict]:
    roles = ['R1', 'R2', 'R3']
    compact = _finish(
        'OSPF 单区域基础实验精简版',
        '适合第一次学习 OSPF。观察已有进程、指定邻居和学习到的路由，最后解释一份邻居状态记录。',
        [
            _step(1, '查看 OSPF 进程与区域', '认出三个角色各自的进程、区域和 Router ID',
                  '按本次环境逐台查看现有进程，记录进程号、区域和 Router ID。缺少进程时先记录缺项，请管理员确认实验是否已准备。',
                  'display ospf peer', '记录能对应到三个已绑定角色。根据具体回显确认能读到的字段。'),
            _step(2, '查看指定邻居', '核对邻居身份和状态',
                  '比较两端区域、接口地址、认证、网络类型与定时器。按本次环境预期选中目标邻居。',
                  'display ospf peer', '各角色的目标邻居和状态符合本次预期。', 'ospf_expectations', components=['neighbors']),
            _step(3, '查看指定对端路由', '确认通过 OSPF 学到的前缀与下一跳',
                  '按本次绑定预期查找目标前缀，记录前缀长度、下一跳和学习角色。业务互通另用获准的探测验证。',
                  'display ospf routing', '目标前缀及学习角色与预期一致。', 'ospf_expectations', components=['routes']),
            _step(4, '解释一条邻居状态', '用教材和观察解释状态含义',
                  '记录所见的邻居、状态与时间，解释处于这个状态需要哪些条件。轮询可能错过中间状态。',
                  'display ospf peer', '记录能区分实测到的状态与教材解释。'),
        ],
        45, _requirements(roles, ['绑定三台独立路由器', '准备已有单区域配置与邻居、路由预期'], [OSPF_SOURCE]),
        source_pages=((11, 12), (13,), (14,), (13, 19)),
    )
    full = _finish(
        'OSPF 单区域基础实验完整版',
        '适合已读懂邻居与路由表的学员。先核对三台设备的单区域基线，再在专用环境比较接口和协议参数变化。',
        [
            _step(1, '互联与环回地址核对', '确认三台路由器的互联与环回映射',
                  '按本次绑定逐台读取接口摘要。记录互联、环回接口的地址、掩码和状态。有缺项请管理员核对映射。',
                  'display ip interface brief', '三个角色均有与映射对应的接口观察。', 'interface_expectations'),
            _step(2, '单区域进程与认证', '核对进程、区域、Router ID 与认证方式',
                  '对照管理员提供的区域计划及原配置，记录双方认证方式。需要调整时从受控变更流程提交草稿，保护管理口。',
                  'display ospf peer', '进程、Router ID 与区域匹配，认证方式有独立记录。'),
            _step(3, '核对邻居和环回路由', '分别验证邻居状态与所学前缀',
                  '对每个角色采集邻居和路由。需要验证环回互通时，用批准的源地址和目标另行探测。',
                  'display ospf peer', '指定邻居和路由符合本次预期。业务探测单独记录。', 'ospf_expectations'),
            _step(4, '观察邻居状态与 DR/BDR', '解释指定邻居变化和选举结果',
                  '在已批准的业务接口和时间窗操作，保存原状态。记录变化前后邻居与选举角色，结束恢复并关闭本次调试。',
                  'display ospf peer', '能用目标邻居的前后记录解释变化。广播网络中的 DROther 间可能停在 2-Way。'),
            _step(5, '对比环回通告前缀', '比较主机通告与实际接口掩码',
                  '先查绑定环回的掩码、LSDB 和路由。只有专用环境中的前缀独立且没有重叠时，才按目标版本比较网络类型并恢复原值。',
                  'display ospf routing', '在同一目标前缀看到两次可对照的通告，说明对路由选择的影响。'),
            _step(6, '比较接口开销与路径代价', '理解接口 Cost 如何影响整条路径',
                  '保存目标接口的原 Cost、经过的路径和对端代价。批准后修改业务接口，比较前后总 Cost 并恢复。',
                  'display ospf routing', '观察结果可用完整路径代价解释，并有原值恢复记录。'),
            _step(7, '比较 silent 状态前后', '区分 Hello、邻居与前缀通告的变化',
                  '保存本次绑定业务口和环回的原 silent 设置。选择获准的角色分别对照，结束恢复所有改变并再次观察。',
                  'display ospf peer', '记录清楚目标接口的 Hello、邻居和路由结果，说明哪些行为没有观察到。'),
        ],
        90, _requirements(roles, ['绑定三台独立路由器并确认广播域', '保存基线，确定业务接口、变更窗口和回退条件'], [OSPF_SOURCE]),
        source_pages=((9, 11), (12,), (13, 14), (13, 19), (20, 21), (21, 22), (22, 23)),
    )
    return [full, compact]


def builtin_labs() -> list[dict]:
    """Return detached definitions for the seven existing labs, no DB access."""
    labs = _ospf_courses()

    labs.append(_finish('OSPF 与 BFD 联动实验',
        '在已就绪OSPF环境中观察BFD会话与邻居联动，计时测量与业务转发分别记录。', [
        _step(1, 'OSPF与BFD前提及会话', '核对两端OSPF、设备版本、BFD能力与协商定时器',
              '按绑定设备型号核对全局 BFD、OSPF 进程及业务接口设置，保存原值。记录触发会话的接口与协商定时器。',
              'display ospf bfd session all', '记录实际会话、对端、接口及状态；BFD Up不单独证明转发正常。'),
        _step(2, 'BFD检测与收敛测量', '区分BFD检测时间、OSPF重计算与业务恢复时间',
              '教员选定可中断的业务接口与回退方案后，分别记录故障时点、BFD/OSPF变化和业务探测；实验后恢复原接口与配置，不操作管理口。',
              'display ospf bfd session all', '有可复核计时、协商定时器和业务探测才能讨论耗时；不能由单次Up输出承诺一秒或毫秒收敛。'),
        ],45,_requirements(['R1','R2','R3'],['OSPF已稳定','两端型号/版本支持BFD且已核对定时器','故障窗口与恢复方案已确认'],[IGP_SOURCE],
                           capability_requirements=['ospf','bfd']), sandbox=True,
        source_pages=((8, 16, 17, 18), (18, 19, 20))))
    labs.append(_finish('OSPF 路由过滤实验',
        '在独立多区域环境比较ABR的Type3过滤效果；单区域广播参考环境不具备本实验前提。', [
        _step(1, '确认ABR与过滤对象', '明确ABR的两个区域、过滤方向、目标前缀与应保留控制前缀',
              '不能仅因角色名R3就当作ABR。按目标版本在区域视图核对filter ip-prefix <列表名> import/export；前缀列表需明确目标拒绝与其余允许范围，不使用只deny而未说明后续策略的示例。',
              'display ospf lsdb summary', '区域、ABR、目标与控制前缀都有前置证据；不能以配置条目存在证明过滤生效。'),
        _step(2, '前后路由与LSA比较', '比较指定接收角色的目标前缀消失及控制前缀保留',
              '保留过滤前后同设备/同环境的完整观察，另查Type3 LSA；区分区域LSA过滤、本地RIB过滤和外部路由引入过滤。实验后恢复原策略并核对。',
              'display ospf routing', '过滤前目标/控制均存在，过滤后目标缺失且控制仍在；全表为空或错误设备不能判通过。',
              'route_filter_effect', requires_before_after=True, requires_allowed_control=True),
        ],45,_requirements(['R1','R2','R3'],['至少两个OSPF区域并绑定实际ABR','明确源/接收角色与目标/控制前缀'],[IGP_SOURCE],
                           minimum_areas=2,requires_abr_binding=True,unready_reasons=['single_area_not_ready']),
        source_pages=((8, 22, 25), (23, 24))))
    bgp_env = _requirements(
        ['R1', 'R2'], ['独立 BGP 环境', '管理员已确认两端 AS 和互联地址', '待发布的 /32 前缀在本地路由表精确存在'],
        [BGP_SOURCE], loopback_prefix_length=32,
    )
    labs.append(_finish('BGP 邻居建立与路由发布实验',
        '在R1/R2独立绑定环境核对eBGP、精确发布前缀及邻居变化；所有变更结束按基线恢复。', [
        _step(1,'基础地址与路由前提','核对互联与LoopBack0 /32及本地精确路由',
              '打开设备页，分别选择已绑定的 R1 和 R2。读取接口状态与地址，再查看两台设备的本地精确路由。记录指定环回的 /32 地址和下一跳。',
              'display ip interface brief','绑定接口与地址正确；IP转发/本地路由另查。','interface_expectations'),
        _step(2,'配置并核对eBGP邻居','核对两个绑定角色的 AS 与对等体地址',
              '在确认的独立环境按设备版本配置对应AS和peer，检查对等体及Established状态；不要用其他邻居的状态代替目标。',
              'display bgp peer','目标对等体、远端AS和状态一致；当前没有受支持BGP结构化证据时由教员核对。'),
        _step(3,'精确发布与最优路由','确认network的精确前缀在本地RIB存在，再核对对端学习',
              '选择与本地路由表精确匹配的环回前缀，分别记录本地发布、对端接收、最优状态和下一跳。本课约定使用 /32；教材还演示了发布 /24，按所绑定的训练环境核对。',
              'display bgp routing-table','指定对端前缀与路径属性有依据；BGP表存在不单独证明业务可达。'),
        _step(4,'中断观察与恢复','对照基线观察目标邻居与路由变化并恢复',
              '保存绑定业务接口的原管理状态，按批准的时间窗观察。结束恢复并分别核对邻居、路由和业务探测。',
              'display bgp peer','同一目标的中断与恢复有前后证据；Idle/Active/Connect属于可能状态而不是都必须出现。'),
        ],60,bgp_env, source_pages=((91, 96, 100), (97, 98), (98, 99), (97, 99))))
    labs.append(_finish('MPLS LDP 基础实验',
        '核对LSR-ID可达性、LDP能力及目标会话/LSP；没有对应解析能力时保留原输出供教员复核。', [
        _step(1,'LSR-ID与底层可达性','确认独立LSR-ID、底层IGP路由及设备MPLS能力',
              '先绑定两端LoopBack/LSR-ID与实际路由，按目标版本核对全局MPLS/LDP；不把可见LDP字样当成进程或对端正常。',
              'display mpls ldp','LSR-ID、可达路由与所需能力有实际依据。'),
        _step(2,'接口与LDP会话','核对指定业务接口及目标LDP对等体',
              '按绑定角色选择业务接口，先保存原值，保护管理口。',
              'display mpls ldp session','指定对等体会话达到预期Operational；其他会话不能代替。'),
        _step(3,'目标前缀与标签','核对指定FEC前缀、下一跳和标签映射',
              '读取目标 FEC 的 LSP 与标签，结合底层路由和转发探测，记下所查角色和下一跳。',
              'display mpls lsp','目标FEC和标签方向正确；仅有标签不能证明业务恢复。'),
        _step(4,'目标会话中断与恢复','记录指定LDP会话/LSP变化，并恢复原配置',
              '教员确认窗口后仅改变目标业务接口上的LDP，比较对应会话和FEC；恢复原值并重新核对。',
              'display mpls ldp session','目标会话和相关LSP前后变化可解释；不要求或声称整个标签转发表清空。'),
        ],60,_requirements(['R1','R2'],['两端MPLS/LDP能力确认','LSR-ID唯一且底层路由可达','明确目标对等体和FEC'],[MPLS_SOURCE]),
        source_pages=((365,), (364, 365), (372, 376), (364, 376))))
    labs.append(_finish('链路故障排查演练',
        '按基线、现象、恢复与复盘完成维护；故障注入记录与实际设备状态分开。', [
        _step(1,'记录故障前基线','核对指定两端接口、邻居、路由及业务探测范围',
              '分别保存完整接口/邻居/路由观察与时间，先确认已有业务可达性；不由Full推断路由或业务完整。',
              'display ospf peer','有角色/预期匹配的邻居与路由证据；业务基线另证。','ospf_expectations'),
        _step(2,'定位现象与范围','根据实际接口、邻居、路由与探测区分受影响范围',
              '同一目标逐层比较；某接口down、某邻居缺失不单独证明所有路由或业务失败。',
              'display ospf peer','已知与未知分开，不能用任意Full/Init/Down字符串完成步骤。'),
        _step(3,'恢复并核对','按基线恢复目标接口，再核对邻居和路由',
              '按本次批准的业务接口与原值恢复。持续观察邻居和路由至稳定，另做业务验证。',
              'display ospf peer','目标邻居与路由符合冻结预期；业务恢复须额外探测。','ospf_expectations'),
        _step(4,'复盘结论','记录现象、证据、假设、变更与恢复边界',
              '查看或显式生成复盘报告；旧报告读取不重新收费。保留缺失项，AI报告不替代技能核验。',
              '', '结论可追溯至本会话原证据；邻居Full不能替代完成复盘。'),
        ],45,_requirements(['R1','R2','R3'],['维护前基线与业务探测范围','故障窗口与原配置恢复方案','明确两端业务接口'],[OSPF_SOURCE]),
        source_pages=((13, 14), (19, 20), (19, 20), ())))
    return labs


def workflow_demo_lab() -> dict:
    """The existing seed_sim_devices demo is separate from the seven courses."""
    steps = [
        _step(1, '读取一台设备的接口', '从拓扑选一台设备，找出一条可读的接口记录',
              '点「看拓扑」，记下设备名。到「设备」选择同一设备，点「只读观察」，选择「接口状态与地址」。从结果记下一条接口的地址、物理状态、协议状态和观察时间。',
              'display ip interface brief', '笔记里的设备、接口、状态和时间与观察一致。'),
        _step(2, '写下一个判断', '根据一条记录说明知道什么，还缺什么',
              '用刚才的接口回显写一句判断。如接口显示 Up，可以确认样例中的接口状态。业务是否可达需要另一条证据。故障登记不连SSH、不改设备。',
              '', '判断能对应观察，未知项另有说明。'),
        _step(3, '保存并回看', '确认自己能从会话历史找回记录',
              '点「保存笔记/步骤」，关上窗口，从顶部实训条重新打开检查内容。确认记录已保存后结束，再从「我的实训会话」回看。',
              '', '能从历史读到刚才的观察与判断。复盘可按需生成。'),
    ]
    steps[0]['record_example'] = '填入自己的观察。设备［名称］，接口［名称］，地址［地址］，物理/协议［状态］，时间［回显时间］。'
    steps[1]['record_example'] = '如果看到接口 Up，可写「这条接口显示工作中，业务可达性待核对」。'
    for step in steps:
        step['verification'].update(scope='本地接口观察与记录', limitations='按本步的判断依据自查。')
    return _finish('模拟网络巡检实训',
        '适合第一次使用工作台。完成一次只读接口观察、写下判断并从历史找回记录。', steps,
        15, {'kind':'workflow_demo','requires_binding':True,'binding_status':'unverified',
              'supports_binding':False,'devices':[],
              'prerequisites':['本机以模拟方式运行，工作台已有设备与拓扑'],
              'sources':['docs/ops/开发操作手册.md','docs/ai/实训教练提示词与工作台操作手册.md']})
