<template>
  <details class="step-check-panel">
    <summary>步骤核对 <span class="muted">按服务端观察比较，不改变技能成绩</span></summary>
    <div class="step-check-body">
      <p v-if="bindingSupported === false" class="muted">这是流程演示，步骤由人工回看记录；现场核验请使用网络实验。</p>
      <p v-else-if="!environmentId" class="muted">本会话未绑定环境。可阅读步骤；请管理员在实验步骤中绑定环境，预检后新开会话再核对。</p>
      <p v-if="!active" class="muted">该会话已结束。历史内容保留，新核对请新开会话。</p>
      <label>核对步骤</label>
      <el-select v-model="selectedStep" aria-label="核对步骤" class="full-width" @change="resetResult">
        <el-option v-for="step in supportedSteps" :key="step.id" :value="step.id" :label="`${step.id}. ${step.name || step.goal || '步骤'}`" />
      </el-select>
      <template v-if="currentStep">
        <p class="muted">{{ currentStep.expected || currentStep.goal }}</p>
        <p class="muted">{{ currentStep.verification?.limitations || '该版本没有自动核验规则，请教员复核。' }}</p>
        <div class="check-actions">
          <el-button :loading="collecting" :disabled="!active || !environmentId || !actions.length || loading || checking" @click="collect">采集当前观察</el-button>
          <el-button :loading="loading" :disabled="collecting || checking || !environmentId" @click="load">刷新记录</el-button>
        </div>
        <label>选择本次观察 <small class="muted">每角色、每类选择一份；前后比较需同设备两份路由</small></label>
        <el-select v-model="selectedIds" multiple collapse-tags collapse-tags-tooltip aria-label="选择核对观察" class="full-width" @change="invalidateSelection">
          <el-option v-for="row in relevantObservations" :key="row.id" :value="row.id" :label="observationLabel(row)" />
        </el-select>
        <el-button type="primary" :loading="checking" :disabled="!active || collecting || loading" @click="verify">核对本步</el-button>
      </template>
      <p v-else class="muted">该会话版本没有可核对的结构化步骤，仍可记录笔记与查阅原文。</p>
      <el-alert v-if="error" type="error" :title="error" :closable="false" show-icon />
      <div v-if="result" class="check-result" aria-live="polite">
        <strong>{{ resultLabel }}</strong>
        <p>{{ result.reason }}</p>
        <p class="muted">内容 {{ result.content_version }} · 观察 {{ result.evidence_ids.join('、') || '无' }} · {{ formatApiTime(result.checked_at) }}</p>
        <p class="muted">{{ result.limitations }}</p>
        <ul v-if="result.checks.length">
          <li v-for="(check, index) in result.checks" :key="index">{{ check.role }} · {{ componentLabel(check.component) }}：{{ check.matched ? '符合本步预期' : '与预期不一致' }}</li>
        </ul>
        <details><summary>核对详情</summary><pre>{{ JSON.stringify(result, null, 2) }}</pre></details>
      </div>
    </div>
  </details>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { createObservation, getObservations, type EnvironmentDevice, type ObservationRecord } from '../../api/trust'
import { verifyTrainingStep } from '../../api/training'
import { formatApiTime } from '../../utils/datetime'

interface Step {
  id: number; name?: string; goal?: string; expected?: string
  verification?: { kind?: string; components?: string[]; limitations?: string; filter?: { role?: string } }
}
interface CheckResult {
  status: string; reason: string; content_version: string; evidence_ids: number[]; checked_at: string
  limitations: string; checks: Array<{ role: string; component: string; matched: boolean }>
}
const props = defineProps<{
  sessionId: number; active: boolean; steps: Step[]; environmentId: number | null; devices: EnvironmentDevice[]; bindingSupported?: boolean
}>()
const selectedStep = ref<number | null>(null)
const selectedIds = ref<number[]>([])
const observations = ref<ObservationRecord[]>([])
const result = ref<CheckResult | null>(null)
const error = ref('')
const loading = ref(false), collecting = ref(false), checking = ref(false)
let epoch = 0
let readSequence = 0
const supportedSteps = computed(() => props.steps.filter((s) => Number.isInteger(s.id)))
const currentStep = computed(() => supportedSteps.value.find((s) => s.id === selectedStep.value))
const actions = computed(() => {
  const rule = currentStep.value?.verification
  if (rule?.kind === 'interface_expectations') return ['interface_brief']
  if (rule?.kind === 'route_filter_effect') return ['ospf_route']
  if (rule?.kind !== 'ospf_expectations') return []
  return (rule.components || ['neighbors', 'routes']).map((c) => c === 'neighbors' ? 'ospf_peer' : 'ospf_route')
})
const relevantObservations = computed(() => observations.value.filter((r) => actions.value.includes(r.action_id)))
const resultLabel = computed(() => ({ satisfied: '本步事实符合预期', not_matched: '本步事实不符合预期', stale: '观察已过期', manual_review: '本步需人工复核' }[result.value?.status || ''] || '当前无法判断'))
function componentLabel(value: string) { return ({ neighbors: '邻居', routes: '路由', link: '互联接口', loopback: '环回接口' }[value] || value) }
function resetResult() { result.value = null; error.value = '' }
function invalidateSelection() {
  epoch++; readSequence++
  checking.value = false; collecting.value = false; loading.value = false
  resetResult()
}
function observationLabel(row: ObservationRecord) {
  const role = props.devices.find((d) => d.device_id === row.device_id)?.role || `设备#${row.device_id}`
  return `#${row.id} · ${role} · ${row.command} · ${formatApiTime(row.collected_at)}`
}
function message(e: unknown) {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof detail === 'string' ? detail : '请求失败，请检查本地服务连接后重试；原记录仍保留。'
}
async function load() {
  const ownEpoch = epoch, ownRead = ++readSequence
  const env = props.environmentId
  if (!env) return
  loading.value = true
  try {
    const rows = await Promise.all(props.devices.map((d) => getObservations({ device_id: d.device_id, environment_id: env, limit: 50 })))
    if (ownEpoch !== epoch || ownRead !== readSequence) return
    observations.value = rows.flat() as unknown as ObservationRecord[]
    error.value = ''
  } catch (e) { if (ownEpoch === epoch && ownRead === readSequence) error.value = message(e) }
  finally { if (ownEpoch === epoch && ownRead === readSequence) loading.value = false }
}
async function collect() {
  const ownEpoch = epoch, env = props.environmentId, step = currentStep.value
  const requestedActions = [...actions.value]
  if (!env || !step || !props.active || collecting.value) return
  const devices = props.devices.filter((d) => step.verification?.kind !== 'route_filter_effect' || d.role === step.verification.filter?.role)
  collecting.value = true; result.value = null; error.value = ''
  const created: number[] = []
  try {
    for (const d of devices) for (const action_id of requestedActions) {
      if (ownEpoch !== epoch || !props.active) return
      const row = await createObservation({ device_id: d.device_id, environment_id: env, action_id }) as unknown as ObservationRecord
      if (ownEpoch !== epoch) return
      created.push(row.id)
    }
    await load()
    if (ownEpoch === epoch) selectedIds.value = created
  } catch (e) { if (ownEpoch === epoch) error.value = `${message(e)} 已成功的观察可刷新记录后选择。` }
  finally { if (ownEpoch === epoch) collecting.value = false }
}
async function verify() {
  if (!currentStep.value || checking.value || !props.active) return
  const ownEpoch = epoch
  checking.value = true; error.value = ''; result.value = null
  try {
    const checked = await verifyTrainingStep(props.sessionId, currentStep.value.id, [...selectedIds.value])
    if (ownEpoch === epoch) result.value = checked as unknown as CheckResult
  } catch (e) { if (ownEpoch === epoch) error.value = message(e) }
  finally { if (ownEpoch === epoch) checking.value = false }
}
watch(() => [props.sessionId, props.environmentId, props.active, selectedStep.value], () => {
  epoch++; loading.value = false; collecting.value = false; checking.value = false
  selectedIds.value = []
  resetResult()
})
watch(supportedSteps, (steps) => { selectedStep.value = steps[0]?.id ?? null }, { immediate: true })
onUnmounted(() => { epoch++; readSequence++ })
</script>

<style scoped>
.step-check-panel { margin-top: 16px; border: 1px solid var(--v7b-line); border-radius: 8px; padding: 12px; color: var(--v7b-text); }
summary { cursor: pointer; font-weight: 600; }
.step-check-body { display: grid; gap: 10px; padding-top: 12px; }
.step-check-body p { margin: 0; line-height: 1.6; overflow-wrap: anywhere; }
.muted { color: var(--v7b-muted); font-size: 12px; font-weight: 400; }
.full-width { width: 100%; min-width: 0; }
.check-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.check-actions :deep(.el-button + .el-button) { margin-left: 0; }
.check-result { border-top: 1px solid var(--v7b-line); padding-top: 12px; display: grid; gap: 8px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 260px; overflow-y: auto; background: var(--v7b-surface-2); padding: 10px; }
</style>
