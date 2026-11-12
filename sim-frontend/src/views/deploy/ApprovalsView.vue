<template>
  <div class="approvals-view v7b-page">
    <PageHeader
      title="变更审批"
      subtitle="审批只记录结论并取得设备写锁，不会自动执行；高风险动作需要人工二次确认。"
    />
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <div>
            <span class="title">变更审批</span>
            <span class="subtitle">待确认 / 待执行 / 执行中的下发任务（高风险任务需二次确认）</span>
          </div>
          <div class="header-actions">
            <el-select v-model="statusFilter" size="small" style="width: 150px" @change="loadTasks">
              <el-option label="全部待处理" value="" />
              <el-option label="等待确认" value="awaiting_confirmation" />
              <el-option label="已确认待执行" value="confirmed" />
              <el-option label="执行中" value="deploying" />
              <el-option label="已完成" value="success" />
              <el-option label="失败" value="failed" />
              <el-option label="已回滚" value="rolled_back" />
            </el-select>
            <el-button size="small" :loading="loading" @click="loadTasks">刷新</el-button>
            <el-button size="small" type="primary" @click="router.push({ path: '/deploy', query: { tab: 'tasks' } })">
              去下发中心
            </el-button>
          </div>
        </div>
      </template>

      <el-alert v-if="taskLoadError" :title="taskLoadError" type="error" :closable="false" show-icon />
      <RecordOriginFilter v-model="originFilter" :records="tasks" :unavailable="!!taskLoadError" />
      <el-table :data="visibleTasks" v-loading="loading">
        <template #empty>
          <el-empty :image-size="72">
            <template #description>
              <div class="empty-desc">
                <p>{{ taskLoadError || (tasks.length?'当前来源筛选没有匹配任务，可恢复全部来源。':'当前没有待处理的变更任务。') }}</p>
                <p v-if="!taskLoadError">待审批任务有两个来源：在「配置下发 → 新建任务」创建的下发任务；在「配置管理」对某个快照点「回滚」生成的高风险回滚任务。</p>
              </div>
            </template>
            <el-button v-if="!taskLoadError" type="primary" @click="router.push({ path: '/deploy', query: { tab: 'deploy' } })">去配置下发</el-button>
            <el-button v-if="!taskLoadError" @click="router.push('/config-versions')">去配置管理</el-button>
          </el-empty>
        </template>
        <el-table-column prop="id" label="任务" width="80">
          <template #default="{ row }">#{{ row.id }}</template>
        </el-table-column>
        <el-table-column label="设备" min-width="140">
          <template #default="{ row }">{{ deviceName(row.device_id) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="140">
          <template #default="{ row }">
            <span :class="statusClass(row.status)">{{ statusLabel(row.status) }}</span>
            <el-tag v-if="row.has_lock" type="success" size="small" effect="plain" style="margin-left: 6px">已加锁</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="风险级别" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.change_level === 'high_risk'" type="danger" size="small">高风险</el-tag>
            <el-tag v-else-if="row.change_level === 'emergency'" type="warning" size="small">紧急</el-tag>
            <el-tag v-else type="info" size="small">日常</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="150">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <div class="approval-actions">
            <el-button size="small" @click="openDetail(row)">详情</el-button>
            <el-button
              v-if="row.status === 'pending' || row.status === 'awaiting_confirmation'"
              size="small"
              type="primary"
              :loading="actingId === row.id"
              @click="approve(row)"
            >{{ row.change_level === 'high_risk' ? '高风险确认' : '确认' }}</el-button>
            <!-- 确认之后必须能继续执行/验证：回滚任务没有批次，配置下发页看不到它，
                 此前确认完就成死路（2026-10-05 审计发现） -->
            <el-button
              v-if="row.status === 'confirmed'"
              size="small"
              type="success"
              :loading="actingId === row.id"
              @click="execute(row)"
            >执行</el-button>
            <el-button
              v-if="row.status === 'deploying'"
              size="small"
              type="warning"
              :loading="actingId === row.id"
              @click="verify(row)"
            >验证</el-button>
            <el-button
              v-if="['success', 'failed', 'rolled_back'].includes(row.status)"
              size="small"
              type="success"
              plain
              :loading="actingId === row.id"
              @click="verify(row)"
            >查看结果</el-button>
            <el-button
              v-if="isCancelable(row.status)"
              size="small"
              type="danger"
              plain
              :loading="actingId === row.id"
              @click="cancel(row)"
            >取消</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="verifyVisible" class="v7b-record-dialog" top="4vh" :title="verifyTitle" width="min(620px, 94vw)" draggable append-to-body>
      <el-descriptions v-if="verifyReport" :column="2" border size="small">
        <el-descriptions-item label="执行模式">{{ modeLabel(verifyReport.mode) }}</el-descriptions-item>
        <el-descriptions-item label="验证结果">{{ verificationLabel(verifyReport.verification) }}</el-descriptions-item>
        <el-descriptions-item label="处理结果">{{ resultLabel(verifyReport.result) }}</el-descriptions-item>
        <el-descriptions-item label="回滚">{{ rollbackLabel(verifyReport.rollback) }}</el-descriptions-item>
        <el-descriptions-item v-if="verifyReport.error_message" label="异常说明">{{ executionErrorLabel(verifyReport.error_message) }}</el-descriptions-item>
      </el-descriptions>
      <div v-if="verifyReport?.verify_diff" class="config-block" style="margin-top: 12px">
        <div class="block-title">回读差异</div>
        <pre class="config-text">{{ verifyReport.verify_diff }}</pre>
      </div>
      <p class="verify-tip">
        模拟模式（DEPLOY_SIMULATE_ONLY=true）不会回读设备，报告中的"未回读"属正常；真实下发才会产生回读与差异比对。
      </p>
      <template #footer><el-button @click="verifyVisible = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="detailVisible" class="v7b-record-dialog" top="4vh" :title="detail ? `任务 #${detail.id} 详情` : '任务详情'" width="min(720px, 94vw)" draggable>
      <div v-if="detail" class="detail-body">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="设备">{{ deviceName(detail.device_id) }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ statusLabel(detail.status) }}</el-descriptions-item>
          <el-descriptions-item label="风险级别">{{ changeLevelLabel(detail.change_level) }}</el-descriptions-item>
          <el-descriptions-item label="执行引擎">{{ detail.engine || '-' }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatTime(detail.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="确认人">{{ detail.confirmed_by ? `用户 #${detail.confirmed_by}` : '未记录' }}</el-descriptions-item>
          <el-descriptions-item label="确认时间">{{ formatTime(detail.confirmed_at || '') }}</el-descriptions-item>
          <el-descriptions-item label="执行模式" :span="2">{{ executionModeLabel(detail.execution_mode) }}</el-descriptions-item>
        </el-descriptions>
        <div class="config-block">
          <div class="block-title">任务配置脚本 · {{ statusLabel(detail.status) }}</div>
          <pre class="config-text">{{ detail.config_content || '（空）' }}</pre>
        </div>
        <div v-if="detail.verify_diff" class="config-block">
          <div class="block-title warn-text">上次验证差异</div>
          <pre class="config-text">{{ detail.verify_diff }}</pre>
        </div>
        <div v-if="detail.error_message" class="config-block"><div class="block-title">执行或恢复异常</div><pre class="config-text">{{ detail.error_message }}</pre></div>
        <p class="verify-tip">确认只记录审批并取得写锁；执行、回读与恢复须查看该任务保存的结果。当前开关不能补写历史执行模式。</p>
      </div>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button
          v-if="detail && (detail.status === 'pending' || detail.status === 'awaiting_confirmation')"
          type="primary"
          :loading="actingId === detail.id"
          @click="approve(detail)"
        >确认下发</el-button>
        <el-button
          v-if="detail && isCancelable(detail.status)"
          type="danger"
          plain
          :loading="actingId === detail.id"
          @click="cancel(detail)"
        >取消任务</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import PageHeader from '../../components/v7b/PageHeader.vue'
import { useSnapshotRequest } from '../../composables/useSnapshotRequest'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus/es/components/message/index'
import { ElMessageBox } from 'element-plus/es/components/message-box/index'
import { notifyRequestError } from '../../utils/requestError'
import { confirmWithRisk } from '../../utils/deployConfirmation'
import { formatApiTime } from '../../utils/datetime'
import { getDeployTask, getDeployTasks, confirmDeployTask, cancelDeployTask, executeDeployTask, verifyDeployTask } from '../../api/deploy'
import { getDevices, type DeviceRecord } from '../../api/device'
import { executionModeLabel, savedVerificationState } from '../../utils/display'
import RecordOriginFilter from '../../components/RecordOriginFilter.vue'
import {filterByRecordOrigin} from '../../utils/recordOrigin'

interface DeployTaskRow {
  record_origin?: string
  id: number
  device_id: number
  status: string
  change_level?: string
  engine?: string
  created_at: string
  confirmed_by?: number | null
  confirmed_at?: string | null
  config_content?: string
  verify_diff?: string | null
  execution_mode?: string | null
  error_message?: string | null
  has_lock?: boolean
}

const router = useRouter()
const tasks = ref<DeployTaskRow[]>([])
const originFilter=ref('all')
const visibleTasks=computed(()=>filterByRecordOrigin(tasks.value,originFilter.value))
const devices = ref<DeviceRecord[]>([])
const taskRequest = useSnapshotRequest('审批列表')
const loading = taskRequest.loading
const taskLoadError = taskRequest.error
const actingId = ref<number | null>(null)
const detailVisible = ref(false)
const detail = ref<DeployTaskRow | null>(null)
const statusFilter = ref('')
const verifyVisible = ref(false)
const verifyReport = ref<any>(null)
const verifyTitle = ref('验证报告')

const PENDING_STATUSES = ['pending', 'awaiting_confirmation', 'confirmed', 'deploying', 'verifying']
const CANCELABLE = ['pending', 'awaiting_confirmation', 'confirmed']

const deviceName = (id: number) => devices.value.find(item => item.id === id)?.hostname || `设备 ${id}`
const isCancelable = (status: string) => CANCELABLE.includes(status)
const statusLabel = (status: string) => ({
    pending: '等待中', awaiting_confirmation: '待确认', confirmed: '已确认待执行',
    deploying: '执行中 / 待验证', verifying: '验证中', success: '已完成', failed: '失败', rolled_back: '已回滚', cancelled: '已取消',
} as Record<string, string>)[status] || status
const statusClass = (status: string) => ['success'].includes(status) ? 'ok-text'
  : ['failed'].includes(status) ? 'danger-text'
    : ['awaiting_confirmation', 'pending'].includes(status) ? 'warn-text' : 'cyan-text'
const formatTime = (value: string) => formatApiTime(value)
// 后端返回的是英文 token，直接展示学员看不懂（2026-10-05 审计：模拟模式下满是 not_performed/no_readback）
const modeLabel = executionModeLabel
const executionErrorLabel = (code: string) => code === 'UnsupportedRestoreError'
  ? '当前差异不支持自动恢复；未继续写入，请核对配置快照差异并人工处理。'
  : `执行或恢复失败（${code}），请查看任务差异与审计记录。`
const changeLevelLabel = (level?: string | null) => ({
  high_risk: '高风险（需二次确认）', emergency: '紧急', daily: '日常',
} as Record<string, string>)[String(level)] || (level || '-')
const verificationLabel = (v: string) => ({
  passed: '已回读并比对通过', failed: '回读比对不一致', not_performed: '未回读（模拟模式）', unknown:'核验记录范围未知',unverified:'未记录回读核验通过',
} as Record<string, string>)[v] || (v || '-')
const resultLabel = (r: string) => ({
  success: '成功', failed: '失败', no_readback: '未取到回读内容', rollback_required: '需要回滚',
  rolled_back: '已回滚', rollback_unavailable: '无法回滚（无备份）', rollback_failed: '回滚失败',
} as Record<string, string>)[r] || (r || '-')
const rollbackLabel = (r: string) => ({
  required: '需要回滚', unavailable: '不可用（未抓到执行前配置）', rolled_back: '已回滚并核验', rollback_failed: '回滚失败', rollback_unsupported: '当前差异不支持自动恢复，需人工处理',
} as Record<string, string>)[r] || (r ? r : '无需回滚')

const loadTasks = async () => {
  await taskRequest.run(() => Promise.all([
      getDeployTasks(statusFilter.value ? { status: statusFilter.value } : undefined),
      devices.value.length ? Promise.resolve(devices.value) : getDevices(),
    ]), ([taskList, deviceList]) => {
    devices.value = deviceList as DeviceRecord[]
    const rows = (Array.isArray(taskList) ? taskList : []) as DeployTaskRow[]
    // 默认只看待处理；选「已完成」时看终态，否则终态任务会"确认完就消失"、结果无处可查
    tasks.value = statusFilter.value
      ? rows
      : rows.filter(row => PENDING_STATUSES.includes(row.status))
  })
}

const openDetail = async (row: DeployTaskRow) => {
  try {
    detail.value = await getDeployTask(row.id) as DeployTaskRow
    detailVisible.value = true
  } catch (error) {
    notifyRequestError(error, '加载任务详情失败')
  }
}

const approve = async (row: DeployTaskRow) => {
  actingId.value = row.id
  try {
    const riskConfirmed = await confirmWithRisk(
      risk => confirmDeployTask(row.id, risk),
      () => ElMessageBox.confirm(
        `任务 #${row.id}（${deviceName(row.device_id)}）为高风险变更，确认只记录审批结论并取得设备写锁，不会自动执行；执行请在审批通过后单独点「执行」。是否继续？`,
        '高风险二次确认',
        { type: 'warning', confirmButtonText: '确认下发', cancelButtonText: '取消' },
      ),
    )
    ElMessage.success(riskConfirmed ? '已二次确认并取得写锁；请点「执行」下发' : '已确认并取得写锁；请点「执行」下发')
    detailVisible.value = false
    await loadTasks()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') notifyRequestError(error, '确认失败')
  } finally {
    actingId.value = null
  }
}

/** 执行（默认模拟模式不改真机）。执行完刷新列表，状态会变成 deploying/success。 */
const execute = async (row: DeployTaskRow) => {
  actingId.value = row.id
  try {
    const result: any = await executeDeployTask(row.id)
    if (result.error_category) ElMessage.error(executionErrorLabel(result.error_category))
    else ElMessage.success(result.mode === 'simulated'
      ? '已执行（模拟）；接下来点「验证」查看模拟结果'
      : '已执行下发；接下来点「验证」核对设备回读')
    await loadTasks()
    if (detailVisible.value) await openDetail(row)
  } catch (error) {
    notifyRequestError(error, '执行失败')
  } finally {
    actingId.value = null
  }
}

/** 验证执行回读；终态只读取已保存结果，不重新触发写操作。 */
const verify = async (row: DeployTaskRow) => {
  actingId.value = row.id
  try {
    const terminal = ['success', 'failed', 'rolled_back'].includes(row.status)
    const report: any = terminal ? null : await verifyDeployTask(row.id)
    const saved = await getDeployTask(row.id)
    verifyReport.value = {
      ...(report || {
        mode: (saved as any).execution_mode || 'unknown',
        verification: savedVerificationState(saved),
        result: saved.status,
        rollback: saved.status === 'rolled_back' ? 'rolled_back' : saved.error_message === 'UnsupportedRestoreError' ? 'rollback_unsupported' : undefined,
      }),
      verify_diff: saved.verify_diff, error_message: saved.error_message,
    }
    verifyTitle.value = `验证报告 · 任务 #${row.id}（${deviceName(row.device_id)}）`
    verifyVisible.value = true
    await loadTasks()
  } catch (error) {
    notifyRequestError(error, '验证失败')
  } finally {
    actingId.value = null
  }
}

const cancel = async (row: DeployTaskRow) => {  try {
    await ElMessageBox.confirm(
      `取消任务 #${row.id} 会同时释放 ${deviceName(row.device_id)} 的写锁，是否继续？`,
      '取消任务',
      { type: 'warning', confirmButtonText: '取消任务', cancelButtonText: '返回' },
    )
  } catch {
    return
  }
  actingId.value = row.id
  try {
    const result = await cancelDeployTask(row.id)
    ElMessage.success(result.released_lock ? '任务已取消，设备写锁已释放' : '任务已取消')
    detailVisible.value = false
    await loadTasks()
  } catch (error) {
    notifyRequestError(error, '取消失败')
  } finally {
    actingId.value = null
  }
}

onMounted(loadTasks)
</script>

<style scoped>
.approvals-view { min-height: 100%; }
.card-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.card-header .title { font-size: 14px; font-weight: 600; }
.card-header .subtitle { margin-left: 10px; color: var(--v7b-muted); font-size: 11px; }
.header-actions { display: flex; align-items: center; gap: 8px; }
.ok-text { color: var(--v7b-ok); }
.warn-text { color: var(--v7b-warn); }
.danger-text { color: var(--v7b-danger); }
.cyan-text { color: var(--v7b-accent); }
.muted { color: var(--v7b-muted); }
.lock-on { color: var(--v7b-warn); }
.detail-body { display: flex; flex-direction: column; gap: 12px; }
.config-block { display: flex; flex-direction: column; gap: 6px; }
.block-title { color: var(--v7b-muted); font-size: 11px; }
.config-text {
  max-height: 280px;
  margin: 0;
  padding: 10px;
  overflow: auto;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  background: var(--el-fill-color-light);
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
  white-space: pre-wrap;
}
.verify-tip { margin: 12px 0 0; color: var(--v7b-muted); font-size: 11.5px; line-height: 1.6; }
.empty-desc { max-width: 460px; color: var(--v7b-muted); font-size: 12px; line-height: 1.7; }
.empty-desc p { margin: 0 0 4px; }
.approval-actions { display: flex; flex-wrap: wrap; gap: 4px; }
.approval-actions :deep(.el-button + .el-button) { margin-left: 0; }
</style>
