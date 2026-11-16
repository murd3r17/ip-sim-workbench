/**
 * 展示层的枚举文案 / el-tag 类型集中定义（P2-20）。
 *
 * 此前「严重程度」「状态」的中文标签与 tag 颜色在 MonitorDashboardView、AlarmView、
 * DeviceListView、BackgroundTaskView、DashboardView 各抄了一份，改一处忘一处就会出现
 * 同一状态在两个页面显示不同颜色/文案。
 */

const SEVERITY_TAG: Record<string, string> = {
  critical: 'danger',
  major: 'warning',
  minor: 'info',
  warning: 'warning',
  info: 'info',
}

const SEVERITY_LABEL: Record<string, string> = {
  critical: '严重',
  major: '主要',
  minor: '次要',
  warning: '警告',
  info: '提示',
}

/** 告警严重程度 → el-tag type */
export function severityTagType(severity?: string): string {
  return (severity && SEVERITY_TAG[severity]) || 'info'
}

/** 告警严重程度 → 中文（未知值原样返回，避免把后端新枚举吞成空串） */
export function severityLabel(severity?: string): string {
  return (severity && SEVERITY_LABEL[severity]) || severity || '-'
}

const ALARM_STATUS_TAG: Record<string, string> = {
  fired: 'danger',
  acknowledged: 'warning',
  resolved: 'success',
  closed: 'info',
}

const ALARM_STATUS_LABEL: Record<string, string> = {
  fired: '未处理',
  acknowledged: '已接手',
  resolved: '已解除',
  closed: '已关闭',
}

export function alarmStatusTagType(status?: string): string {
  return (status && ALARM_STATUS_TAG[status]) || 'info'
}

export function alarmStatusLabel(status?: string): string {
  return (status && ALARM_STATUS_LABEL[status]) || status || '-'
}

const DEVICE_STATUS_TAG: Record<string, string> = {
  online: 'success',
  offline: 'danger',
  maintenance: 'warning',
  unknown: 'info',
}

const DEVICE_STATUS_LABEL: Record<string, string> = {
  online: '在线',
  offline: '离线',
  maintenance: '维护',
  unknown: '未知',
}

export function deviceStatusTagType(status?: string): string {
  return (status && DEVICE_STATUS_TAG[status]) || 'info'
}

export function deviceStatusLabel(status?: string): string {
  return (status && DEVICE_STATUS_LABEL[status]) || status || '-'
}

/** 后台任务 / 下发 / 巡检等通用状态文案（跨模块共用的一套词） */
const TASK_STATUS_LABEL: Record<string, string> = {
  pending: '等待中',
  awaiting_confirmation: '待确认',
  confirmed: '已确认',
  validating: '校验中',
  deploying: '下发中',
  verifying: '验证中',
  running: '运行中',
  in_progress: '进行中',
  success: '成功',
  completed: '已完成',
  failed: '失败',
  rolled_back: '已回滚',
  cancelled: '已取消',
}

const TASK_STATUS_TAG: Record<string, string> = {
  pending: 'info',
  awaiting_confirmation: 'warning',
  confirmed: 'warning',
  validating: 'warning',
  deploying: 'warning',
  verifying: 'warning',
  running: '',
  in_progress: '',
  success: 'success',
  completed: 'success',
  failed: 'danger',
  rolled_back: 'info',
  cancelled: 'warning',
}

export function taskStatusLabel(status?: string): string {
  return (status && TASK_STATUS_LABEL[status]) || status || '-'
}

export function deployTaskStatusLabel(status?: string, phase?: string): string {
  const stages: Record<string, string> = {
    pending: '待确认', awaiting_confirmation: '待确认', confirmed: '已确认，待执行',
    deploying: '执行状态待确认', execution_unconfirmed: '执行状态待确认', execution_blocked: '缺少执行锁',
    executing: '正在执行', awaiting_verification: '已执行，待核对', verifying: '正在核对',
    simulation_complete: '模拟流程已完成', success: '已完成',
  }
  return stages[phase || ''] || stages[status || ''] || taskStatusLabel(status)
}

export function deployNextAction(status?: string, phase?: string, mode?: string | null): string {
  const statements: Record<string, string> = {
    pending: '核对这台设备和配置内容，再确认变更。',
    awaiting_confirmation: '核对这台设备和配置内容，再确认变更。',
    confirmed: '本任务已取得设备执行锁，可以执行。',
    execution_blocked: '本任务已失去执行锁。请核对任务状态和审计记录。',
    executing: '正在执行。刷新任务可以查看最新阶段。',
    awaiting_verification: mode === 'simulated' ? '查看并保存本次模拟流程结果。' : '核对设备回读与预期配置。',
    verifying: '正在比对并保存结果。完成后可查看回读明细。',
    execution_unconfirmed: '重新读取任务状态。执行结果仍不明确时，请核对审计与设备状态。',
    simulation_complete: '已保存模拟流程结果，设备配置无变更。',
    success: '查看已保存的处理结果。',
    failed: '查看异常详情和变更记录，核对已完成的部分。',
    rolled_back: '查看恢复结果和关联配置版本。',
  }
  return statements[phase || status || ''] || ''
}

export function taskStatusTagType(status?: string): string {
  return (status && TASK_STATUS_TAG[status]) || 'info'
}

export function alarmTypeLabel(kind?: string): string {
  const labels: Record<string,string> = {
    interface_expected_down: '预期启用接口未 Up', interface_review: '端口状态待核对',
    interface_down_high: '接口 Down 总数（旧规则）', cpu_usage_high: 'CPU 使用率超限',
    memory_usage_high: '内存使用率超限', temperature_high: '温度超限',
    ospf_neighbor_count_review: 'OSPF 邻居基线待核对', ospf_neighbor_count_expected_low: 'OSPF 邻居少于预期',
    ospf_neighbor_count_low: 'OSPF 邻居达到旧告警阈值', ospf_neighbor_count_high: 'OSPF 邻居达到旧告警阈值',
  }
  return (kind && labels[kind]) || kind || '未知类型'
}

export function alarmMeasurementLabel(value?: number | string | null, kind?: string | null): string {
  if (value == null || value === '') return '未记录'
  const unit = kind === 'cpu_usage_high' || kind === 'memory_usage_high' ? '%' : kind === 'temperature_high' ? ' °C' : ''
  return `${value}${unit}`
}

export function alarmMeaning(kind?: string): string {
  if (kind === 'interface_down_high') return '旧规则按接口down总数触发，未区分闲置、预期状态或用途；历史等级保留，不等于当前业务严重故障。'
  if (kind === 'interface_expected_down') return '采样时登记为预期启用的接口未Up；需核对物理、协议与管理状态，尚未证明业务中断。'
  if (kind === 'interface_review') return '用途/预期、缺失接口、意外启用或解析覆盖待核对；不会按down总数升级为业务严重故障。'
  if (kind === 'ospf_neighbor_count_review') return '这次采样触发了人工复核。先按网络设计确认该设备应有哪些邻居，再查看本机 OSPF 回显。'
  if (kind === 'ospf_neighbor_count_expected_low') return '本次观察到的 Full 或 2-Way 邻居数量少于已登记下限。优先核对缺少的邻居、接口和协议状态。'
  if (kind === 'ospf_neighbor_count_low' || kind === 'ospf_neighbor_count_high') return '旧版按全局阈值保留的历史告警。确认设备角色及应有邻居后，再判断当前影响。'
  return '该记录反映采样时的指标阈值判断；严重程度不代替业务影响核实，处理状态不证明当前已恢复。'
}

export function alarmTriggerLabel(alarm: { alarm_type?: string | null; metric_value?: number | string | null; threshold?: number | string | null }): string {
  const kind = alarm.alarm_type
  const observed = alarmMeasurementLabel(alarm.metric_value, kind)
  if (kind === 'ospf_neighbor_count_review') return `观察到 ${observed} 个 OSPF 邻居，设备预期未登记`
  if (alarm.metric_value == null || alarm.threshold == null) return '查看观察依据'
  const target = alarmMeasurementLabel(alarm.threshold, kind)
  if (kind === 'ospf_neighbor_count_expected_low') return `邻居 ${observed} < 本设备下限 ${target}`
  if (kind?.endsWith('_low')) return `观察值 ${observed} ≤ 记录阈值 ${target}`
  return `观察值 ${observed} ≥ 记录阈值 ${target}`
}

export function configSourceLabel(source?: string): string {
  return ({pre_backup:'执行前备份',post_readback:'执行后回读',manual:'手动采集',manual_capture:'手动采集',rollback:'恢复回读',rollback_readback:'恢复回读',snapshot_capture:'手动采集'} as Record<string,string>)[source || ''] || source || '来源未记录'
}

export function executionModeLabel(mode?: unknown): string {
  return mode === 'real' ? '真实执行' : mode === 'simulated' ? '模拟执行' : '未记录可确认的执行模式'
}

export function savedVerificationState(record: {execution_mode?:unknown;verified?:unknown;status?:string}): string {
  if(record.execution_mode === 'simulated') return 'not_performed'
  if(record.execution_mode !== 'real') return 'unknown'
  if(record.verified === true) return 'passed'
  return ['failed','rolled_back'].includes(record.status || '') ? 'failed' : 'unverified'
}

export function auditActionLabel(action?: string): string {
  const labels: Record<string,string>={deploy_task_confirmed:'确认下发任务',deploy_task_executed:'执行下发任务',deploy_task_verified:'核对设备回读',deploy_task_cancelled:'取消任务',device_write_lock_acquired:'取得设备写锁',device_write_lock_released:'释放设备写锁',port_expectations_updated:'更新本地端口期望',alarm_acknowledged:'接手告警',alarm_closed:'结束告警记录',login:'登录',logout:'退出登录',create:'创建记录',update:'更新记录',delete:'删除记录'}
  Object.assign(labels,{deploy_task_created:'提交变更任务',deploy_rollback_task_created:'提交恢复任务',create_config:'新增配置项',update_config:'更新配置项',delete_config:'删除配置项',llm_test:'测试模型连通性',health_check:'检查管理连接',device_health_check:'检查管理连接',capture_config:'采集配置快照'})
  Object.assign(labels, { account_created: '创建账号', account_password_reset: '重置账号密码', account_password_changed: '修改个人密码' })
  return (action&&labels[action])||action||'未记录动作'
}

export function auditModuleLabel(value?:string):string {
 return ({auth:'认证',device:'设备',deploy:'配置下发',monitor:'监控',ai:'模型助手',training:'实训',trust:'环境核验',system:'系统管理',knowledge:'知识库',webssh:'终端'} as Record<string,string>)[value||'']||value||'模块未记录'
}
export function auditResultLabel(value?:string):string {
 return ({success:'成功',failed:'失败',error:'异常',denied:'已拒绝'} as Record<string,string>)[value||'']||value||'结果未记录'
}

export function observationStatusLabel(value?: string): string {
  return ({ok:'读取成功',partial:'部分返回',error:'读取异常',unreachable:'连接不可达',busy:'设备占用',empty:'没有可用事实',unknown:'结果未知'} as Record<string,string>)[value||''] || value || '结果未记录'
}
export function observationCompletenessLabel(value?: string): string {
  return ({complete:'输出完整',partial:'输出不完整',empty:'未解析到事实',unknown:'完整性未知'} as Record<string,string>)[value||''] || value || '完整性未记录'
}
export function observationModeLabel(value?: string): string {
  return ({real:'真实读取',sim:'模拟读取',simulated:'模拟读取',unknown:'来源模式未知'} as Record<string,string>)[value||''] || value || '来源模式未记录'
}

export function environmentStatusLabel(status: string): string {
  return ({ ready: '映射已核对', mismatch: '映射不一致', unreachable: '设备不可达', busy: '设备占用中', unknown: '证据不足', draft: '待预检' } as Record<string, string>)[status] || '状态待确认'
}
