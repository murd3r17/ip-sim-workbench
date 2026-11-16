import request from './request'
import { browserSessionRevision, expireBrowserSession, sessionFetch } from '../stores/browserSession'

export const getAICapabilities = () =>
  request.get<unknown, { vision_enabled: boolean; image_mime_types: string[] }>('/ai/capabilities', { silent: true })

export const generateCLI = (data: { natural_language: string; device_model?: string }) =>
  request.post('/ai/generate-cli', data)

export const generateAndValidate = (data: { natural_language: string; device_model?: string }) =>
  request.post('/ai/generate-and-validate', data)

export const generateConfigPlan = (data: { natural_language: string; devices: Array<{ device_id: number; hostname: string; role?: string }> }) =>
  request.post('/ai/config-plans', data)

export const reviewConfig = (data: { config_text: string; device_model?: string }) =>
  request.post('/ai/review-config', data)

export const askKnowledge = (data: { question: string; kb_id?: string; top_k?: number }) =>
  request.post('/ai/ask', data)

export const copilotChat = (data: {
  message: string
  request_id?: string
  history?: Array<{ role: string; content: string; request_id?: string }>
  context?: {
    route?: string
    page_name?: string
    selection?: string
    notes?: string
  }
  want_draft?: boolean
  device_model?: string
  top_k?: number
  page_data?: string
}) => request.post('/ai/copilot/chat', data)

export interface CopilotReference {
  source_id?: string
  reference_index?: number
  filename?: string
  title?: string
  score?: number
  content?: string
  version?: string
  captured_at?: string
  page?: number
}

export type CopilotStreamEvent =
  | {
      type: 'meta'
      request_id?: string
      provider?: string
      status?: string
      knowledge_status?: string
      draft_refused_reason?: string
      draft_target?: { device_id: number; hostname: string; alarm_id?: number } | null
      replayed?: boolean
      historical?: boolean
    }
  | { type: 'references'; request_id?: string; generation_status?: string; sources?: CopilotReference[] }
  | { type: 'policy'; draft_refused_reason?: string; draft_target?: null; replace_answer?: string }
  | { type: 'tool'; name?: string; status?: string }
  | { type: 'progress'; stage: string; message?: string; request_id?: string }
  | { type: 'reasoning'; text: string; request_id?: string }
  | { type: 'token'; text: string; request_id?: string }
  | { type: 'draft'; draft_commands?: string[]; draft_explanation?: string }
  | { type: 'cancelled'; request_id?: string; upstream?: string; note?: string }
  | { type: 'done'; status?: string; assist_only?: boolean; has_reasoning?: boolean; cancelled?: boolean; reason?: string }
  | { type: 'error'; message?: string; code?: string; retryable?: boolean }

export async function copilotChatStream(
  data: {
    message: string
    history?: Array<{ role: string; content: string }>
    context?: {
      route?: string
      page_name?: string
      selection?: string
      notes?: string
    }
    want_draft?: boolean
    device_model?: string
    top_k?: number
    page_data?: string
    attachments?: Array<{ contentString: string; mime?: string; name?: string }>
    conversation_id?: string
    attachment_message_id?: string
    lab_steps?: any[]
    lab_id?: number | null
    lab_session_id?: number | null
    request_id?: string
  },
  onEvent: (event: CopilotStreamEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const observedRevision = browserSessionRevision()
  const res = await sessionFetch('/api/v1/ai/copilot/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(data),
    signal,
  })

  if (!res.ok) {
    let detail = ''
    let code = ''
    try {
      const payload = await res.json()
      const raw = payload?.detail ?? payload?.message ?? payload
      detail = typeof raw === 'string' ? raw : (raw?.message || '')
      code = typeof raw?.code === 'string' ? raw.code : ''
    } catch {
      detail = await res.text().catch(() => '')
    }
    throw Object.assign(new Error(detail || `流式请求失败 (${res.status})`), { code, status: res.status })
  }

  const reader = res.body?.getReader()
  if (!reader) throw new Error('浏览器不支持流式读取')

  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let terminal = false

  const dispatch = (raw: string) => {
    for (const line of raw.split('\n')) {
      const trimmed = line.trim()
      if (!trimmed.startsWith('data:')) continue
      const payload = trimmed.slice(5).trim()
      if (!payload || payload === '[DONE]') continue
      let event: CopilotStreamEvent | { type: 'auth_expired' }
      try { event = JSON.parse(payload) } catch {
        throw new Error('回答数据格式异常，请查询原回答。')
      }
      if (observedRevision !== browserSessionRevision()) throw new Error('登录状态已变化。')
      if (event.type === 'auth_expired') {
        expireBrowserSession(observedRevision)
        throw new Error('登录已失效，请重新登录。')
      }
      if (terminal) continue
      onEvent(event)
      if (event.type === 'done') terminal = true
    }
  }

  try {
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    buffer = buffer.replace(/\r\n/g, '\n')
    const parts = buffer.split('\n\n')
    buffer = parts.pop() || ''

    for (const part of parts) dispatch(part)
  }
  // flush 残留帧：末帧未以空行结尾时此前会被静默丢弃（回答尾部缺字）
  buffer += decoder.decode()
  if (buffer.trim()) dispatch(buffer)
  if (!terminal) throw new Error('连接中断，尚未收到完成确认，请查询原回答。')
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}

export interface CopilotRecovery {
  request_id: string
  state: 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted'
  historical: boolean
  response: {
    knowledge_status?: string
    answer?: string
    sources?: Array<{ source_id?: string; filename?: string; title?: string; score?: number; content?: string; version?: string; captured_at?: string; page?: number }>
    draft_commands?: string[]
    draft_refused_reason?: string
    draft_target?: { device_id: number; hostname: string; alarm_id?: number } | null
    status?: string
    error_message?: string
  } | null
}

/** Read only: recovering a reply never sends a new generation request. */
export const getCopilotRequest = (requestId: string) =>
  request.get<unknown, CopilotRecovery>(`/ai/copilot/requests/${encodeURIComponent(requestId)}`, { silent: true, timeout: 10000 })

export const generateReport = (data: { title: string; source_text: string; context?: string }) =>
  request.post('/ai/report', data)

/** 取消本次 AI 请求（检索/生成阶段均可）。只取消本次请求，不撤销设备配置。 */
export const cancelCopilotRequest = (requestId: string) =>
  request.post<{ request_id: string; cancelled: boolean; upstream: string; note?: string },
    { request_id: string; cancelled: boolean; upstream: string; note?: string }>(
    `/ai/copilot/requests/${encodeURIComponent(requestId)}/cancel`, {}, { silent: true })

export interface InspectionSummary {
  summary: string
  coverage?: { observed?: number; target?: number; failed?: number; skipped?: number; finished_at?: string }
  basis?: string
  missing_devices?: Array<{ device_id?: number; hostname: string; status: 'failed' | 'skipped'; reason?: string }>
  key_findings?: string[]
  root_causes?: string[]
  recommendations?: string[]
  report_text?: string
}

export const inspectionSummary = (jobId: number) =>
  request.post<InspectionSummary, InspectionSummary>('/ai/inspection-summary', { job_id: jobId }, { silent: true })

/** B5：用白话解释两个配置版本之间的差异（后端已脱敏）。 */
export const diffExplanation = (versionIdA: number, versionIdB: number) =>
  request.post('/ai/diff-explanation', { version_id_a: versionIdA, version_id_b: versionIdB }, { silent: true })

export const coachTraining = (data: {
  goal: string
  scenario: string
  current_step?: string
  history?: string
}) => request.post('/ai/coach', data)

// ── Copilot 会话持久化（后端） ─────────────────────────────
export interface CopilotSessionMeta {
  id: string
  title: string
  created_at?: string
  updated_at?: string
  message_count?: number
  revision: number
}

export interface CopilotSessionDetail extends CopilotSessionMeta {
  messages: any[]
  exists?: boolean
}

export const getCopilotSessions = () =>
  request.get<CopilotSessionMeta[], CopilotSessionMeta[]>('/ai/copilot/sessions')

export const getCopilotSession = (id: string, opts?: { silent?: boolean }) =>
  request.get<CopilotSessionDetail, CopilotSessionDetail>(`/ai/copilot/sessions/${encodeURIComponent(id)}`, opts)

export const saveCopilotSession = (id: string, data: { title: string; messages: any[]; revision?: number }, opts?: { silent?: boolean }) =>
  request.put<unknown, { success: boolean; id: string; revision: number }>(`/ai/copilot/sessions/${encodeURIComponent(id)}`, data, opts)

export const deleteCopilotSession = (id: string) =>
  request.delete(`/ai/copilot/sessions/${encodeURIComponent(id)}`)
