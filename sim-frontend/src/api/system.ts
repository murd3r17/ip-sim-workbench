import request from './request'

// ── 系统信息 ──────────────────────────────────────────────────────────
export function getSystemInfo() {
  return request.get('/system/info')
}

export function getSystemHealth() {
  return request.post('/system/health')
}

// ── 系统配置 ──────────────────────────────────────────────────────────
export function listSystemConfigs() {
  return request.get('/system/config')
}

export interface EffectiveField {
  key:string;group:string;value:unknown;default_value:unknown;configured:boolean;is_secret:boolean;active:boolean
  activation:string;source:string;override_status:string;inherited_from?:string
}
export interface ConfigConsumer {key:string;consumer:string;activation:string;note:string}
export interface EffectiveConfig {
  generated_at:string;fields:EffectiveField[];stored_items:ConfigConsumer[];known_items:ConfigConsumer[];monitor_thresholds:unknown
  source_note:string;scope:string;chains:Record<string,string>
}
export const getEffectiveSystemConfig=()=>request.get<EffectiveConfig,EffectiveConfig>('/system/effective-config',{silent:true})
export const testModelConnectivity=()=>request.post<unknown,any>('/system/llm-health',undefined,{silent:true})

export function getSystemConfig(key: string) {
  return request.get(`/system/config/${key}`)
}

export function createSystemConfig(data: { config_key: string; config_value?: string; description?: string }) {
  return request.post('/system/config', data)
}

export function updateSystemConfig(key: string, data: { config_value?: string; description?: string }) {
  return request.put(`/system/config/${key}`, data)
}

export function deleteSystemConfig(key: string) {
  return request.delete(`/system/config/${key}`)
}

// ── 审计日志 ──────────────────────────────────────────────────────────
export function getAuditLogs(params?: { page?: number; page_size?: number; module?: string; user_id?: number }) {
  return request.get('/system/audit-logs', { params })
}

// ── 后台任务 ──────────────────────────────────────────────────────────
export function listBackgroundTasks(status?: string) {
  return request.get('/system/tasks', { params: status ? { status } : {} })
}

export function getBackgroundTask(taskId: number) {
  return request.get(`/system/tasks/${taskId}`)
}

// ── 日志文件 ──────────────────────────────────────────────────────────
export function listLogFiles() {
  return request.get('/system/logs')
}

export function readLogFile(filename: string, tail?: number) {
  return request.get(`/system/logs/${filename}`, { params: tail ? { tail } : {} })
}
