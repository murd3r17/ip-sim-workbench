"""Versioned current builtins; retain V7-A parameters and historical migrator.

Catalogue requirements describe a task, never grant execution permission.
Runtime checks must resolve the recipient's actual bound environment.
"""
from __future__ import annotations

from copy import deepcopy

from .lab_content import ENVIRONMENT_SPEC, lab_seed_payloads, site_device

CATALOG_VERSION = 'v7d.2026-11-07'
CORPUS = 'knowledge/corpus/huawei-ip/'
OSPF_SOURCE = CORPUS + 'HCIP-Datacom-Core-Lab/01-11-ospf-单区域.md'
IGP_SOURCE = CORPUS + 'HCIP-Datacom-Advanced-RS-Lab/01-1-igp-高级特性实验.md'
BGP_SOURCE = CORPUS + 'HCIP-Datacom-Core-Lab/06-3-bgp-实验.md'
MPLS_SOURCE = CORPUS + 'HCIP-Datacom-Advanced-RS-Training/06-风暴控制dhcp与mpls基础.md'


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


def _interfaces():
    return '；'.join(f"{role}：{site_device(role)['link_interface']}" for role in ('R1', 'R2', 'R3'))


def _requirements(roles, prerequisites, sources, **extra):
    result = deepcopy(ENVIRONMENT_SPEC)
    result.update(label='实验参考参数（运行前按接收方环境绑定核对）',
                  source='环境与部署上下文.md', prerequisites=prerequisites,
                  sources=sources, **extra)
    result['devices'] = [d for d in result['devices'] if d['role'] in roles]
    return result


def _finish(title, description, steps, minutes, requirements, sandbox=False):
    return {'title': title, 'description': description, 'objectives': steps,
            'time_limit_minutes': minutes, 'is_sandbox': sandbox,
            'content_version': CATALOG_VERSION, 'environment_spec': requirements}


def builtin_labs() -> list[dict]:
    """Return detached definitions for the seven existing labs, no DB access."""
    labs = deepcopy(lab_seed_payloads())
    for lab in labs:
        full = '完整版' in lab['title']
        lab['content_version'] = CATALOG_VERSION
        lab['environment_spec'] = _requirements(
            ['R1', 'R2', 'R3'],
            ['三台独立路由器与广播域映射已核对', '运行前保存基线与恢复内容',
             '管理口只读；接口/认证变更需原有权限与确认', 'LoopBack /24参考参数不能替代接收方实际地址计划'],
            [OSPF_SOURCE],
        )
        for step in lab['objectives']:
            step['verification'] = _verification()
            step['verify_contains'] = []
            step['config_hint'] = '以下为参考步骤，先按已绑定角色/接口/地址核对：' + step['config_hint']
        process = lab['objectives'][1 if full else 0]
        process['config_hint'] = process['config_hint'].replace('authentication-mode simple plain huawei',
                                                               'authentication-mode simple plain <由管理员提供的实验认证值>')
        process['expected'] = '实际进程、区域与Router ID符合绑定计划；单次brief输出不能证明认证方式或所有network配置正确。'
        lab['description'] = (
            '沿用三路由器单区域参考环境，接口与地址由环境绑定核对。'
            + ('依次核对地址、OSPF、邻居/路由，再按已满足的前提选做debug、LoopBack、Cost和Silent对比。'
               if full else '精简步骤与完整版共享参数，观察进程、邻居和路由；状态机由教材和实际输出对照。')
            + '管理口不变更；单次邻居或路由输出不证明业务正常。'
        )
        if full:
            lab['objectives'][0]['config_hint'] = lab['objectives'][0]['config_hint'].replace('现场已配好', '参考环境曾配好，当前状态需重新核对')
            lab['objectives'][0]['verification'] = _verification('interface_expectations')
            lab['objectives'][2]['verification'] = _verification('ospf_expectations')
            lab['objectives'][2]['expected'] = '按角色预期核对Full邻居与对端路由；ping与业务转发另行取证，不能由Full代替。'
            lab['objectives'][2]['goal'] = '核对指定邻居、对端路由与环回探测，分别记录证据'
            debug = lab['objectives'][3]
            debug.update(goal='在已授权故障窗口观察邻居状态变化与DR/BDR选举',
                         config_hint='先保存业务接口管理状态，确认管理口保护和恢复方案；按目标版本与教员确认启停接口及debug范围。' + _interfaces() + '。单次轮询可能错过中间状态，不要求逐个抓到所有状态；广播网络DROther之间可停在2-Way。结束关闭本次调试、恢复原接口并核对邻居/路由。',
                         expected='实际记录能解释目标邻居与选举变化；恢复Full或出现DR字样不能单独完成状态机分析。')
            loop = lab['objectives'][4]
            loop.update(goal='对比LoopBack网络类型的通告前缀；先排除不同设备同/24前缀重叠',
                        config_hint='先只读核对各LoopBack实际掩码与LSDB/路由。当前10.0.0.1/2/3均为/24的参考环境有前缀重叠；未提供独立、无重叠的绑定环境前，不执行网络类型修改。专用环境下再按目标版本对照默认主机通告与实际掩码，记录并恢复原值。',
                        expected='能说明通告前缀及本地直连/路由选择的影响；单个包含10.0.0字样的输出不能证明变更正确。')
            cost = lab['objectives'][5]
            cost.update(goal='比较接口Cost变更前后的路径代价，区分接口开销与整条路径开销',
                        config_hint='先保存原Cost、完整路径和对端通告代价；仅对已绑定业务接口按批准值修改，再比较实际路径总Cost，结束恢复原值。' + _interfaces(),
                        expected='观察结果与完整路径代价计算一致，不固定承诺R1=20或R3=10，也不由Cost字段存在判通过。')
            lab['objectives'][6]['config_hint'] = ('先记录目标业务接口与LoopBack的原silent设置，按已批准角色逐项比较Hello/邻居与路由；' + _interfaces() +
                                                   '。未改变其他条件时LoopBack silent通常不撤销其通告；实际路由仍要观察。结束恢复所有本次改变的silent设置并核对，不只恢复业务口。')
        else:
            lab['objectives'][1]['verification'] = _verification('ospf_expectations', components=['neighbors'])
            lab['objectives'][2]['verification'] = _verification('ospf_expectations', components=['routes'])
            lab['objectives'][1].update(config_hint='先核对两端进程、区域、地址/掩码、认证、网络类型与定时器等前提，再观察指定邻居；同一广播域不保证自动Full。',
                                        verify_command='display ospf peer', expected='各角色的指定邻居与状态符合冻结预期，不用其他邻居的Full代替目标。')
            lab['objectives'][2].update(goal='确认指定对端前缀的OSPF路由；业务互通另行探测', verify_command='display ospf routing',
                                        expected='指定前缀与冻结预期一致；路由存在不单独证明业务可达。')
            lab['objectives'][3].update(config_hint='对照教材与实际display ospf peer观察记录解释状态；轮询可能错过中间状态，当前Full不能证明已经观测过完整状态机。',
                                        expected='能用记录解释状态及形成邻接的条件，不以State或Full字样作为理解达标证据。')

    labs.append(_finish('OSPF 与 BFD 联动实验',
        '在已就绪OSPF环境中观察BFD会话与邻居联动，计时测量与业务转发分别记录。', [
        _step(1, 'OSPF与BFD前提及会话', '核对两端OSPF、设备版本、BFD能力与协商定时器',
              '按目标型号官方配置指南核对全局BFD、OSPF进程和业务接口配置，先保存原值；不把进程命令当通用全局命令。' + _interfaces(),
              'display ospf bfd session all', '记录实际会话、对端、接口及状态；BFD Up不单独证明转发正常。'),
        _step(2, 'BFD检测与收敛测量', '区分BFD检测时间、OSPF重计算与业务恢复时间',
              '教员选定可中断的业务接口与回退方案后，分别记录故障时点、BFD/OSPF变化和业务探测；实验后恢复原接口与配置，不操作管理口。',
              'display ospf bfd session all', '有可复核计时、协商定时器和业务探测才能讨论耗时；不能由单次Up输出承诺一秒或毫秒收敛。'),
        ],45,_requirements(['R1','R2','R3'],['OSPF已稳定','两端型号/版本支持BFD且已核对定时器','故障窗口与恢复方案已确认'],[IGP_SOURCE],
                           capability_requirements=['ospf','bfd']),sandbox=True))
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
                           minimum_areas=2,requires_abr_binding=True,unready_reasons=['single_area_not_ready'])))
    bgp_env=_requirements(['R1','R2'],['独立BGP环境，不直接沿用OSPF /24环回方案','AS100/200与互联地址已核对','待发布/32必须在本地路由表精确存在'],[BGP_SOURCE])
    for d in bgp_env['devices']: d['loopback_address']=d['loopback_address'].split('/')[0]+'/32'
    labs.append(_finish('BGP 邻居建立与路由发布实验',
        '在R1/R2独立绑定环境核对eBGP、精确发布前缀及邻居变化；所有变更结束按基线恢复。', [
        _step(1,'基础地址与路由前提','核对互联与LoopBack0 /32及本地精确路由',
              'R1/R2使用本实验独立/32地址计划；现有OSPF参考/24不可直接当作本步骤通过。' + _interfaces(),
              'display ip interface brief','绑定接口与地址正确；IP转发/本地路由另查。','interface_expectations'),
        _step(2,'配置并核对eBGP邻居','核对R1 AS100、R2 AS200及两端对等体地址',
              '在确认的独立环境按设备版本配置对应AS和peer，检查对等体及Established状态；不要用其他邻居的状态代替目标。',
              'display bgp peer','目标对等体、远端AS和状态一致；当前没有受支持BGP结构化证据时由教员核对。'),
        _step(3,'精确发布与最优路由','确认network的精确前缀在本地RIB存在，再核对对端学习',
              '仅发布本实验已绑定且本地精确存在的环回前缀；分别核对本地发布、对端接收、最优状态与下一跳，不能只匹配10.0.0。',
              'display bgp routing-table','指定对端前缀与路径属性有依据；BGP表存在不单独证明业务可达。'),
        _step(4,'中断观察与恢复','对照基线观察目标邻居与路由变化并恢复',
              '只对批准的业务接口操作：' + _interfaces() + '。保存原管理状态；结束恢复并分别核对邻居、路由和业务探测，不固定等待30秒。',
              'display bgp peer','同一目标的中断与恢复有前后证据；Idle/Active/Connect属于可能状态而不是都必须出现。'),
        ],60,bgp_env))
    labs.append(_finish('MPLS LDP 基础实验',
        '核对LSR-ID可达性、LDP能力及目标会话/LSP；没有对应解析能力时保留原输出供教员复核。', [
        _step(1,'LSR-ID与底层可达性','确认独立LSR-ID、底层IGP路由及设备MPLS能力',
              '先绑定两端LoopBack/LSR-ID与实际路由，按目标版本核对全局MPLS/LDP；不把可见LDP字样当成进程或对端正常。',
              'display mpls ldp','LSR-ID、可达路由与所需能力有实际依据。'),
        _step(2,'接口与LDP会话','核对指定业务接口及目标LDP对等体',
              '按绑定角色选择业务接口使能；' + _interfaces() + '。先保存原值，保护管理口。',
              'display mpls ldp session','指定对等体会话达到预期Operational；其他会话不能代替。'),
        _step(3,'目标前缀与标签','核对指定FEC前缀、下一跳和标签映射',
              '读取目标LSP与标签，结合底层路由和转发探测；不只匹配10.0.0字样。',
              'display mpls ldp lsp','目标FEC和标签方向正确；仅有标签不能证明业务恢复。'),
        _step(4,'目标会话中断与恢复','记录指定LDP会话/LSP变化，并恢复原配置',
              '教员确认窗口后仅改变目标业务接口上的LDP，比较对应会话和FEC；恢复原值并重新核对。',
              'display mpls ldp session','目标会话和相关LSP前后变化可解释；不要求或声称整个标签转发表清空。'),
        ],60,_requirements(['R1','R2'],['两端MPLS/LDP能力确认','LSR-ID唯一且底层路由可达','明确目标对等体和FEC'],[MPLS_SOURCE])))
    labs.append(_finish('链路故障排查演练',
        '按基线、现象、恢复与复盘完成维护；故障注入记录与实际设备状态分开。', [
        _step(1,'记录故障前基线','核对指定两端接口、邻居、路由及业务探测范围',
              '分别保存完整接口/邻居/路由观察与时间，先确认已有业务可达性；不由Full推断路由或业务完整。',
              'display ospf peer','有角色/预期匹配的邻居与路由证据；业务基线另证。','ospf_expectations'),
        _step(2,'定位现象与范围','根据实际接口、邻居、路由与探测区分受影响范围',
              '同一目标逐层比较；某接口down、某邻居缺失不单独证明所有路由或业务失败。',
              'display ospf peer','已知与未知分开，不能用任意Full/Init/Down字符串完成步骤。'),
        _step(3,'恢复并核对','按基线恢复目标接口，再核对邻居和路由',
              '按已批准业务接口与原值恢复：' + _interfaces() + '。持续观察至稳定，另做业务验证，不固定等30秒就宣布完成。',
              'display ospf peer','目标邻居与路由符合冻结预期；业务恢复须额外探测。','ospf_expectations'),
        _step(4,'复盘结论','记录现象、证据、假设、变更与恢复边界',
              '查看或显式生成复盘报告；旧报告读取不重新收费。保留缺失项，AI报告不替代技能核验。',
              '', '结论可追溯至本会话原证据；邻居Full不能替代完成复盘。'),
        ],45,_requirements(['R1','R2','R3'],['维护前基线与业务探测范围','故障窗口与原配置恢复方案','明确两端业务接口'],[OSPF_SOURCE])))
    return labs


def workflow_demo_lab() -> dict:
    """The existing seed_sim_devices demo is separate from the seven courses."""
    return _finish('模拟网络巡检实训',
        '演示会话、只读观察、操作记录、笔记与报告回看的工作台流程；故障登记不修改设备，也不代表已经排障或修复。', [
        _step(1,'浏览拓扑与接口','从拓扑/设备定位对象，读取接口状态并记录来源与时间',
              '在设备页选定对象→只读观察→接口状态与地址；区分拓扑关系、设备可连接与业务可达。',
              'display ip interface brief','记录对象、观察时间与未知项；不以拓扑连线或接口Up证明整网正常。'),
        _step(2,'核对故障记录含义','区分本会话故障登记、设备实际观察与已经执行的恢复',
              '会话内的故障登记不连SSH、不改设备。记录假设后用只读事实核对，不把登记/标记已解决当作设备已修复。',
              '', '结论区分记录与设备事实；没有实际前后证据时保留未验证。'),
        _step(3,'保存过程与回看','保存笔记和步骤状态，区分显式生成报告与读取版本',
              '在连续任务中保存笔记/步骤；查看复盘只读已存版本，需要生成时再显式请求。',
              '', '重开会话可读回原笔记，回看报告不再次生成；手动勾选不构成技能达标。'),
        ],60,{'kind':'workflow_demo','requires_binding':True,'binding_status':'unverified',
              'supports_binding':False,'devices':[],
              'prerequisites':['工作台已有纳管设备与拓扑；此条用于流程演示，不生成现场配置指导'],
              'sources':['docs/ops/开发操作手册.md','docs/ai/实训教练提示词与工作台操作手册.md']})
