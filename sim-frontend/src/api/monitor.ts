import request from './request'

// ── 响应类型 ──────────────────────────────────────────────────────────
export interface MonitorStats {
  totalDevices: number
  onlineDevices: number
  activeAlarms: number
  warningAlarms: number
}

export interface MonitorTrendPoint {
  device_id: number
  device_name?: string
  time?: string
  value?: number
}

export interface MonitorTrend {
  metrics?: Record<string, MonitorTrendPoint[]>
  alarms?: unknown[]
  summary?: Record<string, unknown>
}

export interface MonitorTaskRecord {
  id: number
  job_type?: string
  status?: string
  success_count?: number
  failure_count?: number
  summary?: { expected: number; success: number; failed: number; skipped: number }
  created_at?: string
  report?: {
    alarm_count?: number
    metric_types?: string[]
    [key: string]: unknown
  }
}

export interface AlarmRecord {
  id: number
  device_id?: number
  device_name?: string
  alarm_type?: string
  severity?: string
  message?: string
  metric_value?: string | number
  threshold?: string | number
  status: string
  fired_at?: string
  acknowledged_at?: string
  resolved_at?: string
  closed_at?: string
}

export interface PortExpectation {
  name: string
  purpose: 'unknown' | 'unused' | 'business' | 'uplink' | 'management'
  expected_enabled: boolean | null
}
export interface PortObservationRow extends PortExpectation {
  physical?: string
  protocol?: string
  admin_state?: string
  assessment?: string
}
export interface PortState {
  device_id: number
  hostname: string
  policy: { revision: string; ports: PortExpectation[]; valid: boolean; reason?: string }
  fresh: boolean
  policy_changed: boolean
  mode_changed: boolean
  latest_attempt?: { job_id: number; status: string; reason?: string; time?: string }
  observation?: { ports: PortObservationRow[]; complete: boolean; observed_at: string; reason?: string; missing_expected_ports: string[]; expected_down: number; review_count: number; policy_revision: string }
}
export const getPortState = (deviceId: number) => request.get<PortState, PortState>(`/monitor/ports/${deviceId}`, { silent: true })
export const savePortExpectations = (deviceId: number, baseRevision: string, ports: PortExpectation[]) =>
  request.put(`/monitor/ports/${deviceId}/expectations`, { base_revision: baseRevision, ports }, { silent: true })

// 监控指标
export const getDeviceMetrics = (deviceId: number, params?: { metric_type?: string; limit?: number }) =>
  request.get(`/monitor/metrics/${deviceId}`, { params })

export const triggerCollection = (topologyId: number) =>
  request.post(`/monitor/collect/${topologyId}`)

// 轮询类 GET 一律 silent：由页面自己决定怎么提示。
// 否则后端不可用时，告警页每 15s、首页每 20s 各弹一条 toast，大盘一次刷新还叠 4 条（2026-10-05 审计）。
export const getMonitorStats = (opts?: { silent?: boolean }) =>
  request.get<MonitorStats, MonitorStats>('/monitor/stats', { silent: opts?.silent })

export const getMonitorTrends = (params?: { topology_id?: number; device_id?: number; metric_type?: string; limit?: number }, opts?: { silent?: boolean }) =>
  request.get<MonitorTrend, MonitorTrend>('/monitor/trends', { params, silent: opts?.silent })

export const getMonitorTasks = (params?: { topology_id?: number; job_type?: string; limit?: number }, opts?: { silent?: boolean }) =>
  request.get<MonitorTaskRecord[], MonitorTaskRecord[]>('/monitor/tasks', { params, silent: opts?.silent })

export const runInspection = (topologyId: number) =>
  request.post(`/monitor/inspections/${topologyId}`)

// 告警
export const getAlarms = (params?: { status?: string; device_id?: number; limit?: number; offset?: number }, opts?: { silent?: boolean }) =>
  request.get<AlarmRecord[], AlarmRecord[]>('/alarms', { params, silent: opts?.silent })

export const acknowledgeAlarm = (alarmId: number) =>
  request.put(`/alarms/${alarmId}/acknowledge`)

export const closeAlarm = (alarmId: number) =>
  request.put(`/alarms/${alarmId}/close`)

// SSE流（fetch + Authorization 头；EventSource 无法携带 Bearer token）
export const createMonitorStream = (
  onEvent: (data: any) => void,
  onError?: (err: any) => void,
  onClose?: () => void,
): { close: () => void } => {
  const controller = new AbortController()
  const dispatch = (raw: string) => {
    for (const line of raw.split('\n')) {
      if (!line.startsWith('data: ')) continue
      try { onEvent(JSON.parse(line.slice(6))) } catch { /* 忽略坏帧 */ }
    }
  }
  const connect = async () => {
    const token = localStorage.getItem('token')
    try {
      const res = await fetch('/api/v1/monitor/stream', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: controller.signal,
      })
      if (!res.ok || !res.body) throw new Error(`SSE HTTP ${res.status}`)
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''
        for (const part of parts) dispatch(part)
      }
      // 服务端正常关闭：先 flush 残留帧（末帧没有结尾空行时此前会被整段丢弃），
      // 再通知调用方——否则界面会静默停更且永不重连。
      buffer += decoder.decode()
      if (buffer.trim()) dispatch(buffer)
      if (!controller.signal.aborted) onClose?.()
    } catch (err) {
      if (!controller.signal.aborted) onError?.(err)
    }
  }
  void connect()
  return { close: () => controller.abort() }
}
