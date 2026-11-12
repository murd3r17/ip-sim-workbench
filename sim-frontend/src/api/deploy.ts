import request from './request'

// 下发任务/批次
export interface DeployTaskItem {
  id: number
  device_id: number
  stage?: string
  config_content: string
  status: string
}

export interface DeployBatchRecord {
  id: number
  name: string
  source?: string
  record_origin?: string
  description?: string
  planned_at?: string
  created_at?: string
  items?: DeployTaskItem[]
}

// 配置模板
export interface ConfigTemplateRecord {
  id: number
  name: string
  category?: string
  description?: string
  content: string
  variables?: Record<string, unknown>
  created_at?: string
}

export interface ConfigValidateResult {
  valid: boolean
  errors?: string[]
  diagnostics?: { line_number?: number; command?: string; message: string; level?: string; risk_level?: string }[]
  coverage?: { checked?: string[]; not_checked?: string[] }
}

export interface ConfigTemplateRenderResult {
  rendered: string
  [key: string]: unknown
}

// 配置快照
export interface ConfigVersionRecord {
  id: number
  device_id: number
  version_number: string
  source?: string
  record_origin?: string
  change_description?: string
  config_snapshot?: string
  deploy_task_id?: number
  created_at: string
}

export interface ConfigVersionCompareResult {
  diff?: Record<string, unknown>
  summary?: Record<string, unknown>
  [key: string]: unknown
}

// 配置下发
export const createDeploy = (data: {
  device_ids: number[]
  config_content: string
  template_id?: number
  change_level?: string
  engine?: string
}) => request.post('/deploy', data)

export type DeployBatchItem = {
  device_id: number
  config_content: string
  template_id?: number
}

export const createDeployBatch = (data: {
  name: string
  description?: string
  source?: 'manual' | 'template' | 'ai'
  planned_at?: string
  engine?: string
  items: DeployBatchItem[]
}) => request.post('/deploy/batches', data)

export const getDeployBatches = () => request.get<DeployBatchRecord[], DeployBatchRecord[]>('/deploy/batches')

export const getDeployBatch = (batchId: number) => request.get<DeployBatchRecord, DeployBatchRecord>(`/deploy/batches/${batchId}`)

export const getDeployTasks = (params?: { status?: string }) =>
  request.get('/deploy/tasks', { params })

export const getDeployTask = (taskId: number) =>
  request.get<any, any>(`/deploy/tasks/${taskId}`)

export const validateConfig = (data: { config_content: string; device_model?: string }) =>
  request.post<ConfigValidateResult, ConfigValidateResult>('/deploy/validate', data)

// 配置模板
export const getTemplates = () =>
  request.get<ConfigTemplateRecord[], ConfigTemplateRecord[]>('/config-templates')

export const createTemplate = (data: {
  name: string
  description?: string
  content: string
  variables?: Record<string, any>
  category?: string
}) => request.post<ConfigTemplateRecord, ConfigTemplateRecord>('/config-templates', data)

export const renderTemplate = (data: { content: string; variables?: Record<string, any>; declarations?: Record<string, any> }) =>
  request.post<ConfigTemplateRenderResult, ConfigTemplateRenderResult>('/config-templates/render', data)

export const confirmDeployTask = (taskId: number, riskConfirm = false) =>
  request.post(`/deploy/tasks/${taskId}/confirm`, { risk_confirm: riskConfirm }, { silent: true })

export const executeDeployTask = (taskId: number) =>
  request.post(`/deploy/tasks/${taskId}/execute`, undefined, { silent: true })

export const verifyDeployTask = (taskId: number) =>
  request.post(`/deploy/tasks/${taskId}/verify`, undefined, { silent: true })

/** 取消未终结的任务并释放设备写锁（设备被残留锁卡住时的人工恢复入口）。 */
export const cancelDeployTask = (taskId: number) =>
  request.post<{ task_id: number; status: string; released_lock: boolean },
    { task_id: number; status: string; released_lock: boolean }>(
    `/deploy/tasks/${taskId}/cancel`, undefined, { silent: true })

// 配置管理
export const getConfigVersions = (params?: { device_id?: number }) =>
  request.get<ConfigVersionRecord[], ConfigVersionRecord[]>('/config-versions', { params })

export const captureConfigVersions = (device_ids: number[]) => request.post<any[], any[]>('/config-versions/capture', { device_ids })

export const compareVersions = (version1: number, version2: number) =>
  request.get<ConfigVersionCompareResult, ConfigVersionCompareResult>('/config-versions/compare', { params: { version1, version2 }, silent:true })

// 注：旧版 `rollbackVersion`（POST /config-versions/{id}/rollback）已删除 —— 后端该入口恒返回
// 409「请通过受控回滚任务执行」（有意禁用，避免绕过写锁与授权）。受控回滚走下面的
// `createRollbackTask`：生成高风险回滚任务，需人工确认后执行。

/** B2：由历史快照生成受控回滚任务（不直接执行，需审批确认）。 */
export const createRollbackTask = (versionId: number) =>
  request.post<{ task_id: number; device_id: number; hostname: string; status: string; source_version_number: number },
    { task_id: number; device_id: number; hostname: string; status: string; source_version_number: number }>(
    `/deploy/config-versions/${versionId}/rollback-task`, undefined, { silent: true })

export const getDeployChangeLogs = (params?: { task_id?: number }) =>
  request.get<any[], any[]>('/deploy/change-logs', { params })
