<template>
  <div class="deploy-center v7b-page">
    <PageHeader
      title="配置下发"
      subtitle="草稿、确认、执行和回读是显式步骤；模拟开关不代表终端只读，真实写入仍需白名单与人工确认。"
    />
    <el-tabs v-model="activeTab">
      <!-- 配置下发 -->
      <el-tab-pane label="新建任务" name="deploy">
        <el-alert v-if="deviceLoadError" :title="deviceLoadError" type="error" :closable="false" show-icon><el-button @click="loadDevices">重试设备列表</el-button></el-alert>
        <!-- AI 草稿提示条：不自动填入，由用户选择载入或清除 -->
        <el-alert
          v-if="draftAvailable"
          type="info"
          show-icon
          :closable="false"
          style="margin-bottom: 12px; max-width: 800px"
        >
          <template #title>检测到 AI 配置草稿（保存于 {{ draftSavedAt || '未知时间' }}）</template>
          <template #default>
            <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap">
              <el-button size="small" type="primary" @click="loadAiDraft">载入草稿</el-button>
              <el-button size="small" @click="clearAiDraft">清除草稿</el-button>
            </div>
          </template>
        </el-alert>
        <el-form :model="deployForm" label-width="100px" class="deploy-form">
          <el-form-item label="任务名称">
            <el-input v-model="deployForm.name" placeholder="输入本次配置任务名称" />
          </el-form-item>
          <el-form-item label="目标设备">
            <el-select v-model="deployForm.device_ids" multiple placeholder="选择设备" style="width: 100%">
              <el-option
                v-for="device in devices"
                :key="device.id"
                :label="deviceOptionLabel(device)"
                :value="device.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="AI 需求">
            <el-input
              v-model="aiIntent"
              type="textarea"
              :rows="3"
              placeholder="用自然语言描述要生成的配置，例如：在接口上配置 IP 并添加静态路由。结果只填入下方文本框，不会自动下发。"
            />
          </el-form-item>
          <el-form-item label="配置内容">
            <el-input ref="configEditor" v-model="deployForm.config_content" type="textarea" :rows="10" placeholder="输入VRP配置命令..." />
          </el-form-item>
          <el-form-item class="deploy-actions">
            <el-button type="primary" @click="handleDeploy" :loading="deploying">创建任务</el-button>
            <el-button @click="handleValidate" :loading="validating">校验配置</el-button>
            <el-dropdown trigger="click" @command="(cmd: string) => cmd === 'generate' ? handleAiGenerate() : handleAiReview()">
              <el-button :loading="aiGenerateLoading || aiReviewLoading">AI 辅助</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="generate">生成并校验（填入草稿）</el-dropdown-item>
                  <el-dropdown-item command="review">审查当前配置（只给建议）</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-button link @click="$router.push('/config-versions')">配置管理</el-button>
            <el-button
              v-if="labCtx.hasLab && labCtx.sessionId"
              link
              @click="$router.push({ path: '/training', query: { session_id: String(labCtx.sessionId) } })"
            >返回实训</el-button>
          </el-form-item>
        </el-form>
        <el-card v-if="staticValidation" class="static-validation" shadow="never" aria-label="静态校验结果">
          <template #header>静态校验结果 · {{ staticValidation.model }} · 未执行</template>
          <el-alert v-if="staticValidationStale" title="配置内容或目标已变化，这份结果仅对应先前输入，请重新校验。" type="warning" :closable="false" show-icon />
          <p>{{ staticValidation.result.valid ? '在已覆盖的规则内未发现问题。' : '发现以下配置问题，请修改后重新校验。' }}</p>
          <ul v-if="staticValidation.result.diagnostics?.length"><li v-for="(error,index) in staticValidation.result.diagnostics" :key="index"><el-button link type="primary" :disabled="staticValidationStale || !error.line_number" @click="focusConfigLine(error.line_number)">第 {{ error.line_number || '?' }} 行</el-button> {{ error.message }} <code>{{ error.command }}</code></li></ul>
          <ul v-else-if="staticValidation.result.errors?.length"><li v-for="(error, index) in staticValidation.result.errors" :key="index">{{ error }}</li></ul>
          <p v-if="staticValidation.result.coverage?.checked?.length">已检查：{{ staticValidation.result.coverage.checked.join('、') }}</p>
          <p v-if="staticValidation.result.coverage?.not_checked?.length">未检查：{{ staticValidation.result.coverage.not_checked.join('、') }}</p>
          <p>此结果不代表设备已执行或业务已恢复。</p>
        </el-card>
        <el-card v-if="aiGenerateResult" shadow="never" style="max-width: 800px; margin-top: 12px">
          <template #header>生成与校验结果（已填入文本框，请核对后再创建任务）</template>
          <el-tag :type="aiGenerateResult.all_passed ? 'success' : 'warning'">
            {{ aiGenerateResult.all_passed ? '校验通过' : '存在风险' }}
          </el-tag>
          <el-tag v-if="aiGenerateResult.risk_level" style="margin-left: 8px">{{ aiGenerateResult.risk_level }}</el-tag>
          <p v-if="aiGenerateResult.explanation" style="margin: 10px 0 0; color: var(--v7b-muted)">{{ aiGenerateResult.explanation }}</p>
          <el-alert
            v-for="(warning, index) in (aiGenerateResult.warnings || [])"
            :key="'gw-' + index"
            type="warning"
            :title="warning"
            :closable="false"
            style="margin-top: 8px"
          />
        </el-card>
        <el-card v-if="aiReviewResult" shadow="never" style="max-width: 800px; margin-top: 12px">
          <template #header>配置审查</template>
          <p style="margin: 0 0 8px; color: var(--v7b-muted)">{{ aiReviewResult.summary || '审查完成' }}</p>
          <el-tag v-if="aiReviewResult.risk_level">{{ aiReviewResult.risk_level }}</el-tag>
          <ul v-if="aiReviewResult.issues?.length" style="margin: 8px 0 0; padding-left: 18px">
            <li v-for="(issue, index) in aiReviewResult.issues" :key="'ri-' + index">
              {{ issue.severity }}：{{ issue.description }}{{ issue.suggestion ? `（建议：${issue.suggestion}）` : '' }}
            </li>
          </ul>
        </el-card>
      </el-tab-pane>

      <!-- 下发任务列表 -->
      <el-tab-pane label="任务管理" name="tasks">
        <el-alert v-if="taskLoadError" :title="taskLoadError" type="error" :closable="false" show-icon><el-button @click="loadTasks">重试任务列表</el-button></el-alert>
        <RecordOriginFilter v-model="originFilter" :records="tasks" :unavailable="!!taskLoadError" />
        <el-table :data="visibleTasks" v-loading="tasksLoading">
          <template #empty>
            <el-empty :description="taskLoadError || (tasks.length?'当前来源筛选没有匹配任务，可恢复全部来源。':'暂无下发任务。在「新建任务」提交后，可从这里查看进度。')" :image-size="72" />
          </template>
          <el-table-column prop="name" label="任务名称" min-width="200" show-overflow-tooltip />
          <el-table-column prop="source" label="来源" width="100" />
          <el-table-column label="状态" width="180">
            <template #default="{ row }">
              <span style="color: var(--v7b-muted); font-size: 12px">
                待确认 {{ row.summary?.pending ?? 0 }} · 执行中 {{ row.summary?.running ?? 0 }} · 成功 {{ row.summary?.success ?? 0 }} · 失败 {{ row.summary?.failed ?? 0 }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="计划日期" width="180">
            <template #default="{ row }">{{ formatApiTime(row.planned_at) }}</template>
          </el-table-column>
          <el-table-column label="创建时间" width="180">
            <template #default="{ row }">{{ formatApiTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="下一步" min-width="220">
            <template #default="{ row }">
              <span class="next-hint">{{ batchNextHint(row) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link @click="handleViewDetail(row)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 配置模板 -->
      <el-tab-pane label="配置模板" name="templates">
        <el-alert v-if="templateLoadError" :title="templateLoadError" type="error" :closable="false" show-icon><el-button @click="loadTemplates">重试模板列表</el-button></el-alert>
        <div style="margin-bottom: 16px">
          <el-button type="primary" @click="showTemplateDialog = true">新建模板</el-button>
        </div>
        <el-table :data="templates" v-loading="templatesLoading">
          <template #empty>
            <el-empty :description="templateLoadError || '暂无配置模板。可点「新建模板」保存常用 CLI。'" :image-size="72" />
          </template>
          <el-table-column prop="name" label="模板名称" min-width="180" show-overflow-tooltip />
          <el-table-column prop="category" label="分类" width="100" />
          <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
          <el-table-column label="创建时间" width="180">
            <template #default="{ row }">{{ formatApiTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link @click="handleUseTemplate(row)">使用</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 任务详情对话框（操作后自动刷新，无需关闭重开） -->
    <el-dialog class="v7b-record-dialog" top="4vh" v-model="detailDialogVisible" title="任务详情" width="min(800px, 92vw)" draggable append-to-body destroy-on-close>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="任务名称">{{ currentTask?.name }}</el-descriptions-item>
        <el-descriptions-item label="来源">{{ currentTask?.source }}</el-descriptions-item>
        <el-descriptions-item label="批次汇总">
          <span v-if="currentTask?.summary">
            待确认 {{ currentTask.summary.pending }} · 执行中 {{ currentTask.summary.running }} · 成功 {{ currentTask.summary.success }} · 失败 {{ currentTask.summary.failed }}
          </span>
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatApiTime(currentTask?.created_at) }}</el-descriptions-item>
      </el-descriptions>
      <div v-for="item in currentTask?.items || []" :key="item.id" style="margin-top: 16px; border: 1px solid #273444; border-radius: 6px; padding: 12px">
        <div style="display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap">
          <h4 style="margin: 0">设备 {{ deviceName(item.device_id) }}（任务项 #{{ item.id }}）</h4>
          <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap">
            <el-tag :type="stageTagType(item.stage)" size="small">{{ stageLabel(item.stage) }}</el-tag>
            <el-button v-if="item.status === 'awaiting_confirmation'" type="warning" size="small" :loading="actingTaskId === item.id" :disabled="!!actingTaskId && actingTaskId !== item.id" @click="handleTaskConfirmation(item)">确认</el-button>
            <el-button v-if="item.status === 'confirmed'" type="success" size="small" :loading="actingTaskId === item.id" :disabled="!!actingTaskId && actingTaskId !== item.id" @click="handleExecution(item)">执行</el-button>
            <el-button v-if="item.status === 'deploying'" type="primary" size="small" :loading="actingTaskId === item.id" :disabled="!!actingTaskId && actingTaskId !== item.id" @click="handleVerification(item)">验证报告</el-button>
            <el-button v-if="['success', 'failed', 'rolled_back'].includes(item.status)" type="success" link size="small" @click="handleVerification(item)">查看结果</el-button>
            <!-- 取消并释放设备写锁：确认了却没执行的任务会一直占着锁，设备终端会被拒接 -->
            <el-button
              v-if="['pending', 'awaiting_confirmation', 'confirmed'].includes(item.status)"
              type="danger" link size="small"
              :loading="actingTaskId === item.id" :disabled="!!actingTaskId && actingTaskId !== item.id"
              @click="handleCancelTask(item)"
            >取消任务</el-button>
          </div>
        </div>
        <!-- 5 步流程：让"还差哪一步"一眼可见 -->
        <el-steps :active="flowStageIndex(item.status)" simple class="deploy-steps">
          <el-step v-for="name in DEPLOY_FLOW_STEPS" :key="name" :title="name" />
        </el-steps>
        <div v-if="nextActionHint(item.status)" class="next-hint">{{ nextActionHint(item.status) }}</div>
        <pre style="background: #0d151e; color: #c5d4e0; padding: 12px; border-radius: 4px; max-height: 180px; overflow-y: auto; margin: 10px 0 0">{{ item.config_content }}</pre>
        <div v-if="item.status === 'success' || item.status === 'failed'" style="margin-top: 8px; color: var(--v7b-muted); font-size: 12px">
          <span v-if="item.status === 'success'">{{ item.execution_mode === 'real' ? '✅ 真实执行已完成；请核对回读与恢复状态。' : item.execution_mode === 'simulated' ? '✅ 模拟执行已完成（未改动设备）。' : '✅ 任务已完成，但执行模式未记录，不能推断是否改动了设备。' }}</span>
          <span v-else>❌ 任务失败{{ item.error_message ? `：${item.error_message}` : '' }}</span>
        </div>
        <!-- 失败时给出可点入口（后端已算好深链，此前前端从未渲染 → 学员不知道该去哪查） -->
        <div v-if="item.links && (item.status === 'failed' || item.verify_diff)" class="link-row">
          <el-button v-if="item.links.change_log" link type="primary" size="small" @click="goLink(item.links.change_log)">变更日志</el-button>
          <el-button v-if="item.links.snapshot" link type="primary" size="small" @click="goLink(item.links.snapshot)">设备快照</el-button>
          <el-button v-if="item.links.compare" link type="primary" size="small" @click="goLink(item.links.compare)">配置比对</el-button>
        </div>
      </div>
      <template #footer>
        <el-button @click="refreshCurrentTask" :loading="detailLoading">刷新</el-button>
        <el-button type="primary" @click="detailDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 新建模板对话框 -->
    <el-dialog class="v7b-record-dialog" top="4vh" v-model="showTemplateDialog" title="新建配置模板" width="min(600px, 92vw)" draggable append-to-body destroy-on-close>
      <el-form :model="templateForm" label-width="80px">
        <el-form-item label="模板名称">
          <el-input v-model="templateForm.name" placeholder="输入模板名称" />
        </el-form-item>
        <el-form-item label="分类">
          <el-input v-model="templateForm.category" placeholder="输入分类" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="templateForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="配置内容">
          <el-input v-model="templateForm.content" type="textarea" :rows="10" placeholder="输入配置模板..." />
        </el-form-item>
        <el-form-item label="变量">
          <el-input v-model="templateForm.variables" type="textarea" :rows="3" placeholder='JSON格式，如 {"hostname": {"required": true}}' />
        </el-form-item>
        <el-form-item label="预览变量值">
          <el-input v-model="previewVariables" type="textarea" :rows="3" placeholder='JSON格式，如 {"hostname": "Router01"}' />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showTemplateDialog = false">取消</el-button>
        <el-button @click="handleTemplatePreview">渲染预览</el-button>
        <el-button type="primary" @click="handleCreateTemplate">确定</el-button>
      </template>
    </el-dialog>
    <el-dialog class="v7b-record-dialog" top="4vh" v-model="previewVisible" title="渲染预览" width="min(600px, 92vw)" draggable append-to-body destroy-on-close>
      <pre>{{ previewContent }}</pre>
      <template #footer>
        <el-button type="primary" @click="previewVisible = false">关闭</el-button>
      </template>
    </el-dialog>
    <el-dialog class="v7b-record-dialog" top="4vh" v-model="verificationVisible" title="验证报告" width="min(560px, 94vw)" draggable append-to-body destroy-on-close>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="任务ID">{{ verificationReport?.task_id }}</el-descriptions-item>
        <el-descriptions-item label="设备">{{ deviceName(verificationReport?.device_id) }}</el-descriptions-item>
        <el-descriptions-item label="执行模式">{{ modeLabel(verificationReport?.mode) }}</el-descriptions-item>
        <el-descriptions-item label="验证结果">{{ verificationLabel(verificationReport?.verification) }}</el-descriptions-item>
        <el-descriptions-item label="处理结果">{{ resultLabel(verificationReport?.result || verificationReport?.rollback) }}</el-descriptions-item>
        <el-descriptions-item label="回滚">{{ rollbackLabel(verificationReport?.rollback) }}</el-descriptions-item>
      </el-descriptions>
      <div v-if="verificationReport?.verify_diff" class="verify-block">
        <div class="block-title">回读差异</div>
        <pre class="verify-pre">{{ verificationReport.verify_diff }}</pre>
      </div>
      <div v-if="verificationReport?.error_message" class="verify-block">
        <div class="block-title">失败原因</div>
        <pre class="verify-pre">{{ verificationReport.error_message }}</pre>
      </div>
      <p class="verify-tip">
        {{ verificationHint(verificationReport) }}
      </p>
      <template #footer>
        <el-button type="primary" @click="verificationVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import PageHeader from '../../components/v7b/PageHeader.vue'
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus/es/components/message/index'
import { notifyRequestError } from '../../utils/requestError'
import { formatApiTime } from '../../utils/datetime'
import { executionModeLabel, savedVerificationState } from '../../utils/display'
import RecordOriginFilter from '../../components/RecordOriginFilter.vue'
import { useSnapshotRequest } from '../../composables/useSnapshotRequest'
import {filterByRecordOrigin} from '../../utils/recordOrigin'
import { confirmWithRisk } from '../../utils/deployConfirmation'
import { ElMessageBox } from 'element-plus/es/components/message-box/index'
import { getDevices, type DeviceRecord } from '../../api/device'
import { generateAndValidate, reviewConfig } from '../../api/ai'
import { cancelDeployTask, confirmDeployTask, createDeployBatch, createTemplate, executeDeployTask, getDeployBatch, getDeployBatches, getDeployTask, getTemplates, renderTemplate, validateConfig, verifyDeployTask, type ConfigTemplateRecord } from '../../api/deploy'
import { useLabContextStore } from '../../stores/labContext'
import { useAiCopilotStore } from '../../stores/aiCopilot'
import { useAutoRefresh } from '../../utils/autoRefresh'
import { resolveWorkbenchDeviceModel } from '../../utils/deviceModel'
import type { ConfigValidateResult } from '../../api/deploy'

const route = useRoute()
const router = useRouter()
const labCtx = useLabContextStore()
const copilot = useAiCopilotStore()
const activeTab = ref('deploy')
const deploying = ref(false)
const validating = ref(false)
const actingTaskId = ref<number | null>(null)
const deviceRequest = useSnapshotRequest('设备列表')
const deviceLoadError = deviceRequest.error
const taskRequest = useSnapshotRequest('下发任务列表')
const tasksLoading = taskRequest.loading
const taskLoadError = taskRequest.error
const templateRequest = useSnapshotRequest('配置模板列表')
const templatesLoading = templateRequest.loading
const templateLoadError = templateRequest.error
const detailDialogVisible = ref(false)
const showTemplateDialog = ref(false)
const previewVisible = ref(false)
const previewContent = ref('')
const previewVariables = ref('')
const verificationVisible = ref(false)
const verificationReport = ref<any>(null)

// 设备列表
const devices = ref<DeviceRecord[]>([])

// 下发表单
const deployForm = ref({
  name: '',
  device_ids: [] as number[],
  engine: 'netmiko',
  config_content: ''
})
const aiIntent = ref('')
const aiGenerateLoading = ref(false)
const aiReviewLoading = ref(false)
const aiGenerateResult = ref<any>(null)
const aiReviewResult = ref<any>(null)

// 任务列表
const tasks = ref<any[]>([])
const originFilter=ref('all')
const visibleTasks=computed(()=>filterByRecordOrigin(tasks.value,originFilter.value))
const currentTask = ref<any>(null)

// 模板列表
const templates = ref<ConfigTemplateRecord[]>([])
const templateForm = ref({
  name: '',
  category: '',
  description: '',
  content: '',
  variables: ''
})

// 加载设备列表
const loadDevices = async () => {
  await deviceRequest.run(() => getDevices(), value => { devices.value = value })
}

// 加载任务列表
const loadTasks = async () => {
  await taskRequest.run(() => getDeployBatches(), value => { tasks.value = value })
}

// 加载模板列表
const loadTemplates = async () => {
  await templateRequest.run(() => getTemplates(), value => { templates.value = value })
}

// 下发配置
const handleDeploy = async () => {
  if (!deployForm.value.device_ids.length) {
    ElMessage.warning('请选择目标设备')
    return
  }
  if (!deployForm.value.config_content.trim()) {
    ElMessage.warning('请输入配置内容')
    return
  }
  deploying.value = true
  try {
    await createDeployBatch({
      name: deployForm.value.name.trim() || `配置任务 ${new Date().toLocaleString()}`,
      source: 'manual', engine: deployForm.value.engine,
      items: deployForm.value.device_ids.map(device_id => ({ device_id, config_content: deployForm.value.config_content })),
    })
    ElMessage.success('配置任务已创建，请在任务管理中确认后执行')
    loadTasks()
    activeTab.value = 'tasks'
  } catch (error: any) {
    notifyRequestError(error, '下发失败')
  } finally {
    deploying.value = false
  }
}

const handleAiGenerate = async () => {
  if (!aiIntent.value.trim()) {
    ElMessage.warning('请先填写 AI 需求描述')
    return
  }
  aiGenerateLoading.value = true
  try {
    const res: any = await generateAndValidate({
      natural_language: aiIntent.value,
      device_model: resolveValidateModel(),
    })
    aiGenerateResult.value = res
    const commands = Array.isArray(res?.commands) ? res.commands.filter(Boolean) : []
    if (commands.length) {
      deployForm.value.config_content = commands.join('\n')
    }
    ElMessage.success('已填入配置文本框，请核对后手动创建任务（不会自动下发）')
  } catch (error: any) {
    notifyRequestError(error, '生成失败，请稍后重试')
  } finally {
    aiGenerateLoading.value = false
  }
}

const handleAiReview = async () => {
  if (!deployForm.value.config_content.trim()) {
    ElMessage.warning('请先输入或生成待审查配置')
    return
  }
  aiReviewLoading.value = true
  try {
    aiReviewResult.value = await reviewConfig({
      config_text: deployForm.value.config_content,
      device_model: resolveValidateModel(),
    })
    ElMessage.success('审查完成，结果仅供参考，不会自动下发')
  } catch (error: any) {
    notifyRequestError(error, '审查失败，请稍后重试')
  } finally {
    aiReviewLoading.value = false
  }
}

/** 设备 id → 主机名（确认是不可逆授权动作，只显示"设备 7"学员认不出是 R1 还是 R3） */
const deviceName = (deviceId: unknown) => {
  const found = devices.value.find((item) => Number(item.id) === Number(deviceId))
  return found ? `${found.hostname}` : `设备 ${deviceId ?? '-'}`
}

function deviceOptionLabel(device: DeviceRecord) {  const model = resolveWorkbenchDeviceModel(device.model)
  return `${device.hostname} · ${model}`
}

function resolveValidateModel(): string {
  const selected = devices.value.filter((d) => deployForm.value.device_ids.includes(d.id))
  const fromDevice = selected.map((d) => (d.model || '').trim()).find(Boolean)
  return resolveWorkbenchDeviceModel(fromDevice)
}

// 校验配置
const staticValidation = ref<{ config: string; model: string; targets: string; result: ConfigValidateResult } | null>(null)
const configEditor=ref<{textarea?:HTMLTextAreaElement}|null>(null)
const focusConfigLine=(line?:number)=>{
  if(!line||staticValidationStale.value)return
  const textarea=configEditor.value?.textarea;if(!textarea)return
  const lines=deployForm.value.config_content.split('\n'),start=lines.slice(0,line-1).reduce((n,s)=>n+s.length+1,0)
  textarea.focus();textarea.setSelectionRange(start,start+(lines[line-1]?.length||0));textarea.scrollTop=Math.max(0,(line-3)*(parseFloat(getComputedStyle(textarea).lineHeight)||20));textarea.scrollIntoView({block:'center'})
}
const staticValidationStale = computed(() => !!staticValidation.value && (
  staticValidation.value.config !== deployForm.value.config_content ||
  staticValidation.value.targets !== JSON.stringify(deployForm.value.device_ids) ||
  staticValidation.value.model !== resolveValidateModel()
))

const handleValidate = async () => {
  if (!deployForm.value.config_content.trim()) {
    ElMessage.warning('请输入配置内容')
    return
  }
  const device_model = resolveValidateModel()
  const config_content = deployForm.value.config_content
  const targets = JSON.stringify(deployForm.value.device_ids)
  validating.value = true
  try {
    const res = await validateConfig({
      config_content,
      device_model,
    })
    staticValidation.value = { config: config_content, model: device_model, targets, result: res }
  } catch (error: any) {
    notifyRequestError(error, '校验失败')
  } finally {
    validating.value = false
  }
}

// 查看任务详情
const handleViewDetail = async (task: any) => {
  try {
    currentTask.value = await getDeployBatch(task.id)
    detailDialogVisible.value = true
  } catch (error) {
    notifyRequestError(error, '获取详情失败')
  }
}

// 刷新当前详情（操作后调用，避免"关闭重开"）
const detailLoading = ref(false)
const refreshCurrentTask = async () => {
  if (!currentTask.value?.id) return
  detailLoading.value = true
  try {
    currentTask.value = await getDeployBatch(currentTask.value.id)
  } catch (error) {
    notifyRequestError(error, '刷新详情失败')
  } finally {
    detailLoading.value = false
  }
}

const stageLabel = (stage: string) => ({
  pending: '待确认', waiting: '已确认待执行', deploying: '执行中', readback: '回读验证中',
  success: '已完成', failed: '失败',
}[stage] || stage)

const stageTagType = (stage: string) => ({
  pending: 'warning', waiting: 'info', deploying: 'primary', readback: 'primary',
  success: 'success', failed: 'danger',
}[stage] || 'info') as '' | 'success' | 'warning' | 'info' | 'primary' | 'danger'

// ── 下发流程可视化（2026-10-05 用户反馈"得点很多个按钮，不知道下一步点哪个"）──
// 流程：创建任务 → 确认下发 → 执行 → 验证 → 完成（5 步，缺一步都不算完成）
const DEPLOY_FLOW_STEPS = ['创建任务', '确认下发', '执行', '验证', '完成']
const flowStageIndex = (status: string) => ({
  awaiting_confirmation: 1,
  confirmed: 2,
  deploying: 3,
  verifying: 3,
  // success 要给 5：el-steps 的 active 是"当前进行到第几个"，给 4 会让第 5 步永远停在进行中
  success: 5,
  failed: 4,
  rolled_back: 4,
  cancelled: 4,
}[status] ?? 0)

const nextActionHint = (status: string) => ({
  awaiting_confirmation: '下一步：点「确认」下发（高风险命令会弹二次确认）',
  confirmed: '下一步：点「执行」；执行模式由服务端配置决定',
  deploying: '下一步：点「验证报告」回读设备配置并比对',
  verifying: '正在回读比对，稍等',
  success: '已完成：需要复核时点「查看结果」',
  failed: '已失败：看验证报告或变更日志定位原因',
  cancelled: '已取消（设备写锁已释放）',
  rolled_back: '已回滚',
}[status] || '')

// 验证报告里的英文 token 直接给学员看等于没说（审计：模拟模式下满是 not_performed/no_readback）
const modeLabel = executionModeLabel
const verificationLabel = (v: unknown) => ({
  passed: '已回读并比对通过', failed: '回读比对不一致', not_performed: '未回读（模拟模式）', unknown:'核验记录范围未知',unverified:'未记录回读核验通过',
} as Record<string, string>)[String(v)] || (v ? String(v) : '-')
const resultLabel = (r: unknown) => ({
  success: '成功', failed: '失败', no_readback: '未取到回读内容', rollback_required: '需要回滚',
  rolled_back: '已回滚', rollback_unavailable: '无法回滚（未抓到执行前配置）', rollback_failed: '回滚失败',
} as Record<string, string>)[String(r)] || (r ? String(r) : '-')
const rollbackLabel = (r: unknown) => ({
  required: '需要回滚', unavailable: '不可用（未抓到执行前配置）', rolled_back: '已回滚并核验', rollback_failed: '回滚失败', rollback_unsupported: '当前差异不支持自动恢复，需人工处理',
} as Record<string, string>)[String(r)] || (r ? String(r) : '无需回滚')

const verificationHint = (report: any) => {
  if (!report) return ''
  if (report.verification === 'not_performed') {
    return '模拟模式下不会回读设备，报告为占位；要看真实回读与差异，需要关闭 DEPLOY_SIMULATE_ONLY 并命中白名单后执行。'
  }
  if (report.verification === 'passed') return '回读内容与下发内容一致，这一步可以判定通过。'
  if (report.verification === 'failed') return '回读与下发内容存在差异，请先看「回读差异」；必要时在配置管理里比对并回滚。'
  return ''
}

const goLink = (path: string) => {
  detailDialogVisible.value = false
  router.push(path)
}

/** 批次级"下一步"：让用户不用点开详情就知道该干什么 */
const batchNextHint = (row: any) => {  const summary = row?.summary || {}
  if ((summary.pending ?? 0) > 0) return `有 ${summary.pending} 台待确认 → 点「详情」确认下发`
  if ((summary.running ?? 0) > 0) return `有 ${summary.running} 台执行中 → 完成后点「详情」验证`
  if ((summary.success ?? 0) > 0) return '已完成 → 点「详情」查看验证结果'
  if ((summary.failed ?? 0) > 0) return '有失败项 → 点「详情」看失败原因'
  return '—'
}

// 使用模板
const handleUseTemplate = (template: any) => {
  deployForm.value.config_content = template.content
  activeTab.value = 'deploy'
}

// 创建模板
const handleCreateTemplate = async () => {
  try {
    let variables = {}
    if (templateForm.value.variables) {
      try {
        variables = JSON.parse(templateForm.value.variables)
      } catch {
        ElMessage.error('变量格式必须为有效的JSON')
        return
      }
    }
    await createTemplate({
      ...templateForm.value,
      variables
    })
    ElMessage.success('模板创建成功')
    showTemplateDialog.value = false
    loadTemplates()
  } catch (error: any) {
    notifyRequestError(error, '创建失败')
  }
}

const handleTemplatePreview = async () => {
  try {
    const variables = previewVariables.value ? JSON.parse(previewVariables.value) : {}
    const payload: any = { content: templateForm.value.content, variables }
    if (templateForm.value.variables) {
      payload.declarations = JSON.parse(templateForm.value.variables)
    }
    const res = await renderTemplate(payload)
    previewContent.value = res.rendered
    previewVisible.value = true
  } catch (error: any) {
    notifyRequestError(error, '渲染预览失败')
  }
}

const handleTaskConfirmation = async (task: any) => {
  actingTaskId.value = task.id
  try {
    const riskConfirmed = await confirmWithRisk(
      risk => confirmDeployTask(task.id, risk),
      () => ElMessageBox.confirm(
        '该任务被判定为高风险变更，需要二次确认。请确认已核对命令内容后再继续。',
        '高风险任务确认',
        { confirmButtonText: '我确认，继续', cancelButtonText: '取消', type: 'warning' },
      ),
    )
    ElMessage.success(riskConfirmed ? '高风险二次确认完成' : '任务已确认')
    await refreshCurrentTask()
    loadTasks()
  } catch (error: any) {
    if (error !== 'cancel' && error !== 'close') notifyRequestError(error, '确认失败')
  } finally {
    actingTaskId.value = null
  }
}

const handleExecution = async (task: any) => {
  actingTaskId.value = task.id
  try {
    const result: any = await executeDeployTask(task.id)
    if (result.error_category) {
      ElMessage.error(result.error_category === 'UnsupportedRestoreError'
        ? '当前差异不支持自动恢复，未继续写入；请核对快照差异并人工处理。'
        : `执行失败（${result.error_category}），请查看任务结果。`)
    } else {
      ElMessage.success(result.mode === 'simulated' ? '模拟执行完成，请验证模拟结果' : '下发完成，请验证设备回读')
    }
    await refreshCurrentTask()
    loadTasks()
  } catch (error: any) {
    notifyRequestError(error, '执行失败')
  } finally {
    actingTaskId.value = null
  }
}

const handleCancelTask = async (task: any) => {
  try {
    await ElMessageBox.confirm(
      `确认取消任务 ${task.id}？将同时释放设备 ${task.device_id} 的写锁（设备终端与后续下发恢复可用）。`,
      '取消任务',
      { confirmButtonText: '确认取消', cancelButtonText: '返回', type: 'warning' }
    )
  } catch {
    return // 用户放弃
  }
  actingTaskId.value = task.id
  try {
    const result: any = await cancelDeployTask(task.id)
    ElMessage.success(result?.released_lock ? '任务已取消，设备写锁已释放' : '任务已取消')
    await refreshCurrentTask()
    loadTasks()
  } catch (error: any) {
    notifyRequestError(error, '取消失败')
  } finally {
    actingTaskId.value = null
  }
}

const handleVerification = async (task: any) => {
  actingTaskId.value = task.id
  try {
    const terminal = ['success', 'failed', 'rolled_back'].includes(task.status)
    const report: any = terminal ? null : await verifyDeployTask(task.id)
    const saved = await getDeployTask(task.id)
    verificationReport.value = {
      ...(report || {
        task_id: saved.id, device_id: saved.device_id,
        mode: (saved as any).execution_mode || 'unknown',
        verification: savedVerificationState(saved),
        result: saved.status,
        rollback: saved.status === 'rolled_back' ? 'rolled_back' : saved.error_message === 'UnsupportedRestoreError' ? 'rollback_unsupported' : undefined,
      }),
      verify_diff: saved.verify_diff,
      error_message: saved.error_message === 'UnsupportedRestoreError' ? '当前差异不支持自动恢复，请核对快照差异并人工处理。' : saved.error_message,
    }
    await refreshCurrentTask()
    loadTasks()
    verificationVisible.value = true
  } catch (error: any) {
    notifyRequestError(error, '验证失败')
  } finally {
    actingTaskId.value = null
  }
}


// ── AI 配置草稿：提示条 + 手动载入/清除（不再打开页面自动填入） ──
const draftAvailable = ref(false)
const draftSavedAt = ref('')

function refreshDraftState() {
  draftAvailable.value = !!localStorage.getItem('deploy_ai_draft')?.trim()
  const at = localStorage.getItem('deploy_ai_draft_at')
  draftSavedAt.value = at ? new Date(Number(at)).toLocaleString('zh-CN', { hour12: false }) : ''
}

function loadAiDraft() {
  const draft = localStorage.getItem('deploy_ai_draft')
  if (!draft?.trim()) return false
  // A loaded draft replaces the target selection, never adds to an old batch.
  // Legacy or mismatched metadata requires an explicit new selection.
  let targetId: number | null = null
  try {
    const context = JSON.parse(localStorage.getItem('deploy_ai_draft_context') || 'null')
    const id = context?.target?.deviceId
    if (context?.text === draft && context?.target?.verifiedByServer === true && Number.isSafeInteger(id) && id > 0 && devices.value.some(d => d.id === id)) targetId = id
  } catch { /* Unbound legacy draft; clear stale target below. */ }
  deployForm.value.device_ids = targetId == null ? [] : [targetId]
  deployForm.value.config_content = draft
  activeTab.value = 'deploy'
  ElMessage.success(targetId == null ? '已载入 AI 草稿，请选择目标设备并核对配置' : '已载入 AI 草稿及原目标设备，请核对后再创建任务')
  refreshDraftState()
  return true
}

function maybeAutoLoadDraft() {
  if (String(route.query.draft || '') !== '1') return
  if (loadAiDraft()) {
    const nextQuery = { ...route.query }
    delete nextQuery.draft
    router.replace({ path: '/deploy', query: nextQuery })
  }
}

function clearAiDraft() {
  localStorage.removeItem('deploy_ai_draft')
  localStorage.removeItem('deploy_ai_draft_at')
  localStorage.removeItem('deploy_ai_draft_context')
  ElMessage.success('配置草稿已清除')
  refreshDraftState()
}

function prefillDevice(id?: number | null) {
  if (!id) return
  if (!deployForm.value.device_ids.includes(id)) {
    deployForm.value.device_ids = [...deployForm.value.device_ids, id]
  }
}

function syncDeploySelection() {
  const ids = deployForm.value.device_ids
  if (!ids.length) return
  const primary = devices.value.find((d) => d.id === ids[0])
  if (!primary) return
  labCtx.setDevice({
    id: primary.id,
    hostname: primary.hostname,
    mgmt_ip: primary.mgmt_ip,
    model: primary.model,
  })
  copilot.setSelection({
    kind: 'device',
    id: primary.id,
    label: primary.hostname,
    detail: ids.length > 1 ? `下发目标 ${ids.length} 台 · ${primary.mgmt_ip || ''}` : (primary.mgmt_ip || ''),
    model: primary.model,
  })
}

watch(() => [...deployForm.value.device_ids], () => syncDeploySelection())
watch(
  () => route.query.tab,
  (tab) => {
    const name = String(tab || '')
    if (name === 'tasks' || name === 'templates' || name === 'deploy') activeTab.value = name
  },
)

function onAiDraftEvent(ev: Event) {
  refreshDraftState()
  const autoLoad = Boolean((ev as CustomEvent).detail?.autoLoad)
  if (autoLoad) loadAiDraft()
}

function onAiDeviceEvent(ev: Event) {
  const detail = (ev as CustomEvent).detail || {}
  prefillDevice(Number(detail.device_id || 0) || null)
}

watch(
  () => route.query.draft,
  () => maybeAutoLoadDraft(),
)

async function openTaskDeepLink() {
  const taskId = Number(route.query.task_id || 0)
  if (!taskId) return
  activeTab.value = 'tasks'
  try {
    const item = await getDeployTask(taskId)
    if (item?.batch_id) {
      currentTask.value = await getDeployBatch(item.batch_id)
      detailDialogVisible.value = true
      return
    }
    const batches = await getDeployBatches() as { id: number }[]
    for (const batch of batches) {
      const detail = await getDeployBatch(batch.id)
      if ((detail.items || []).some((it: { id: number }) => it.id === taskId)) {
        currentTask.value = detail
        detailDialogVisible.value = true
        return
      }
    }
  } catch {
    /* 拦截器已提示 */
  }
}

watch(
  () => route.query.task_id,
  () => { void openTaskDeepLink() },
)

onMounted(async () => {
  await loadDevices()
  loadTasks()
  loadTemplates()
  const tab = String(route.query.tab || '')
  if (tab === 'tasks' || tab === 'templates') activeTab.value = tab
  const qid = Number(route.query.device_id || labCtx.device?.id || 0)
  prefillDevice(qid || null)
  refreshDraftState()
  maybeAutoLoadDraft()
  await openTaskDeepLink()
  window.addEventListener('deploy-ai-draft', onAiDraftEvent as EventListener)
  window.addEventListener('deploy-ai-device', onAiDeviceEvent as EventListener)
  useAutoRefresh(loadTasks, 20000)
})

onUnmounted(() => {
  window.removeEventListener('deploy-ai-draft', onAiDraftEvent)
  window.removeEventListener('deploy-ai-device', onAiDeviceEvent as EventListener)
})
</script>

<style scoped>
.deploy-actions :deep(.el-form-item__content) { display:flex;gap:10px;flex-wrap:wrap }
.deploy-actions :deep(.el-button + .el-button) { margin-left:0 }

.deploy-center {
  min-height: 100%;
  display: flex;
  flex-direction: column;
}
.deploy-form{width:100%;max-width:1100px;display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,380px),1fr));column-gap:18px}
.deploy-form>.el-form-item:nth-child(n+3){grid-column:1/-1}
.deploy-form :deep(.el-form-item__content){min-width:0}
.static-validation { max-width: 1100px; margin-top: 12px; overflow-wrap: anywhere; }
.static-validation p, .static-validation li { line-height: 1.6; }
.deploy-center :deep(.el-tabs) {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.deploy-center :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
/* 流程步进与「下一步」提示（用户反馈"点很多按钮不知点哪个"） */
.deploy-steps { margin: 10px 0 6px; }
.deploy-steps :deep(.el-step__title) { font-size: 11px; line-height: 1.4; }
.next-hint { color: var(--v7b-warn); font-size: 12px; line-height: 1.6; }
.link-row { margin-top: 8px; display: flex; gap: 4px; flex-wrap: wrap; }
.verify-block { margin-top: 12px; }
.verify-block .block-title { margin-bottom: 4px; color: var(--v7b-muted); font-size: 11px; }
.verify-pre {
  margin: 0;
  padding: 10px;
  max-height: 220px;
  overflow: auto;
  border: 1px solid #273444;
  border-radius: 4px;
  background: #0d151e;
  color: #c5d4e0;
  font-size: 12px;
  white-space: pre-wrap;
}
.verify-tip { margin: 12px 0 0; color: var(--v7b-muted); font-size: 11.5px; line-height: 1.6; }
</style>
