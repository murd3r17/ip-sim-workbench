import request from './request'

export interface EnvironmentDevice {
  device_id: number
  role: string
  mgmt_ip?: string
  vendor?: string
  os_version?: string
  interfaces: Array<{ name: string; address?: string; peer?: string; purpose?: string }>
  expected_neighbors?: string[] | null
  expected_routes?: string[] | null
}

export interface EnvironmentRecord {
  id: number
  name: string
  version: string
  site: string
  status: string
  devices: EnvironmentDevice[]
  protections: Array<Record<string, unknown>>
  expected_neighbors: string[]
  expected_routes: string[]
  source: string
  revision: number
  content_hash: string
  last_preflight_status: string
  last_preflight_at: string
  updated_at: string
}

export interface PreflightResult {
  environment_id: number
  version: string
  status: string
  checks: Array<{ check: string; status: string; detail: string; device_id?: number }>
  checked_at: string
  verification_mode: string
  real_device_verified: boolean
  environment_revision: number
}

export interface ObservationRecord {
  id: number
  environment_id: number | null
  environment_version: string
  environment_snapshot: Record<string, unknown>
  device_id: number
  action_id: string
  command: string
  collected_at: string
  source: string
  mode: string
  adapter_mode: string
  completeness: string
  parser_version: string
  facts: {
    interfaces?: Array<{ name: string; state: string; address: string }>
    peers?: Array<{ neighbor_id: string; state: string }>
    routes?: Array<{ destination: string; next_hop: string }>
    [key: string]: unknown
  }
  raw_excerpt?: string
  status: string
  error_message: string
}

export const getEnvironments = () => request.get<EnvironmentRecord[]>('/trust/environments')
export const getEnvironment = (id: number) => request.get<EnvironmentRecord>(`/trust/environments/${id}`)
export const createEnvironment = (data: Record<string, unknown>) => request.post<EnvironmentRecord>('/trust/environments', data)
export const updateEnvironment = (id: number, data: Record<string, unknown>) => request.put<EnvironmentRecord>(`/trust/environments/${id}`, data)
export const preflightEnvironment = (id: number) => request.post<PreflightResult>(`/trust/environments/${id}/preflight`, {})
export const getObservations = (params?: Record<string, unknown>) => request.get<ObservationRecord[]>('/trust/observations', { params })
export const createObservation = (data: { device_id: number; action_id: string; environment_id?: number | null }) =>
  request.post<ObservationRecord>('/trust/observations', data)
export const evaluateOspf = (data: Record<string, unknown>) => request.post<Record<string, unknown>>('/trust/rules/ospf/evaluate', data)
export const getLocks = () => request.get<Array<Record<string, unknown>>>('/trust/locks')
export const recoverLock = (deviceId: number, options?: { silent?: boolean }) =>
  request.post<Record<string, unknown>>(`/trust/locks/${deviceId}/recover`, {}, { silent: options?.silent })
export const getPageCatalog = () => request.get<Array<Record<string, unknown>>>('/trust/pages')
export const getActionCatalog = () => request.get<Array<Record<string, unknown>>>('/trust/actions')
