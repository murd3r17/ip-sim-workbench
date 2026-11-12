<template>
  <el-card class="monitor-ports">
    <el-alert v-if="deviceError" :title="deviceError" type="error" :closable="false"><el-button @click="loadDeviceOptions">重试设备列表</el-button></el-alert>
    <div class="port-entry">
      <div><strong>端口观察与用途</strong><p>分别核对物理、协议、管理关闭与预期状态；down 总数只是统计。</p></div>
      <div class="port-actions">
        <el-select v-model="selected" placeholder="选择设备" filterable aria-label="端口观察设备">
          <el-option v-for="d in devices" :key="d.id" :label="d.hostname" :value="d.id" />
        </el-select>
        <el-button :disabled="!selected" @click="open">查看端口观察</el-button>
      </div>
    </div>
  </el-card>
  <el-dialog v-model="visible" class="port-dialog" top="4vh" :title="`${state?.hostname || '设备'} · 端口观察`" width="min(980px, 94vw)" :before-close="beforeClose" :close-on-click-modal="false" :close-on-press-escape="!saving" @closed="invalidate">
    <div v-loading="loading" class="port-body">
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
      <template v-if="state">
        <p class="port-help">读取已保存的监控结果。管理员在监控页「触发采集」后产生新观察；此处刷新与登记用途均不向设备写配置。</p>
        <el-alert v-if="!state.policy.valid" :title="state.policy.reason || '端口期望格式无效'" type="error" :closable="false" />
        <div class="port-snapshot">
          <span>采样：{{ formatApiTime(state.observation?.observed_at) }}</span>
          <el-tag :type="currentFresh && state.observation?.complete ? 'success' : 'warning'">{{ evidenceLabel }}</el-tag>
          <span v-if="state.latest_attempt">任务 #{{ state.latest_attempt.job_id }} · {{ state.latest_attempt.reason || '查看本次覆盖' }}</span>
        </div>
        <p v-if="state.observation">{{ state.observation.reason }}；预期启用未 Up {{ state.observation.expected_down }}，待核对 {{ state.observation.review_count }}。用途来自采样时的本地期望，管理未关闭不代表已核实管理配置。</p>
        <p v-else>本次没有可用端口明细；旧汇总指标不能补造端口状态。</p>
        <el-table :data="rows" border max-height="340" empty-text="暂无端口明细，仍可由管理员登记预期" class="port-table">
          <el-table-column prop="name" label="接口" min-width="135" />
          <el-table-column prop="physical" label="物理" width="90" />
          <el-table-column prop="protocol" label="协议" width="90" />
          <el-table-column label="管理状态" min-width="130"><template #default="{ row }">{{ row.admin_state === 'disabled' ? '明确管理关闭' : '未核实' }}</template></el-table-column>
          <el-table-column label="用途 / 预期" min-width="150"><template #default="{ row }">{{ purposeLabels[row.purpose as PortExpectation['purpose']] || '未登记' }} / {{ expectedLabel(row.expected_enabled) }}</template></el-table-column>
          <el-table-column label="核对结果" min-width="150"><template #default="{ row }">{{ assessmentLabels[row.assessment || ''] || '本次未观察到' }}</template></el-table-column>
        </el-table>
        <p v-if="state.observation?.missing_expected_ports.length">未观察到已登记接口：{{ state.observation.missing_expected_ports.join('、') }}</p>
        <details v-if="!editing"><summary>当前期望、版本与采样来源</summary><p v-for="p in state.policy.ports" :key="p.name">{{ p.name }} · {{ purposeLabels[p.purpose] }} · 预期{{ expectedLabel(p.expected_enabled) }}</p><p v-if="!state.policy.ports.length">尚未登记端口期望。</p><p class="revision">当前期望 {{ state.policy.revision }}<br>采样期望 {{ state.observation?.policy_revision || '未知' }}<br>观察超过五分钟、模式变化或期望改变均需重新采集；端口 Up 不证明业务可达。</p></details>
        <section v-if="editing" class="port-editor">
          <h3>登记本地期望</h3><p>保存后须重新采集，再与新期望核对。移除一行只撤销本地登记。</p>
          <div v-for="(port, index) in draft" :key="index" class="port-edit-row">
            <el-input v-model="port.name" aria-label="接口名称" placeholder="如 GE0/0/1" :disabled="saving" />
            <el-select v-model="port.purpose" aria-label="端口用途" :disabled="saving"><el-option v-for="(label, key) in purposeLabels" :key="key" :label="label" :value="key" /></el-select>
            <el-select :model-value="port.expected_enabled === null ? 'unknown' : String(port.expected_enabled)" aria-label="预期状态" :disabled="saving" @update:model-value="setExpected(port, $event)">
              <el-option label="预期未知" value="unknown" /><el-option label="预期启用" value="true" /><el-option label="预期停用" value="false" />
            </el-select>
            <el-button :disabled="saving" @click="draft.splice(index, 1)">移除</el-button>
          </div>
          <el-button :disabled="saving || draft.length >= 256" @click="draft.push({name:'', purpose:'unknown', expected_enabled:null})">添加接口期望</el-button>
        </section>
      </template>
    </div>
    <template #footer>
      <div class="port-footer">
        <template v-if="editing"><el-button :disabled="saving" @click="editing = false; error = ''">取消编辑</el-button><el-button type="primary" :loading="saving" @click="save">保存本地期望</el-button></template>
        <template v-else><el-button :disabled="loading" @click="reload">刷新观察</el-button><AdminAction v-slot="{ disabled }"><el-button :disabled="disabled || loading || !state" @click="edit">登记用途与预期</el-button></AdminAction><el-button @click="visible = false">返回</el-button></template>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus/es/components/message/index'
import AdminAction from './AdminAction.vue'
import { getDevices, type DeviceRecord } from '../api/device'
import { getPortState, savePortExpectations, type PortExpectation, type PortState } from '../api/monitor'
import { formatApiTime } from '../utils/datetime'
import { requestErrorMessage } from '../utils/requestError'

const props = defineProps<{ topologyId: number | null }>()
const devices = ref<DeviceRecord[]>([]), selected = ref<number | null>(null)
const deviceError = ref(''), now = ref(Date.now())
const clock = window.setInterval(() => { now.value = Date.now() }, 1000)
const visible = ref(false), loading = ref(false), saving = ref(false), editing = ref(false)
const state = ref<PortState | null>(null), error = ref(''), draft = ref<PortExpectation[]>([])
let epoch = 0, deviceEpoch = 0
const purposeLabels = { unknown: '用途未知', unused: '闲置', business: '业务', uplink: '上联', management: '管理' }
const assessmentLabels: Record<string,string> = {expected_up:'符合端口Up预期',expected_down:'预期启用但未Up',expected_inactive:'符合闲置/停用预期',unexpected_up:'预期停用但观察到Up',unknown_up:'Up，用途/预期待核对',review_down:'down，用途/预期待核对'}
const expectedLabel = (v: boolean | null | undefined) => v === true ? '启用' : v === false ? '停用' : '未知'
const setExpected = (port: PortExpectation, value: string) => { port.expected_enabled = value === 'unknown' ? null : value === 'true' }
const rows = computed(() => state.value?.observation?.ports || [])
const currentFresh = computed(() => {
  const age = now.value - Date.parse(state.value?.observation?.observed_at || '')
  return !!state.value?.fresh && Number.isFinite(age) && age >= -60000 && age <= 300000
})
const evidenceLabel = computed(() => !state.value?.observation ? '无可用明细' : state.value.policy_changed ? '期望已改变，需重采' : state.value.mode_changed ? '模式已改变，需重采' : !currentFresh.value ? '样本陈旧，需重采' : !state.value.observation.complete ? '本次覆盖不完整' : '五分钟内的已保存观察')
const invalidate = () => { epoch++; loading.value = false; state.value = null; editing.value = false }
const beforeClose = (done: () => void) => { if (!saving.value) { epoch++; done() } }
const reload = async () => {
  if (!selected.value) return
  const id = selected.value, token = ++epoch
  loading.value = true; error.value = ''; state.value = null
  try { const data = await getPortState(id); if (token === epoch && visible.value) state.value = data }
  catch (e) { if (token === epoch) error.value = requestErrorMessage(e, '端口观察读取失败，请重试') }
  finally { if (token === epoch) loading.value = false }
}
const open = () => { visible.value = true; editing.value = false; reload() }
const edit = () => {
  if (!state.value) return
  draft.value = state.value.policy.ports.map(p => ({ ...p }))
  for (const p of rows.value) if (!draft.value.some(x => x.name.toLowerCase() === p.name.toLowerCase())) draft.value.push({name:p.name,purpose:'unknown',expected_enabled:null})
  editing.value = true
}
const save = async () => {
  if (!state.value || !selected.value || saving.value) return
  saving.value = true; error.value = ''
  const token = epoch, id = selected.value
  try {
    await savePortExpectations(id, state.value.policy.revision, draft.value)
    if (token === epoch) { editing.value = false; ElMessage.success('本地期望已保存，请重新采集核对'); await reload() }
  } catch (e) { if (token === epoch) error.value = requestErrorMessage(e, '保存失败，编辑内容已保留') }
  finally { saving.value = false }
}
const loadDeviceOptions = async () => {
  const id = props.topologyId, token = ++deviceEpoch; devices.value = []; selected.value = null; deviceError.value = ''
  if (!id) return
  try { const data = await getDevices({ topology_id:id }); if (token === deviceEpoch) { devices.value = data; selected.value = data[0]?.id || null } }
  catch (e) { if (token === deviceEpoch) deviceError.value = requestErrorMessage(e, '端口设备列表加载失败') }
}
watch(() => props.topologyId, loadDeviceOptions, { immediate:true })
onBeforeUnmount(() => { epoch++; deviceEpoch++; window.clearInterval(clock) })
</script>

<style scoped>
.monitor-ports{margin-bottom:16px}.port-entry,.port-actions,.port-footer{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.port-entry{justify-content:space-between}.port-entry p,.port-help{color:#53647a;margin:8px 0}.port-actions .el-select{width:210px}.port-body{max-height:64vh;overflow:auto;padding-right:6px;color:#26364b;--el-text-color-primary:#26364b;--el-text-color-regular:#344760;--el-text-color-secondary:#53647a}.port-snapshot{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:12px 0}.port-snapshot span{overflow-wrap:anywhere}.port-table{margin:12px 0}.port-editor{border-top:1px solid var(--el-border-color);margin-top:14px;padding-top:4px}.port-edit-row{display:grid;grid-template-columns:minmax(120px,1.4fr) minmax(120px,1fr) minmax(120px,1fr) auto;gap:8px;margin-bottom:10px}.revision{overflow-wrap:anywhere;font-size:12px}.port-footer{justify-content:flex-end}summary{cursor:pointer;color:var(--el-color-primary);padding:8px 0}@media(max-width:750px){.port-edit-row{grid-template-columns:minmax(100px,1fr) minmax(100px,1fr)}.port-actions{width:100%}.port-actions .el-select{flex:1;min-width:140px}.port-body{max-height:58vh}}
</style>
<style>
.port-dialog { display:flex;flex-direction:column;max-height:92vh;overflow:hidden;--el-text-color-primary:var(--v7b-text);--el-text-color-regular:var(--v7b-muted);--el-text-color-secondary:var(--v7b-muted);--el-border-color:var(--v7b-line);--el-mask-color:rgba(255,255,255,.85) }
.port-dialog .el-dialog__header,.port-dialog .el-dialog__footer { flex-shrink:0 }
.port-dialog .el-dialog__body { min-height:0;overflow:auto }
.port-dialog .port-body { max-height:none;overflow:visible }
.port-dialog .el-button:not(.el-button--primary) { background:#fff;color:var(--v7b-text);border-color:var(--v7b-line) }
.port-dialog .el-button:not(.el-button--primary):hover { color:var(--v7b-accent);border-color:var(--v7b-accent) }
.port-dialog .el-button.is-disabled { background:var(--v7b-surface-2);color:#778396;border-color:var(--v7b-line) }
</style>
