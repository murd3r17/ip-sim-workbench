<template>
  <div class="v7b-page">
    <PageHeader title="环境映射" subtitle="登记实训使用的设备、接口和保护项。保存后运行预检，核对登记内容和实际读取结果。">
      <template #actions>
        <el-button @click="load">刷新</el-button>
        <el-button type="primary" @click="openCreate">新建环境</el-button>
      </template>
    </PageHeader>
    <el-alert v-if="courseGuide" :title="`为「${courseGuide.title}」准备环境`" type="info" :closable="false" show-icon>
      <p>需要 {{ courseGuide.roles.length }} 台独立设备，分别承担 {{ courseGuide.roles.join('、') }}。先保存映射，再做一次预检。</p>
      <el-button link type="primary" @click="backToCourse()">返回实验步骤</el-button>
    </el-alert>

    <SectionCard title="环境列表">
      <el-alert v-if="environmentLoadError" :title="environmentLoadError" type="error" :closable="false" show-icon />
      <el-table :data="environments" v-loading="loading" height="420">
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column prop="version" label="版本" width="90" />
        <el-table-column prop="site" label="站点" width="120" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <span class="v7b-pill" :class="statusClass(row.status)">{{ statusLabel(row.status) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="设备/角色" min-width="200">
          <template #default="{ row }">
            <span v-if="row.devices.length">{{ row.devices.map((d: EnvironmentDevice) => `${d.role || '未命名'} · ${deviceLabel(d.device_id)}`).join('、') }}</span>
            <span v-else class="muted">未配置</span>
            <small v-if="courseGuide && missingRoles(row.devices).length">缺少 {{ missingRoles(row.devices).join('、') }}</small>
          </template>
        </el-table-column>
        <el-table-column label="保护项" width="130">
          <template #default="{ row }">{{ row.protections.length ? `${row.protections.length} 项` : '缺失' }}</template>
        </el-table-column>
        <el-table-column label="更新时间" width="180"><template #default="{ row }">{{ formatApiTime(row.updated_at) }}</template></el-table-column>
        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <el-button size="small" :loading="preflighting === row.id" :disabled="preflighting !== null" @click="runPreflight(row)">预检</el-button>
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
          </template>
        </el-table-column>
        <template #empty><div class="v7b-empty">{{ environmentLoadError || '还没有环境映射。新建一个，绑定设备与保护项后再预检。' }}</div></template>
      </el-table>
    </SectionCard>

    <SectionCard v-if="isAdmin" title="终端锁核查/恢复">
      <el-alert v-if="lockLoadError" :title="lockLoadError" type="error" :closable="false" show-icon />
      <el-table :data="locks" v-loading="lockLoading" height="260">
        <el-table-column prop="hostname" label="设备" min-width="130" />
        <el-table-column prop="owner" label="占用实例" min-width="150" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <span class="v7b-pill" :class="row.recovery_required ? 'warn' : 'info'">{{ row.state || 'legacy' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="last_seen_at" label="最近活动" width="170" />
        <el-table-column prop="expire_at" label="租约到期" width="170" />
        <el-table-column prop="reason" label="恢复原因" min-width="150" />
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="warning" :disabled="!row.recovery_required || row.lock_type !== 'terminal'" :loading="recovering === row.device_id" @click="recoverTerminalLock(row)">核查恢复</el-button>
          </template>
        </el-table-column>
        <template #empty><div class="v7b-empty">{{ lockLoadError || '没有设备写占用。' }}</div></template>
      </el-table>
      <div class="muted" style="margin-top:8px">只有已关闭/释放失败/旧孤儿锁可恢复；活动终端必须先断开。恢复写入审计。</div>
    </SectionCard>

    <el-dialog v-model="showForm" class="environment-dialog" :title="editingId ? '编辑环境' : '新建环境'" width="min(820px, 94vw)" top="5vh" draggable destroy-on-close>
      <el-alert v-if="deviceLoadError" :title="deviceLoadError" type="error" :closable="false" show-icon><el-button @click="loadDeviceOptions">重试设备列表</el-button></el-alert>
      <el-alert v-if="formError" :title="formError" type="error" show-icon :closable="false" />
      <el-form label-width="88px" class="env-form">
        <div class="form-grid">
          <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
          <el-form-item label="版本"><el-input v-model="form.version" /></el-form-item>
          <el-form-item label="站点"><el-input v-model="form.site" /></el-form-item>
          <el-form-item label="状态">
            <el-input :model-value="'保存映射后运行预检'" disabled />
          </el-form-item>
        </div>
        <el-form-item label="设备映射">
          <div class="mapping-list">
            <div v-for="(item, index) in form.devices" :key="index" class="mapping-row">
              <el-select :model-value="item.device_id || undefined" placeholder="选择设备" style="width: 190px"
                :aria-label="item.role ? `${item.role} 的设备` : '映射设备'" @change="assignDevice(item, $event)">
                <el-option v-for="d in devices" :key="d.id" :label="`${d.hostname} · ${d.mgmt_ip}`" :value="d.id"
                  :disabled="!!courseGuide && form.devices.some(other => other !== item && other.device_id === d.id)" />
              </el-select>
              <el-input v-model="item.role" aria-label="实验角色" placeholder="角色，如 R1" style="width: 132px" />
              <el-button text type="danger" @click="form.devices.splice(index, 1)">移除设备映射</el-button>
              <fieldset class="interface-fields">
                <legend>本设备的接口</legend>
                <div v-for="(iface, ifaceIndex) in item.interfaces" :key="ifaceIndex" class="interface-row">
                  <el-input v-model="iface.purpose" aria-label="接口用途" placeholder="用途，如 link 或 loopback" />
                  <el-input v-model="iface.name" aria-label="接口名称" placeholder="接口名，如 GE0/0/1" />
                  <el-input v-model="iface.address" aria-label="地址及掩码" placeholder="地址/掩码，如 192.0.2.1/24" />
                  <el-button text type="danger" @click="item.interfaces.splice(ifaceIndex, 1)">移除接口</el-button>
                </div>
                <el-button size="small" @click="item.interfaces.push({ name: '', purpose: '', address: '' })">添加接口</el-button>
                <details class="advanced-interfaces">
                  <summary>从文本批量填入</summary>
                  <el-input v-model="item.interfacesText" aria-label="接口映射文本" placeholder="link:GE0/0/1=192.0.2.1/24,loopback:LoopBack0=192.0.2.2/32" />
                  <el-button size="small" @click="applyInterfaceText(item)">替换本设备的接口行</el-button>
                </details>
              </fieldset>
              <details class="role-options" :open="Boolean(item.neighborsText || item.routesText)">
                <summary>邻居与路由的预期结果</summary>
                <div class="role-expectations">
                  <label>本角色预期 Full 邻居
                    <el-input v-model="item.neighborsText" placeholder="邻居 Router ID，逗号分隔" aria-label="本角色预期邻居" />
                  </label>
                  <label>本角色预期 OSPF 路由
                    <el-input v-model="item.routesText" placeholder="精确前缀及掩码，逗号分隔" aria-label="本角色预期路由" />
                  </label>
                </div>
              </details>
            </div>
            <el-button size="small" @click="addDeviceRow">添加设备映射</el-button>
            <p class="muted">角色名来自实验说明。接口用途填 link（互联）或 loopback（环回），地址填写实际掩码。每个角色的邻居和路由用于步骤核对。</p>
          </div>
        </el-form-item>
        <el-form-item label="管理口保护">
          <div class="mapping-list">
            <div class="protection-entry">
              <el-select v-model="protectedDevice" aria-label="保护口所属设备" placeholder="选择所属设备">
                <el-option v-for="item in form.devices.filter(row => row.device_id)" :key="item.role" :label="`${item.role} · ${deviceLabel(item.device_id)}`" :value="item.device_id" />
              </el-select>
              <el-input v-model="protectedInterface" aria-label="管理接口名称" placeholder="填写已核对的接口" />
              <el-button :disabled="!protectedDevice || !protectedInterface.trim()" @click="addProtection">加入保护</el-button>
            </div>
            <small>{{ form.protectionsText.split('\n').filter(Boolean).length }} 项已登记</small>
            <details><summary>编辑保护明细</summary><el-input v-model="form.protectionsText" type="textarea" :rows="3"
              aria-label="保护明细" placeholder="例 mgmt_port=GE0/0/0;device_id=1;role=R1" /></details>
          </div>
        </el-form-item>
        <details class="environment-advanced">
          <summary>整个环境的预期结果</summary>
          <el-form-item label="预期邻居"><el-input v-model="form.expectedNeighborsText" placeholder="多个 Router ID 以逗号分隔" /></el-form-item>
          <el-form-item label="预期路由"><el-input v-model="form.expectedRoutesText" placeholder="多个前缀以逗号分隔" /></el-form-item>
        </details>
        <el-alert type="info" :closable="false" show-icon title="保存只登记映射。随后运行预检，检查设备连接、接口地址和保护项，再把该环境选进对应实训。" />
      </el-form>
      <template #footer>
        <el-button @click="showForm = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showPreflight" :title="`环境预检 · ${preflightName}`" width="min(680px, 92vw)">
      <div v-if="preflight" class="preflight">
        <div class="preflight-head">
          <span class="v7b-pill" :class="statusClass(preflight.status)">{{ statusLabel(preflight.status) }}</span>
          <span>{{ preflight.version }} · {{ formatApiTime(preflight.checked_at) }} · {{ observationModeLabel(preflight.verification_mode) }}</span>
        </div>
        <p>{{ preflightNextStep(preflight.status) }}</p>
        <el-button v-if="courseGuide && preflight.status === 'ready' && preflightEnvironmentId" link type="primary"
          @click="backToCourse(preflightEnvironmentId)">返回实验并选择此环境</el-button>
        <ul v-if="preflightProblems.length" aria-label="待处理检查项">
          <li v-for="(check, index) in preflightProblems" :key="index">
            <strong>{{ checkTitle(check) }}</strong><span>{{ check.detail }}</span>
          </li>
        </ul>
        <details>
          <summary>查看全部 {{ preflight.checks.length }} 项检查</summary>
          <ul>
            <li v-for="(check, index) in preflight.checks" :key="index">
              <span class="v7b-pill" :class="statusClass(check.status)">{{ check.status === 'ok' ? '通过' : check.status === 'simulated' ? '模拟读取' : '需核对' }}</span>
              <strong>{{ checkTitle(check) }}</strong><span>{{ check.check === 'adapter' ? observationModeLabel(preflight.verification_mode) : check.detail }}</span>
            </li>
          </ul>
        </details>
        <p class="muted">本次检查只读取设备信息。涉及配置变更时，仍须在变更审批页核对并确认。</p>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useSnapshotRequest } from '../../composables/useSnapshotRequest'
import { ElMessageBox } from 'element-plus/es/components/message-box/index'
import { ElMessage } from 'element-plus/es/components/message/index'
import PageHeader from '../../components/v7b/PageHeader.vue'
import SectionCard from '../../components/v7b/SectionCard.vue'
import { getDevices, type DeviceRecord } from '../../api/device'
import { useCurrentUser } from '../../composables/useCurrentUser'
import { notifyRequestError, requestErrorMessage } from '../../utils/requestError'
import { getLab } from '../../api/training'
import { formatApiTime } from '../../utils/datetime'
import { environmentStatusLabel as statusLabel, observationModeLabel } from '../../utils/display'
import {
  createEnvironment, getEnvironments, preflightEnvironment, updateEnvironment,
  type EnvironmentDevice, type EnvironmentRecord, type PreflightResult,
  getLocks, recoverLock,
} from '../../api/trust'

const { isAdmin } = useCurrentUser()
const route = useRoute()
const router = useRouter()
const courseGuide = ref<{ id: number; title: string; roles: string[] } | null>(null)
const formError = ref('')
const protectedDevice = ref<number | undefined>()
const protectedInterface = ref('')
const preflightEnvironmentId = ref<number>()
const environments = ref<EnvironmentRecord[]>([])
const locks = ref<Array<Record<string, any>>>([])
const lockRequest = useSnapshotRequest('设备占用列表')
const lockLoading = lockRequest.loading
const lockLoadError = lockRequest.error
const recovering = ref<number | null>(null)
const devices = ref<DeviceRecord[]>([])
const environmentRequest = useSnapshotRequest('环境列表')
const loading = environmentRequest.loading
const environmentLoadError = environmentRequest.error
const deviceRequest = useSnapshotRequest('设备列表')
const deviceLoadError = deviceRequest.error
const loadDeviceOptions = async () => { await deviceRequest.run(() => getDevices(), value => { devices.value = value }) }
const saving = ref(false)
const showForm = ref(false)
const showPreflight = ref(false)
const preflight = ref<PreflightResult | null>(null)
const preflighting = ref<number | null>(null)
const preflightName = ref('')
const preflightProblems = computed(() => preflight.value?.checks.filter(check => !['ok', 'simulated'].includes(check.status)) || [])
const editingId = ref<number | null>(null)
type DeviceMappingForm = EnvironmentDevice & { interfacesText: string; neighborsText: string; routesText: string }
const form = ref({
  name: '', version: 'v1', site: '', status: 'draft', protectionsText: '',
  expectedNeighborsText: '', expectedRoutesText: '',
  devices: [] as DeviceMappingForm[],
})

function checkTitle(check: PreflightResult['checks'][number]) {
  const labels: Record<string, string> = {
    adapter: '读取来源', verification_mode: '设备来源', reachability: '管理连接', completeness: '输出完整性', observation: '接口采集',
    mapping: '设备映射', protection: '保护项', protection_target: '保护目标', device: '设备登记', role: '角色', mgmt_ip: '管理地址',
    vendor: '厂商', interface: '接口', interface_address: '接口地址', interface_state: '接口状态', lock: '设备占用', fact: '观察记录',
  }
  const device = check.device_id && (devices.value.find(item => item.id === check.device_id)?.hostname || `设备 #${check.device_id}`)
  return [device, labels[check.check] || '其他检查'].filter(Boolean).join(' · ')
}

function preflightNextStep(status: string) {
  if (status === 'ready') return '这次读取结果与登记的映射一致。可回到实训的实验步骤选择该环境。'
  if (status === 'mismatch') return '先根据下方检查项修改设备、接口或保护项，保存后再预检。'
  if (status === 'busy') return '设备正在被终端或变更任务占用。待操作结束后再预检。'
  if (status === 'unreachable') return '先核对下方设备的管理地址、连接状态和登录配置，再重试预检。'
  return '本次读取未能确认映射。请查看检查项并补齐信息后重试。'
}
function statusClass(status: string) {
  if (status === 'ready' || status === 'ok') return 'ok'
  if (status === 'mismatch' || status === 'unreachable') return 'danger'
  if (status === 'busy') return 'warn'
  return 'info'
}

async function loadLocks() {
  await lockRequest.run(() => getLocks(), value => { locks.value = value as unknown as Array<Record<string, any>> })
}

async function recoverTerminalLock(row: Record<string, any>) {
  await ElMessageBox.confirm(`恢复设备 ${row.hostname || row.device_id} 的终端占用？仅限已关闭/释放失败/旧孤儿锁；活动终端会被服务端拒绝。`, '核查恢复', { type: 'warning' })
  recovering.value = Number(row.device_id)
  try {
    // silent：拦截器不再弹原始 detail（如 audit_failed），只保留下面这条可读主提示
    await recoverLock(Number(row.device_id), { silent: true })
    ElMessage.success('已恢复并写入审计')
    await loadLocks()
  } catch (error: any) {
    const detail = String(error?.response?.data?.detail || '')
    ElMessage.error(detail === 'audit_failed'
      ? '审计写入失败，锁未释放；请检查审计存储后重试'
      : detail === 'active_terminal_requires_disconnect'
        ? '活动终端仍在线，拒绝恢复；请先断开终端'
        : detail === 'active_state_unknown_requires_disconnect'
          ? '活动状态无法确认，保守拒绝；请人工核实持有进程'
          : (detail || '恢复被拒绝，请先断开活动终端'))
  } finally { recovering.value = null }
}

async function load() {
  await environmentRequest.run(() => getEnvironments(), value => { environments.value = value as unknown as EnvironmentRecord[] })
  await loadLocks()
}

function addDeviceRow() {
  form.value.devices.push(blankMapping())
}
function blankMapping(role = ''): DeviceMappingForm {
  return { device_id: 0, role, interfaces: [], interfacesText: '', neighborsText: '', routesText: '' }
}
function deviceLabel(id: number) {
  return devices.value.find(device => device.id === id)?.hostname || `设备 #${id}`
}
function missingRoles(mappings: EnvironmentDevice[]) {
  return courseGuide.value?.roles.filter(role => !mappings.some(item => item.role.trim() === role && item.device_id > 0)) || []
}
function backToCourse(environmentId?: number) {
  if (!courseGuide.value) return
  void router.push({ path: '/training', query: { lab_id: courseGuide.value.id, preparation: '1', environment_id: environmentId } })
}
function addProtection() {
  const row = form.value.devices.find(item => item.device_id === protectedDevice.value)
  const name = protectedInterface.value.trim()
  if (!row || !/^[A-Za-z][A-Za-z0-9./-]*\d$/.test(name) || !row.role.trim()) {
    formError.value = '请先填写设备角色并核对管理接口名称，例如 GE0/0/0。'
    return
  }
  const lines = form.value.protectionsText.split('\n').filter(Boolean)
  const entry = `mgmt_port=${name};device_id=${row.device_id};role=${row.role.trim()}`
  if (!lines.includes(entry)) form.value.protectionsText = [...lines, entry].join('\n')
  protectedInterface.value = ''
  formError.value = ''
}

function openCreate() {
  editingId.value = null
  formError.value = ''
  protectedDevice.value = undefined
  protectedInterface.value = ''
  const guided = courseGuide.value
  form.value = {
    name: guided ? `${guided.title} 环境` : '', version: 'v1', site: '', status: 'draft', protectionsText: '',
    expectedNeighborsText: '', expectedRoutesText: '', devices: guided ? guided.roles.map(blankMapping) : [blankMapping()],
  }
  showForm.value = true
}

function openEdit(row: EnvironmentRecord) {
  editingId.value = row.id
  formError.value = ''
  protectedDevice.value = undefined
  protectedInterface.value = ''
  form.value = {
    name: row.name, version: row.version, site: row.site, status: row.status,
    expectedNeighborsText: (row.expected_neighbors || []).join(','),
    expectedRoutesText: (row.expected_routes || []).join(','),
    protectionsText: (row.protections || []).map((item) => {
      const parts = [`${item.kind || 'other'}=${item.target || ''}`]
      if (item.device_id !== undefined && item.device_id !== null) parts.push(`device_id=${item.device_id}`)
      if (item.role) parts.push(`role=${item.role}`)
      return parts.join(';')
    }).join('\n'),
    devices: (row.devices || []).map((item) => ({
      ...item,
      interfaces: (item.interfaces || []).map(iface => ({ ...iface })),
      interfacesText: (item.interfaces || []).map((iface) => `${iface.purpose ? `${iface.purpose}:` : ''}${iface.name}=${iface.address || ''}`).join(','),
      neighborsText: (item.expected_neighbors || []).join(','),
      routesText: (item.expected_routes || []).join(','),
    })),
  }
  showForm.value = true
}

function parseInterfaces(text: string) {
  return text.split(',').map((part) => part.trim()).filter(Boolean).map((part) => {
    const [identity, address] = part.split('=').map((value) => value.trim())
    const [purpose, mappedName] = identity.includes(':') ? identity.split(':', 2) : ['', identity]
    return { name: mappedName.trim(), address: address || '', ...(purpose ? { purpose: purpose.trim() } : {}) }
  })
}

function applyInterfaceText(item: DeviceMappingForm) {
  const incoming = parseInterfaces(item.interfacesText)
  if (!incoming.length || incoming.some(iface => !iface.name)) {
    ElMessage.warning('请在文本中提供至少一个接口名，再填入表格。')
    return
  }
  item.interfaces = incoming.map(iface => ({
    ...item.interfaces.find(old => old.name === iface.name), ...iface,
  }))
}

function assignDevice(item: DeviceMappingForm, id: number) {
  item.device_id = id
  item.mgmt_ip = ''
  item.vendor = ''
  item.os_version = ''
}

async function save() {
  formError.value = ''
  if (!form.value.name.trim()) {
    formError.value = '请填写环境名称。'
    return
  }
  const absent = missingRoles(form.value.devices)
  if (absent.length) {
    formError.value = `请为 ${absent.join('、')} 选择独立设备。`
    return
  }
  const incomplete = form.value.devices.findIndex(item => !item.device_id || !item.role.trim() ||
    item.interfaces.some(iface => !iface.name.trim()))
  if (incomplete >= 0) {
    formError.value = `第 ${incomplete + 1} 条映射缺少设备、角色或接口名称。`
    return
  }
  const payload = {
    name: form.value.name.trim(), version: form.value.version.trim() || 'v1', site: form.value.site.trim(),
    devices: form.value.devices.filter((item) => item.device_id).map((item) => ({
      device_id: item.device_id, role: item.role.trim(), mgmt_ip: item.mgmt_ip || '',
      vendor: item.vendor || '', os_version: item.os_version || '',
      interfaces: item.interfaces.map(iface => ({
        ...iface, name: iface.name.trim(), address: iface.address?.trim() || '', purpose: iface.purpose?.trim(),
      })),
      expected_neighbors: item.neighborsText.trim() ? item.neighborsText.split(',').map((v) => v.trim()).filter(Boolean) : null,
      expected_routes: item.routesText.trim() ? item.routesText.split(',').map((v) => v.trim()).filter(Boolean) : null,
    })),
    expected_neighbors: form.value.expectedNeighborsText.split(',').map((item) => item.trim()).filter(Boolean),
    expected_routes: form.value.expectedRoutesText.split(',').map((item) => item.trim()).filter(Boolean),
    protections: form.value.protectionsText.split('\n').map((line) => line.trim()).filter(Boolean).map((line) => {
      const [head, ...attrs] = line.split(';').map((part) => part.trim())
      const [kind, ...rest] = head.split('=')
      const item: Record<string, unknown> = { kind: kind.trim(), target: rest.join('=').trim() }
      for (const attr of attrs) {
        const [key, ...value] = attr.split('=')
        if (key === 'device_id' && value.join('=').trim()) item.device_id = Number(value.join('=').trim())
        if (key === 'role' && value.join('=').trim()) item.role = value.join('=').trim()
      }
      return item
    }),
  }
  saving.value = true
  try {
    if (editingId.value) await updateEnvironment(editingId.value, payload)
    else await createEnvironment(payload)
    ElMessage.success('映射已保存。下一步请运行预检。')
    showForm.value = false
    await load()
  } catch (error: any) {
    formError.value = requestErrorMessage(error, '保存失败。请核对映射后重试。')
  } finally {
    saving.value = false
  }
}

async function runPreflight(row: EnvironmentRecord) {
  if (preflighting.value !== null) return
  preflighting.value = row.id
  try {
    preflight.value = await preflightEnvironment(row.id) as unknown as PreflightResult
    preflightEnvironmentId.value = row.id
    preflightName.value = row.name
    showPreflight.value = true
    await load()
  } catch (error: any) {
    notifyRequestError(error, '预检失败')
  } finally {
    preflighting.value = null
  }
}

onMounted(async () => {
  await Promise.all([load(), loadDeviceOptions()])
  const id = Number(route.query.lab_id)
  if (!Number.isSafeInteger(id) || id < 1) return
  try {
    const lab = await getLab(id) as unknown as { id: number; title: string; environment_spec?: { devices?: { role: string }[] } }
    const roles = (lab.environment_spec?.devices || []).map(device => device.role).filter(Boolean)
    if (roles.length) courseGuide.value = { id: lab.id, title: lab.title, roles }
  } catch (error) {
    notifyRequestError(error, '读取实验的设备角色失败')
  }
})
</script>

<style scoped>
:global(.environment-dialog) { display: flex; flex-direction: column; max-height: 90vh; overflow: hidden; }
:global(.environment-dialog .el-dialog__body) { min-height: 0; overflow-y: auto; }
:global(.environment-dialog .el-dialog__header), :global(.environment-dialog .el-dialog__footer) { flex-shrink: 0; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; }
.mapping-list { display: flex; flex-direction: column; gap: 8px; width: 100%; }
.role-options, .environment-advanced { width: 100%; }
.protection-entry { display: flex; gap: 8px; flex-wrap: wrap; }
.protection-entry .el-select, .protection-entry .el-input { flex: 1 1 150px; min-width: 0; }
.mapping-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.interface-fields { width: 100%; min-width: 0; margin: 0; padding: 8px; border: 1px solid var(--v7b-line); border-radius: 6px; }
.interface-fields legend { padding-inline: 5px; color: var(--v7b-muted); }
.interface-row { display: grid; grid-template-columns: minmax(120px, 1fr) minmax(110px, 1fr) minmax(140px, 1.3fr) auto; align-items: center; gap: 8px; margin-bottom: 8px; }
.advanced-interfaces { margin-top: 8px; }
.advanced-interfaces summary { color: var(--v7b-muted); cursor: pointer; }
.role-expectations { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); width: 100%; gap: 8px; }
.role-expectations label { color: var(--v7b-muted); font-size: 12px; line-height: 1.7; }
.muted { color: var(--v7b-faint); font-size: 11px; }
.preflight-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.preflight ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; max-height: 50vh; overflow: auto; }
.preflight li { display: flex; gap: 8px; align-items: flex-start; font-size: 12px; line-height: 1.5; }
@media (max-width: 760px) { .form-grid, .role-expectations, .interface-row { grid-template-columns: 1fr; } }
</style>
