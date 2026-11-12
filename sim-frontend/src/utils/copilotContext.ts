/** Route-aware starter prompts + quick links for Copilot. */

export type ChipAction = {
  label: string
  prompt: string
  wantDraft?: boolean
}

export type QuickLink = {
  label: string
  path: string
}

const PAGE_META: Record<
  string,
  { title: string; chips: ChipAction[]; links: QuickLink[]; placeholder: string }
> = {
  '/dashboard': {
    title: '工作台',
    placeholder: '问工作台指标含义、先看哪块、怎么开始练…',
    chips: [
      { label: '从哪开始练', prompt: '工作台这一页是做什么的？初学者该从哪开始练？' },
      { label: '指标怎么看', prompt: '工作台里常见设备状态/告警指标分别代表什么？怎么判断是否异常？' },
      { label: '下一步建议', prompt: '看完工作台后，下一步建议去哪个模块做实验？给我一个简短路径。' },
    ],
    links: [
      { label: '设备', path: '/devices' },
      { label: '拓扑', path: '/topology' },
      { label: '实训', path: '/training' },
    ],
  },
  '/devices': {
    title: '设备',
    placeholder: '问设备录入、SSH 连通、型号差异或选中设备怎么练…',
    chips: [
      { label: '本页做什么', prompt: '设备页是做什么的？初学者怎么把 eNSP/仿真设备加进来？' },
      { label: '连不上怎么办', prompt: '设备加了但 SSH 连不上，按什么顺序排查？（仿真环境）' },
      { label: '打开终端练', prompt: '我已经选中一台设备，第一次进 终端 该先敲哪些查看命令？' },
    ],
    links: [
      { label: '终端', path: '/webssh' },
      { label: '拓扑', path: '/topology' },
      { label: '下发', path: '/deploy' },
    ],
  },
  '/topology': {
    title: '拓扑',
    placeholder: '问拓扑怎么看、链路含义、基线与运行态差异…',
    chips: [
      { label: '怎么读拓扑', prompt: '拓扑页怎么读？节点和链路分别代表什么？' },
      { label: '基线 vs 运行态', prompt: '拓扑里的基线和运行态校验有什么区别？初学者怎么用？' },
      { label: '练组网', prompt: '根据常见三层组网，给我一套适合仿真练习的检查清单。' },
    ],
    links: [
      { label: '终端', path: '/webssh' },
      { label: '工作台', path: '/dashboard' },
      { label: '实训', path: '/training' },
    ],
  },
  '/webssh': {
    title: '终端',
    placeholder: '问查看命令、配置思路；生成的 CLI 请自己粘贴执行…',
    chips: [
      { label: '先敲什么', prompt: '刚连上华为设备，第一次实训建议先敲哪些 display 命令？' },
      { label: '接口+路由草稿', prompt: '帮我写一段 NE40E 接口 IP + 静态路由配置草稿', wantDraft: true },
      { label: '保存配置注意', prompt: '仿真里改完配置，save 和重启要注意什么？' },
    ],
    links: [
      { label: '设备', path: '/devices' },
      { label: '下发', path: '/deploy' },
    ],
  },
  '/deploy': {
    title: '配置下发',
    placeholder: '描述要下发的配置目标，或让我生成可编辑草稿…',
    chips: [
      { label: '下发流程', prompt: '配置下发页的完整流程是什么？确认和执行分别做什么？' },
      { label: '生成草稿', prompt: '帮我写一段可填入下发表单的接口+静态路由 CLI 草稿', wantDraft: true },
      { label: '校验要点', prompt: '下发前本地校验一般看哪些风险点？' },
    ],
    links: [
      { label: '终端', path: '/webssh' },
      { label: '配置版本', path: '/config-versions' },
    ],
  },
  '/config-versions': {
    title: '配置版本',
    placeholder: '问备份、对比、回滚在仿真里怎么练…',
    chips: [
      { label: '本页用途', prompt: '配置版本页是做什么的？和配置下发有什么关系？' },
      { label: '怎么练备份', prompt: '初学者怎么练配置备份与对比？给步骤清单。' },
    ],
    links: [{ label: '下发', path: '/deploy' }],
  },
  '/approvals': {
    title: '变更审批',
    placeholder: '问任务状态、确认与执行的区别，或需要核对哪些内容…',
    chips: [
      { label: '确认后会执行吗', prompt: '变更审批页的确认和执行有什么区别？确认前应核对什么？' },
      { label: '任务在哪里', prompt: '变更审批页的任务从哪里来？看不到任务时应检查什么？' },
    ],
    links: [{ label: '配置下发', path: '/deploy' }, { label: '配置版本', path: '/config-versions' }],
  },
  '/environments': {
    title: '环境映射',
    placeholder: '问设备映射、保护项和预检结果的含义…',
    chips: [
      { label: '预检是什么', prompt: '环境映射页的预检会检查什么？通过后是否代表已执行配置？' },
      { label: '保护项怎么填', prompt: '环境映射里的保护项如何填写？为什么管理接口需要保护？' },
    ],
    links: [{ label: '设备', path: '/devices' }, { label: '实训', path: '/training' }],
  },
  '/monitor': {
    title: '监控',
    placeholder: '问监控指标含义、异常时怎么查…',
    chips: [
      { label: '指标含义', prompt: '监控主要看哪些指标？初学者怎么判断设备是否正常？' },
      { label: '异常怎么查', prompt: '监控显示异常时，建议按什么顺序去告警/终端 排查？' },
    ],
    links: [
      { label: '告警', path: '/alarms' },
      { label: '终端', path: '/webssh' },
    ],
  },
  '/alarms': {
    title: '告警',
    placeholder: '粘贴告警内容，或问怎么确认/关闭/排查…',
    chips: [
      { label: '告警怎么处理', prompt: '告警页里确认/关闭分别代表什么？实训时怎么用？' },
      { label: '帮我解读', prompt: '请根据当前选中的告警，解释可能原因和仿真环境排查步骤。' },
      { label: '联查设备', prompt: '这类告警下一步该去 终端 看哪些命令？' },
    ],
    links: [
      { label: '监控', path: '/monitor' },
      { label: '终端', path: '/webssh' },
    ],
  },
  '/knowledge': {
    title: '知识库',
    placeholder: '问教材知识点、命令对比、实验步骤…（也可直接用右侧助手）',
    chips: [
      { label: '用右侧助手', prompt: '知识库和右侧 AI 助手怎么配合用？什么时候用右侧助手发文件，什么时候直接提问？' },
      { label: 'OSPF Hello', prompt: 'OSPF Hello 报文做什么用？简短回答并给关键点。' },
      { label: 'Silent-Interface', prompt: 'OSPF Silent-Interface 怎么配？给关键 CLI', wantDraft: true },
      { label: '源NAT vs NAPT', prompt: '源 NAT 和 NAPT 有什么区别？' },
    ],
    links: [
      { label: '实训', path: '/training' },
      { label: '终端', path: '/webssh' },
    ],
  },
  '/training': {
    title: '实训',
    placeholder: '问实验目标、步骤卡点、验证命令…',
    chips: [
      { label: '怎么开始', prompt: '实训怎么用？初学者第一次建议选什么实验路径？' },
      { label: '卡点怎么办', prompt: '实训做到一半卡住时，应该怎么向助手提问才有效？' },
      { label: '验证命令', prompt: '常见路由实验做完后，用哪些 display 命令验证？' },
      { label: '这步做对了吗', prompt: '请根据当前实训会话的步骤和最近操作日志，判断我这一步做对了没有，并指出还缺什么。' },
      { label: '看操作日志', prompt: '请根据当前实训会话的最近操作日志，指出哪里可能做错了，以及建议怎么改。' },
      { label: '下一步敲什么', prompt: '请根据当前实训步骤和我刚敲过的命令，告诉我下一步该敲什么、在哪台设备上敲。' },
    ],
    links: [
      { label: '拓扑', path: '/topology' },
      { label: '设备', path: '/devices' },
      { label: '终端', path: '/webssh' },
    ],
  },
  '/system/info': {
    title: '系统信息', placeholder: '问服务状态和运行环境信息…',
    chips: [{ label: '状态怎么理解', prompt: '系统信息页的服务状态分别代表什么？' }],
    links: [{ label: '工作台', path: '/dashboard' }],
  },
  '/system/config': {
    title: '系统配置', placeholder: '问模型配置和参数含义，请勿粘贴密钥…',
    chips: [{ label: '模型如何配置', prompt: '系统配置页如何配置模型？哪些信息需要接收方自己填写？请不要要求我在对话里粘贴密钥。' }],
    links: [{ label: '系统信息', path: '/system/info' }],
  },
  '/system/audit': {
    title: '审计日志', placeholder: '问审计筛选与操作记录的含义…',
    chips: [{ label: '怎么查操作记录', prompt: '审计日志页怎样查找一次操作的结果？记录成功是否等于设备业务正常？' }],
    links: [{ label: '变更审批', path: '/approvals' }],
  },
  '/system/tasks': {
    title: '后台任务', placeholder: '问后台任务状态和失败后的检查步骤…',
    chips: [{ label: '失败后怎么查', prompt: '后台任务页如何核对一次失败任务？怎么避免重复提交？' }],
    links: [{ label: '工作台', path: '/dashboard' }],
  },
  '/system/logs': {
    title: '日志文件', placeholder: '问日志筛选与错误含义，请先移除敏感信息…',
    chips: [{ label: '怎样找错误', prompt: '日志文件页如何查看问题发生时的相关记录？分享日志前需要移除什么信息？' }],
    links: [{ label: '审计日志', path: '/system/audit' }],
  },
}

const DEFAULT_META = {
  title: '工作台',
  placeholder: '询问当前页面、拓扑、告警或网络知识点…',
  chips: [
    { label: '从哪开始', prompt: '当前页面是做什么的？我该从哪开始练？' },
    { label: 'OSPF 配置', prompt: 'OSPF Silent-Interface 怎么配？给关键 CLI', wantDraft: true },
    { label: '接口路由草稿', prompt: '帮我写一段 NE40E 接口+静态路由配置草稿', wantDraft: true },
    { label: 'NAT 区别', prompt: '源 NAT 和 NAPT 有什么区别？' },
  ] as ChipAction[],
  links: [
    { label: '工作台', path: '/dashboard' },
    { label: '设备', path: '/devices' },
    { label: '实训', path: '/training' },
  ] as QuickLink[],
}

export function resolvePageMeta(path: string) {
  const exact = PAGE_META[path]
  if (exact) return exact
  if (path.startsWith('/webssh')) return PAGE_META['/webssh']
  if (path.startsWith('/system')) {
    return {
      title: '系统管理',
      placeholder: '问系统配置、审计、任务或日志怎么看…',
      chips: [
        { label: '系统模块做什么', prompt: '系统管理相关页面分别做什么？运维学习需要关注哪些？' },
        { label: 'JWT/密钥含义', prompt: '系统信息里的 JWT 密钥和 Fernet 加密分别干什么用？未配置会有什么影响？' },
        { label: '审计怎么查', prompt: '审计日志一般怎么筛？出了问题时先看哪些字段？' },
      ],
      links: [
        { label: '工作台', path: '/dashboard' },
        { label: '系统信息', path: '/system/info' },
        { label: '审计', path: '/system/audit' },
      ],
    }
  }
  return DEFAULT_META
}
