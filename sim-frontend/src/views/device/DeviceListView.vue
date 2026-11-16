<template>
  <div class="device-page v7b-page">
    <PageHeader
      title="设备"
      subtitle="列表显示已保存的连接状态。检查管理连接可更新状态；要判断接口、邻居或路由，请对具体设备做只读观察。"
    >
      <template #actions>
        <el-button :loading="healthChecking" @click="handleHealthCheck">检查管理连接</el-button>
        <el-button :disabled="!filteredDevices.length" @click="openObservation()">只读观察</el-button>
        <AdminAction v-slot="{ disabled }">
          <el-button type="primary" :disabled="disabled" @click="openCreate">添加设备</el-button>
        </AdminAction>
      </template>
    </PageHeader>
    <div class="toolbar">
      <el-input v-model="search" placeholder="搜索设备..." clearable class="search" />
      <div class="v7b-actions">
        <el-tag v-if="statusFilter" closable @close="clearDeviceFilters">只看{{ statusLabel(statusFilter) }}设备</el-tag>
        <el-button
          v-if="labCtx.hasLab && labCtx.sessionId"
          @click="router.push({ path: '/training', query: { session_id: String(labCtx.sessionId) } })"
        >返回实训</el-button>
        <span class="table-hint">{{ deviceLoadError ? '设备列表暂不可用' : `显示 ${filteredDevices.length} / ${devices.length} 台` }}</span>
      </div>
    </div>

    <el-alert v-if="deviceLoadError" :title="deviceLoadError" type="error" :closable="false" show-icon><el-button @click="loadDevices">重试设备列表</el-button></el-alert>
    <el-alert v-else-if="linkedDeviceMissing" title="指定设备已不在设备列表。请从下方选择要观察的设备。" type="warning" :closable="false" show-icon />
    <el-alert v-if="healthResult" :type="healthProblems.length ? 'warning' : 'info'" :title="healthTitle" :closable="true" show-icon @close="healthResult = null">
      <ul v-if="healthProblems.length" class="device-check-errors">
        <li v-for="row in healthProblems" :key="row.device_id ?? row.hostname">
          {{ row.hostname }} · {{ connectionIssue(row.reason) }}
        </li>
      </ul>
    </el-alert>
    <el-table :data="filteredDevices" border class="device-table" height="100%" v-loading="loading" highlight-current-row @row-click="onRowClick">
      <template #empty>
        <el-empty :description="emptyDeviceText" :image-size="72">
          <el-button v-if="!deviceLoadError && hasDeviceFilter" type="primary" @click="clearDeviceFilters">清除筛选</el-button>
          <el-button v-else-if="!deviceLoadError" type="primary" @click="router.push('/topology')">查看拓扑</el-button>
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
      <el-table-column label="保存的连接状态" min-width="170">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          <div class="device-sub">{{ row.last_seen_at ? '上次可达 ' + formatApiTime(row.last_seen_at) : '无可达时间记录' }}</div>
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

    <el-drawer v-model="showObservation" :title="observationDevice ? `只读观察 · ${observationDevice.hostname}` : '只读观察'" size="min(560px, 94vw)" destroy-on-close @close="closeObservation">
      <el-alert v-if="environmentLoadError" :title="environmentLoadError" type="error" :closable="false" show-icon><el-button @click="loadEnvironments">重试环境列表</el-button></el-alert>
      <div class="obs-form">
        <el-alert type="info" :closable="false" show-icon title="按要排查的问题选择接口、邻居或路由。采集结果会记录设备与时间，可回看或交给助手解读。" />
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
          <el-button type="primary" :disabled="!observationDevice" :loading="observing" @click="runObservation">采集只读事实</el-button>
          <el-button @click="loadRecentObservations">最近证据</el-button>
          <el-button v-if="observationEnvironment && isAdmin" @click="runPreflight">环境预检</el-button>
        </div>
        <el-alert v-if="preflightText" :title="preflightText" :type="preflightReady ? 'success' : 'warning'" :closable="false" show-icon />
        <el-alert v-if="observationError" :title="observationError" type="error" :closable="false" show-icon />
        <div v-if="observation" class="obs-result">
          <h4>本次观察 · {{ observationActionLabel(observation.action_id) }}</h4>
          <div class="obs-meta">
            <span class="v7b-pill" :class="observation.status === 'ok' ? 'ok' : 'danger'">{{ observationStatusLabel(observation.status) }}</span>
            <span class="v7b-pill" :class="observation.completeness === 'complete' ? 'ok' : 'warn'">{{ observationCompletenessLabel(observation.completeness) }}</span>
            <span>采集 {{ formatApiTime(observation.collected_at) }}</span>
            <span>{{ observation.source === 'server_observed' ? '工作台采集' : '采集来源未确认' }}</span>
            <span>{{ observationModeLabel(observation.mode) }}</span>
          </div>
          <p class="observation-help">{{ observationHelp(observation) }}</p>
          <div v-if="observation.facts.interfaces?.length" class="facts">
            <h4>接口</h4>
            <el-table :data="observation.facts.interfaces" size="small">
              <el-table-column prop="name" label="接口" min-width="150" />
              <el-table-column label="状态" width="110"><template #default="{ row }">{{ interfaceStateLabel(row.state) }}</template></el-table-column>
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
            <summary>查看命令输出（前 2000 字）</summary>
            <pre>{{ observation.raw_excerpt || '（无）' }}</pre>
          </details>
          <details><summary>原始记录字段</summary><pre>{{ JSON.stringify({status:observation.status,completeness:observation.completeness,collected_at:observation.collected_at,source:observation.source,mode:observation.mode,parser_version:observation.parser_version},null,2) }}</pre></details>
          <div class="v7b-actions">
            <el-button size="small" @click="askAboutObservation">请助手解读</el-button>
            <el-button v-if="observationEnvironment && observation.action_id !== 'interface_brief'" size="small" @click="evaluateRule">比对环境预期</el-button>
          </div>
          <el-alert v-if="ruleText" :title="ruleText" :type="ruleMatched ? 'success' : 'info'" :closable="false" show-icon />
        </div>
        <el-alert v-if="historyError" :title="historyError" type="error" :closable="false" show-icon />
        <div v-if="recentObservations.length" class="recent">
          <h4>最近证据</h4>
          <button v-for="item in recentObservations" :key="item.id" class="recent-row" @click="useObservation(item)">
            <span>{{ observationActionLabel(item.action_id) }} · 记录 #{{ item.id }}</span>
            <small>{{ formatApiTime(item.collected_at) }} · {{ observationStatusLabel(item.status) }} / {{ observationCompletenessLabel(item.completeness) }}</small>
          </button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus/es/components/message/index'
import { ElMessageBox } from 'element-plus/es/components/message-box/index'
import type { FormInstance, FormRules } from 'element-plus'
import { getDevices, getTopologies, createDevice, updateDevice, deleteDevice, checkDevicesHealth, type DeviceRecord, type DeviceHealthResult } from '../../api/device'
import { useAutoRefresh } from '../../utils/autoRefresh'
import { useSnapshotRequest } from '../../composables/useSnapshotRequest'
import { deviceStatusLabel, deviceStatusTagType, environmentStatusLabel, observationStatusLabel, observationCompletenessLabel, observationModeLabel } from '../../utils/display'
import { formatApiTime } from '../../utils/datetime'
import { useAiCopilotStore } from '../../stores/aiCopilot'
import { useLabContextStore } from '../../stores/labContext'
import { useCurrentUser } from '../../composables/useCurrentUser'
import { requestErrorMessage } from '../../utils/requestError'
import AdminAction from '../../components/AdminAction.vue'
import PageHeader from '../../components/v7b/PageHeader.vue'
import { createObservation, evaluateOspf, getEnvironments, getObservations, preflightEnvironment, type EnvironmentRecord, type ObservationRecord, type PreflightResult } from '../../api/trust'

const router = useRouter()
const route = useRoute()
const { isAdmin } = useCurrentUser()
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
const healthResult = ref<DeviceHealthResult | null>(null)
const healthProblems = computed(() => healthResult.value?.results.filter(row => row.status !== 'online') || [])
const sshIssues: Record<string, string> = {
  missing_credentials: '缺少设备登录信息，请管理员配置。',
  ssh_host_unknown: '尚未登记 SSH 主机密钥，请管理员核对设备指纹。',
  ssh_host_changed: '设备 SSH 主机密钥已变化，请管理员重新核对。',
  ssh_known_hosts_invalid: 'SSH 已知主机文件无法使用，请管理员检查路径和文件内容。',
}
function connectionIssue(reason: string | null | undefined) {
  return sshIssues[reason || ''] || '未验证 SSH 登录，请检查设备管理连接或请管理员核对。'
}
const healthTitle = computed(() => {
  const result = healthResult.value
  if (!result?.total) return '没有设备可以检查。'
  const online = result.total - healthProblems.value.length
  const scope = result.results.every(row => row.mode === 'sim') ? '当前练习环境记录' : '本次管理连接检查'
  return `${scope}：${online}/${result.total} 台可达 · ${formatApiTime(result.checked_at)}`
})
const search = ref('')
const statusFilter = computed(() => route.query.status === 'online' || route.query.status === 'offline' ? route.query.status : '')
const hasDeviceFilter = computed(() => Boolean(search.value.trim() || statusFilter.value))
const requestedDeviceId = computed(() => Number(route.query.observe_device))
const linkedDeviceMissing = computed(() => !loading.value && requestedDeviceId.value > 0 && !devices.value.some(device => device.id === requestedDeviceId.value))
const emptyDeviceText = computed(() => deviceLoadError.value || (hasDeviceFilter.value
  ? '当前筛选没有匹配设备。可清除筛选查看完整列表。'
  : '设备列表为空。可查看现有拓扑，或请管理员添加设备。'))
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
const ruleMatched = ref(false)
const preflightReady = ref(false)
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
  const s = search.value.trim().toLowerCase()
  return devices.value.filter(device => (!statusFilter.value || device.status === statusFilter.value)
    && (!s || device.hostname.toLowerCase().includes(s) || device.mgmt_ip.includes(s)))
})

function clearDeviceFilters() {
  search.value = ''
  const { status: _status, ...query } = route.query
  void router.replace({ path: '/devices', query })
}

const statusType = deviceStatusTagType
const statusLabel = deviceStatusLabel

const loadDevices = async () => {
  if (await deviceRequest.run(() => getDevices(), value => { devices.value = value })) openLinkedObservation()
}

function handleRowCommand(command: string, row: DeviceRecord) {
  if (command === 'deploy') openDeploy(row)
  else if (command === 'alarms') openAlarms(row)
  else if (command === 'edit') openEdit(row)
  else if (command === 'delete') handleDelete(row)
}

async function openObservation(row?: DeviceRecord) {
  observationDeviceId.value = row?.id || filteredDevices.value[0]?.id || 0
  showObservation.value = true
  selectObservationDevice()
  if (!environments.value.length) {
    await loadEnvironments()
  }
}

function openLinkedObservation() {
  const id = requestedDeviceId.value
  if (route.path !== '/devices' || !Number.isSafeInteger(id) || id < 1) return
  if (showObservation.value && observationDeviceId.value === id) return
  const device = devices.value.find(item => item.id === id)
  if (device) {
    observationAction.value = route.query.observe_action === 'ospf_peer' ? 'ospf_peer' : 'interface_brief'
    void openObservation(device)
  }
}

watch(() => route.query.observe_device, openLinkedObservation)

function closeObservation() {
  invalidateObservation()
  if (route.path !== '/devices' || !route.query.observe_device) return
  const { observe_device: _observe, observe_action: _action, ...query } = route.query
  void router.replace({ path: '/devices', query })
}

function observationActionLabel(action: string) {
  return ({ interface_brief: '接口状态与地址', ospf_peer: 'OSPF 邻居', ospf_route: 'OSPF 路由' } as Record<string, string>)[action] || '设备观察'
}

function interfaceStateLabel(state: string) {
  if (state === 'up') return 'Up · 正常'
  if (state === 'down') return 'Down · 待核对'
  return '状态未确认'
}

function observationHelp(result: ObservationRecord) {
  if (result.completeness !== 'complete') return '本次可用数据有限。先查看原因或重试采集，再判断状态。'
  if (result.action_id === 'interface_brief') return 'Up 表示本次观察到物理和协议状态均为 Up。可结合邻居与路由进一步判断通信情况。'
  if (result.action_id === 'ospf_peer') return '先对照预期的邻居及其状态。Full 表示这个邻接已建立。'
  return '先核对预期的目的网段和下一跳，再判断是否需要检查邻居或接口。'
}

function askAboutObservation() {
  if (!observation.value || !observationDevice.value) return
  const device = observationDevice.value
  const result = observation.value
  const label = observationActionLabel(result.action_id)
  const prompt = `请解读 ${device.hostname} 的「${label}」观察（记录 #${result.id}）。我能从结果判断什么，接下来应该核对什么？`
  const wasPinned = copilot.selectionPinned
  copilot.setSelectionPinned(false)
  bindDevice(device)
  copilot.setSelection({
    kind: 'device', id: device.id, label: device.hostname, model: device.model,
    detail: `${label} · 采集于 ${formatApiTime(result.collected_at)} · 记录 #${result.id}`,
  })
  copilot.setEvidenceId(result.id)
  if (wasPinned) copilot.setSelectionPinned(true)
  showObservation.value = false
  window.dispatchEvent(new CustomEvent('copilot-prefill', { detail: { prompt } }))
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
  ruleMatched.value = false
  preflightReady.value = false
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
    }, { silent: true })
    if (epoch !== observationEpoch || !showObservation.value) return
    if (result.device_id !== device.id) throw new Error('只读证据与当前设备不一致')
    observation.value = result
    bindDevice(device)
    copilot.setEvidenceId(result.id)
    await loadRecentObservations()
  } catch (error: any) {
    if (epoch === observationEpoch) observationError.value = requestErrorMessage(error, '只读采集失败，请重试')
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
    const result = await preflightEnvironment(observationEnvironment.value) as unknown as PreflightResult
    const firstProblem = result.checks.find(check => !['ok', 'simulated'].includes(check.status))
    if (epoch !== observationEpoch || !showObservation.value) return
    preflightReady.value = result.status === 'ready'
    preflightText.value = [environmentStatusLabel(result.status), observationModeLabel(result.verification_mode), firstProblem?.detail].filter(Boolean).join(' · ')
  } catch (error) {
    if (epoch === observationEpoch) {
      preflightReady.value = false
      preflightText.value = requestErrorMessage(error, '环境预检失败，请重试')
    }
  }
}

async function evaluateRule() {
  const evidence = observation.value
  const epoch = observationEpoch
  if (!evidence) return
  const env = environments.value.find((item) => item.id === observationEnvironment.value)
  ruleMatched.value = false
  if (!env) {
    ruleText.value = '请先选择要比对的环境。'
    return
  }
  const hasNeighbors = Boolean(env.expected_neighbors?.length)
  const hasRoutes = Boolean(env.expected_routes?.length)
  if (hasNeighbors && hasRoutes) {
    ruleText.value = '这个环境同时登记了邻居与路由预期。请在实训的「步骤核对」中按步骤采集对应证据。'
    return
  }
  if ((hasNeighbors && evidence.action_id !== 'ospf_peer') || (hasRoutes && evidence.action_id !== 'ospf_route')) {
    ruleText.value = `这个环境登记的是${hasNeighbors ? ' OSPF 邻居' : ' OSPF 路由'}预期。请选择对应动作再采集。`
    return
  }
  try {
    const result = await evaluateOspf({
      observation_ids: [evidence.id],
      environment_id: env.id,
      device_id: evidence.device_id,
    }) as unknown as { status: string; reason: string; rejected_reason?: string; missing?: string[]; unexpected?: string[] }
    if (epoch !== observationEpoch || !showObservation.value) return
    ruleMatched.value = result.status === 'satisfied'
    if (result.rejected_reason === 'untrusted_mode') ruleText.value = '正式比对需要当前真实设备的只读观察。可回看这份模拟记录并请助手解读。'
    else if (result.rejected_reason === 'objects_mismatch') {
      const missing = result.missing?.length ? `未观察到 ${result.missing.join('、')}` : ''
      const unexpected = result.unexpected?.length ? `额外观察到 ${result.unexpected.join('、')}` : ''
      ruleText.value = ['与登记预期有差异', missing, unexpected].filter(Boolean).join(' · ')
    } else ruleText.value = ruleMatched.value ? '这份观察中的对象与当前环境预期一致。' : result.reason
  } catch (error) {
    if (epoch === observationEpoch) ruleText.value = requestErrorMessage(error, '比对失败，请重试')
  }
}

const handleHealthCheck = async () => {
  healthChecking.value = true
  try {
    healthResult.value = await checkDevicesHealth()
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
.observation-help { color: var(--v7b-muted); font-size: 12px; line-height: 1.55; }
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
