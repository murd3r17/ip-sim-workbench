<template>
  <div class="webssh-page v7b-page">
    <el-alert v-if="deviceListError" :title="deviceListError" type="error" :closable="false" show-icon><el-button @click="loadDevices">重试设备列表</el-button></el-alert>
    <div style="margin-bottom: 16px; display: flex; gap: 16px; align-items: center; flex-wrap: wrap">
      <el-select v-model="selectedDeviceId" placeholder="选择设备" style="width: 300px">
        <el-option v-for="d in devices" :key="d.id" :label="`${d.hostname} (${d.mgmt_ip})`" :value="d.id" />
      </el-select>
      <el-button type="primary" :disabled="!selectedDeviceId || connected" @click="connect">连接</el-button>
      <el-button type="danger" :disabled="!connected && !reconnectNeeded" @click="disconnect">断开</el-button>
      <el-button v-if="reconnectNeeded" type="warning" :disabled="!selectedDeviceId" @click="reconnect">重新连接</el-button>
      <el-tag v-if="connected" type="success">已连接</el-tag>
      <el-tag v-else-if="reconnectNeeded" type="warning">已停止自动重连</el-tag>
      <el-tag v-else type="info">未连接</el-tag>
      <el-button @click="router.push('/devices')">返回设备</el-button>
      <el-button
        v-if="labCtx.hasLab && labCtx.sessionId"
        @click="router.push({ path: '/training', query: { session_id: String(labCtx.sessionId) } })"
      >返回实训</el-button>
    </div>
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
      v-if="!loading && selectedDeviceId && !connected && !connectRequested && !reconnectNeeded && !route.params.deviceId"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
      title="已预选设备，请点「连接」建立 SSH。从设备页点「终端」会自动连上对应设备。"
    />
    <WebSSHConsole
      v-if="selectedDeviceId"
      :device-id="selectedDeviceId"
      :auto-connect="connectRequested"
      style="width: 100%; height: calc(100vh - 260px)"
      @status="onStatus"
      @error="onConnectError"
      @command="onTerminalCommand"
      @reconnect-exhausted="reconnectNeeded = true"
    />
    <el-empty v-if="!loading && !devices.length" :description="deviceListError ? '设备列表暂不可用，请从上方重试读取。' : '暂无设备，请先导入拓扑基线或到设备管理添加设备'" :image-size="80" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus/es/components/message/index'
import { getDevices, type DeviceRecord } from '../../api/device'
import { notifyRequestError } from '../../utils/requestError'
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
onBeforeUnmount(() => { deviceListEpoch++ })
const selectedDeviceId = ref<number | null>(null)
const connected = ref(false)
const connectRequested = ref(false)
const reconnectNeeded = ref(false)
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
  copilot.setSelection({
    kind: 'device',
    id: d.id,
    label: d.hostname,
    detail: `${d.mgmt_ip || ''} · WebSSH${connected.value ? '已连接' : '未连接'}`,
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
      connectRequested.value = !!route.params.deviceId
      autoConnectHandled = true
    }
    syncSelection()
  } catch (err) {
    if (epoch === deviceListEpoch) {
      deviceListError.value = '设备列表读取失败，原选择与已显示设备保留；请重试。'
      notifyRequestError(err, '加载设备列表失败')
    }
  } finally {
    if (epoch === deviceListEpoch) loading.value = false
  }
}

const onConnectError = (message: string) => {
  ElMessage.error(message || '设备未接入或凭据为空')
}

const onStatus = (value: boolean) => {
  connected.value = value
  if (value) reconnectNeeded.value = false
}

const onTerminalCommand = (payload: { command: string; success: boolean; result: string }) => {
  const d = devices.value.find((x) => x.id === selectedDeviceId.value)
  logTerminalCommand({ ...payload, hostname: d?.hostname })
}

const connect = () => {
  if (!selectedDeviceId.value || connected.value) return
  reconnectNeeded.value = false
  connectRequested.value = true
  syncSelection()
}

const reconnect = () => {
  connectRequested.value = false
  reconnectNeeded.value = false
  requestAnimationFrame(() => {
    connectRequested.value = true
  })
}

const disconnect = () => {
  reconnectNeeded.value = false
  connectRequested.value = false
}

watch(selectedDeviceId, syncSelection)
watch(connected, syncSelection)

// 路由参数变化（如从设备列表跳转 /webssh/:id）时重新装载目标设备
watch(
  () => route.params.deviceId,
  (newId) => {
    if (!newId) return
    autoConnectHandled = true
    selectedDeviceId.value = Number(newId)
    connectRequested.value = true
    syncSelection()
  }
)

onMounted(() => {
  loadDevices()
  useAutoRefresh(loadDevices, 15000)
})
</script>
