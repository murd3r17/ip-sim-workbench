<template>
  <div class="v7b-page">
    <PageHeader title="环境映射" subtitle="把实验/任务绑定到接收方现场的设备、角色、接口和保护项。状态由服务端 preflight 判定，缺项不会自动绿灯。">
      <template #actions>
        <el-button @click="load">刷新</el-button>
        <el-button type="primary" @click="openCreate">新建环境</el-button>
      </template>
    </PageHeader>

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
            <span v-if="row.devices.length">{{ row.devices.map((d: EnvironmentDevice) => `${d.role || '未命名'}#${d.device_id}`).join('、') }}</span>
            <span v-else class="muted">未配置</span>
          </template>
        </el-table-column>
        <el-table-column label="保护项" width="130">
          <template #default="{ row }">{{ row.protections.length ? `${row.protections.length} 项` : '缺失' }}</template>
        </el-table-column>
        <el-table-column prop="updated_at" label="更新时间" width="180" />
        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="runPreflight(row)">预检</el-button>
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
      <el-form label-width="88px" class="env-form">
        <div class="form-grid">
          <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
          <el-form-item label="版本"><el-input v-model="form.version" /></el-form-item>
          <el-form-item label="站点"><el-input v-model="form.site" /></el-form-item>
          <el-form-item label="状态">
            <el-input :model-value="'由预检写入，不能手填 ready'" disabled />
          </el-form-item>
        </div>
        <el-form-item label="设备映射">
          <div class="mapping-list">
            <div v-for="(item, index) in form.devices" :key="index" class="mapping-row">
              <el-select v-model="item.device_id" placeholder="选择设备" style="width: 190px">
                <el-option v-for="d in devices" :key="d.id" :label="`${d.hostname} · ${d.mgmt_ip}`" :value="d.id" />
              </el-select>
              <el-input v-model="item.role" placeholder="角色，如 R1" style="width: 110px" />
              <el-input v-model="item.interfacesText" placeholder="link:GE3/0/3=10.0.123.1/24,loopback:LoopBack0=10.0.0.1/32" style="flex: 1; min-width: 220px" />
              <div class="role-expectations">
                <label>本角色预期 Full 邻居
                  <el-input v-model="item.neighborsText" placeholder="邻居 Router ID，逗号分隔" aria-label="本角色预期邻居" />
                </label>
                <label>本角色预期 OSPF 路由
                  <el-input v-model="item.routesText" placeholder="精确前缀及掩码，逗号分隔" aria-label="本角色预期路由" />
                </label>
              </div>
              <el-button text type="danger" @click="form.devices.splice(index, 1)">移除</el-button>
            </div>
            <el-button size="small" @click="addDeviceRow">添加设备映射</el-button>
            <p class="muted">步骤核对按各角色自己的预期比较。接口用途写 link（互联）或 loopback（环回），并保留地址掩码；保存预期不会判通过。全局预期继续用于原环境规则。</p>
          </div>
        </el-form-item>
        <el-form-item label="保护项">
          <el-input v-model="form.protectionsText" type="textarea" :rows="3" placeholder="每行一项：mgmt_port=GE0/0/0;device_id=1;role=R1。多设备必须写归属，单设备可省略。" />
        </el-form-item>
        <el-form-item label="预期邻居">
          <el-input v-model="form.expectedNeighborsText" placeholder="逗号分隔，如 10.0.0.2,10.0.0.3；用于环境规则，不手填通过" />
        </el-form-item>
        <el-form-item label="预期路由">
          <el-input v-model="form.expectedRoutesText" placeholder="逗号分隔，如 10.0.9.9/32；用于环境规则，不手填通过" />
        </el-form-item>
        <el-alert type="info" :closable="false" show-icon title="接口/地址是接收方现场映射，不把 R1/R2/R3 当作全局默认；缺失角色、接口或保护项时 preflight 返回 mismatch。" />
      </el-form>
      <template #footer>
        <el-button @click="showForm = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showPreflight" title="环境预检" width="min(680px, 92vw)">
      <div v-if="preflight" class="preflight">
        <div class="preflight-head">
          <span class="v7b-pill" :class="statusClass(preflight.status)">{{ statusLabel(preflight.status) }}</span>
          <span class="muted">{{ preflight.version }} · {{ preflight.checked_at }} · {{ preflight.verification_mode }}<template v-if="!preflight.real_device_verified"> · 未验证真实设备</template></span>
        </div>
        <ul>
          <li v-for="(check, index) in preflight.checks" :key="index">
            <span class="v7b-pill" :class="statusClass(check.status)">{{ check.status }}</span>
            <span>{{ check.check }}：{{ check.detail }}</span>
          </li>
        </ul>
        <p class="muted">预检只读，不修改设备；ready 表示本次固定只读事实与映射一致，不替代真实写权限或人工确认。模拟模式会显式标注，不宣称真实设备通过。</p>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useSnapshotRequest } from '../../composables/useSnapshotRequest'
import { ElMessageBox } from 'element-plus/es/components/message-box/index'
import { ElMessage } from 'element-plus/es/components/message/index'
import PageHeader from '../../components/v7b/PageHeader.vue'
import SectionCard from '../../components/v7b/SectionCard.vue'
import { getDevices, type DeviceRecord } from '../../api/device'
import { useCurrentUser } from '../../composables/useCurrentUser'
import { notifyRequestError } from '../../utils/requestError'
import {
  createEnvironment, getEnvironments, preflightEnvironment, updateEnvironment,
  type EnvironmentDevice, type EnvironmentRecord, type PreflightResult,
  getLocks, recoverLock,
} from '../../api/trust'

const { isAdmin } = useCurrentUser()
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
const editingId = ref<number | null>(null)
const form = ref({
  name: '', version: 'v1', site: '', status: 'draft', protectionsText: '',
  expectedNeighborsText: '', expectedRoutesText: '',
  devices: [] as Array<EnvironmentDevice & { interfacesText: string; neighborsText: string; routesText: string }>,
})

function statusLabel(status: string) {
  return ({ ready: '就绪', mismatch: '映射不一致', unreachable: '不可达', busy: '占用中', unknown: '未知', draft: '草稿' } as Record<string, string>)[status] || status
}
function statusClass(status: string) {
  if (status === 'ready') return 'ok'
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
  form.value.devices.push({ device_id: devices.value[0]?.id || 0, role: '', interfaces: [], interfacesText: '', neighborsText: '', routesText: '' })
}

function openCreate() {
  editingId.value = null
  form.value = { name: '', version: 'v1', site: '', status: 'draft', protectionsText: '', expectedNeighborsText: '', expectedRoutesText: '', devices: [] }
  if (devices.value[0]) addDeviceRow()
  showForm.value = true
}

function openEdit(row: EnvironmentRecord) {
  editingId.value = row.id
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

async function save() {
  if (!form.value.name.trim()) {
    ElMessage.warning('请填写环境名称')
    return
  }
  const payload = {
    name: form.value.name.trim(), version: form.value.version.trim() || 'v1', site: form.value.site.trim(),
    devices: form.value.devices.filter((item) => item.device_id).map((item) => ({
      device_id: item.device_id, role: item.role.trim(), mgmt_ip: item.mgmt_ip || '',
      vendor: item.vendor || '', os_version: item.os_version || '',
      interfaces: parseInterfaces(item.interfacesText).map((iface) => ({ ...item.interfaces.find((old) => old.name === iface.name), ...iface })),
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
    ElMessage.success('环境已保存；请点「预检」查看真实状态')
    showForm.value = false
    await load()
  } catch (error: any) {
    // 拦截器已弹服务端 detail；这里不再重复弹第二条
    notifyRequestError(error, '保存失败')
  } finally {
    saving.value = false
  }
}

async function runPreflight(row: EnvironmentRecord) {
  try {
    preflight.value = await preflightEnvironment(row.id) as unknown as PreflightResult
    showPreflight.value = true
    await load()
  } catch (error: any) {
    notifyRequestError(error, '预检失败')
  }
}

onMounted(async () => {
  await load()
  await loadDeviceOptions()
})
</script>

<style scoped>
:global(.environment-dialog) { display: flex; flex-direction: column; max-height: 90vh; overflow: hidden; }
:global(.environment-dialog .el-dialog__body) { min-height: 0; overflow-y: auto; }
:global(.environment-dialog .el-dialog__header), :global(.environment-dialog .el-dialog__footer) { flex-shrink: 0; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; }
.mapping-list { display: flex; flex-direction: column; gap: 8px; width: 100%; }
.mapping-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.role-expectations { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); width: 100%; gap: 8px; }
.role-expectations label { color: var(--v7b-muted); font-size: 12px; line-height: 1.7; }
.muted { color: var(--v7b-faint); font-size: 11px; }
.preflight-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.preflight ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; max-height: 50vh; overflow: auto; }
.preflight li { display: flex; gap: 8px; align-items: flex-start; font-size: 12px; line-height: 1.5; }
@media (max-width: 760px) { .form-grid, .role-expectations { grid-template-columns: 1fr; } }
</style>
