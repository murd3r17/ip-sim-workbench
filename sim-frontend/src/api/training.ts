import request from './request'

// ── Lab 管理 ──────────────────────────────────────────────────────────
export function listLabs() {
  return request.get('/training/labs')
}

export function getLab(id: number) {
  return request.get(`/training/labs/${id}`)
}

export function createLab(data: {
  title: string
  description?: string
  topology_id: number
  objectives?: string[] | any[]
  scoring_rules?: Record<string, number>
  time_limit_minutes?: number
  is_sandbox?: boolean
}) {
  return request.post('/training/labs', data)
}

export function updateLab(id: number, data: Record<string, unknown>) {
  return request.put(`/training/labs/${id}`, data)
}

export function bindLabEnvironment(id: number, environmentId: number | null) {
  return request.put(`/training/labs/${id}/environment`, { environment_id: environmentId })
}

export function verifyTrainingStep(sessionId: number, stepId: number, observationIds: number[]) {
  return request.post(`/training/sessions/${sessionId}/steps/${stepId}/verify`, { observation_ids: observationIds })
}

export function deleteLab(id: number) {
  return request.delete(`/training/labs/${id}`)
}

// ── 会话管理 ──────────────────────────────────────────────────────────
export function startSession(labId: number) {
  return request.post('/training/sessions', { lab_id: labId })
}

export function listSessions(params?: { status?: string; lab_id?: number }) {
  return request.get('/training/sessions', { params })
}

export function getSession(sessionId: number) {
  return request.get(`/training/sessions/${sessionId}`)
}

export function completeSession(sessionId: number) {
  return request.post(`/training/sessions/${sessionId}/complete`)
}

/** 放弃会话：之后只读回看，不能继续记录/绑定终端/请求教练。 */
export function abandonSession(sessionId: number) {
  return request.post(`/training/sessions/${sessionId}/abandon`)
}

export function deleteSession(sessionId: number) {
  return request.delete(`/training/sessions/${sessionId}`)
}

// ── 故障注入 ──────────────────────────────────────────────────────────
export function injectFaults(sessionId: number, faultScenario: unknown[]) {
  return request.post(`/training/sessions/${sessionId}/inject`, {
    fault_scenario: faultScenario,
  })
}

export function resolveFault(faultId: number, resolvedCorrectly: boolean) {
  return request.post(`/training/faults/${faultId}/resolve?resolved_correctly=${resolvedCorrectly}`)
}

// ── 评分 ──────────────────────────────────────────────────────────────
export function scoreSession(sessionId: number) {
  return request.post(`/training/sessions/${sessionId}/score`)
}

// ── 沙箱模式 ──────────────────────────────────────────────────────────
export function startSandbox(labId: number, faultTypes?: string[]) {
  return request.post('/training/sandbox/start', {
    lab_id: labId,
    fault_types: faultTypes,
  })
}

// ── 操作日志 ──────────────────────────────────────────────────────────
export function logOperation(sessionId: number, data: {
  lab_id: number
  action: string
  target_device?: string
  command?: string
  result?: string
  success?: boolean
  meta?: Record<string, unknown>
}, opts?: { silent?: boolean }) {
  return request.post(`/training/sessions/${sessionId}/log`, data, { silent: opts?.silent })
}

export function getOperationLogs(sessionId: number) {
  return request.get(`/training/sessions/${sessionId}/logs`)
}

export function getSessionFaults(sessionId: number) {
  return request.get(`/training/sessions/${sessionId}/faults`)
}

export function exportLogsJsonl(sessionId: number) {
  return request.get(`/training/sessions/${sessionId}/logs/jsonl`, { responseType: 'text' })
}

export function getTrainingHint(sessionId: number) {
  return request.get(`/training/sessions/${sessionId}/hint`)
}

/** 读取已保存的复盘报告（不调用模型）。 */
export function getTrainingReport(sessionId: number, version?: number) {
  return request.get(`/training/sessions/${sessionId}/report`, { silent: true, params: { version } })
}

/** Export only saved state; no model or retrieval request. */
export function exportTrainingSession(sessionId: number, version?: number) {
  return request.get(`/training/sessions/${sessionId}/export`, { silent: true, params: { version } })
}

/** 显式生成复盘报告；regenerate=true 才新增版本。 */
export function generateTrainingReport(
  sessionId: number,
  data?: { regenerate?: boolean; idempotency_key?: string },
) {
  return request.post(`/training/sessions/${sessionId}/report/generate`, data || {})
}


/** B-10：读取实训连续任务（笔记/步骤），刷新可恢复。 */
export function getTrainingWorkspace(sessionId: number) {
  return request.get(`/training/sessions/${sessionId}/workspace`, { silent: true })
}

/** B-10：保存笔记/步骤；revision 冲突时后端返回 409。 */
export function updateTrainingWorkspace(sessionId: number, data: { notes: string; steps: Array<Record<string, unknown>>; revision?: number }) {
  return request.put(`/training/sessions/${sessionId}/workspace`, data)
}
