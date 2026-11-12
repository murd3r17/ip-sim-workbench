<template>
  <div class="device-page v7b-page">
    <PageHeader
      title="设备"
      subtitle="先看对象、状态和最近一次只读事实，再决定是否进入终端或变更；这里的观察不会写设备。"
    >
      <template #actions>
        <el-button :loading="healthChecking" @click="handleHealthCheck">健康检查</el-button>
        <el-button @click="openObservation()">只读观察</el-button>
        <AdminAction v-slot="{ disabled }">
          <el-button type="primary" :disabled="disabled" @click="openCreate">添加设备</el-button>
        </AdminAction>
      </template>
    </PageHeader>
    <div class="toolbar">
      <el-input v-model="search" placeholder="搜索设备..." clearable class="search" />
      <div class="v7b-actions">
        <el-button
          v-if="labCtx.hasLab && labCtx.sessionId"
          @click="router.push({ path: '/training', query: { session_id: String(labCtx.sessionId) } })"
        >返回实训</el-button>
        <span class="table-hint">{{ deviceLoadError ? '设备列表暂不可用' : `共 ${filteredDevices.length} 台` }} · 观察只读，终端/下发另开</span>
      </div>
    </div>

    <el-alert v-if="deviceLoadError" :title="deviceLoadError" type="error" :closable="false" show-icon><el-button @click="loadDevices">重试设备列表</el-button></el-alert>
    <el-table :data="filteredDevices" border class="device-table" height="100%" v-loading="loading" @row-click="onRowClick">
      <template #empty>
        <el-empty :description="deviceLoadError || '暂无设备。可先去拓扑页新建拓扑并导入 Excel，或在此添加设备。'" :image-size="72">
          <el-button v-if="!deviceLoadError" type="primary" @click="router.push('/topology')">去拓扑导入</el-button>
        </el-empty>
      </template>
      <el-table-column label="设备" min-width="190">
        <template #default="{ row }">
          <div class="device-name">{{ row.hostname }}</div>
          <div class="device-sub">{{ row.vendor || '厂商未知' }} · {{ row.model || '型号未登记' }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="mgmt_ip" label="管理IP" width="132" />
      <el-table-column prop="device_type" label="类型" width="92" />
      <el-table-column label="状态" width="92">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="230" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" @click.stop="openObservation(row)">只读观察</el-button>
          <el-button size="small" @click.stop="openWebSSH(row)">终端</el-button>
          <el-dropdown trigger="click" @command="(cmd: string) => handleRowCommand(cmd, row)">
            <el-button size="small" text>更多</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="deploy">配置下发</el-dropdown-item>
                <el-dropdown-item command="alarms">查看告警</el-dropdown-item>
                <AdminAction v-slot="{ disabled }">
                  <el-dropdown-item command="edit" :disabled="disabled">编辑设备</el-dropdown-item>
                  <el-dropdown-item command="delete" :disabled="disabled" divided>删除设备</el-dropdown-item>
                </AdminAction>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
      </el-table-column>
    </el-table>

    <!-- 添加 / 编辑设备弹窗 -->
    <el-dialog v-model="showForm" :title="editingId ? '编辑设备' : '添加设备'" width="500px" draggable>
      <el-alert v-if="topologyLoadError" :title="topologyLoadError" type="error" :closable="false" show-icon><el-button @click="loadTopologies">重试拓扑列表</el-button></el-alert>
      <el-form ref="addFormRef" :model="addForm" :rules="addRules" label-width="80px">
        <el-form-item label="主机名" prop="hostname"><el-input v-model="addForm.hostname" /></el-form-item>
        <el-form-item label="管理IP" prop="mgmt_ip"><el-input v-model="addForm.mgmt_ip" /></el-form-item>
        <el-form-item label="SSH端口"><el-input-number v-model="addForm.ssh_port" :min="1" :max="65535" /></el-form-item>
        <el-form-item label="设备类型">
          <el-select v-model="addForm.device_type">
            <el-option label="路由器" value="router" />
            <el-option label="二层交换机" value="switch_l2" />
            <el-option label="三层交换机" value="switch_l3" />
            <el-option label="防火墙" value="firewall" />
          </el-select>
        </el-form-item>
        <el-form-item label="型号"><el-input v-model="addForm.model" /></el-form-item>
        <el-form-item v-if="!editingId" label="所属拓扑">
          <el-select v-model="addForm.topology_id" placeholder="选择拓扑">
            <el-option v-for="t in topologies" :key="t.id" :label="`${t.name} (id=${t.id})`" :value="t.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showForm = false">取消</el-button>
        <el-button type="primary" :loading="adding" @click="handleSave">确定</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="showObservation" :title="observationDevice ? `只读观察 · ${observationDevice.hostname}` : '只读观察'" size="min(560px, 94vw)" destroy-on-close @close="invalidateObservation">
      <el-alert v-if="environmentLoadError" :title="environmentLoadError" type="error" :closable="false" show-icon><el-button @click="loadEnvironments">重试环境列表</el-button></el-alert>
      <div class="obs-form">
        <el-alert type="info" :closable="false" show-icon title="只允许目录内只读动作；命令由服务端固定，不接受任意命令/换行注入。记录来源为 server_observed。" />
        <el-form label-width="86px">
          <el-form-item label="动作">
            <el-select v-model="observationAction" style="width: 100%" @change="resetObservation">
              <el-option label="接口状态与地址" value="interface_brief" />
              <el-option label="OSPF 邻居" value="ospf_peer" />
              <el-option label="OSPF 路由" value="ospf_route" />
            </el-select>
          </el-form-item>
          <el-form-item label="环境映射">
            <el-select v-model="observationEnvironment" clearable placeholder="可选：归到某个环境" style="width: 100%" @change="resetObservation">
              <el-option v-for="env in environments" :key="env.id" :label="`${env.name} · ${env.version}`" :value="env.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="设备">
            <el-select v-model="observationDeviceId" style="width: 100%" @change="selectObservationDevice">
              <el-option v-for="d in devices" :key="d.id" :label="`${d.hostname} · ${d.mgmt_ip}`" :value="d.id" />
            </el-select>
          </el-form-item>
        </el-form>
        <div class="v7b-actions" style="margin: 4px 0 10px">
          <el-button type="primary" :loading="observing" @click="runObservation">采集只读事实</el-button>
          <el-button @click="loadRecentObservations">最近证据</el-button>
          <el-button v-if="observationEnvironment" @click="runPreflight">环境预检</el-button>
        </div>
        <el-alert v-if="preflightText" :title="preflightText" type="warning" :closable="false" show-icon />
        <el-alert v-if="observationError" :title="observationError" type="error" :closable="false" show-icon />
        <div v-if="observation" class="obs-result">
          <div class="obs-meta">
            <span class="v7b-pill" :class="observation.status === 'ok' ? 'ok' : 'danger'">{{ observationStatusLabel(observation.status) }}</span>
            <span class="v7b-pill" :class="observation.completeness === 'complete' ? 'ok' : 'warn'">{{ observationCompletenessLabel(observation.completeness) }}</span>
            <span>采集 {{ formatApiTime(observation.collected_at) }}</span>
            <span>来源 {{ observation.source === 'server_observed' ? '服务端观察' : observation.source || '未记录' }}</span>
            <span>{{ observationModeLabel(observation.mode) }}</span>
            <span>解析器 {{ observation.parser_version }}</span>
            <span v-if="observation.environment_version">环境 {{ observation.environment_version }}</span>
          </div>
          <div v-if="observation.facts.interfaces?.length" class="facts">
            <h4>接口</h4>
            <el-table :data="observation.facts.interfaces" size="small">
              <el-table-column prop="name" label="接口" min-width="150" />
              <el-table-column prop="state" label="状态" width="80" />
              <el-table-column prop="address" label="地址" min-width="130" />
            </el-table>
          </div>
          <div v-if="observation.facts.peers?.length" class="facts">
            <h4>OSPF 邻居</h4>
            <el-table :data="observation.facts.peers" size="small">
              <el-table-column prop="neighbor_id" label="邻居" min-width="140" />
              <el-table-column prop="state" label="状态" width="100" />
            </el-table>
          </div>
          <div v-if="observation.facts.routes?.length" class="facts">
            <h4>OSPF 路由</h4>
            <el-table :data="observation.facts.routes" size="small">
              <el-table-column prop="destination" label="目的" min-width="140" />
              <el-table-column prop="next_hop" label="下一跳" min-width="130" />
            </el-table>
          </div>
          <div v-if="observation.error_message" class="obs-error">{{ observation.error_message }}</div>
          <details>
            <summary>受控原文（前 2000 字）</summary>
            <pre>{{ observation.raw_excerpt || '（无）' }}</pre>
          </details>
          <details><summary>原始记录字段</summary><pre>{{ JSON.stringify({status:observation.status,completeness:observation.completeness,collected_at:observation.collected_at,source:observation.source,mode:observation.mode,parser_version:observation.parser_version},null,2) }}</pre></details>
          <div class="v7b-actions">
            <el-button size="small" @click="evaluateRule">与本环境预期比对</el-button>
            <span v-if="ruleText" class="rule-text">{{ ruleText }}</span>
          </div>
        </div>
        <el-alert v-if="historyError" :title="historyError" type="error" :closable="false" show-icon />
        <div v-if="recentObservations.length" class="recent">
          <h4>最近证据</h4>
          <button v-for="item in recentObservations" :key="item.id" class="recent-row" @click="useObservation(item)">
            <span>#{{ item.id }} · {{ item.action_id }}</span>
            <small>{{ formatApiTime(item.collected_at) }} · {{ observationStatusLabel(item.status) }} / {{ observationCompletenessLabel(item.completeness) }}</small>
          </button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus/es/components/message/index'
import { ElMessageBox } from 'element-plus/es/components/message-box/index'
import type { FormInstance, FormRules } from 'element-plus'
import { getDevices, getTopologies, createDevice, updateDevice, deleteDevice, checkDevicesHealth, type DeviceRecord } from '../../api/device'
import { useAutoRefresh } from '../../utils/autoRefresh'
import { useSnapshotRequest } from '../../composables/useSnapshotRequest'
import { deviceStatusLabel, deviceStatusTagType, observationStatusLabel, observationCompletenessLabel, observationModeLabel } from '../../utils/display'
import { formatApiTime } from '../../utils/datetime'
import { useAiCopilotStore } from '../../stores/aiCopilot'
import { useLabContextStore } from '../../stores/labContext'
import AdminAction from '../../components/AdminAction.vue'
import PageHeader from '../../components/v7b/PageHeader.vue'
import { createObservation, getEnvironments, getObservations, preflightEnvironment, type EnvironmentRecord, type ObservationRecord } from '../../api/trust'

const router = useRouter()
const copilot = useAiCopilotStore()
const labCtx = useLabContextStore()
const devices = ref<DeviceRecord[]>([])
const topologies = ref<{ id: number; name: string; status?: string }[]>([])
const topologyRequest = useSnapshotRequest('拓扑列表')
const topologyLoadError = topologyRequest.error
const environmentRequest = useSnapshotRequest('环境列表')
const environmentLoadError = environmentRequest.error
const deviceRequest = useSnapshotRequest('设备列表')
const loading = deviceRequest.loading
const deviceLoadError = deviceRequest.error
const healthChecking = ref(false)
const search = ref('')
const showForm = ref(false)
const editingId = ref<number | null>(null)
const adding = ref(false)
const addFormRef = ref<FormInstance>()
const emptyForm = () => ({ hostname: '', mgmt_ip: '', ssh_port: 22, device_type: 'router', model: '', topology_id: 0 })
const addForm = ref(emptyForm())
const ipv4 = /^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$/
const showObservation = ref(false)
const observing = ref(false)
const observationDeviceId = ref(0)
const observationDevice = computed(() => devices.value.find(d => d.id === observationDeviceId.value))
const observationAction = ref('interface_brief')
const observationEnvironment = ref<number | undefined>()
const observation = ref<ObservationRecord | null>(null)
const observationError = ref('')
const preflightText = ref('')
const ruleText = ref('')
const environments = ref<EnvironmentRecord[]>([])
const recentObservations = ref<ObservationRecord[]>([])
const historyError = ref('')
let observationEpoch = 0
let historyRequest = 0

const addRules: FormRules = {
  hostname: [{ required: true, message: '请填写主机名', trigger: 'blur' }],
  mgmt_ip: [
    { required: true, message: '请填写管理 IP', trigger: 'blur' },
    { validator: (_r, v, cb) => (ipv4.test(String(v || '').trim()) ? cb() : cb(new Error('请输入合法 IPv4 地址'))), trigger: 'blur' },
  ],
}

const loadTopologies = async () => {
  await topologyRequest.run(() => getTopologies(), value => {
    topologies.value = value as { id: number; name: string; status?: string }[]
    if (topologies.value.length && !addForm.value.topology_id) {
      addForm.value.topology_id = topologies.value[0].id
    }
  })
}
const loadEnvironments = async () => {
  await environmentRequest.run(() => getEnvironments(), value => { environments.value = value as unknown as EnvironmentRecord[] })
}

const filteredDevices = computed(() => {
  if (!search.value) return devices.value
  const s = search.value.toLowerCase()
  return devices.value.filter(d => d.hostname.toLowerCase().includes(s) || d.mgmt_ip.includes(s))
})

const statusType = deviceStatusTagType
const statusLabel = deviceStatusLabel

const loadDevices = async () => {
  await deviceRequest.run(() => getDevices(), value => { devices.value = value })
}

function handleRowCommand(command: string, row: DeviceRecord) {
  if (command === 'deploy') openDeploy(row)
  else if (command === 'alarms') openAlarms(row)
  else if (command === 'edit') openEdit(row)
  else if (command === 'delete') handleDelete(row)
}

async function openObservation(row?: DeviceRecord) {
  observationDeviceId.value = row?.id || devices.value[0]?.id || 0
  showObservation.value = true
  selectObservationDevice()
  if (!environments.value.length) {
    await loadEnvironments()
  }
}

// Responses belong to the selection that started them, including reopening the
// same device. Closing preserves the last committed assistant evidence.
function invalidateObservation() {
  observationEpoch++
  historyRequest++
  observing.value = false
}

function resetObservation() {
  invalidateObservation()
  observation.value = null
  observationError.value = ''
  preflightText.value = ''
  ruleText.value = ''
  copilot.setEvidenceId(null)
}

function selectObservationDevice() {
  resetObservation()
  recentObservations.value = []
  historyError.value = ''
  if (observationDevice.value) bindDevice(observationDevice.value)
  else copilot.setSelection(null)
  void loadRecentObservations()
}

async function loadRecentObservations() {
  const deviceId = observationDeviceId.value
  const requestId = ++historyRequest
  if (!deviceId || !showObservation.value) return
  try {
    const items = await getObservations({ device_id: deviceId, limit: 8 }) as unknown as ObservationRecord[]
    if (requestId === historyRequest && deviceId === observationDeviceId.value && showObservation.value) {
      recentObservations.value = items
      historyError.value = ''
    }
  } catch {
    if (requestId === historyRequest && deviceId === observationDeviceId.value && showObservation.value) historyError.value = '最近证据读取失败，已显示记录可能陈旧，请点「最近证据」重试。'
  }
}

async function runObservation() {
  const device = observationDevice.value
  if (!device || observing.value) return
  resetObservation()
  const epoch = observationEpoch
  observing.value = true
  try {
    const result = await createObservation({
      device_id: device.id,
      action_id: observationAction.value,
      environment_id: observationEnvironment.value || undefined,
    }) as unknown as ObservationRecord
    if (epoch !== observationEpoch || !showObservation.value) return
    if (result.device_id !== device.id) throw new Error('只读证据与当前设备不一致')
    observation.value = result
    bindDevice(device)
    copilot.setEvidenceId(result.id)
    await loadRecentObservations()
  } catch (error: any) {
    if (epoch === observationEpoch) observationError.value = error?.response?.data?.detail || error?.message || '只读采集失败'
  } finally {
    if (epoch === observationEpoch) observing.value = false
  }
}

function useObservation(item: ObservationRecord) {
  if (item.device_id !== observationDeviceId.value || !observationDevice.value) return
  resetObservation()
  observationAction.value = item.action_id
  observationEnvironment.value = item.environment_id || undefined
  observation.value = item
  bindDevice(observationDevice.value)
  // 选中的最近证据同时作为助手可信证据（后端会按 evidence_id 回读核验）
  copilot.setEvidenceId(item.id)
}

async function runPreflight() {
  if (!observationEnvironment.value) return
  const epoch = observationEpoch
  try {
    const result = await preflightEnvironment(observationEnvironment.value) as unknown as { status: string; checks: Array<{ check: string; status: string; detail: string }> }
    const failed = (result.checks || []).filter((check) => check.status !== 'ok')
    if (epoch !== observationEpoch || !showObservation.value) return
    preflightText.value = `环境预检：${result.status}${failed.length ? `；${failed.map((item) => item.detail).join('；')}` : ''}`
  } catch (error: any) {
    if (epoch === observationEpoch) preflightText.value = error?.response?.data?.detail || '预检失败'
  }
}

async function evaluateRule() {
  const evidence = observation.value
  const epoch = observationEpoch
  if (!evidence) return
  const env = environments.value.find((item) => item.id === observationEnvironment.value)
  if (!env) {
    ruleText.value = '请先在“环境映射”选择或建立带预期邻居/路由的环境；不能用空数组冒充比对。'
    return
  }
  try {
    const result = await import('../../api/trust').then((mod) => mod.evaluateOspf({
      observation_ids: [evidence.id],
      environment_id: env.id,
      device_id: evidence.device_id,
      expected_neighbors: env.expected_neighbors || [],
      expected_routes: env.expected_routes || [],
    })) as unknown as {
      status: string; reason: string; expected: Record<string, unknown>; observed: Record<string, unknown>
      evaluation_scope?: string; expected_source?: string; target_version?: string; verification_mode?: string
      rejected_reason?: string
    }
    if (epoch !== observationEpoch || !showObservation.value) return
    ruleText.value = `规则：${result.status} · ${result.reason}；scope=${result.evaluation_scope || '—'}；预期来源=${result.expected_source || '—'}；目标版本=${result.target_version || '—'}；模式=${result.verification_mode || '—'}；拒绝原因=${result.rejected_reason || '—'}；预期=${JSON.stringify(result.expected)}；观察=${JSON.stringify(result.observed)}`
  } catch (error: any) {
    if (epoch === observationEpoch) ruleText.value = error?.response?.data?.detail || '规则比对失败'
  }
}

const handleHealthCheck = async () => {
  healthChecking.value = true
  try {
    const res = await checkDevicesHealth()
    const online = (res.results || []).filter(r => r.status === 'online').length
    ElMessage.success(`健康检查完成：${online}/${res.total ?? 0} 台在线`)
    await loadDevices()
  } catch {
    /* 拦截器已提示 */
  } finally {
    healthChecking.value = false
  }
}

const bindDevice = (row: any) => {
  labCtx.setDevice({
    id: row.id,
    hostname: row.hostname,
    mgmt_ip: row.mgmt_ip,
    model: row.model,
  })
  copilot.setSelection({
    kind: 'device',
    id: row.id,
    label: row.hostname,
    detail: `${row.mgmt_ip || ''} ${row.model || row.device_type || ''}`.trim(),
    model: row.model,
  })
  copilot.setEvidenceId(null)
  if (!copilot.open) copilot.setOpen(true)
}

const onRowClick = (row: any) => {
  bindDevice(row)
}

const openCreate = () => {
  editingId.value = null
  addForm.value = emptyForm()
  if (topologies.value.length) addForm.value.topology_id = topologies.value[0].id
  showForm.value = true
}

const openEdit = (row: DeviceRecord) => {
  editingId.value = row.id
  addForm.value = {
    hostname: row.hostname,
    mgmt_ip: row.mgmt_ip,
    ssh_port: row.ssh_port || 22,
    device_type: row.device_type || 'router',
    model: row.model || '',
    topology_id: row.topology_id || 0,
  }
  showForm.value = true
}

const handleSave = async () => {
  if (!editingId.value && !addForm.value.topology_id) {
    ElMessage.warning('请先选择拓扑。若还没有拓扑，请到拓扑页新建。')
    return
  }
  try {
    await addFormRef.value?.validate()
  } catch {
    return
  }
  adding.value = true
  try {
    if (editingId.value) {
      const { hostname, mgmt_ip, ssh_port, device_type, model } = addForm.value
      await updateDevice(editingId.value, { hostname, mgmt_ip, ssh_port, device_type, model })
      ElMessage.success('设备已更新')
    } else {
      await createDevice(addForm.value)
      ElMessage.success('设备添加成功')
    }
    showForm.value = false
    loadDevices()
  } catch {
    /* 拦截器已提示 */
  } finally {
    adding.value = false
  }
}

const handleDelete = async (device: DeviceRecord) => {
  try {
    await ElMessageBox.confirm(`确定删除设备 ${device.hostname}？有关联链路或历史记录时将拒绝删除，不会连带删除历史数据。`, '确认')
    await deleteDevice(device.id)
    ElMessage.success('设备已删除')
    loadDevices()
  } catch (err: any) {
    if (err !== 'cancel') { /* 拦截器已提示 */ }
  }
}

const openWebSSH = (device: any) => {
  bindDevice(device)
  router.push(`/webssh/${device.id}`)
}

const openDeploy = (device: any) => {
  bindDevice(device)
  router.push({ path: '/deploy', query: { device_id: String(device.id) } })
}

const openAlarms = (device: any) => {
  bindDevice(device)
  router.push({ path: '/alarms', query: { device_id: String(device.id) } })
}

onBeforeUnmount(invalidateObservation)

onMounted(() => {
  loadDevices()
  loadTopologies()
  useAutoRefresh(loadDevices, 15000)
})
</script>

<style scoped>
.device-page {
  min-height: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.toolbar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-shrink: 0;
}
.search { width: min(360px, 100%); }
.device-table { flex: 1; min-height: 360px; }

.obs-form { display: flex; flex-direction: column; gap: 8px; }
.obs-meta { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; color: var(--v7b-muted); font-size: 11px; margin: 8px 0; }
.obs-result { border: 1px solid var(--v7b-line); border-radius: 9px; padding: 10px; background: rgba(16, 26, 36, .7); }
.facts h4, .recent h4 { margin: 10px 0 6px; font-size: 12px; color: var(--v7b-text); }
.obs-error { color: var(--v7b-danger); font-size: 12px; margin: 8px 0; }
details { margin: 10px 0; color: var(--v7b-muted); font-size: 12px; }
pre { max-height: 240px; overflow: auto; white-space: pre-wrap; background: #0a121a; padding: 8px; border-radius: 6px; color: #c8d7e4; font-size: 11px; }
.recent-row { display: flex; flex-direction: column; gap: 2px; width: 100%; text-align: left; border: 1px solid var(--v7b-line); background: transparent; color: var(--v7b-text); border-radius: 6px; padding: 7px 9px; margin-bottom: 6px; cursor: pointer; }
.recent-row:hover { border-color: var(--v7b-line-strong); }
.recent-row small, .rule-text { color: var(--v7b-faint); font-size: 11px; }

.table-hint { color: var(--v7b-faint); font-size: 11px; }

.device-name { color: var(--v7b-text); font-size: 12px; font-weight: 600; }
.device-sub { color: var(--v7b-faint); font-size: 10px; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.obs-result { background: #f8fafc !important; border-color: var(--v7b-line) !important; }
.obs-meta { color: #52606d !important; }
.obs-result h4, .recent h4 { color: #1f2933 !important; }
.obs-result .el-table, .obs-result .el-table__cell { color: #1f2933 !important; }
.obs-result pre { background: #eef4fa !important; color: #1f2933 !important; border: 1px solid #dbe3ea; }
.obs-error { color: #b42318 !important; }
.recent-row { background: #fff !important; color: #1f2933 !important; border-color: #dbe3ea !important; }
.recent-row small { color: #52606d !important; }
.rule-text { color: #344054 !important; }
</style>
