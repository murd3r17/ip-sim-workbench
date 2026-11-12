import request from './request'

export interface DeviceRecord {
  id: number
  hostname: string
  mgmt_ip: string
  ssh_port?: number
  status: string
  device_type: string
  vendor?: string
  model?: string
  topology_id?: number
  network_role?: string
}

export interface TopologyRecord {
  id: number
  name: string
  device_count?: number
  status?: string
  topology_type?: string
}

export interface TopologyLinkRecord {
  id: number
  source_device_id: number
  source_interface: string
  target_device_id: number
  target_interface: string
  link_type: string
  status: string
  bandwidth?: string
  discovery_source?: string
  source_type: string
  source_ip?: string
  target_ip?: string
}

export interface ImportedLink {
  source_device: string
  source_interface: string
  target_device: string
  target_interface: string
  source_ip?: string
  target_ip?: string
}

export interface TopologyRuntimeDiff {
  missing: ImportedLink[]
  unexpected: ImportedLink[]
}

export interface RuntimeCheckResult {
  check_id: number
  status: 'matched' | 'different' | 'partial' | 'no_baseline'
  discovered: number
  imported: 0
  ssh_success: number
  ssh_failed: number
  links: ImportedLink[]
  diff: TopologyRuntimeDiff
  errors: string[]
  created_at?: string
  compared_version_id?: number | null
  confirmed_version_id?: number | null
  current_version_id?: number | null
  is_stale?: boolean
  evidence_stale?: boolean
  mode_changed?: boolean
  coverage?: {
    version: string; mode: string; expected_devices: number; parsed_devices: number
    baseline_count: number; manual_count: number; bidirectional_links: number; one_sided_links: number
    devices: { device_id: number; hostname: string; state: string; complete: boolean; ssh_ok: boolean; observed_at: string }[]
    unmanaged_neighbors: { hostname: string; local_interface: string; neighbor_device: string; remote_interface: string }[]
    multi_neighbor_ports: { hostname: string; local_interface: string; neighbors: string[] }[]
  } | null
}

export interface RuntimeBaselineConfirmationResult {
  version: number
  runtime_check_id: number
  device_count: number
  link_count: number
  diff: Record<string, number>
}

export interface ImportPreview {
  is_valid: boolean
  inventory_only: boolean
  device_count: number
  link_count: number
  issues: Array<{ code: string; message: string; row?: number }>
  ignored_sensitive_columns: string[]
  current_device_count: number
  current_link_count: number
  replaced_link_count: number
}

export interface TopologyVersion {
  id: number
  version: number
  batch_id: string
  source_name: string
  source_type: string
  summary: Record<string, number>
  rollback_of_version?: number
  created_at: string
}

export interface TopologyLayoutPosition {
  x: number
  y: number
}

export interface TopologyLayout {
  draft_positions: Record<string, TopologyLayoutPosition>
  published_positions: Record<string, TopologyLayoutPosition>
}

export const getDevices = (params?: { topology_id?: number; status?: string }) =>
  request.get<DeviceRecord[], DeviceRecord[]>('/devices', { params })

export const getDevice = (id: number) => request.get<DeviceRecord, DeviceRecord>(`/devices/${id}`)

export const createDevice = (data: any) => request.post('/devices', data)

export const updateDevice = (id: number, data: any) => request.put(`/devices/${id}`, data)

export const deleteDevice = (id: number) => request.delete(`/devices/${id}`)

export const checkDevicesHealth = (topologyId?: number) =>
  request.post<{ total: number; results: { hostname: string; status: string }[] }, { total: number; results: { hostname: string; status: string }[] }>(
    '/devices/health-check',
    undefined,
    { params: topologyId ? { topology_id: topologyId } : undefined },
  )

export const getTopologies = () => request.get<TopologyRecord[], TopologyRecord[]>('/topologies')

export const createTopology = (data: any) => request.post('/topologies', data)

export const getTopologyLinks = (topologyId: number) =>
  request.get<TopologyLinkRecord[], TopologyLinkRecord[]>(`/topologies/${topologyId}/links`)

export const getTopologyLayout = (topologyId: number) =>
  request.get<TopologyLayout, TopologyLayout>(`/topologies/${topologyId}/layout`)

export const saveTopologyLayoutDraft = (topologyId: number, positions: Record<string, TopologyLayoutPosition>) =>
  request.put<TopologyLayout, TopologyLayout>(`/topologies/${topologyId}/layout/draft`, { positions })

export const publishTopologyLayout = (topologyId: number) =>
  request.post<TopologyLayout, TopologyLayout>(`/topologies/${topologyId}/layout/publish`)

export const discoverTopologyLinks = (topologyId: number) =>
  request.post<RuntimeCheckResult, RuntimeCheckResult>(`/topologies/${topologyId}/discover`)

export const getLatestRuntimeCheck = (topologyId: number) =>
  request.get<RuntimeCheckResult | null, RuntimeCheckResult | null>(`/topologies/${topologyId}/runtime-checks/latest`)

export const confirmRuntimeTopologyBaseline = (topologyId: number, runtimeCheckId: number) =>
  request.post<RuntimeBaselineConfirmationResult, RuntimeBaselineConfirmationResult>(
    `/topologies/${topologyId}/runtime-checks/${runtimeCheckId}/confirm-baseline`,
    undefined,
    { params: { confirm: true } },
  )

const excelForm = (file: File) => {
  const form = new FormData()
  form.append('file', file)
  return form
}

export const validateTopologyImport = (topologyId: number, file: File, inventoryOnly = false) =>
  request.post<ImportPreview, ImportPreview>(
    `/topologies/${topologyId}/imports/validate`,
    excelForm(file),
    { params: { inventory_only: inventoryOnly } },
  )

export const importTopologyBaseline = (topologyId: number, file: File, inventoryOnly = false) =>
  request.post(`/topologies/${topologyId}/imports`, excelForm(file), {
    params: { confirm: true, inventory_only: inventoryOnly },
  })

export const getTopologyVersions = (topologyId: number) =>
  request.get<TopologyVersion[], TopologyVersion[]>(`/topologies/${topologyId}/versions`)

export const rollbackTopologyVersion = (topologyId: number, version: number) =>
  request.post(`/topologies/${topologyId}/versions/${version}/rollback`, undefined, {
    params: { confirm: true },
  })
