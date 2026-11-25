"""Recognize study context, workbench navigation, and read-only workflow explanations."""
from __future__ import annotations

import re

from modules.knowledge.query_focus import protocol_names
from . import skills


_LEARNING_OBJECT = re.compile(
    r"(?:教材|课本|书上|书中|书里|课件|习题|例题|练习题|题目|题图|题设|教学(?:示意)?图|"
    r"课堂(?:练习|示意图)|示意图|教材图|协议示例|推演示例)"
)
_LEARNING_ACTION = re.compile(
    r"怎么看|怎么读|怎么理解|解释|含义|代表|为何|为什么|哪(?:个|一|两)|如何|会不会|是不是|是否|"
    r"比较|对比|区别|含义|举例|定义|说一下|是什么意思|推演|画着|画的是|写的是"
)
_TEACHING_NOT_LIVE = re.compile(r"(?:用|按|依据|根据|结合|就|看|做的?|以).{0,4}(?:教材|课本|课件|"
    r"教学(?:示意)?图|课堂示意图|例题|练习题|题设)|(?:教材|课本|课件|示意图|题图|题设|例题|练习题)"
    r"(?:上|里|中|中的|上的|里的|画着|画的是|给出|给了|显示|出现|提到|提过|用了|的|这[张幅道页]|那[张幅道页])")
_TEACHING_SOURCE = re.compile(r'教材|课本|课件|讲义|原书|知识库|(?:教材|教学)截图|题设|例题')
_TEACHING_RECORD = re.compile(r'案例|实验|示例|证据|冲突|命令|步骤|操作顺序|回显|输出|图|说明|核对|查找|字段|写的是|'
                              r'怎么|如何|哪(?:个|一|条|步|段)|各是什么|是什么|是多少', re.I)
_TEACHING_ANAPHOR = re.compile(r'本节|这(?:一)?章|这(?:个)?例子|本例|图里的|资料里|书里的|本(?:张|条)截图')
_GUIDED_PAGE = re.compile(r'^请只根据本地教材《[^》\n]+》PDF 第 (?P<page>[1-9][0-9]{0,5}) 页回答。'
                          r'本页没有依据的内容请指出。')
_SKIP_TEACHING = re.compile(r'(?:不查|不按|不要看|不参考|不用|改看现场).{0,5}(?:教材|课本|知识库|课件)')
_TEACHING_NAVIGATION = re.compile(
    r'(?:入口|菜单|按钮|页签).{0,8}(?:怎么用|什么意思|什么含义|在哪|如何使用)|'
    r'(?:打开|进到|进入|回到|返回|跳转).{0,8}(?:同版书页|同版正文|书页|片段详情|资料目录|原教材页位|教材正文|知识库页面)'
)
_CLEAR_NEW_READ = re.compile(r'(?:现在|立刻|马上|此刻|本次|重新).{0,14}(?:采集|读取|新读|执行)|'
                             r'真实设备|真机|实机|现场设备|(?:当前|目标)设备|模拟设备')
_PREVIOUS_RECORD_CONTEXT = re.compile(r'话术|怎么说|原句|步骤里|命令的含义|用于课堂|写在(?:表|图|书|讲义)')
_FRESH_DEVICE_ACTION = re.compile(
    r"(?:现在|请(?:帮我)?|帮我|重新|再|去|实际|现场)\s*(?:实际|重新|现在|现场|再|去)?\s*"
    r"(?:采集|读取|登录|连接|执行|查询|检查|查看)\s*.{0,24}"
    r"(?:真机|设备|接口|邻居|路由表|命令|\bdisplay\b|\bshow\b|" + skills.DEVICE_LABEL_PATTERN + r")", re.I)
_EXPLICIT_FIELD_REFERENCE = re.compile(r"本次(?:实采|现场采集|真的读)|当前真机|真实设备刚采|已核验的本次观察")
_UI_INTENT = re.compile(r"(?:从哪|去哪|哪里|在哪|点哪|哪个(?:菜单项|控件|选项|入口|钮)|按钮|菜单|导航|"
    r"打开|关闭|收起|展开|返回|退回|回到|跳转|切到|切回|如何操作|怎么操作|从哪找|怎么(?:进|开|关|退)|"
    r"能做什么|会做什么|各做什么|各有(?:什么|何)用)"
)
_EXPLICIT_UI_CONTEXT = re.compile(r"工作台|页面|界面|左侧|侧栏|页签|顶部|功能入口|应用里|这个软件|按钮|菜单|卡片")
_READING_UI_OBJECT = re.compile(r"原(?:教材)?页|教材正文|教材原图|全文|片段详情|引用(?:卡|详情|原文)|资料目录|保存的记录|"
    r"原回答|操作日志|原图|实训详情|实验详情|继续实训|巡检报告|配置差异|核对回读|审批详情|"
    r"正文读完|阅读定位|版本记录|已保存的报告|已保存巡检|片段回到书页")
_FOLLOWUP = re.compile(r"^(?:请|再|那|同样|继续|接着|刚才|还有|具体|进一步|这个|这种|其中|它|前面|上面)|"
    r"(?:还是|仍然)(?:那|这|原)|(?:换|切).{0,20}(?:页|窗口|面板).{0,20}(?:那|继续|还是|刚才|同样)")
_DEICTIC = re.compile(r"它|这种|这个|那条|那项|这一项|两者|刚才|上一个|前面|原来|仍然|同样|同一|其中|继续|接着")
_INTENT_RESET = re.compile(r"换(?:个|一)(?:题|话题|协议)|另一个问题|另问|新问题|不聊.{0,8}(?:了|改问)|改问|"
                           r"不查教材|不用书上|不看教材|改看现场|现在查实机")
_NEW_ACTOR = re.compile(r"(?:现在|这次|请).{0,8}(?:读|采|查).{0,12}(?:实机|真机|设备|接口|邻居|路由表)")
_STATE_QUESTION = re.compile(r"含义|代表|能否|可以|是否|算|区别|完成|说明|保存|凭|证据|回读|实机|真机|模式|还差|还要|会不会")
_APPROVAL_PAGE = re.compile(r'变更审批|审批(?:详情|页|单|列表|记录)|配置批次')
_APPROVAL_STATUS = re.compile(r'已确认|已批准|已审批|审批通过|批准通过|确认(?:后|通过|状态|没有)|'
                              r'待核对|执行回执|(?:已经|已)(?:发起|开始)(?:验证|核验|回读)|验证(?:通过|结果|报告)|核验(?:通过|结果|报告)|'
                              r'核对回读|确认演练结果|查看结果|(?:核验|验证|回读).{0,6}(?:哪里|怎么看|怎么查)')
_START_VERIFICATION = re.compile(r'(?:怎么|如何|怎样|从哪里|在哪|去哪|点(?:什么|哪个)).{0,12}'
                                 r'(?:(?:发起|开始|启动|触发|执行|提交).{0,8}|做\s*)(?:核验|验证|回读|演练确认)|'
                                 r'(?<!已)(?<!已经)(?<!刚刚)(?<!刚才)(?:发起|开始|启动|触发|执行|提交).{0,8}(?:核验|验证|回读|演练确认)'
                                 r'.{0,8}(?:在哪里|怎么做|如何做|用哪个按钮)|'
                                 r'(?:怎么|如何|怎样)\s*点(?:击)?[「“]?\s*(?:核对回读|确认演练结果)')
_NO_START_VERIFICATION = re.compile(r'只(?:想|要)?(?:看|查|读|核对)(?:一下)?(?:已有|之前|已保存|历史|是否|是不)|'
                                    r'(?:不要|不用|无需|不想|避免|禁止|别).{0,6}(?:发起|开始|启动|触发|执行|重新)')
_NEGATED_UI = re.compile(r"(?:不问|没问|不是在问|不用讲).{0,10}(?:按钮|菜单|入口|界面|页面)")
_SAVED_READ_REFERENCE = re.compile(
    r'(?:已保存|已存|存档|历史|刚才|先前|此前|上一轮|前一次|原有|原来|原来的|这份|这条|本次|那份|那条)'
    r'.{0,12}(?:记录|观察|证据|回显|结果|快照)|(?:记录|观察|证据|回显|快照).{0,9}(?:哪台|对象|何时|时间|还有效)'
)
_FRESH_READ_MARKER = re.compile(r'现在(?:就)?|立刻|马上|这次重新|本次重新|重新|再(?:次|读|查|采)|实机|真机|新采集|最新')
_READ_FIELD = re.compile(r'接口|邻居|路由表|真机|实机|设备状态|设备回显|设备输出|设备上|当前状态|\bdisplay\b|\bshow\b', re.I)
_DIRECT_READ = re.compile(r'^(?:(?:我同意你|我授权你|请|帮我|替我|麻烦|现在|立刻|马上|可以|能否|能不能|只读|先|再|重新|实际|现场)\s*)*'
                          r'(?:采集|读取|读一下|查一下|查询|查看|检查|核对|看一下|执行\s*(?:只读\s*)?(?=display|show))', re.I)
_DIAGNOSTIC_READ = re.compile(r'^(?:请|帮我|麻烦).{0,16}(?:排查|诊断|定位).{0,66}(?:先|请|再|实际|现在).{0,8}'
                              r'(?:采集|读[取出]?|查[看询]?|核对|检查)(?:两端|各台|两台|的|\s)*(?:接口|邻居|路由表|设备状态)')
_READ_DENIAL = re.compile(r'(?:不要|不用|不许|禁止|无需|不必|别)(?:先|再|重新|实际|现在|现场|去|\s)*'
                          r'(?:执行|采集|读取|读一下|查一下|查询|查看|检查|核对)')
_SCENARIO_FRAME = re.compile(
    r'(?:^|[。；，：\s])(?:先|我们)?(?:假设|假定|设(?=\s|有|定|两|三|[A-Z]+\d))|'
    r'题设|题图|示意图|(?:这|那|本)(?:一)?[张幅]图例|示例(?:中|图|拓扑)|附例|这(?:个|一)例|本例|例(?:子)?中|按图|图中|图里|图上画|'
    r'(?:给定|已知|如下|下列).{0,12}(?:拓扑|组网|场景|条件)|'
    r'(?:拓扑|组网|场景)(?:是这样的|如下|设为)|(?:如果|若).{0,36}(?:会|应该|应当|那么|将)'
)
_NETWORK_REASONING = re.compile(
    r'(?:哪(?:一|几)?[条个项种步两]|什么|怎样|怎么|如何).{0,12}(?:命令|步骤|回显|输出|字段|状态|阶段|顺序|角色)|'
    r'(?:命令|步骤|回显|输出|字段|表项|状态|阶段|顺序|角色|证据).{0,12}(?:为什么|怎么理解|什么意思|含义|表示|说明|区别|'
    r'能(?:否|不能)证明|证明了什么|应该|应当|会(?:变|保持|显示|变成)|是什么)|'
    r'两(?:条|段|份).{0,6}(?:回显|输出|证据).{0,14}(?:为准|优先)|'
    r'(?:该|应|要)先(?:看|读|查|核对).{0,18}还是.{0,14}(?:看|查|读|核对)', re.I,
)
_NETWORK_ARTIFACT = re.compile(r'\b(?:display|show)\s+\S|\btrunk\b|路由表|邻居表|转发表|接口回显', re.I)
_TABLE_REFERENCE = re.compile(r'(?:这|那|本|另(?:外)?|同一)(?:一)?(?:张|个)表|表(?:格)?(?:里|中|上)')
_READOUT_REFERENCE = re.compile(r'(?:读回|回显|实际输出)(?:上|中|里|里的)|(?:这份|那份|上述)(?:读回|回显|输出)')
_WRITTEN_ACCOUNT = re.compile(r'正文|原文|叙述|图注|注释|说明段|说明文字|解说词|文字说明|文字描述|'
                              r'(?:这|那|前|后)一?段(?:话|.{0,12}(?:说|写|提到|记载|给出))')
_PROOF_BOUNDARY = re.compile(
    r'(?:能(?:否|不能)?|可否|是否|足以|可以).{0,12}(?:证明|支持|推出|推断|印证|佐证|得出|认定|代表|算作)|'
    r'(?:只|最多|仅|至多)(?:能|可)?.{0,8}(?:证明|支持|证实|说明|判断|推出|推到|得出)|'
    r'(?:证据|依据|记录|结论).{0,10}(?:边界|限度|够不够|到哪|止于|撑到|支持范围)|'
    r'(?:合成|合并为|并进|作为|算作|当作|认作|写成).{0,10}(?:同一|一次)',
)
_REAL_OBSERVATION = re.compile(
    r'(?:当前|现在|此刻|最新|目前|这次|本次|现场|生产).{0,12}(?:状态|设备|接口|链路|邻居|路由|采集|回显|告警|任务)|'
    r'(?:状态|设备|接口|链路|邻居|路由|回显).{0,12}(?:当前|现在|目前|此刻)|真机|实机|真实设备|'
    r'我(?:刚|已经|们刚|们已经).{0,10}(?:采集|测到|读取|抓到|查到|观察到)|我的(?:设备|网络|现场)|'
    r'(?:重新|实际).{0,4}(?:采集|读一下|读取|查询)|'
    r'(?:刚才|刚刚|此前|前一次|上回).{0,6}(?:采集|读取|采样)|'
    r'最近证据|历史(?:观察记录|回显|设备输出)|已保存.{0,8}(?:观察|记录|回显)|'
    r'(?:这份|这条|本次|所选)(?:采样|样本)(?:记录|的|里|中|时间|时点)'
)
_EXISTING_OBSERVATION = re.compile(r'已有.{0,8}(?:观察|记录|回显)')
_OBSERVATION_POINTER = re.compile(r'这些数字|这(?:个告警|台设备|条链路)|这个观测|本次读数')
_OPERATIONAL_FOLLOWUP = re.compile(r'^(?:那|同样|照旧|再|接着)|(?:更正|对象改为).{0,18}(?:同样|照样)(?:读取|查询|读一下)')
_LEAVE_SCENARIO = re.compile(r'^(?:另外|另请|改为|改问|转到实际|脱离)')
_ACTUAL_READ_LANGUAGE = re.compile(r'(?:实际|现场|真机|实机|真实).{0,8}(?:采集|读取|查询|查看|执行|设备)')
_REQUEST_CLAUSE = re.compile(r'(?:^|(?P<separator>[。，；、？！;,!?\n]))(?P<clause>[^。，；、？！;,!?\n]+)')
_READ_MODES = (
    ('sim', re.compile(r'模拟(?:器|设备|环境)|演练(?:设备|环境)')),
    ('ssh', re.compile(r'真实(?:设备|环境)|真机|实机')),
)
_SAVED_PAGE_VIEW = re.compile(r'只(?:想|要)?(?:抄|看|查|读|核对).{0,9}(?:保存|已有|留存|图上|历史)|'
                              r'不(?:打算|用|要|需|必).{0,8}(?:发起|验证|采集|探测|读设备)')
_TOPOLOGY_RECORD = re.compile(r'连接线|连线|用线|链路|两端|图上.{0,6}关系')
_DEVICE_RECORD = re.compile(r'设备列表|在线标志|上次可达|最近证据|保存的连接状态')
_READ_NAVIGATION = re.compile(r'点|按钮|哪里|在哪|从哪|怎么(?:看|查|找|打开|回去)|如何(?:看|查|找|打开|回去)|入口|路径|步骤|回到')
_TRAINING_PREVIEW = re.compile(r'先修|环境要求|课前.{0,5}(?:准备|要求)|预习|预览.{0,6}(?:课|实验|实训)')
_TRAINING_START_NAVIGATION = re.compile(r'(?:怎样|如何|怎么|哪里|在哪|点哪个).{0,10}(?:开始实训|新开会话|创建会话)')
_ORIGINAL_QUOTE = re.compile(r'原书原句|(?:复制|可选|选中).{0,12}(?:原文|文字|原句|那行)|'
                             r'(?:原文|原句|那行).{0,12}(?:能复制|可复制|能选中)|近义改写|逐字查')
_BOOK_VIEW = re.compile(r'原书|原页|原图|原版\s*PDF|老师.{0,8}(?:那|这|一).{0,5}(?:页|图)|查看同版正文|阅读同版正文', re.I)
_BOOK_RESULT = re.compile(r'命中|检索结果|查询结果|筛选|资料目录|原来.{0,6}列表')
_BOOK_RETURN = re.compile(r'退回|返回|回到|回去|读完|看完|关(?:闭|掉)|保留|不(?:丢|重来|清空|用重新)|避免重')
_CHAT_REFERENCE = re.compile(r'引用|出处|来源')
_CHAT_SOURCE = re.compile(r'回复|回答|对话|助手|(?:上一轮|刚才).{0,10}引用')
_CHAT_REF_STATUS = re.compile(r'还(?:在|能|保留|有效)|仍(?:能|可)|失效|撤权|(?:能否|是否).{0,12}(?:留|读|看|打开|版)|是哪一?版|看哪一?版')
_MONITOR_SAVED = re.compile(r'已保存|已有|已存|现有|历史|只看|只想看|不.{0,5}(?:新建|重新|再).{0,5}采|重新(?:加载|显示)|刷新|切换|所选|计数|暂无')
_MONITOR_VIEW = re.compile(r'图表|曲线|大盘|面板|趋势|采样|样本|采集时间|时间戳|刷新已保存记录|保存的监控记录|拓扑图')
_MONITOR_SCOPE = re.compile(r'图表.{0,4}巡检范围|(?:下拉|切到|切成|切回|换到|换成|选成|选了|所选|这个|另一|另一个).{0,9}(?:拓扑|范围)|'
                            r'这个范围|当前范围|所选范围|下面.{0,6}(?:图|曲线)')
_MONITOR_SAVED_STATUS = re.compile(r'样本|采样|实际.{0,5}时间|时间戳|数据|记录|告警|健康|(?:上面|顶部).{0,8}(?:数字|统计|计数)|'
                                   r'哪(?:一)?次|哪(?:一)?条|最近|最新|有无|空图|空白')
_MONITOR_NEW_ACTION = re.compile(r'(?:^|[，。；])(?:帮我|请(?:马上|现在|立即|直接)|立即|现在就).{0,8}(?:采集指标|巡检并保存报告|重新采样)')
_MONITOR_TIME = re.compile(r'(?:采样|采集).{0,7}(?:时间|时点|时刻|时间戳|几点|何时|是什么时候)|(?:最近|最新|上次)采样|'
                           r'(?:哪一?刻|几点|何时|什么时候).{0,6}(?:采样|采集)')
_LATEST_MONITOR_SAMPLE = re.compile(r'(?:最近|最新|上次|所选拓扑|这个拓扑|另一拓扑|当前范围|暂无).{0,12}(?:采样|样本)|'
                                    r'(?:有没有|有无|是否有|是否存在).{0,12}(?:样本|采样)')
_MONITOR_EMPTY_CHART = re.compile(
    r'没(?:有)?(?:画出|出来|显示|出现)?\s*(?:图|曲线|趋势|样本|采样)|'
    r'(?:图表|曲线|趋势|样本|采样).{0,8}(?:空白|没有|没显示|暂无)|暂无(?:图|曲线|趋势|样本|采样)|空图'
)
_MONITOR_SCOPE_VERDICT = re.compile(r'健康|(?:都|全|状态|设备|就|算).{0,6}正常|告警|报警|故障|事件|零(?:条|个)')
_PORT_VIEW = re.compile(r'端口观察|刷新观察|(?:端口|接口)(?:的)?(?:最近|最新|上次|已存|保存的)?(?:样本|采样|明细)')
_SIMULATION_RECORD = re.compile(r'(?:模拟|演练).{0,12}(?:记录|结果|回执|已完成)|只保留(?:模拟|演练)')
_REPORT_CLAIM = re.compile(r'怎么写|如何写|怎么记|如何记|交接|总结|能.{0,6}写|可以.{0,6}写|能否.{0,6}说|'
                           r'能.{0,12}(?:证明|算成).{0,10}(?:生产|真机|真实|回读)')
_SINGLE_SNAPSHOT = re.compile(r'(?:单条|单份|一个|某条|一条|某个|这条|该条|目标).{0,8}(?:快照|已保存.{0,4}版本)|'
                              r'(?:已保存|已有|历史).{0,8}(?:配置快照|配置版本|版本|快照)')
_SNAPSHOT_DOWNLOAD = re.compile(r'导出|下载|存成文件|保存为文件')
_CONFIG_COMPARISON = re.compile(r'A\s*(?:和|与|/|→)\s*B|两份|两个版本|配置差异|比较|比对', re.I)
_RUNTIME_MODE = re.compile(r'设备(?:接入|连接)(?:方式|模式)|模拟(?:设备|环境|模式|下发|练习|实训|演练|\s*(?:还是|或|和|与))|仿真|'
                           r'(?:正式|真实)(?:连接|连通|接入|验收)|真实(?:设备|环境)|真机|终端模式|演练.{0,8}(?:连通|连得通|连接)')
_RUNTIME_MODE_CHECK = re.compile(r'怎么看|怎么判|怎么区分|怎么确认|怎么确定|怎么知道|如何辨|如何判断|如何(?:确认|确定)|从哪|哪里|哪个|依据|证明|'
                                 r'(?:正式|真实|真机).{0,10}(?:验收|核验|连接)|(?:现在|当前).{0,8}(?:是不是|是否|是模拟)|'
                                 r'(?:算不算|能不能|能否|可以|能把).{0,20}(?:验收|交接|记成|当成|写进)')
_CHANGE_LOG = re.compile(r'配置变更(?:日志|详情)|变更日志|这条日志|日志时间|查看变更|任务项\s*(?:ID|编号|#)|同(?:一|个)任务|本任务|当前任务', re.I)
_CHANGE_RECORD_FACTS = re.compile(r'回读|备份|存档|执行前|执行后|对照|差异|记录|查阅|查看|查询|时间|时点|何时|几点|什么时候')
_TRAINING_NOTES = re.compile(r'笔记|手记|笔记与步骤')
_TRAINING_NOTES_WORKFLOW = re.compile(r'保存|没存|未存|修订|只读|回看|原会话|刷新|导出|下载|哪里|在哪')
_TRAINING_CONFLICT = re.compile(r'载入.{0,6}(?:最新版|最新版本|服务端)|(?:保存|笔记|步骤|版本)(?:出现)?冲突|并发|'
                                r'放弃当前稿|另(?:一个)?窗(?:口)?|本(?:机|地)稿|冲突(?:窗(?:口)?|提示|版)|覆盖.{0,5}(?:服务端|最新版)')
_TRAINING_WORKSPACE = re.compile(r'笔记|手记|草稿|(?:本|这)步|步骤|服务端|未提交|保存|标记')
_TRAINING_SAVED_RELOAD = re.compile(
    r'(?:只(?:想|要)?|重新|再)\s*(?:看|读回|回读|读(?:取)?|核对|载入|加载).{0,12}'
    r'(?:已(?:经)?保存|已存|服务端|(?:之前|先前|原来|刚才|早先)保存)|'
    r'(?:已(?:经)?保存|已存|服务端).{0,12}(?:版本|稿|那份).{0,10}(?:回读|载入|加载)'
)
_ALARM_LIST_VIEW = re.compile(r'告警列表|报警列表|告警页|报警页|(?:左侧|侧栏|左边).{0,20}(?:告警|报警)')
_ALARM_ACTION = re.compile(r'(?:帮我|请直接|请同时|请顺便|顺手|顺便|并(?:且)?|然后|立即|现在|一键|批量|自动).{0,8}'
                           r'(?:确认|接手|关闭|关掉|触发|发起)|(?:确认|接手|关闭|关掉|触发|发起).{0,8}(?:所有|全部|这条|这几条|某条|它们)|'
                           r'(?:在哪里|从哪|点哪里|怎么|怎样|如何).{0,8}(?:确认|接手|关闭|关掉|触发|发起)|'
                           r'(?:帮我|请)?把.{0,10}(?:告警|报警|它们).{0,7}(?:确认|接手|关闭|触发|发起)')
_ALARM_ACTION_DENIAL = re.compile(r'(?:不要|不必|不用|无需|不想|不打算|别|会不会|是否会|会自动)'
                                 r'(?:再|去|替我|帮我|自动)?\s*(?:确认|接手|关闭|关掉|触发|发起)')
_DRAFT_STAGING = re.compile(r'暂存|草稿.{0,8}(?:先存|先保存|本地保存|切页保留)|切页.{0,12}(?:保留|恢复).{0,6}草稿')
_DRAFT_STAGING_QUESTION = re.compile(r'怎么|如何|哪里|哪个|哪一个|区别|怎么确认|接着写|继续编辑|只保存|没建变更|会不会')

_ROUTE_NAMES = {
    '/dashboard': '工作台', '/': '工作台', '/monitor': '监控', '/knowledge': '知识库',
    '/training': '实训', '/devices': '设备', '/topology': '拓扑', '/webssh': '终端',
    '/deploy': '配置下发', '/approvals': '变更审批', '/config-versions': '配置版本',
    '/environments': '环境映射', '/alarms': '告警',
}

_APPROVAL_RULE = (
    "「已确认，待执行」只表明确认已记录，不证明已执行、保存、回读或设备变化。"
    "以同一任务及其设备的阶段、执行回执、模式和核验结果为准。缺少该任务执行记录时模式未知，不能用当前模拟开关反推。"
)
_APPROVAL_RECORD_RULE = (
    _APPROVAL_RULE + "本题是查阅既有记录。先在「变更审批」打开该任务「详情」核对对象、阶段和模式，"
    "成功、失败或回滚的终态可点「查看结果」读取已保存报告和差异。只有确认或仍在待核对时，说明尚无核验通过的证据。"
    "「执行」「核对回读」「确认演练结果」会改变工作流；不能把这些按钮作为查阅已有结果的操作建议。"
    "模拟完成只记录演练，不能当真机回读；配置一致也不代表业务恢复。"
)
_APPROVAL_START_RULE = (
    _APPROVAL_RULE + "本题明确问发起核验。先定位该任务和设备，检查阶段为「已执行，待核对」且同一任务有效持锁；"
    "只有任务操作人或管理员可发起。核验真实任务使用「核对回读」，它会启动核验，有差异可触发受控回滚并改写、保存设备配置。"
    "模拟任务用「确认演练结果」保存演练结果，不读取或改变真机。模式无法确认时只说明先核对该任务记录，勿把按钮当作安全的浏览入口。"
    "成功、失败或回滚终态用「查看结果」读已有报告，无需重新核验。"
)
_VALIDATION_RULE = (
    "在「配置下发」按页面功能说明。「静态校验结果」只说明当前草稿通过相应规则检查，状态仍是「未执行」。"
    "它不代表审批、真实连接、实际执行、保存或设备回读。当前真实/模拟模式不能从静态校验推出；"
    "需要同一草稿绑定的任务、目标及后续实际执行和回读证据，才描述设备结果。"
)
_TOPOLOGY_RECORD_RULE = (
    '当前问的是画布已保存的关系。到独立「拓扑」页，点选连线，在「链路详情」读两端的设备名称、接口和来源。'
    '这一步只看库中登记的关系。连接线和标题无法证明两端接口物理、协议状态或业务可达；未采集时说明未核验。'
    '若用户只看图上记录，不引导启动「运行态校验」，也不拿教材代替页面操作。'
)
_DEVICE_RECORD_RULE = (
    '本题只查设备页已保存的数据。列表「保存的连接状态」是已存状态，「上次可达」单独表示最后记录到可达的时间。'
    '这个时间不一定就是当前状态最近更新的时点，也不能证明协议或业务。'
    '沿设备行打开「只读观察」，只用其中的「最近证据」读已有记录。核对设备、采集时间、模式和实际已保存的接口、邻居或路由字段。'
    '缺记录就说未保存相应证据。不要建议本轮点击「检查管理连接」「采集只读事实」或进入终端运行命令。'
)
READ_ONLY_WORKBENCH_ANSWERS = {
    'training_preview': (
        '在左侧「实训」列表找到要预习的实验，点实验名称。宽屏有步骤列时，也可点该行的「N 步」。'
        '在「实验步骤」弹窗看「先修与环境」、内容版本和设备角色。只打开这份说明不会新建会话。\n\n'
        '返回列表后，在「我的实训会话」按原实验和会话编号找到原记录，看「状态」是否为「进行中」。'
        '顶部若有「实训进行中 · 原课程名」也可回到该会话。预习时无需点「开始实训」或「新开会话」。'
    ),
    'original_quote_navigation': (
        '打开「知识库」→「检索资料」→「原书原句」，把从 PDF 复制的一小段连续文字粘贴到检索框，点「检索」。'
        '在命中卡片核对教材、版次和 PDF 物理页，再点「查看原页」。这条路径直接查原句；「教材正文」是整理稿的检索入口。\n\n'
        '原图弹窗用「返回正文」，再点「返回原页面」就回到刚才的检索结果；如果只打开了阅读器，直接点「返回原页面」。'
        '若「原书原句」不可选，按页面提示区分原书未挂载和本机索引未建。命中标为「扫描定位」时要打开允许查看的原页核对。'
    ),
    'original_reader_return': (
        '在知识库的「检索资料」里，对「原书原句」命中点「查看原页」。核对教材、版次和 PDF 物理页后，'
        '在原图弹窗点「返回正文」，再在阅读器点「返回原页面」。这会回到原检索页，保留筛选条件和命中列表，无需重新检索。\n\n'
        '如果是从「教材正文」的「片段详情」打开阅读器，先点「返回原页面」回到片段，再点「返回检索结果」。'
        '从「资料目录」打开阅读器时，「返回原页面」回到原目录及其筛选。'
    ),
    'copilot_citation_return': (
        '在助手原回答点对应引用编号。旧回答可从助手顶部「历史」找到。引用面板可显示原回答保存的片段及校验状态；'
        '有「阅读同版正文」时从这里进阅读器，再按「原教材页位」打开允许查看的原图。\n\n'
        '原图里点「返回正文」，阅读器里点「返回原页面」，最后在引用面板点「返回对话」。这会回到原回答，无需重发问题。'
        '若引用已撤权或无法核对，按面板状态处理；新版正文不能替代原回答的出处。'
    ),
    'monitor_saved_samples': (
        '在「监控」选好「图表与巡检范围」，点「刷新已保存记录」。这一步读取库里已保存的趋势和记录。'
        '顶部设备与告警卡片覆盖全部拓扑，所选拓扑决定下方图表和巡检列表的范围。'
        '「采集指标」是管理员发起新采样的入口，只看旧记录时无需点它。\n\n'
        '整体时间看页面的「所选拓扑最近采样」；特定曲线点看该点的时间。端口明细用「查看端口观察」，以弹窗顶部的「采样」为准；'
        '弹窗的「刷新观察」也只重新读取保存结果。页面刷新时点和查询范围都不能替代样本自己的采样时点。'
        '显示「暂无采样」时，当前没有可核对的样本时点。空样本不能证明设备健康或没有告警。'
    ),
    'simulation_report': (
        '在「变更审批」打开同一任务的「详情」，核对执行模式和任务阶段。成功、失败或回滚的记录可点「查看结果」读保存报告。'
        '「演练结果」只能支持演练范围。模拟结果没有生产设备回读，不能写成生产已下发、验证通过或业务恢复。\n\n'
        '若报告确实显示模拟流程完成，可以写「该变更已完成模拟演练；生产执行与设备回读未核验。」'
        '若只看到演练记录，还没确认结果是否完成，可写「已留存模拟演练记录；生产执行与设备回读未核验。」'
    ),
    'single_snapshot_view': (
        '在「配置版本」切到「配置快照」，按设备和版本找到目标行，在该行「操作」列点「查看」。'
        '弹窗会展示已保存快照的版本、设备、来源、时间和内容。这个动作只打开现有记录，不启动新采集或 AI 差异说明。'
        '时间对应该条保存记录，不能据此写成已执行变更或当前设备配置。'
    ),
    'snapshot_download': (
        '在「配置版本」打开「配置快照」，按设备和版本找到已保存的目标行，在该行「操作」列点「导出」。'
        '有多份时勾选相应行，再点「导出已选快照」。「查看」只打开内容弹窗。'
        '导出使用已保存文件；「采集并保存配置」会新读设备，下载旧快照时无需点它。'
    ),
    'alarm_list_view': (
        '在左侧导航找到「观测」分组，点「告警」即可打开告警列表。只打开列表会读取已保存记录，不接手、关闭或发起告警。'
        '列表操作列的「接手」会记录有人处理，「关闭」会结束所选告警记录；两者都与打开列表分开。'
    ),
    'alarm_action_boundary': (
        '我可以指引打开列表。左侧「观测」下点「告警」；这一步只查看已有记录。'
        '接手、关闭或触发是独立操作。本轮未处理任何告警。若还要了解其中一项，请说明要查看哪个操作及目标告警。'
    ),
    'draft_staging': (
        '在「配置下发」编辑区点「暂存草稿」，以「已暂存」时间和「与当前内容一致」提示确认保存。'
        '在同一浏览器标签页回来时，若显示「可恢复上次暂存内容」，点「恢复暂存草稿」。'
        '暂存供当前账号使用，保留 2 小时，主动退出会清除。含口令或密钥的配置不要暂存。\n\n'
        '「校验配置」只做静态检查；点「提交待确认」才创建变更任务。暂存和校验都不会下发。'
        '只想核对是否已建变更时，打开「配置批次」，按目标设备和任务创建时间检查有无对应新增记录。本轮未提交或执行。'
    ),
}
WORKFLOW_GUIDANCE = {
    'validation': _VALIDATION_RULE, 'approval_record': _APPROVAL_RECORD_RULE,
    'approval_start': _APPROVAL_START_RULE, 'topology_record': _TOPOLOGY_RECORD_RULE,
    'device_record': _DEVICE_RECORD_RULE,
    **READ_ONLY_WORKBENCH_ANSWERS,
}


def plain_question(text: str) -> str:
    return re.sub(r'\x60\x60\x60[\s\S]*?(?:\x60\x60\x60|\Z)', '', text or '').strip()


def navigation_question(text: str) -> str:
    return re.sub(r'《[^》\n]+》', ' ', plain_question(text))


def guided_page_question(text: str) -> re.Match[str] | None:
    return _GUIDED_PAGE.match(text)


def textbook_reference_question(text: str, route: str | None = None) -> bool:
    if _SKIP_TEACHING.search(text) or _TEACHING_NAVIGATION.search(text):
        return False
    if guided_page_question(text):
        return True
    source = _TEACHING_SOURCE.search(text) or route == '/knowledge' and _TEACHING_ANAPHOR.search(text)
    if source and _TEACHING_RECORD.search(text):
        return True
    # Within the knowledge view, an explicit question about what a referenced
    # exhibit can establish can be answered from the teaching materials.
    return bool(route == '/knowledge' and (_TABLE_REFERENCE.search(text) or _READOUT_REFERENCE.search(text))
                and _PROOF_BOUNDARY.search(text)
                and _network_subject(text) and not _REAL_OBSERVATION.search(text))


def _network_subject(text: str) -> bool:
    return bool(protocol_names(text) or _NETWORK_ARTIFACT.search(text)
                or re.search(skills.DEVICE_LABEL_PATTERN, text, re.I))


def illustrative_network_question(text: str) -> bool:
    return bool(_SCENARIO_FRAME.search(text) and _network_subject(text)
                and (_LEARNING_ACTION.search(text) or _NETWORK_REASONING.search(text)
                     or _READ_FIELD.search(text) and re.search(r'查看|读取|读出|核对|采集|执行', text)
                     or re.search(r'[？?]|会怎样|会如何', text)))


def compares_written_evidence(text: str) -> bool:
    return bool(_TABLE_REFERENCE.search(text) and _WRITTEN_ACCOUNT.search(text) and _PROOF_BOUNDARY.search(text))


def network_reasoning_question(text: str) -> bool:
    """A protocol procedure or interpretation can name devices without asking to reach them."""
    if illustrative_network_question(text):
        return True
    if (not _network_subject(text) or _REAL_OBSERVATION.search(text)
            or skills.explicit_status_question(text) or _DIAGNOSTIC_READ.search(text)):
        return False
    if compares_written_evidence(text):
        return True
    return bool((_NETWORK_REASONING.search(text) or _TABLE_REFERENCE.search(text) and _LEARNING_ACTION.search(text))
                and not (_SAVED_READ_REFERENCE.search(text) or _EXISTING_OBSERVATION.search(text)))


def operational_evidence_question(text: str) -> bool:
    """Classify current or saved evidence requests independently of read permission."""
    return bool(_OBSERVATION_POINTER.search(text) or _SAVED_READ_REFERENCE.search(text)
                or _REAL_OBSERVATION.search(text) or _EXISTING_OBSERVATION.search(text) or explicit_device_read(text)
                or (_DIRECT_READ.search(text) and _READ_FIELD.search(text)))


def operational_followup_question(text: str, history: list | None) -> bool:
    if not (_OPERATIONAL_FOLLOWUP.search(text) and re.search(skills.DEVICE_LABEL_PATTERN, text, re.I)):
        return False
    for item in reversed((history or [])[-12:]):
        if isinstance(item, dict) and item.get('role') == 'user':
            previous = plain_question(str(item.get('content') or ''))
            return not network_reasoning_question(previous) and operational_evidence_question(previous)
    return False


def explicit_device_read(text: str) -> bool:
    if textbook_reference_question(text) or network_reasoning_question(text):
        return bool(new_device_read_scope(text))
    return bool(skills.explicit_status_question(text) or (
        not _TEACHING_NOT_LIVE.search(text) and (_FRESH_DEVICE_ACTION.search(text) or _EXPLICIT_FIELD_REFERENCE.search(text))
    ) or _NEW_ACTOR.search(text))


def new_device_read_scope(message: str) -> str:
    """Only the action clauses of the current user's request can authorize targets."""
    question = plain_question(message)
    text = re.sub(r'[「『“].*?[」』”]|`[^`]*`|[（(][^）)]*[）)]', '', question)
    # A qualifier can narrow a request even when quoted text itself cannot grant reads.
    illustrative = illustrative_network_question(question) or compares_written_evidence(question)
    course = textbook_reference_question(text) or illustrative
    if (not text or (not course and (explicit_study(text) or network_reasoning_question(text)))
            or skills._device_read_denied(text) or _READ_DENIAL.search(text)):
        return ''
    if (not course and skills.explicit_status_question(text)
            and (not re.search(r'^那|呢[？?。\s]*$', text) or re.search(r'现在|当前', text))):
        return text
    authorized = []
    refers_to_saved = bool(_SAVED_READ_REFERENCE.search(text))
    if not course and (diagnosis := _DIAGNOSTIC_READ.search(text)) and not refers_to_saved:
        authorized.append(diagnosis.group())
    for part in _REQUEST_CLAUSE.finditer(text):
        clause = part['clause'].strip()
        if course:
            separate_request = part['separator'] in {None, '。', '？', '！', '?', '!', '\n'}
            leaves_scenario = _LEAVE_SCENARIO.search(clause) or separate_request and _ACTUAL_READ_LANGUAGE.search(clause)
            if _SCENARIO_FRAME.search(clause) or (illustrative and not leaves_scenario):
                continue
            clause = re.sub(r'^(?:另外|另|同时|另外请|并且|然后)\s*', '', clause)
            if (_TEACHING_SOURCE.search(clause) or _TEACHING_ANAPHOR.search(clause)
                    or _PREVIOUS_RECORD_CONTEXT.search(clause) or not _CLEAR_NEW_READ.search(clause)):
                continue
        if re.search(r'刚才|此前|先前|上次|之前|刚读|历史|存档|已保存|已存|手抄|工单|附件|截图|样例|快照|观察记录|接口记录|'
                     r'能不能证明|怎么|如何|是否意味着|从哪里|在哪里|按哪个|为什么', clause) or _SAVED_READ_REFERENCE.search(clause):
            continue
        if not (_READ_FIELD.search(clause) and _DIRECT_READ.search(clause)):
            continue
        fresh = _FRESH_READ_MARKER.search(clause)
        if refers_to_saved and not fresh:
            continue
        if re.search(skills.DEVICE_LABEL_PATTERN, clause, re.I) or fresh or '只读' in clause:
            authorized.append(re.split(r'用于|作为示例|举例|对照|跟.{0,6}比较|而不是', clause, maxsplit=1)[0])
    return '\n'.join(authorized)


def explicit_device_read_modes(message: str) -> frozenset[str]:
    action = new_device_read_scope(message)
    return frozenset(mode for mode, marker in _READ_MODES if marker.search(action))


def explicit_study(text: str) -> bool:
    return bool(_LEARNING_ACTION.search(text) and (
        (_LEARNING_OBJECT.search(text) and
         (_TEACHING_NOT_LIVE.search(text) or re.search(r"按|就|仅|从|只讲|出处|原理|机制", text)))
        or (_NEGATED_UI.search(text) and protocol_names(text))
    ))


def _named_controls(text: str, route: str | None) -> tuple[str, ...]:
    compact = re.sub(r'\s+', '', text)
    mentioned = {name for name in skills.WORKBENCH_CONTROLS if name in compact}
    if _ROUTE_NAMES.get(route):
        mentioned.add(_ROUTE_NAMES[route])
    return tuple(dict.fromkeys(label for name, controls in skills.WORKBENCH_CONTROLS.items()
                               if name in mentioned for label in controls
                               if len(label) >= 4 and re.sub(r'\s+', '', label) in compact))


def monitor_sample_time_question(text: str) -> bool:
    details = _MONITOR_TIME.search(text) or re.search(r'有没有|有无|是否|多少|暂无|没有|时点|时间|样本', text)
    scoped = _MONITOR_SCOPE.search(text) and _MONITOR_SAVED_STATUS.search(text)
    return bool((scoped or _LATEST_MONITOR_SAMPLE.search(text) and details or monitor_empty_chart_question(text))
                and not _PORT_VIEW.search(text))


def monitor_empty_chart_question(text: str) -> bool:
    return bool(_MONITOR_EMPTY_CHART.search(text) and _MONITOR_SCOPE_VERDICT.search(text))


def previous_citation_status_question(text: str) -> bool:
    return bool(_CHAT_SOURCE.search(text) and _CHAT_REFERENCE.search(text) and _CHAT_REF_STATUS.search(text))


def runtime_mode_question(text: str, route: str | None) -> bool:
    workbench = (route in {None, '/', '/dashboard', '/webssh', '/training'} or (route or '').startswith('/webssh/')
                 or bool(re.search(r'工作台|首页|终端横幅', text)))
    return bool(workbench and _RUNTIME_MODE.search(text) and _RUNTIME_MODE_CHECK.search(text) and not explicit_study(text))


def config_change_log_question(text: str, route: str | None, selected_kind: str | None = None) -> bool:
    return bool(route == '/config-versions' and not explicit_study(text) and _CHANGE_RECORD_FACTS.search(text)
                and (_CHANGE_LOG.search(text) or selected_kind == 'approval_task'))


def training_notes_question(text: str, route: str | None) -> bool:
    return bool(route == '/training' and not explicit_study(text)
                and (training_conflict_question(text) or training_saved_reload_question(text)
                     or _TRAINING_NOTES.search(text) and _TRAINING_NOTES_WORKFLOW.search(text)))


def training_conflict_question(text: str) -> bool:
    version_notice = (re.search(r'版本(?:提示|提醒|警告)', text)
                      and re.search(r'(?:两|另|第二).{0,4}(?:窗口|标签页)', text))
    return bool(_TRAINING_WORKSPACE.search(text) and (_TRAINING_CONFLICT.search(text) or version_notice))


def training_saved_reload_question(text: str) -> bool:
    return bool(_TRAINING_SAVED_RELOAD.search(text))


def workflow_question(text: str, route: str | None) -> str | None:
    text = navigation_question(text)
    # A page name by itself is not a request to read or change a task.
    if (route == '/deploy' or '配置下发' in text) and _DRAFT_STAGING.search(text) and _DRAFT_STAGING_QUESTION.search(text):
        return 'draft_staging'
    if _STATE_QUESTION.search(text) and re.search(r'静态校验|校验配置', text) and (
        route == '/deploy' or '配置下发' in text or 'AI 辅助' in text or '配置草稿' in text
    ):
        return 'validation'
    studying = explicit_study(text)
    if (not studying and (route == '/config-versions' or re.search(r'配置版本|配置快照', text))
            and _SNAPSHOT_DOWNLOAD.search(text) and re.search(r'快照|已保存|历史版本', text)
            and not _CONFIG_COMPARISON.search(text)):
        return 'snapshot_download'
    if (route == '/monitor' or re.search(r'在监控|监控(?:页|面板|大盘|界面|图表)', text)) and not studying:
        scoped = _MONITOR_SCOPE.search(text) and _MONITOR_SAVED_STATUS.search(text)
        saved_view = _MONITOR_VIEW.search(text) and (_MONITOR_SAVED.search(text) or _MONITOR_TIME.search(text))
        no_chart = route == '/monitor' and monitor_empty_chart_question(text)
        if (scoped or saved_view or no_chart) and not (_PORT_VIEW.search(text) or _MONITOR_NEW_ACTION.search(text)):
            return 'monitor_saved_samples'
    if not studying:
        if (_CHAT_SOURCE.search(text) and _CHAT_REFERENCE.search(text)
                and (_BOOK_RETURN.search(text) or previous_citation_status_question(text))):
            return 'copilot_citation_return'
        if ((route == '/knowledge' or re.search(r'知识库|检索资料', text)) and _BOOK_RETURN.search(text)
                and _BOOK_RESULT.search(text) and _BOOK_VIEW.search(text)):
            return 'original_reader_return'
    if (_ALARM_LIST_VIEW.search(text) and (route in {'/', '/dashboard', '/alarms'} or re.search(r'左侧|左边|侧栏', text))
            and (_READ_NAVIGATION.search(text) or re.search(r'打开|进入|只看|切到|去看', text))):
        action = _ALARM_ACTION_DENIAL.sub('', text)
        return 'alarm_action_boundary' if _ALARM_ACTION.search(action) else 'alarm_list_view'
    if _READ_NAVIGATION.search(text):
        if (_TRAINING_PREVIEW.search(text) and not _TRAINING_START_NAVIGATION.search(text)
                and (route == '/training' or re.search(r'实训列表|实训页|实验列表', text))):
            return 'training_preview'
        if _ORIGINAL_QUOTE.search(text) and (route == '/knowledge' or re.search(r'知识库|检索资料', text)):
            from modules.knowledge.query_focus import lookup_parts
            if not any(phrase not in skills.WORKBENCH_CONTROLS['知识库'] for phrase in lookup_parts(text)[1]):
                return 'original_quote_navigation'
        if _SINGLE_SNAPSHOT.search(text) and not _CONFIG_COMPARISON.search(text) and (
            route == '/config-versions' or re.search(r'配置版本|配置快照', text)
        ):
            return 'single_snapshot_view'
    if _APPROVAL_PAGE.search(text) or (route in {'/approvals', '/deploy'} and not studying):
        if _START_VERIFICATION.search(text) and not _NO_START_VERIFICATION.search(text):
            return 'approval_start'
        if _SIMULATION_RECORD.search(text) and _REPORT_CLAIM.search(text):
            return 'simulation_report'
        if _APPROVAL_STATUS.search(text):
            return 'approval_record'
    if not studying and _SAVED_PAGE_VIEW.search(text):
        if _TOPOLOGY_RECORD.search(text) and (route == '/topology' or re.search(r'拓扑页|拓扑画布', text)):
            return 'topology_record'
        if _DEVICE_RECORD.search(text) and (route == '/devices' or '设备列表' in text):
            return 'device_record'
    return None


def read_only_workbench_answer(message: str, route: str | None) -> str:
    text = plain_question(message)
    if _NEGATED_UI.search(text) or new_device_read_scope(message):
        return ''
    return READ_ONLY_WORKBENCH_ANSWERS.get(workflow_question(text, route), '')


def page_operation(text: str, route: str | None) -> bool:
    text = navigation_question(text)
    if _NEGATED_UI.search(text):
        return False
    workflow = workflow_question(text, route)
    if workflow in READ_ONLY_WORKBENCH_ANSWERS and not new_device_read_scope(text):
        return True
    if explicit_device_read(text):
        return False
    if workflow:
        return True
    if not _UI_INTENT.search(text):
        return False
    control_question = re.search(r'(?:按钮|菜单项|页签|选项卡|导航).{0,9}(?:怎么|如何|意思|作用|在哪|做什么|是什么)', text)
    if control_question and not re.search(r'(?:设备|交换机|电源|路由器)(?:的|上)?(?:硬件|物理)?按钮', text):
        return True
    controls = _named_controls(text, route)
    recognized = _READING_UI_OBJECT.search(text)
    explicit_application = _EXPLICIT_UI_CONTEXT.search(text)
    # Incidental page names and protocol terms do not establish a navigation request.
    if explicit_study(text) and not (controls or recognized):
        return False
    if recognized and (explicit_application or re.search(r'打开|返回|回到|点哪|在哪|入口|展开', text)):
        return True
    return bool(controls and (explicit_application or re.search(r'点击|点哪|入口|打开|按钮|区别|各做什么', text)))


def study_followup(text: str, history: list | None) -> tuple[str, frozenset[str]] | None:
    if not (_FOLLOWUP.search(text) and (_DEICTIC.search(text) or text.lstrip().startswith('那'))):
        return None
    if (_INTENT_RESET.search(text) or _REAL_OBSERVATION.search(text) or new_device_read_scope(text)
            or page_operation(text, None)):
        return None
    current_subjects = frozenset(protocol_names(text))
    for item in reversed((history or [])[-12:]):
        if not isinstance(item, dict) or item.get('role') != 'user':
            continue
        old = plain_question(str(item.get('content') or ''))
        subjects = frozenset(protocol_names(old))
        if (_INTENT_RESET.search(old) or explicit_device_read(old) or page_operation(old, None)
                or ((_REAL_OBSERVATION.search(old) or _EXISTING_OBSERVATION.search(old))
                    and not (network_reasoning_question(old) or textbook_reference_question(old)))):
            break
        if subjects:
            if len(subjects) == 1 and (not current_subjects or current_subjects == subjects) and (
                explicit_study(old) or skills.concept_only_question(old) or textbook_reference_question(old)
                or network_reasoning_question(old) or re.search(r'教材|课本|协议原理', old)
            ):
                return old, subjects
            break
        if not (_FOLLOWUP.search(old) and (_DEICTIC.search(old) or old.lstrip().startswith('那'))):
            break
    return None


def saved_record_only(message: str) -> bool:
    text = plain_question(message)
    record = re.search(r'(?:只|仅)(?:看|按|用|根据|解读|依据|回读|核对).{0,8}'
                       r'(?:这条|这份|当前|已有|已存|已保存|旧|原|历史).{0,6}(?:观察记录|服务端观察|观察|快照|证据)', text)
    pasted = re.search(r'粘贴|贴的|手抄|样例|工单|附件|截图|(?:观察|记录)[：:]', message)
    return bool(record and not pasted and '\x60\x60\x60' not in message)
