import request from './request'

export interface DashboardNode {
  id: number
  hostname: string
  status: string
  device_type: string
  network_role: string
}

export interface DashboardLink {
  id: number
  source_device_id: number
  source_interface: string
  target_device_id: number
  target_interface: string
  status: string
}

export interface DashboardTask {
  id: number
  kind: string
  name: string
  status: string
  progress: number
  batch_id?: number | null
  device_name?: string
  high_risk: boolean
  has_diff: boolean
  created_at: string
}

export interface DashboardSummary {
  generated_at: string
  environment_name: string
  environment_status: string
  device_mode?: string | null
  devices: { total: number; online: number; ssh_reachable: number; offline: number; maintenance: number; unknown: number }
  topology: null | {
    id: number
    name: string
    status: string
    device_count: number
    link_count: number
    nodes: DashboardNode[]
    links: DashboardLink[]
    published_positions: Record<string, { x: number; y: number }>
  }
  tasks: { active: number; pending: number; failed: number; with_diff: number; deploy_batches?: number; items: DashboardTask[] }
  alarms: {
    active: number
    critical: number
    items: Array<{
      id: number
      device_id: number
      device_name: string
      alarm_type?: string | null
      severity: string
      message: string
      metric_value?: number | null
      threshold?: number | null
      status: string
      fired_at: string
    }>
    trend?: Array<{ date: string; count: number }>
  }
  services: {
    database: { status: string }
    llm: { status: string; provider?: string; model?: string; config_source?: string; checked_at?: string | null }
    knowledge: { status: string; provider?: string; available?: boolean; document_count?: number; workspace?: string }
  }
  risks: {
    pending_approval: number
    items: Array<{ level: string; title: string; detail: string; recommendation: string; route: string }>
  }
  approvals?: Array<{
    id: number
    name?: string | null
    device_name: string
    status: string
    high_risk: boolean
    change_level?: string
    created_at: string
  }>
  reports?: Array<{
    id: number
    topology_id?: number | null
    job_type: string
    status: string
    trigger_mode: string
    device_count: number
    success_count: number
    failure_count: number
    skipped_count?: number | null
    alarm_count?: number | null
    created_at: string
  }>
  activity: Array<{ id: number; module: string; action: string; result: string; created_at: string }>
  monitor_scheduler_enabled?: boolean
  training?: { active: number; total: number; intro_lab_id?: number | null }
}

export const getDashboardSummary = () => request.get<DashboardSummary, DashboardSummary>('/dashboard/summary', { params: { include_service_health: false } })
export const getDashboardServices = () => request.get<DashboardSummary['services'], DashboardSummary['services']>('/dashboard/services', { silent: true })
