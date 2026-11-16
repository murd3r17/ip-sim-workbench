<template>
  <div class="webssh-page v7b-page">
    <el-alert v-if="deviceListError" :title="deviceListError" type="error" :closable="false" show-icon><el-button @click="loadDevices">重试设备列表</el-button></el-alert>
    <div style="margin-bottom: 16px; display: flex; gap: 16px; align-items: center; flex-wrap: wrap">
      <el-select v-model="selectedDeviceId" :disabled="connectionActive" placeholder="选择设备" style="width: min(300px, 100%)" @change="onDeviceChange">
        <el-option v-for="d in devices" :key="d.id" :label="`${d.hostname} (${d.mgmt_ip})`" :value="d.id" />
      </el-select>
      <el-button v-if="!connectionActive" type="primary" :disabled="!selectedDeviceId" :loading="checkingAccess"
        @click="connect()">{{ phase === 'failed' ? '重新连接' : '连接' }}</el-button>
      <el-button v-else @click="disconnect">{{ phase === 'ready' ? '断开' : '取消连接' }}</el-button>
      <el-tag :type="phase === 'ready' ? 'success' : phase === 'failed' ? 'danger' : 'info'" role="status">{{ phaseLabel }}</el-tag>
      <el-button @click="router.push('/devices')">返回设备</el-button>
      <el-button
        v-if="labCtx.hasLab && labCtx.sessionId"
        @click="router.push({ path: '/training', query: { session_id: String(labCtx.sessionId) } })"
      >返回实训</el-button>
    </div>
    <el-alert v-if="connectionError" :title="connectionError" type="error" :closable="false" show-icon class="terminal-feedback" />
    <el-alert v-else-if="connectedMode === 'ssh'" title="真实设备。终端中的配置命令会作用于当前设备。"
      type="warning" :closable="false" show-icon class="terminal-feedback" />
    <el-alert
      v-if="labCtx.isActive"
      :type="labModeAlertType"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
      :title="`正在记录到实训 #${labCtx.sessionId}。${labModeTitle}点「断开」后不会自动重连。`"
    />
    <el-alert
      v-else-if="labCtx.sessionId"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
      title="该实训会话已结束：终端仍可查看设备，但不再把命令写入会话记录，也不会绑定教练上下文。"
    />
    <el-alert
      v-if="!loading && selectedDeviceId && phase === 'idle' && !route.params.deviceId"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
      title="已选择设备。点击「连接」，等到显示「终端已就绪」后再输入命令。"
    />
    <WebSSHConsole
      v-if="selectedDeviceId"
      :device-id="selectedDeviceId"
      :auto-connect="connectRequested"
      style="width: 100%; height: calc(100vh - 260px)"
      @phase="onPhase"
      @error="connectionError = $event"
      @command="onTerminalCommand"
    />
    <el-empty v-if="!loading && !devices.length" :description="deviceListError ? '设备列表暂不可用，请从上方重试读取。' : '暂无设备，请先导入拓扑基线或到设备管理添加设备'" :image-size="80" />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getDevices, type DeviceRecord } from '../../api/device'
import { getTerminalAccess, type TerminalAccess } from '../../api/auth'
import { notifyRequestError, requestErrorMessage } from '../../utils/requestError'
import { useAutoRefresh } from '../../utils/autoRefresh'
import WebSSHConsole from '../../components/WebSSHConsole.vue'
import { useAiCopilotStore } from '../../stores/aiCopilot'
import { useLabContextStore } from '../../stores/labContext'
import { useTrainingCommandLog } from '../../composables/useTrainingCommandLog'

const route = useRoute()
const router = useRouter()
const copilot = useAiCopilotStore()
const labCtx = useLabContextStore()
const { logTerminalCommand } = useTrainingCommandLog()
const devices = ref<DeviceRecord[]>([])
const loading = ref(false)
const deviceListError = ref('')
let deviceListEpoch = 0
let accessEpoch = 0
onBeforeUnmount(() => { deviceListEpoch++; accessEpoch++ })
const selectedDeviceId = ref<number | null>(null)
const phases = {
  idle: '未连接',
  connecting: '正在打开终端通道',
  handshake: '正在等待设备握手与认证',
  ready: '终端已就绪',
  retrying: '连接已断，正在等待重试',
  failed: '连接未完成',
}
const phase = ref<keyof typeof phases>('idle')
const phaseLabel = computed(() => phases[phase.value])
const connectionActive = computed(() => phase.value !== 'idle' && phase.value !== 'failed')
const connectRequested = ref(false)
const connectionError = ref('')
const checkingAccess = ref(false)
const connectedMode = ref<TerminalAccess['mode']>()
// AF-04：终端横幅按会话开始时的服务端事实显示，不把“模拟下发”当成 SSH 只读保证
const labModeTitle = computed(() => {
  const facts = (labCtx.modeFacts || {}) as Record<string, string>
  if (facts.device_mode === 'sim') {
    return '模拟设备会话：终端命令不会到达真实网络；仍以“客户端上报”写入日志，仅供复盘。'
  }
  if (facts.device_mode === 'ssh') {
    return facts.deploy_mode === 'simulated'
      ? '真实设备 + 模拟下发：WebSSH 仍可能写入设备，模拟开关不保证只读；命令会以“客户端上报”记入日志。'
      : '真实设备（无环境隔离）：终端命令会真实生效；命令会以“客户端上报”记入日志。'
  }
  return '设备连接方式未记录：不能假定终端是模拟或只读。'
})
const labModeAlertType = computed(() => {
  const facts = (labCtx.modeFacts || {}) as Record<string, string>
  return (facts.device_mode === 'sim' ? 'info' : 'warning') as 'info' | 'warning'
})
// 自动连接只处理一次：避免轮询把用户手动「断开」的状态重置回去
let autoConnectHandled = false

const syncSelection = () => {
  const d = devices.value.find((x) => x.id === selectedDeviceId.value)
  if (!d) return
  labCtx.setDevice({
    id: d.id,
    hostname: d.hostname,
    mgmt_ip: d.mgmt_ip,
  })
  updateSelectionDetail(d)
}

const updateSelectionDetail = (d: DeviceRecord) => {
  copilot.setSelection({
    kind: 'device',
    id: d.id,
    label: d.hostname,
    detail: `${d.mgmt_ip || ''} · ${phaseLabel.value}`,
  })
}

const loadDevices = async () => {
  const epoch = ++deviceListEpoch
  loading.value = true
  try {
    const rows = await getDevices()
    if (epoch !== deviceListEpoch) return
    devices.value = rows
    deviceListError.value = ''
    // 路由/实训上下文仅用于首次选中。轮询不能改变用户当前连接的目标。
    if (!autoConnectHandled) {
      const deviceId = route.params.deviceId || labCtx.device?.id
      if (deviceId) selectedDeviceId.value = Number(deviceId)
      else if (devices.value.length) selectedDeviceId.value = devices.value[0].id
      autoConnectHandled = true
      syncSelection()
      if (route.params.deviceId) void connect()
    }
  } catch (err) {
    if (epoch === deviceListEpoch) {
      deviceListError.value = '设备列表读取失败，原选择与已显示设备保留；请重试。'
      notifyRequestError(err, '加载设备列表失败')
    }
  } finally {
    if (epoch === deviceListEpoch) loading.value = false
  }
}

const onPhase = (value: keyof typeof phases) => {
  phase.value = value
  if (value === 'ready') connectionError.value = ''
  const selection = copilot.selection
  if (selection?.kind !== 'device' || selection.id !== selectedDeviceId.value) return
  const device = devices.value.find(row => row.id === selection.id)
  if (device) updateSelectionDetail(device)
}

const onTerminalCommand = (payload: { command: string; success: boolean; result: string }) => {
  const d = devices.value.find((x) => x.id === selectedDeviceId.value)
  logTerminalCommand({ ...payload, hostname: d?.hostname })
}

const invalidateAccess = () => {
  accessEpoch++
  checkingAccess.value = false
  connectionError.value = ''
}

const onDeviceChange = () => {
  invalidateAccess()
  connectedMode.value = undefined
  phase.value = 'idle'
  syncSelection()
}

const connect = async () => {
  const target = selectedDeviceId.value
  if (!target || connectionActive.value) return
  const epoch = ++accessEpoch
  connectionError.value = ''
  if (connectRequested.value) {
    connectRequested.value = false
    await nextTick()
    if (target !== selectedDeviceId.value) return
  }
  checkingAccess.value = true
  try {
    const access = await getTerminalAccess(target)
    if (epoch !== accessEpoch || target !== selectedDeviceId.value) return
    connectedMode.value = access.mode
    if (!access.allowed) {
      phase.value = 'failed'
      connectionError.value = access.reason || '请联系管理员获取该设备的终端权限。'
      return
    }
    connectRequested.value = true
  } catch (error) {
    if (epoch !== accessEpoch || target !== selectedDeviceId.value) return
    phase.value = 'failed'
    connectionError.value = requestErrorMessage(error, '无法核对终端授权，请重新连接。')
  } finally {
    if (epoch === accessEpoch) checkingAccess.value = false
  }
}

const disconnect = () => {
  invalidateAccess()
  connectRequested.value = false
  connectedMode.value = undefined
}

// 路由参数变化（如从设备列表跳转 /webssh/:id）时重新装载目标设备
watch(
  () => route.params.deviceId,
  (newId) => {
    if (!newId || !autoConnectHandled) return
    selectedDeviceId.value = Number(newId)
    connectRequested.value = false
    onDeviceChange()
    void connect()
  }
)

onMounted(() => {
  loadDevices()
  useAutoRefresh(loadDevices, 15000)
})
</script>

<style scoped>
.terminal-feedback { margin-bottom: 12px; }
</style>
