<template>
  <div class="deploy-center v7b-page">
    <PageHeader
      title="配置下发"
      subtitle="选择设备并准备配置。提交后到「变更审批」核对并确认，再执行和查看验证结果。"
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
          <el-alert v-if="drafts.deploy.submitError" class="draft-alert" :title="drafts.deploy.submitError" type="warning" :closable="false" show-icon>
            <el-button link type="primary" @click="showBatchList">查看配置批次</el-button>
          </el-alert>
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
            <el-button type="primary" @click="handleDeploy" :loading="drafts.deploy.submitting">提交待确认</el-button>
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
            <el-button link @click="viewDraftVersions">查看配置版本</el-button>
            <el-button
              v-if="labCtx.hasLab && labCtx.sessionId"
              link
              @click="$router.push({ path: '/training', query: { session_id: String(labCtx.sessionId) } })"
            >返回实训</el-button>
          </el-form-item>
          <div v-if="hasDraft || savedDraft" class="draft-lifetime" aria-label="草稿暂存">
            <p v-if="savedDraft">
              {{ formatApiTime(new Date(savedDraft.savedAt).toISOString()) }} 已暂存
              · {{ draftSaved ? '与当前内容一致' : '可恢复上次暂存内容' }}
            </p>
            <p v-else>可为当前账号在此标签页暂存配置，刷新或登录过期后可恢复。</p>
            <el-button link type="primary" :disabled="!hasDraft || draftSaved || drafts.deploy.submitting" @click="saveCurrentDraft">暂存草稿</el-button>
            <el-button v-if="savedDraft" link type="primary" :disabled="draftSaved || drafts.deploy.submitting" @click="restoreLocalDraft">恢复暂存草稿</el-button>
            <el-button v-if="savedDraft" link :disabled="drafts.deploy.submitting" @click="forgetLocalDraft">清除暂存</el-button>
            <small>保留 2 小时，主动退出时清除。暂存适用于无口令、密钥的配置。</small>
          </div>
        </el-form>
        <el-card v-if="staticValidation" class="static-validation" shadow="never" aria-label="静态校验结果">
          <template #header>静态校验结果 · {{ staticValidation.model }} · 未执行</template>
          <el-alert v-if="staticValidationStale" title="配置内容或目标已变化，这份结果仅对应先前输入，请重新校验。" type="warning" :closable="false" show-icon />
          <p v-if="!staticValidationStale">{{ staticValidation.result.valid ? '已覆盖的规则检查通过，可以继续提交变更。' : '请按下列提示修改配置，然后重新校验。' }}</p>
          <ul v-if="staticValidation.result.diagnostics?.length"><li v-for="(error,index) in staticValidation.result.diagnostics" :key="index"><el-button link type="primary" :disabled="staticValidationStale || !error.line_number" @click="focusConfigLine(error.line_number)">第 {{ error.line_number || '?' }} 行</el-button> {{ error.message }} <code>{{ error.command }}</code></li></ul>
          <ul v-else-if="staticValidation.result.errors?.length"><li v-for="(error, index) in staticValidation.result.errors" :key="index">{{ error }}</li></ul>
          <p v-if="staticValidation.result.coverage?.checked?.length">已检查：{{ staticValidation.result.coverage.checked.join('、') }}</p>
          <p v-if="staticValidation.result.coverage?.not_checked?.length">未检查：{{ staticValidation.result.coverage.not_checked.join('、') }}</p>
          <p>设备执行与回读结果可在「变更审批」中查看。</p>
        </el-card>
        <el-card v-if="aiGenerateResult" shadow="never" style="max-width: 800px; margin-top: 12px">
          <template #header>生成与校验结果</template>
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
      <el-tab-pane label="配置批次" name="tasks">
        <el-alert v-if="taskLoadError" :title="taskLoadError" type="error" :closable="false" show-icon><el-button @click="loadTasks">重试任务列表</el-button></el-alert>
        <RecordOriginFilter v-model="originFilter" :records="tasks" :unavailable="!!taskLoadError" />
        <el-table :data="visibleTasks" v-loading="tasksLoading">
          <template #empty>
            <el-empty :description="taskLoadError || (tasks.length ? '当前来源筛选没有匹配批次，可恢复全部来源。' : '暂无配置批次。提交变更后可在这里查看每台设备的进度。')" :image-size="72" />
          </template>
          <el-table-column prop="name" label="任务名称" min-width="200" show-overflow-tooltip />
          <el-table-column prop="source" label="来源" width="100" />
          <el-table-column label="设备任务" min-width="210">
            <template #default="{ row }">
              <span style="color: var(--v7b-muted); font-size: 12px">
                {{ batchStatusText(row.summary, row.phase_counts) }}
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
          <span>{{ batchStatusText(currentTask?.summary, currentTask?.phase_counts) }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatApiTime(currentTask?.created_at) }}</el-descriptions-item>
      </el-descriptions>
      <div v-for="item in currentTask?.items || []" :key="item.id" style="margin-top: 16px; border: 1px solid #273444; border-radius: 6px; padding: 12px">
        <div style="display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap">
          <h4 style="margin: 0">设备 {{ deviceName(item.device_id) }}（任务项 #{{ item.id }}）</h4>
          <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap">
            <el-tag :type="stageTagType(item.status)" size="small">{{ deployTaskStatusLabel(item.status, item.phase) }}</el-tag>
            <el-button v-if="['pending', 'awaiting_confirmation'].includes(item.status)" type="warning" size="small" :loading="actingTaskId === item.id" :disabled="!!actingTaskId && actingTaskId !== item.id" @click="handleTaskConfirmation(item)">确认变更</el-button>
            <el-button v-if="item.status === 'confirmed' && item.phase !== 'execution_blocked'" type="success" size="small" :loading="actingTaskId === item.id" :disabled="!!actingTaskId && actingTaskId !== item.id" @click="handleExecution(item)">执行</el-button>
            <el-button v-if="item.phase === 'awaiting_verification'" type="primary" size="small" :loading="actingTaskId === item.id" :disabled="!!actingTaskId && actingTaskId !== item.id" @click="handleVerification(item)">{{ item.execution_mode === 'simulated' ? '确认演练结果' : '核对回读' }}</el-button>
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
        <p class="next-hint" v-if="item.started_at || item.completed_at">
          开始 {{ formatApiTime(item.started_at) }} · 结束 {{ formatApiTime(item.completed_at) }}
        </p>
        <el-steps v-if="!['failed', 'rolled_back', 'cancelled'].includes(item.status)" :active="flowStageIndex(item.phase || item.status)" simple class="deploy-steps">
          <el-step v-for="name in DEPLOY_FLOW_STEPS" :key="name" :title="name" />
        </el-steps>
        <p class="next-hint">{{ deployNextAction(item.status, item.phase, item.execution_mode) }}</p>
        <pre style="background: #0d151e; color: #c5d4e0; padding: 12px; border-radius: 4px; max-height: 180px; overflow-y: auto; margin: 10px 0 0">{{ item.config_content }}</pre>
        <div v-if="item.status === 'success' || item.status === 'failed'" style="margin-top: 8px; color: var(--v7b-muted); font-size: 12px">
          <span v-if="item.status === 'success'">{{ item.execution_mode === 'real' ? '✅ 真实执行已完成；请核对回读与恢复状态。' : item.execution_mode === 'simulated' ? '✅ 模拟执行已完成（未改动设备）。' : '✅ 任务已完成，但执行模式未记录，不能推断是否改动了设备。' }}</span>
          <span v-else>❌ 任务失败{{ item.error_message ? `：${item.error_message}` : '' }}</span>
        </div>
        <!-- 失败时给出可点入口（后端已算好深链，此前前端从未渲染 → 学员不知道该去哪查） -->
        <div v-if="item.links && item.execution_mode" class="link-row">
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
import { notifyRequestError, requestErrorMessage } from '../../utils/requestError'
import { formatApiTime } from '../../utils/datetime'
import { deployNextAction, deployTaskStatusLabel, executionModeLabel, savedVerificationState } from '../../utils/display'
import RecordOriginFilter from '../../components/RecordOriginFilter.vue'
import { useSnapshotRequest } from '../../composables/useSnapshotRequest'
import {filterByRecordOrigin} from '../../utils/recordOrigin'
import { confirmWithRisk } from '../../utils/deployConfirmation'
import { ElMessageBox } from 'element-plus/es/components/message-box/index'
import { getDevices, type DeviceRecord } from '../../api/device'
import { generateAndValidate, reviewConfig } from '../../api/ai'
import { cancelDeployTask, confirmDeployTask, createDeployBatch, createTemplate, executeDeployTask, getDeployBatch, getDeployBatches, getDeployTask, getTemplates, renderTemplate, validateConfig, verifyDeployTask, type ConfigTemplateRecord, type DeployBatchRecord } from '../../api/deploy'
import { useLabContextStore } from '../../stores/labContext'
import { useAiCopilotStore } from '../../stores/aiCopilot'
import { accountStorageKey } from '../../stores/browserSession'
import {
  clearSavedDeployDraft, currentDraftOwner, deployDraftMatches, emptyDeployDraft,
  readSavedDeployDraft, saveDeployDraft, useWorkbenchDraftsStore,
} from '../../stores/workbenchDrafts'
import { useAutoRefresh } from '../../utils/autoRefresh'
import { resolveWorkbenchDeviceModel } from '../../utils/deviceModel'

const route = useRoute()
const router = useRouter()
const labCtx = useLabContextStore()
const copilot = useAiCopilotStore()
const drafts = useWorkbenchDraftsStore()
const activeTab = ref(deployTab(route.query.tab))
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

const deployForm = computed(() => drafts.deploy.form)
const aiIntent = computed({
  get: () => drafts.deploy.intent,
  set: (value: string) => { drafts.deploy.intent = value },
})
const hasDraft = computed(() => Boolean(deployForm.value.name.trim() || deployForm.value.device_ids.length || deployForm.value.config_content.trim() || aiIntent.value.trim()))
const draftOwner = currentDraftOwner()
const savedDraft = ref(readSavedDeployDraft(draftOwner))
const draftSaved = computed(() => deployDraftMatches(drafts.deploy, savedDraft.value))

function saveCurrentDraft() {
  try {
    savedDraft.value = saveDeployDraft(draftOwner, drafts.deploy)
    ElMessage.success('此标签页已暂存草稿')
  } catch (error) {
    ElMessage.warning(error instanceof Error && error.name !== 'QuotaExceededError' && error.name !== 'SecurityError'
      ? error.message : '浏览器无法暂存草稿。内容仍在编辑区。')
  }
}

function forgetLocalDraft() {
  clearSavedDeployDraft(draftOwner)
  savedDraft.value = null
}

async function restoreLocalDraft() {
  const saved = readSavedDeployDraft(draftOwner)
  savedDraft.value = saved
  if (!saved) {
    ElMessage.info('暂存已过期或当前账号没有可恢复的草稿')
    return
  }
  const draft = drafts.deploy
  const formAtClick = JSON.stringify(draft.form)
  const intentAtClick = draft.intent
  if (hasDraft.value && !await confirmDraftReplacement('暂存草稿')) return
  if (!viewActive || drafts.deploy !== draft || draft.submitting || formAtClick !== JSON.stringify(draft.form) ||
    intentAtClick !== draft.intent || readSavedDeployDraft(draftOwner)?.savedAt !== saved.savedAt) return
  drafts.deploy = {
    ...emptyDeployDraft(),
    form: { ...saved.form, device_ids: [...saved.form.device_ids] },
    intent: saved.intent,
  }
  aiGenerateResult.value = null
  aiReviewResult.value = null
  ElMessage.success('已恢复暂存草稿，可继续编辑或重新校验')
}
const aiGenerateLoading = ref(false)
const aiReviewLoading = ref(false)
const aiGenerateResult = ref<any>(null)
const aiReviewResult = ref<any>(null)
let viewActive = true

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

function deployTab(value: unknown) {
  return value === 'tasks' || value === 'templates' ? value : 'deploy'
}

function showBatchList() {
  activeTab.value = 'tasks'
  void loadTasks()
  void router.replace({ path: '/deploy', query: { tab: 'tasks' } })
}

function viewDraftVersions() {
  const [deviceId] = deployForm.value.device_ids
  const query: Record<string, string> = { from: 'draft' }
  if (deployForm.value.device_ids.length === 1) query.device_id = String(deviceId)
  void router.push({ path: '/config-versions', query })
}

// Record the submitted snapshot. Edits made while waiting belong to the next draft.
const handleDeploy = async () => {
  const draft = drafts.deploy
  if (draft.submitting) return
  if (!deployForm.value.device_ids.length) {
    ElMessage.warning('请选择目标设备')
    return
  }
  if (!deployForm.value.config_content.trim()) {
    ElMessage.warning('请输入配置内容')
    return
  }
  const submitted = JSON.stringify(draft.form)
  const intent = draft.intent
  const submissionPath = route.fullPath
  draft.submitting = true
  draft.submitError = ''
  let batch
  try {
    batch = await createDeployBatch({
      name: draft.form.name.trim() || `配置任务 ${new Date().toLocaleString()}`,
      source: 'manual', engine: draft.form.engine,
      items: draft.form.device_ids.map(device_id => ({ device_id, config_content: draft.form.config_content })),
    }, true)
  } catch (error) {
    draft.submitError = `草稿已保留。${requestErrorMessage(error, '提交结果暂未确认。')} 重试前可到「配置批次」确认是否已有这条记录。`
    return
  } finally {
    draft.submitting = false
  }
  if (drafts.deploy !== draft) return
  const unchanged = submitted === JSON.stringify(draft.form) && intent === draft.intent
  if (deployDraftMatches({ form: JSON.parse(submitted), intent }, readSavedDeployDraft(draftOwner))) forgetLocalDraft()
  ElMessage.success(unchanged ? '变更已提交，等待人工确认' : '上一份配置已提交。本次编辑仍在草稿中。')
  if (!unchanged) return
  drafts.deploy = emptyDeployDraft()
  aiGenerateResult.value = null
  aiReviewResult.value = null
  if (!viewActive || router.currentRoute.value.fullPath !== submissionPath || activeTab.value !== 'deploy') return
  const task = batch.items?.length === 1 ? batch.items[0] : undefined
  if (task) await router.push({ path: '/approvals', query: { task_id: String(task.id) } })
  else {
    activeTab.value = 'tasks'
    await router.push({ path: '/deploy', query: { tab: 'tasks', batch_id: String(batch.id) } })
    void loadTasks()
  }
}

const handleAiGenerate = async () => {
  if (aiGenerateLoading.value || drafts.deploy.submitting) return
  if (!aiIntent.value.trim()) {
    ElMessage.warning('请先填写 AI 需求描述')
    return
  }
  const draft = drafts.deploy
  const previous = JSON.stringify(draft.form)
  const intent = draft.intent
  aiGenerateLoading.value = true
  try {
    if (draft.form.config_content.trim() && !await confirmDraftReplacement('生成结果')) return
    if (!viewActive || drafts.deploy !== draft || JSON.stringify(draft.form) !== previous || intent !== draft.intent) return
    const res: any = await generateAndValidate({
      natural_language: intent,
      device_model: resolveValidateModel(),
    })
    if (!viewActive || drafts.deploy !== draft) return
    const commands = Array.isArray(res?.commands) ? res.commands.filter(Boolean) : []
    if (commands.length && (JSON.stringify(draft.form) !== previous || intent !== draft.intent || draft.submitting)) {
      ElMessage.info('生成期间草稿已变化，已保留你的编辑。需要替换时请重新生成。')
      return
    }
    aiGenerateResult.value = res
    if (commands.length) {
      draft.form.config_content = commands.join('\n')
      ElMessage.success('已填入配置草稿，核对后可提交变更')
    } else ElMessage.info('本次未生成配置命令，请查看生成结果')
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
const staticValidation = computed(() => drafts.deploy.validation)
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
  const draft = drafts.deploy
  validating.value = true
  try {
    const res = await validateConfig({
      config_content,
      device_model,
    })
    if (drafts.deploy === draft) draft.validation = { config: config_content, model: device_model, targets, result: res }
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

const stageTagType = (stage: string) => ({
  pending: 'warning', awaiting_confirmation: 'warning', deploying: 'primary', verifying: 'primary',
  success: 'success', failed: 'danger', cancelled: 'info', rolled_back: 'warning',
}[stage] || 'info') as '' | 'success' | 'warning' | 'info' | 'primary' | 'danger'

// ── 下发流程可视化（2026-10-05 用户反馈"得点很多个按钮，不知道下一步点哪个"）──
const DEPLOY_FLOW_STEPS = ['提交变更', '确认变更', '执行', '验证', '完成']
const flowStageIndex = (status: string) => ({
  pending: 1,
  awaiting_confirmation: 1,
  confirmed: 2,
  deploying: 2,
  executing: 2,
  execution_blocked: 2,
  execution_unconfirmed: 2,
  awaiting_verification: 3,
  verifying: 3,
  // success 要给 5：el-steps 的 active 是"当前进行到第几个"，给 4 会让第 5 步永远停在进行中
  success: 5,
  simulation_complete: 5,
  failed: 4,
  rolled_back: 4,
  cancelled: 4,
}[status] ?? 0)

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
    return '本次保存的是流程演练结果。实际配置和回读需要在已获准的设备环境中另行核对。'
  }
  if (report.verification === 'passed') return '回读内容与下发内容一致，这一步可以判定通过。'
  if (report.verification === 'failed') return '回读与下发内容存在差异。先查看「回读差异」，再到「配置版本」比对快照。'
  return ''
}

const goLink = (path: string) => {
  detailDialogVisible.value = false
  router.push(path)
}

const batchStatusText = (summary?: DeployBatchRecord['summary'], phases?: DeployBatchRecord['phase_counts']) => {
  if (!summary) return '批次汇总暂不可用'
  if (!summary.total) return '该批次没有设备任务'
  const labels = [
    ['待确认', summary.pending], ['待执行', Math.max(0, (summary.waiting ?? 0) - (phases?.execution_blocked ?? 0))],
    ['缺少执行锁', phases?.execution_blocked], ['执行或核对中', phases?.executing ?? summary.running],
    ['待核对', phases?.awaiting_verification], ['执行状态待确认', phases?.execution_unconfirmed],
    ['完成', summary.success], ['失败', summary.execution_failed],
    ['取消', summary.cancelled], ['回滚', summary.rolled_back],
  ] as const
  const counts = labels.filter(([, count]) => (count ?? 0) > 0).map(([label, count]) => `${label} ${count}`)
  return counts.join(' · ') || '展开详情查看各设备状态'
}

const batchNextHint = (row: DeployBatchRecord) => {
  const summary = row.summary || {}
  if ((summary.pending ?? 0) > 0) return `有 ${summary.pending} 台待确认 → 点「详情」确认下发`
  if ((summary.waiting ?? 0) > 0) return '有任务已确认。打开详情，核对设备后单独执行。'
  if ((summary.running ?? 0) > 0) return '打开详情跟进执行或回读核对。'
  if ((summary.execution_failed ?? 0) > 0) return '有任务失败，打开详情查看具体设备和原因。'
  if ((summary.rolled_back ?? 0) > 0) return '有任务已回滚，打开详情核对恢复结果。'
  if ((summary.success ?? 0) > 0) return '已完成 → 点「详情」查看验证结果'
  if ((summary.cancelled ?? 0) > 0) return '设备任务已取消，可查看明细。'
  return '—'
}

// 使用模板
const handleUseTemplate = async (template: ConfigTemplateRecord) => {
  const draft = drafts.deploy
  const content = draft.form.config_content
  if (draft.submitting) return
  if (content.trim() && content !== template.content && !await confirmDraftReplacement('模板内容')) return
  if (!viewActive || drafts.deploy !== draft || draft.form.config_content !== content || draft.submitting) return
  draft.form.config_content = template.content
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
const transferKey = accountStorageKey('copilot:transfer:')
const draftSavedAt = ref('')

function refreshDraftState() {
  draftAvailable.value = !!localStorage.getItem(transferKey + 'text')?.trim()
  const at = localStorage.getItem(transferKey + 'at')
  draftSavedAt.value = at ? new Date(Number(at)).toLocaleString('zh-CN', { hour12: false }) : ''
}

async function confirmDraftReplacement(source: string) {
  try {
    await ElMessageBox.confirm(`${source}将替换当前配置内容。请先保存需要保留的文字。`, '替换配置草稿', {
      type: 'warning', confirmButtonText: '替换', cancelButtonText: '保留当前草稿',
    })
    return true
  } catch { return false }
}

async function loadAiDraft() {
  const draft = localStorage.getItem(transferKey + 'text')
  const current = drafts.deploy
  if (!draft?.trim() || current.submitting) return
  const previous = JSON.stringify(current.form)
  if (hasDraft.value && !await confirmDraftReplacement('AI 草稿及其目标设备')) return
  if (!viewActive || drafts.deploy !== current || previous !== JSON.stringify(current.form) || current.submitting || localStorage.getItem(transferKey + 'text') !== draft) return
  // A loaded draft replaces the target selection, never adds to an old batch.
  // Legacy or mismatched metadata requires an explicit new selection.
  let targetId: number | null = null
  try {
    const context = JSON.parse(localStorage.getItem(transferKey + 'context') || 'null')
    const id = context?.target?.deviceId
    if (context?.text === draft && context?.target?.verifiedByServer === true && Number.isSafeInteger(id) && id > 0 && devices.value.some(d => d.id === id)) targetId = id
  } catch { /* Unbound legacy draft; clear stale target below. */ }
  deployForm.value.device_ids = targetId == null ? [] : [targetId]
  deployForm.value.config_content = draft
  activeTab.value = 'deploy'
  ElMessage.success(targetId == null ? '已载入 AI 草稿，请选择目标设备并核对配置' : '已载入 AI 草稿及原目标设备，请核对后再提交变更')
  refreshDraftState()
}

function maybeAutoLoadDraft() {
  if (route.path !== '/deploy' || route.query.draft !== '1') return
  if (!hasDraft.value) void loadAiDraft()
  else ElMessage.info('已有配置草稿。可点「载入草稿」查看并替换为 AI 草稿。')
  activeTab.value = 'deploy'
  const { draft: _draft, ...query } = route.query
  void router.replace({ path: '/deploy', query: { ...query, tab: 'deploy' } })
}

function clearAiDraft() {
  for (const key of ['text', 'at', 'context']) localStorage.removeItem(transferKey + key)
  ElMessage.success('配置草稿已清除')
  refreshDraftState()
}

function prefillDevice(id?: number | null, explicit = false) {
  if (!id || !devices.value.some(device => device.id === id) || deployForm.value.device_ids.includes(id)) return
  if (hasDraft.value || drafts.deploy.submitting) {
    if (explicit) ElMessage.info(`已保留草稿原有的目标设备。如需改为 ${deviceName(id)}，请在表单中选择并重新校验。`)
    return
  }
  if (explicit || !deployForm.value.device_ids.length) deployForm.value.device_ids = [id]
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
    if (route.path === '/deploy') activeTab.value = deployTab(tab)
  },
)

function onAiDraftEvent(ev: Event) {
  refreshDraftState()
  const autoLoad = Boolean((ev as CustomEvent).detail?.autoLoad)
  if (autoLoad) {
    activeTab.value = 'deploy'
    if (hasDraft.value) ElMessage.info('已有配置草稿。可点「载入草稿」查看并替换为 AI 草稿。')
    else void loadAiDraft()
  }
}

function onAiDeviceEvent(ev: Event) {
  const detail = (ev as CustomEvent).detail || {}
  prefillDevice(Number(detail.device_id || 0), true)
}

watch(
  () => route.query.draft,
  () => maybeAutoLoadDraft(),
)

let taskLinkEpoch = 0
async function openTaskDeepLink() {
  const epoch = ++taskLinkEpoch
  if (route.path !== '/deploy') return
  const taskId = Number(route.query.task_id)
  const batchId = Number(route.query.batch_id)
  if (!(taskId > 0 || batchId > 0)) return
  activeTab.value = 'tasks'
  try {
    if (batchId > 0) {
      const batch = await getDeployBatch(batchId)
      if (viewActive && epoch === taskLinkEpoch) {
        currentTask.value = batch
        detailDialogVisible.value = true
      }
      return
    }
    const item = await getDeployTask(taskId)
    if (!viewActive || epoch !== taskLinkEpoch) return
    if (item?.batch_id) {
      const batch = await getDeployBatch(item.batch_id)
      if (viewActive && epoch === taskLinkEpoch) {
        currentTask.value = batch
        detailDialogVisible.value = true
      }
      return
    }
    const batches = await getDeployBatches() as { id: number }[]
    for (const batch of batches) {
      const detail = await getDeployBatch(batch.id)
      if (!viewActive || epoch !== taskLinkEpoch) return
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
  () => [route.query.task_id, route.query.batch_id],
  () => { void openTaskDeepLink() },
)
watch(() => route.query.device_id, id => {
  if (route.path === '/deploy' && activeTab.value === 'deploy') prefillDevice(Number(id), true)
})

useAutoRefresh(loadTasks, 20000)

onMounted(async () => {
  await loadDevices()
  if (!viewActive) return
  loadTasks()
  loadTemplates()
  if (activeTab.value === 'deploy' && route.query.draft !== '1') {
    const qid = Number(route.query.device_id)
    prefillDevice(qid || labCtx.device?.id, Boolean(qid))
    syncDeploySelection()
  }
  refreshDraftState()
  maybeAutoLoadDraft()
  window.addEventListener('deploy-ai-draft', onAiDraftEvent as EventListener)
  window.addEventListener('deploy-ai-device', onAiDeviceEvent as EventListener)
  await openTaskDeepLink()
})

onUnmounted(() => {
  viewActive = false
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
.draft-alert { margin-bottom: 14px; }
.draft-lifetime { color: var(--v7b-muted); font-size: 12px; }
.draft-lifetime p { margin: 0 0 4px; }
.draft-lifetime small { display: block; margin-top: 4px; font-size: inherit; }
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
