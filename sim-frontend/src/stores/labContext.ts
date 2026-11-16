import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { useAiCopilotStore } from './aiCopilot'
import { accountStorageKey } from './browserSession'

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
  const scope = accountStorageKey('lab:')
  const get = <T>(key: string) => load<T>(scope + key)
  const save = (key: string, value: unknown) => persist(scope + key, value)
  const sessionId = ref(get<number>('session'))
  const sessionStatus = ref(get<string>('status') || '')
  const labId = ref(get<number>('lab'))
  const labTitle = ref(get<string>('title') || '')
  const topologyId = ref(get<number>('topo'))
  const device = ref(get<LabDeviceRef>('device'))
  const alarm = ref(get<LabAlarmRef>('alarm'))
  // 实验步骤（实训引导用）：[{id,name,goal,config_hint,verify_command,verify_contains}]
  const labSteps = ref<any[]>(get<any[]>('steps') || [])
  // AF-04：会话开始时的服务端模式事实，供终端横幅等页面准确显示
  const modeFacts = ref<any>(get<any>('modes'))

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
    save('session', sessionId.value)
    save('lab', labId.value)
    save('title', labTitle.value)
    save('status', sessionStatus.value)
    save('topo', topologyId.value)
    save('steps', labSteps.value)
    save('modes', modeFacts.value)

    const copilot = useAiCopilotStore()
    copilot.linkLab(payload.sessionId)
    copilot.setOpen(true)
  }

  function setTopology(id: number | null) {
    topologyId.value = id
    save('topo', id)
  }

  function setDevice(dev: LabDeviceRef | null) {
    device.value = dev
    save('device', dev)
    if (dev) syncCopilotDevice()
  }

  function setAlarm(a: LabAlarmRef | null) {
    alarm.value = a
    save('alarm', a)
    if (a) syncCopilotAlarm()
  }

  function clearLab() {
    sessionId.value = null
    sessionStatus.value = ''
    labId.value = null
    labTitle.value = ''
    topologyId.value = null
    labSteps.value = []
    modeFacts.value = null
    for (const key of ['session', 'status', 'lab', 'title', 'topo', 'steps', 'modes']) save(key, null)
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
