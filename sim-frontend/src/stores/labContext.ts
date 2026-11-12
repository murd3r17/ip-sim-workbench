import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { useAiCopilotStore } from './aiCopilot'

export interface LabDeviceRef {
  id: number
  hostname: string
  mgmt_ip?: string
  model?: string
}

export interface LabAlarmRef {
  id: number | string
  label: string
  detail?: string
  device_id?: number
}

function persist(key: string, value: unknown) {
  try {
    if (value == null) localStorage.removeItem(key)
    else localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* ignore */
  }
}

function load<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    return null
  }
}

export const useLabContextStore = defineStore('labContext', () => {
  const sessionId = ref<number | null>(load<number>('lab_ctx_session'))
  const sessionStatus = ref<string>(localStorage.getItem('lab_ctx_status') || '')
  const labId = ref<number | null>(load<number>('lab_ctx_lab'))
  const labTitle = ref(localStorage.getItem('lab_ctx_title') || '')
  const topologyId = ref<number | null>(load<number>('lab_ctx_topo'))
  const device = ref<LabDeviceRef | null>(load<LabDeviceRef>('lab_ctx_device'))
  const alarm = ref<LabAlarmRef | null>(load<LabAlarmRef>('lab_ctx_alarm'))
  // 实验步骤（实训引导用）：[{id,name,goal,config_hint,verify_command,verify_contains}]
  const labSteps = ref<any[]>(load<any[]>('lab_ctx_steps') || [])
  // AF-04：会话开始时的服务端模式事实，供终端横幅等页面准确显示
  const modeFacts = ref<any>(load<any>('lab_ctx_modes'))

  const hasLab = computed(() => sessionId.value != null || !!labTitle.value)
  /** V7-A A-04：只有 active 会话才允许绑定终端与教练。 */
  const isActive = computed(() => sessionId.value != null && sessionStatus.value === 'in_progress')
  const label = computed(() => {
    if (labTitle.value) return labTitle.value
    if (sessionId.value) return `会话 #${sessionId.value}`
    return ''
  })

  function syncCopilotDevice() {
    const copilot = useAiCopilotStore()
    if (!device.value) return
    copilot.setSelection({
      kind: 'device',
      id: device.value.id,
      label: device.value.hostname,
      detail: device.value.mgmt_ip || '',
      model: device.value.model,
    })
  }

  function syncCopilotAlarm() {
    const copilot = useAiCopilotStore()
    if (!alarm.value) return
    copilot.setSelection({
      kind: 'alarm',
      id: alarm.value.id,
      label: alarm.value.label,
      detail: alarm.value.detail,
    })
  }

  function startLab(payload: {
    sessionId: number
    labId: number
    labTitle: string
    topologyId?: number | null
    labSteps?: any[]
    modeFacts?: any
    status?: string
  }) {
    sessionId.value = payload.sessionId
    sessionStatus.value = payload.status || 'in_progress'
    labId.value = payload.labId
    labTitle.value = payload.labTitle
    topologyId.value = payload.topologyId ?? null
    labSteps.value = payload.labSteps || []
    modeFacts.value = payload.modeFacts || null
    persist('lab_ctx_session', sessionId.value)
    persist('lab_ctx_lab', labId.value)
    localStorage.setItem('lab_ctx_title', labTitle.value)
    localStorage.setItem('lab_ctx_status', sessionStatus.value)
    persist('lab_ctx_topo', topologyId.value)
    persist('lab_ctx_steps', labSteps.value)
    persist('lab_ctx_modes', modeFacts.value)

    const copilot = useAiCopilotStore()
    copilot.setNotes(`当前实训：${payload.labTitle}（session=${payload.sessionId}）`)
    copilot.setOpen(true)
  }

  function setTopology(id: number | null) {
    topologyId.value = id
    persist('lab_ctx_topo', id)
  }

  function setDevice(dev: LabDeviceRef | null) {
    device.value = dev
    persist('lab_ctx_device', dev)
    if (dev) syncCopilotDevice()
  }

  function setAlarm(a: LabAlarmRef | null) {
    alarm.value = a
    persist('lab_ctx_alarm', a)
    if (a) syncCopilotAlarm()
  }

  function clearLab() {
    sessionId.value = null
    labId.value = null
    labTitle.value = ''
    topologyId.value = null
    labSteps.value = []
    modeFacts.value = null
    persist('lab_ctx_session', null)
    persist('lab_ctx_lab', null)
    localStorage.removeItem('lab_ctx_title')
    persist('lab_ctx_topo', null)
    persist('lab_ctx_steps', null)
    persist('lab_ctx_modes', null)
    const copilot = useAiCopilotStore()
    if ((copilot.notes || '').startsWith('当前实训：')) copilot.setNotes('')
  }

  function clearAll() {
    clearLab()
    setDevice(null)
    setAlarm(null)
  }

  return {
    sessionId,
    sessionStatus,
    labId,
    labTitle,
    topologyId,
    device,
    alarm,
    labSteps,
    modeFacts,
    hasLab,
    isActive,
    label,
    startLab,
    setTopology,
    setDevice,
    setAlarm,
    clearLab,
    clearAll,
    syncCopilotDevice,
    syncCopilotAlarm,
  }
})
