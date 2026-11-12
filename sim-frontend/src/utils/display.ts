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
  acknowledged: '已确认',
  resolved: '已解决',
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

export function taskStatusTagType(status?: string): string {
  return (status && TASK_STATUS_TAG[status]) || 'info'
}

export function alarmTypeLabel(kind?: string): string {
  const labels: Record<string,string> = {interface_expected_down:'预期启用接口未Up',interface_review:'端口状态待核对',interface_down_high:'接口down总数（旧规则）',cpu_usage_high:'CPU使用率超限',memory_usage_high:'内存使用率超限',temperature_high:'温度超限',ospf_neighbor_count_low:'OSPF邻居数低于阈值'}
  return (kind && labels[kind]) || kind || '未知类型'
}

export function alarmMeaning(kind?: string): string {
  if (kind === 'interface_down_high') return '旧规则按接口down总数触发，未区分闲置、预期状态或用途；历史等级保留，不等于当前业务严重故障。'
  if (kind === 'interface_expected_down') return '采样时登记为预期启用的接口未Up；需核对物理、协议与管理状态，尚未证明业务中断。'
  if (kind === 'interface_review') return '用途/预期、缺失接口、意外启用或解析覆盖待核对；不会按down总数升级为业务严重故障。'
  return '该记录反映采样时的指标阈值判断；严重程度不代替业务影响核实，处理状态不证明当前已恢复。'
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
  Object.assign(labels,{create_config:'新增配置项',update_config:'更新配置项',delete_config:'删除配置项',llm_test:'测试模型连通性',health_check:'检查管理连接',capture_config:'采集配置快照'})
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
