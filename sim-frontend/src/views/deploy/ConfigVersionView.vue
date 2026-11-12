<template>
  <div class="config-management v7b-page">
    <el-alert v-if="deviceLoadError" :title="deviceLoadError" type="error" :closable="false" show-icon><el-button @click="loadDevices">重试设备列表</el-button></el-alert>
    <el-card>
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <span>配置管理</span>
          <el-button @click="$router.push({ path: '/deploy', query: { tab: 'tasks' } })">返回下发</el-button>
        </div>
      </template>
      <el-tabs v-model="activeTab" @tab-change="handleTabChange">
        <el-tab-pane label="配置快照" name="snapshots">
          <el-alert v-if="versionLoadError" :title="versionLoadError" type="error" :closable="false" show-icon><el-button @click="loadVersions">重试快照列表</el-button></el-alert>
          <div class="toolbar">
            <el-button @click="openDeviceSelector">选择采集设备（{{ selectedDeviceIds.length }}）</el-button>
            <el-button @click="selectAllDevices">全量设备</el-button>
            <span v-if="selectedDeviceIds.length" class="selection-tip">已选 {{ selectedDeviceIds.length }} 台设备，确认后采集并保存其当前配置。</span>
            <el-button type="primary" :disabled="!selectedDeviceIds.length" :loading="capturing" @click="handleCapture">采集并保存配置</el-button>
            <el-button :disabled="!snapshotSelection.length" @click="handleExportSnapshots">导出已选快照</el-button>
          </div>
          <el-alert title="采集只执行 display current-configuration，不会下发任何配置。" type="info" :closable="false" show-icon />
          <RecordOriginFilter v-model="originFilter" :records="versions" :unavailable="!!versionLoadError" />
          <el-table ref="snapshotTable" :data="visibleVersions" v-loading="loading" class="table" @selection-change="snapshotSelection = $event">
            <template #empty>
              <el-empty :description="versionLoadError || (versions.length?'当前来源筛选没有匹配快照，可恢复全部来源。':'暂无配置快照。请先选择采集设备，再点「采集并保存配置」。')" :image-size="72">
                <el-button v-if="!versions.length && !versionLoadError" type="primary" @click="openDeviceSelector">选择采集设备</el-button>
              </el-empty>
            </template>
            <el-table-column type="selection" width="48" />
            <el-table-column prop="version_number" label="版本" width="80" />
            <el-table-column label="设备" min-width="130"><template #default="{ row }">{{ deviceName(row.device_id) }}</template></el-table-column>
            <el-table-column prop="device_id" label="设备 ID" width="88" />
            <el-table-column label="来源" width="130"><template #default="{row}">{{ configSourceLabel(row.source) }}</template></el-table-column>
            <el-table-column prop="change_description" label="说明" show-overflow-tooltip />
            <el-table-column label="采集时间" width="180"><template #default="{row}">{{ formatApiTime(row.created_at) }}</template></el-table-column>
            <el-table-column label="操作" width="220"><template #default="{ row }">
              <el-button type="primary" link @click="openSnapshot(row)">查看</el-button>
              <el-button type="success" link @click="exportSnapshot(row)">导出</el-button>
              <el-button type="warning" link @click="openCompare(row)">比对</el-button>
              <el-button type="danger" link :loading="rollbackingId === row.id" @click="createRollback(row)">回滚</el-button>
            </template></el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="配置差异比对" name="compare">
          <div class="toolbar">
            <div class="snapshot-pair">
              <label>快照 A<el-select v-model="compareVersion1" aria-label="快照 A" placeholder="选择快照 A" clearable><el-option v-for="v in versions" :key="v.id" :label="snapshotLabel(v)" :value="v.id" /></el-select></label>
              <label>快照 B<el-select v-model="compareVersion2" aria-label="快照 B" placeholder="选择快照 B" clearable><el-option v-for="v in versions" :key="v.id" :label="snapshotLabel(v)" :value="v.id" /></el-select></label>
            </div>
            <el-button type="primary" :loading="comparing" :disabled="!compareVersion1 || !compareVersion2 || compareVersion1 === compareVersion2" @click="compareSnapshots">比对快照</el-button>
            <el-button :disabled="!diffResult" @click="exportDiff">导出差异</el-button>
            <el-button
              type="warning"
              :disabled="!compareVersion1 || !compareVersion2 || compareVersion1 === compareVersion2"
              :loading="explaining"
              @click="explainDiff"
            >AI 说明差异</el-button>
          </div>
          <el-alert v-if="compareError" :title="compareError" type="warning" :closable="false" show-icon />
          <el-alert v-if="explanationError" :title="explanationError" type="warning" :closable="false" show-icon />
          <el-card v-if="diffExplanation" shadow="never" class="ai-diff-card">
            <template #header>AI 差异说明（已脱敏，仅供参考）</template>
            <p class="summary-line">{{ diffExplanation.summary }}</p>
            <p v-if="diffExplanation.explanation" class="summary-line">{{ diffExplanation.explanation }}</p>
            <p v-if="diffExplanation.text_excerpt_truncated" class="summary-line">AI 仅解释了截断片段；完整文本请在下方 A/B 视图核对。</p>
            <div v-if="diffExplanation.key_findings?.length" class="summary-block">
              <div class="block-title">变更要点</div>
              <ul><li v-for="(item, idx) in diffExplanation.key_findings" :key="`dk-${idx}`">{{ item }}</li></ul>
            </div>
            <div v-if="diffExplanation.recommendations?.length" class="summary-block">
              <div class="block-title">风险与建议</div>
              <ul><li v-for="(item, idx) in diffExplanation.recommendations" :key="`dr-${idx}`">{{ item }}</li></ul>
            </div>
            <pre v-if="diffExplanation.report_text" class="result">{{ diffExplanation.report_text }}</pre>
          </el-card>
          <details class="local-files-entry"><summary>本地 A / B 文件比对（不上传）</summary>
          <el-card shadow="never" class="local-compare">
            <template #header>本地 A / B 配置文件比对（仅本次浏览器会话，不上传文件）</template>
            <div class="local-files">
              <label>配置 A<input type="file" aria-label="本地配置文件 A" accept=".txt,.cfg,.conf" @change="readLocalFile($event, 'left')" /><small>{{ localLeftName || '尚未选择文件' }}</small></label>
              <label>配置 B<input type="file" aria-label="本地配置文件 B" accept=".txt,.cfg,.conf" @change="readLocalFile($event, 'right')" /><small>{{ localRightName || '尚未选择文件' }}</small></label>
            </div>
            <el-button class="local-compare-action" :disabled="!localLeftName || !localRightName" @click="compareLocalFiles">比对本地文件</el-button>
          </el-card>
          </details>
          <ConfigTextDiff v-if="diffResult?.version1 && diffResult?.version2" :left="diffResult.version1.config_snapshot || ''" :right="diffResult.version2.config_snapshot || ''" :left-label="comparisonLabel(diffResult.version1)" :right-label="comparisonLabel(diffResult.version2)" :different-devices="diffResult.same_device === false" :legacy="diffResult.diff" />
          <ConfigTextDiff v-if="localDiff" :left="localDiff.left" :right="localDiff.right" :left-label="localDiff.leftName" :right-label="localDiff.rightName" />
        </el-tab-pane>

        <el-tab-pane label="配置变更日志" name="logs">
          <el-alert v-if="logLoadError" :title="logLoadError" type="error" :closable="false" show-icon />
          <div class="toolbar"><el-input v-model="logTaskId" placeholder="按任务项 ID 筛选" clearable style="width: 220px" /><el-button @click="loadLogs">查询</el-button></div>
          <el-table :data="logs" v-loading="logsLoading">
            <template #empty>
              <el-empty :description="logLoadError || '暂无配置变更日志。'" :image-size="72" />
            </template>
            <el-table-column prop="task_id" label="任务项" width="100" />
            <el-table-column label="操作" min-width="160"><template #default="{row}">{{ auditActionLabel(row.action) }}</template></el-table-column>
            <el-table-column prop="result" label="结果" width="110" />
            <el-table-column prop="detail" label="摘要" show-overflow-tooltip />
            <el-table-column label="时间" width="190"><template #default="{row}">{{ formatApiTime(row.created_at) }}</template></el-table-column>
            <el-table-column label="操作" width="110"><template #default="{ row }"><el-button type="primary" link @click="openChangeDetail(row)">查看变更</el-button></template></el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <el-dialog v-model="viewDialogVisible" class="v7b-record-dialog" top="4vh" title="配置快照" width="min(900px, 92vw)" draggable>
      <el-descriptions :column="2" border><el-descriptions-item label="版本">{{ currentVersion?.version_number }}</el-descriptions-item><el-descriptions-item label="设备">{{ deviceName(currentVersion?.device_id) }}</el-descriptions-item><el-descriptions-item label="来源">{{ configSourceLabel(currentVersion?.source) }}</el-descriptions-item><el-descriptions-item label="时间">{{ formatApiTime(currentVersion?.created_at) }}</el-descriptions-item></el-descriptions>
      <pre class="snapshot-content">{{ currentVersion?.config_snapshot }}</pre>
    </el-dialog>

    <el-dialog v-model="changeDialogVisible" class="v7b-record-dialog" top="4vh" title="配置变更详情" width="min(960px, 94vw)" draggable @close="changeEpoch++">
      <el-skeleton :loading="changeLoading" animated>
        <template #default>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="任务项">{{ changeTask?.id }}</el-descriptions-item><el-descriptions-item label="设备">{{ deviceName(changeTask?.device_id) }}</el-descriptions-item>
            <el-descriptions-item label="状态">{{ taskStatusLabel(changeTask?.status) }}</el-descriptions-item><el-descriptions-item label="执行引擎">{{ changeTask?.engine }}</el-descriptions-item>
            <el-descriptions-item label="执行模式">{{ executionModeLabel(changeTask?.execution_mode) }}</el-descriptions-item><el-descriptions-item label="记录时间">{{ formatApiTime(changeLog?.created_at) }}</el-descriptions-item>
            <el-descriptions-item label="原始动作码" :span="2">{{ changeLog?.action }}</el-descriptions-item>
          </el-descriptions>
          <h4>本次下发脚本</h4><pre class="snapshot-content">{{ changeTask?.config_content || '无' }}</pre>
          <template v-if="changeTask?.result_output"><h4>设备回读结果</h4><pre class="snapshot-content">{{ changeTask.result_output }}</pre></template>
          <template v-if="changeTask?.error_message"><h4>执行失败原因</h4><pre class="snapshot-content">{{ changeTask.error_message }}</pre></template>
          <template v-if="changeTask?.verify_diff"><h4>校验差异</h4><pre class="snapshot-content">{{ changeTask.verify_diff }}</pre></template>
          <template v-if="changeTask?.backup_config && changeTask?.result_output"><h4>同一任务的执行前备份与回读</h4><ConfigTextDiff :left="changeTask.backup_config" :right="changeTask.result_output" :left-label="`${deviceName(changeTask.device_id)} · 任务 #${changeTask.id} 执行前`" :right-label="`${deviceName(changeTask.device_id)} · 同任务回读`" /></template>
          <el-alert v-else title="该任务未同时保存执行前备份与回读；不采用时间相邻的其他快照代替。" type="info" :closable="false" show-icon />
        </template>
      </el-skeleton>
    </el-dialog>

    <el-dialog v-model="deviceDialogVisible" class="v7b-record-dialog" top="4vh" title="选择需要保存配置的设备" width="min(860px, 94vw)" draggable>
      <el-alert title="仅采集所勾选设备的运行配置；采集过程不会下发配置。" type="info" :closable="false" show-icon />
      <div class="toolbar"><el-button @click="selectAllPending">全选</el-button><el-button @click="clearPending">取消全选</el-button></div>
      <el-table ref="deviceTableRef" :data="devices" row-key="id" max-height="420" @selection-change="updatePendingDevices">
        <el-table-column type="selection" reserve-selection width="55" />
        <el-table-column prop="hostname" label="设备名称" min-width="180" />
        <el-table-column prop="mgmt_ip" label="管理地址" min-width="160" />
        <el-table-column prop="status" label="状态" width="120" />
        <el-table-column prop="model" label="型号" min-width="140" />
      </el-table>
      <template #footer><el-button @click="deviceDialogVisible = false">取消</el-button><el-button type="primary" @click="confirmDevices">确定选择（{{ pendingDeviceIds.length }}）</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus/es/components/message/index'
import { ElMessageBox } from 'element-plus/es/components/message-box/index'
import { getDevices, type DeviceRecord } from '../../api/device'
import { captureConfigVersions, compareVersions, createRollbackTask, getConfigVersions, getDeployChangeLogs, getDeployTask, type ConfigVersionRecord } from '../../api/deploy'
import { diffExplanation as diffExplanationApi } from '../../api/ai'
import { notifyRequestError } from '../../utils/requestError'
import ConfigTextDiff from '../../components/ConfigTextDiff.vue'
import RecordOriginFilter from '../../components/RecordOriginFilter.vue'
import {filterByRecordOrigin} from '../../utils/recordOrigin'
import { formatApiTime } from '../../utils/datetime'
import { taskStatusLabel, configSourceLabel, auditActionLabel, executionModeLabel } from '../../utils/display'
import { buildConfigDiff } from '../../utils/configTextDiff'
import { useSnapshotRequest } from '../../composables/useSnapshotRequest'

const route = useRoute()
const router = useRouter()
const activeTab = ref(String(route.query.tab || 'snapshots'))
const devices = ref<DeviceRecord[]>([])
const deviceRequest = useSnapshotRequest('设备列表')
const deviceLoadError = deviceRequest.error
const versions = ref<ConfigVersionRecord[]>([])
const originFilter=ref('all')
const visibleVersions=computed(()=>filterByRecordOrigin(versions.value,originFilter.value))
const snapshotTable=ref<any>(null)
watch(originFilter,()=>{snapshotSelection.value=[];snapshotTable.value?.clearSelection()})
const logs = ref<any[]>([])
const selectedDeviceIds = ref<number[]>([])
const pendingDeviceIds = ref<number[]>([])
const snapshotSelection = ref<ConfigVersionRecord[]>([])
const versionRequest = useSnapshotRequest('配置快照列表')
const loading = versionRequest.loading
const versionLoadError = versionRequest.error
const logRequest = useSnapshotRequest('配置变更日志')
const logsLoading = logRequest.loading
const logLoadError = logRequest.error
const capturing = ref(false)
const rollbackingId = ref<number | null>(null)
const logTaskId = ref(String(route.query.task_id || ''))
const viewDialogVisible = ref(false)
const currentVersion = ref<ConfigVersionRecord | null>(null)
const compareVersion1 = ref<number | null>(null)
const compareVersion2 = ref<number | null>(null)
const diffResult = ref<any>(null)
const diffExplanation = ref<any>(null)
const compareError=ref(''),explanationError=ref('')
const explaining = ref(false)
const comparing = ref(false)
let compareEpoch = 0, explanationEpoch = 0, changeEpoch = 0
const localLeft = ref('')
const localRight = ref('')
const localLeftName = ref(''), localRightName = ref('')
const localDiff = ref<any>(null)
const deviceDialogVisible = ref(false)
const deviceTableRef = ref<any>(null)
const changeDialogVisible = ref(false)
const changeLoading = ref(false)
const changeLog = ref<any>(null)
const changeTask = ref<any>(null)

const snapshotLabel = (v: ConfigVersionRecord) => `${deviceName(v.device_id)} · V${v.version_number} · ${formatApiTime(v.created_at)}`
const deviceName = (deviceId?: number) => devices.value.find(device => device.id === deviceId)?.hostname || `设备 ${deviceId || '未知'}`
const comparisonLabel = (v: any) => `${deviceName(v.device_id)} · V${v.version_number} · 快照 #${v.id}`
const downloadText = (filename: string, content: string) => { const link = document.createElement('a'); link.href = URL.createObjectURL(new Blob([content], { type: 'text/plain;charset=utf-8' })); link.download = filename; link.click(); URL.revokeObjectURL(link.href) }
const loadDevices = async () => { await deviceRequest.run(() => getDevices(), value => { devices.value = value }) }
const loadVersions = async () => { await versionRequest.run(() => getConfigVersions(), value => { versions.value = value }) }
const loadLogs = async () => { await logRequest.run(() => getDeployChangeLogs(logTaskId.value ? { task_id: Number(logTaskId.value) } : undefined), value => { logs.value = value as any[] }) }
const openChangeDetail = async (log: any) => {
  const epoch = ++changeEpoch
  changeDialogVisible.value = true; changeLoading.value = true; changeLog.value = log; changeTask.value = null
  try {
    const task = await getDeployTask(Number(log.task_id)); if(epoch !== changeEpoch)return; changeTask.value = task
  } catch (error) { if(epoch===changeEpoch)notifyRequestError(error, '加载配置变更详情失败') } finally { if(epoch===changeEpoch)changeLoading.value = false }
}
const openDeviceSelector = async () => { pendingDeviceIds.value = [...selectedDeviceIds.value]; deviceDialogVisible.value = true; await nextTick(); devices.value.forEach(device => deviceTableRef.value?.toggleRowSelection(device, pendingDeviceIds.value.includes(device.id))) }
const updatePendingDevices = (selected: any[]) => { pendingDeviceIds.value = selected.map(device => device.id) }
const selectAllPending = () => devices.value.forEach(device => deviceTableRef.value?.toggleRowSelection(device, true))
const clearPending = () => deviceTableRef.value?.clearSelection()
const confirmDevices = () => { selectedDeviceIds.value = [...pendingDeviceIds.value]; deviceDialogVisible.value = false }
const selectAllDevices = () => { selectedDeviceIds.value = devices.value.map(device => device.id); ElMessage.success(`已选择全部 ${selectedDeviceIds.value.length} 台设备`) }
const handleCapture = async () => { capturing.value = true; try { const result: any[] = await captureConfigVersions(selectedDeviceIds.value); ElMessage.success(`已保存 ${result.length} 个配置快照`); await loadVersions() } catch (error: any) { notifyRequestError(error, '配置采集失败') } finally { capturing.value = false } }
const openSnapshot = (version: ConfigVersionRecord) => { currentVersion.value = version; viewDialogVisible.value = true }
/** B2：回滚不直接执行 —— 生成一个高风险回滚任务，人工确认后才走受控执行/验证链路。 */
const createRollback = async (version: ConfigVersionRecord) => {
  try {
    await ElMessageBox.confirm(
      `将用快照 #${version.id}（${deviceName(version.device_id)} v${version.version_number}）生成一个高风险回滚任务。`
      + '任务需要人工确认后才会执行，不会立即改动设备。是否继续？',
      '回滚到该版本',
      { type: 'warning', confirmButtonText: '生成回滚任务', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  rollbackingId.value = version.id
  try {
    const result = await createRollbackTask(version.id) as any
    ElMessage.success(`已生成回滚任务 #${result.task_id}，请在变更审批页确认执行`)
    router.push('/approvals')
  } catch (error) {
    notifyRequestError(error, '生成回滚任务失败')
  } finally {
    rollbackingId.value = null
  }
}
const exportSnapshot = (version: ConfigVersionRecord) => downloadText(`config-snapshot-${version.device_id}-v${version.version_number}.txt`, version.config_snapshot || '')
const handleExportSnapshots = () => snapshotSelection.value.forEach(exportSnapshot)
const openCompare = (version: ConfigVersionRecord) => { activeTab.value = 'compare'; compareVersion1.value = version.id; compareVersion2.value = null; diffResult.value = null }
const compareSnapshots = async () => {
  if (!compareVersion1.value || !compareVersion2.value) return ElMessage.warning('请选择两个快照')
  const a=compareVersion1.value,b=compareVersion2.value,epoch=++compareEpoch
  comparing.value=true;diffResult.value=null;diffExplanation.value=null;compareError.value='';explanationError.value=''
  try { const result=await compareVersions(a,b); if(epoch===compareEpoch)diffResult.value=result }
  catch(error){if(epoch===compareEpoch){compareError.value='配置快照比对失败，请保留当前选择并重试。';notifyRequestError(error,'配置快照比对失败')}}
  finally{if(epoch===compareEpoch)comparing.value=false}
}
/** B5：AI 差异说明（后端只把脱敏后的差异行送进模型） */
const explainDiff = async () => {
  if (!compareVersion1.value || !compareVersion2.value) return ElMessage.warning('请选择两个快照')
  explaining.value = true
  explanationError.value=''
  const epoch = ++explanationEpoch
  try {
    const result = await diffExplanationApi(compareVersion1.value, compareVersion2.value)
    if (epoch === explanationEpoch) diffExplanation.value = result
  } catch (error) {
    if (epoch === explanationEpoch) {explanationError.value='AI 差异说明生成失败；当前快照和文本差异保留，可重试。';notifyRequestError(error, 'AI 差异说明生成失败')}
  } finally {
    if (epoch === explanationEpoch) explaining.value = false
  }
}
const exportDiff = () => downloadText('config-diff.json', JSON.stringify({scope:'display_text_only',version1:diffResult.value?.version1?.id,version2:diffResult.value?.version2?.id,same_device:diffResult.value?.same_device,display:buildConfigDiff(diffResult.value?.version1?.config_snapshot||'',diffResult.value?.version2?.config_snapshot||''),legacy_diff:diffResult.value?.diff}, null, 2))
let leftFileEpoch=0,rightFileEpoch=0
const readLocalFile = async (event: Event, side: 'left' | 'right') => {
  const file=(event.target as HTMLInputElement).files?.[0];if(!file)return
  const token=side==='left'?++leftFileEpoch:++rightFileEpoch
  localDiff.value=null
  if(side==='left'){localLeft.value='';localLeftName.value=''}else{localRight.value='';localRightName.value=''}
  if(file.size>2*1024*1024)return ElMessage.warning('本地文件超过2MB，请先选取需要核对的配置片段')
  try{const text=await file.text();if(token!==(side==='left'?leftFileEpoch:rightFileEpoch))return;if(side==='left'){localLeft.value=text;localLeftName.value=file.name}else{localRight.value=text;localRightName.value=file.name}}
  catch(error){notifyRequestError(error,'本地文件读取失败')}
}
const compareLocalFiles = () => { localDiff.value={left:localLeft.value,right:localRight.value,leftName:localLeftName.value,rightName:localRightName.value} }
watch([compareVersion1,compareVersion2],()=>{compareEpoch++;explanationEpoch++;diffResult.value=null;diffExplanation.value=null;compareError.value='';explanationError.value='';comparing.value=false;explaining.value=false},{flush:'sync'})
const handleTabChange = (tab: string | number) => { if (tab === 'logs') loadLogs() }
watch(() => route.query.tab, (tab) => {
  if (tab) activeTab.value = String(tab)
  if (String(tab) === 'logs') loadLogs()
})
onMounted(async () => { await Promise.all([loadDevices(), loadVersions()]); if (activeTab.value === 'logs') loadLogs() })
</script>

<style scoped>
.config-management {
  --el-text-color-primary: var(--v7b-text);
  --el-text-color-regular: var(--v7b-muted);
  --el-border-color: var(--v7b-line);
  --el-border-color-light: var(--v7b-line);
  --el-border-color-lighter: var(--v7b-line);
  --el-fill-color-light: var(--v7b-surface-2);
  min-height: 100%;
  display: flex;
  flex-direction: column;
}
.config-management :deep(.el-card) {
  border-color: var(--v7b-line);
  box-shadow: none;
  flex: 1;
  display: flex;
  flex-direction: column;
}
.config-management :deep(.el-card__body) {
  flex: 1;
  min-height: 0;
}
.toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }
.snapshot-pair{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr));gap:12px;width:100%}.snapshot-pair label{display:grid;gap:6px;min-width:0;color:var(--v7b-muted);font-size:12px}.local-files-entry{margin:14px 0}.local-files-entry summary{cursor:pointer;color:var(--v7b-accent);font-size:13px;line-height:1.8}
.toolbar :deep(.el-button + .el-button) { margin-left: 0; }
.config-management :deep(.el-button:not(.el-button--primary):not(.el-button--warning):not(.el-button--danger):not(.el-button--success):not(.is-link)) { background: #fff; color: var(--v7b-text); border-color: var(--v7b-line); }
.config-management :deep(.el-button.is-disabled) { color: #778396; background: var(--v7b-surface-2); }
.selection-tip { color: var(--v7b-muted); }
.table { margin-top: 16px; }
.local-compare { margin: 16px 0; }
.local-files { display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr));gap:16px; }
.local-files label { display:flex;flex-direction:column;gap:8px;min-width:0;font-size:13px; }
.local-files input { width:100%;min-width:0; }
.local-files small { overflow-wrap:anywhere;color:var(--v7b-muted); }
.local-compare-action { margin-top:14px; }
.result, .snapshot-content { margin-top: 16px; padding: 12px; background: var(--v7b-surface-2); border: 1px solid var(--v7b-line); border-radius: 4px; max-height: 420px; overflow: auto; white-space: pre-wrap; color: var(--v7b-text); }
.ai-diff-card { margin-top: 14px; }
.ai-diff-card .summary-line { margin: 0 0 8px; color: var(--v7b-text); font-size: 13px; }
.ai-diff-card .summary-block { margin-bottom: 8px; }
.ai-diff-card .block-title { margin-bottom: 4px; color: var(--v7b-muted); font-size: 11px; }
.ai-diff-card ul { margin: 0; padding-left: 18px; }
.ai-diff-card li { font-size: 12px; line-height: 1.7; }
h4 { margin: 18px 0 8px; }
</style>
