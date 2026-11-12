<template>
  <div class="monitor-dashboard">
    <el-alert v-if="statsError" :title="statsError" type="error" :closable="false" show-icon />
    <!-- 顶部统计卡片 -->
    <el-row :gutter="16" style="margin-bottom: 16px">
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-value">{{ stats?.totalDevices ?? '—' }}</div>
            <div class="stat-label">设备总数</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-value" style="color: var(--v7b-ok)">{{ stats?.onlineDevices ?? '—' }}</div>
            <div class="stat-label">在线设备</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-value" style="color: var(--v7b-danger)">{{ stats?.activeAlarms ?? '—' }}</div>
            <div class="stat-label">活跃告警</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-value" style="color: var(--v7b-warn)">{{ stats?.warningAlarms ?? '—' }}</div>
            <div class="stat-label">警告告警</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 设备选择和采集触发 -->
    <el-card style="margin-bottom: 16px">
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px">
        <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap">
          <span>选择拓扑:</span>
          <el-select v-model="selectedTopology" placeholder="选择拓扑" style="width: 200px">
            <el-option v-for="t in topologies" :key="t.id" :label="t.name" :value="t.id" />
          </el-select>
          <AdminAction v-slot="{ disabled }">
            <el-button type="primary" :disabled="disabled || inspecting || !selectedTopology" @click="handleCollect" :loading="collecting">触发采集</el-button>
          </AdminAction>
          <AdminAction v-slot="{ disabled }">
            <el-button type="success" :disabled="disabled || collecting || !selectedTopology" @click="handleInspection" :loading="inspecting">触发巡检</el-button>
          </AdminAction>
        </div>
        <div>
          <el-button @click="refreshData()">刷新数据</el-button>
        </div>
      </div>
      <div v-if="collectHint" class="collect-hint">{{ collectHint }}</div>
      <div class="collect-hint">实时统计：{{ streamStatus }}；图表最近采样：{{ latestSampleTime }}。图表按设备展示历史采样，刷新不会触发采集。</div>
      <div class="collect-hint">统计与活跃告警覆盖全部拓扑；图表及巡检任务使用所选拓扑。</div>
      <el-alert v-if="topologyLoadError" :title="topologyLoadError" type="error" :closable="false" show-icon><el-button @click="loadTopologies">重试拓扑列表</el-button></el-alert>
      <el-alert v-if="chartError" :title="chartError" type="error" :closable="false" show-icon />
      <el-alert
        v-if="collectFailures.length"
        type="warning"
        :closable="true"
        show-icon
        style="margin-top: 8px"
        title="本轮采集未完整完成；下方图表可能包含历史数据，请核对采样时间"
        @close="collectFailures = []"
      >
        <template #default>
          <ul class="collect-fail-list">
            <li v-for="(item, idx) in collectFailures" :key="`cf-${idx}`">{{ item }}</li>
          </ul>
        </template>
      </el-alert>
      <el-alert
        v-if="!topologiesLoading && !topologies.length && !topologyLoadError"
        title="暂无可用拓扑，请先导入拓扑基线后再触发采集/巡检"
        type="info"
        :closable="false"
        show-icon
        style="margin-top: 12px"
      >
        <template #default>
          <el-button size="small" link type="primary" @click="$router.push('/topology')">去拓扑可视化</el-button>
        </template>
      </el-alert>
    </el-card>

    <MonitorPorts :topology-id="selectedTopology" />

    <el-alert
      v-if="selectedTopology && !chartsHaveData && !chartError && !topologyLoadError"
      title="趋势图来自手动刷新的采集结果，SSE 只更新上方统计和告警。无数据时请先点「触发采集」。"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 16px"
    />

    <!-- 图表区域 -->
    <el-row :gutter="16" style="margin-bottom: 16px">
      <el-col :span="12">
        <el-card>
          <template #header>CPU使用率趋势</template>
          <div ref="cpuChart" style="height: 300px"></div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>内存使用率趋势</template>
          <div ref="memoryChart" style="height: 300px"></div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <el-col :span="12">
        <el-card>
          <template #header>接口状态分布（各设备最近样本合计）</template>
          <div ref="interfaceChart" style="height: 300px"></div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>OSPF邻居数量</template>
          <div ref="ospfChart" style="height: 300px"></div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 最近告警 -->
    <el-card style="margin-top: 16px">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <span>最近告警</span>
          <el-button type="primary" link @click="$router.push('/alarms?status=active')">查看全部</el-button>
        </div>
      </template>
      <el-alert v-if="recentAlarmError" :title="recentAlarmError" type="error" :closable="false" show-icon />
      <el-table :data="recentAlarms">
        <template #empty>
          <el-empty :description="recentAlarmError || '暂无告警记录'" :image-size="72" />
        </template>
        <el-table-column prop="device_name" label="设备" width="140" />
        <el-table-column prop="device_id" label="设备ID" width="80" />
        <el-table-column prop="alarm_type" label="告警类型" width="150" />
        <el-table-column prop="severity" label="严重程度" width="100">
          <template #default="{ row }">
            <el-tag :type="getSeverityType(row.severity)">{{ getSeverityLabel(row.severity) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="告警信息" show-overflow-tooltip />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'fired' ? 'danger' : 'success'">{{ getAlarmStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="fired_at" label="触发时间" width="180" />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.device_id" type="primary" link @click="$router.push(`/webssh/${row.device_id}`)">终端</el-button>
            <el-button type="primary" link @click="$router.push('/alarms?status=active')">告警</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card style="margin-top: 16px">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <span>巡检任务</span>
          <span style="color: var(--el-text-color-secondary)">最近巡检与报告回看</span>
        </div>
      </template>
      <el-alert v-if="inspectionError" :title="inspectionError" type="error" :closable="false" show-icon />
      <el-table :data="inspectionTasks">
        <template #empty>
          <el-empty :description="inspectionError || '暂无巡检任务'" :image-size="72" />
        </template>
        <el-table-column prop="id" label="任务ID" width="80" />
        <el-table-column prop="job_type" label="类型" width="100">
          <template #default="{ row }">
            <el-tag>{{ getTaskTypeLabel(row.job_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getTaskStatusType(row.status)">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="success_count" label="成功" width="80" />
        <el-table-column prop="failure_count" label="失败" width="80" />
        <el-table-column label="跳过" width="80">
          <template #default="{ row }">{{ row.summary?.skipped ?? '—' }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="180" />
        <el-table-column label="报告摘要">
          <template #default="{ row }">
            <span v-if="row.report">{{ row.report.alarm_count }} 条告警，{{ (row.report.metric_types || []).length }} 类指标</span>
            <span v-else>无</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button
              type="primary"
              link
              :loading="summaryJobId === row.id"
              :disabled="row.status === 'running'"
              @click="handleAiSummary(row)"
            >AI 总结</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="aiSummaryVisible" :title="aiSummaryTitle" width="720px" draggable>
      <div v-if="aiSummary" class="ai-summary">
        <p class="summary-line">{{ aiSummary.summary }}</p>
        <div v-if="aiSummary.key_findings?.length" class="summary-block">
          <div class="block-title">关键发现</div>
          <ul><li v-for="(item, idx) in aiSummary.key_findings" :key="`kf-${idx}`">{{ item }}</li></ul>
        </div>
        <div v-if="aiSummary.root_causes?.length" class="summary-block">
          <div class="block-title">根因</div>
          <ul><li v-for="(item, idx) in aiSummary.root_causes" :key="`rc-${idx}`">{{ item }}</li></ul>
        </div>
        <div v-if="aiSummary.recommendations?.length" class="summary-block">
          <div class="block-title">处置建议</div>
          <ul><li v-for="(item, idx) in aiSummary.recommendations" :key="`rec-${idx}`">{{ item }}</li></ul>
        </div>
        <div v-if="aiSummary.report_text" class="summary-block">
          <div class="block-title">报告正文</div>
          <pre class="report-text">{{ aiSummary.report_text }}</pre>
        </div>
      </div>
      <template #footer><el-button @click="aiSummaryVisible = false">关闭</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { formatApiTime } from '../../utils/datetime'
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage } from 'element-plus/es/components/message/index'
import * as echarts from 'echarts/core'
import { LineChart, BarChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ECharts } from 'echarts/core'
import { getTopologies, type TopologyRecord } from '../../api/device'
import { getAlarms, getMonitorStats, getMonitorTasks, getMonitorTrends, triggerCollection, runInspection, createMonitorStream, type AlarmRecord, type MonitorStats, type MonitorTaskRecord, type MonitorTrend } from '../../api/monitor'
import { inspectionSummary } from '../../api/ai'
import { notifyRequestError } from '../../utils/requestError'
import { buildMonitorSeries } from '../../utils/monitorSeries'
import { useSnapshotRequest } from '../../composables/useSnapshotRequest'
import { severityLabel as getSeverityLabel, severityTagType as getSeverityType } from '../../utils/display'
import { useAiCopilotStore } from '../../stores/aiCopilot'
import { useLabContextStore } from '../../stores/labContext'
import AdminAction from '../../components/AdminAction.vue'
import MonitorPorts from '../../components/MonitorPorts.vue'

echarts.use([LineChart, BarChart, PieChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const copilot = useAiCopilotStore()
const labCtx = useLabContextStore()

const collecting = ref(false)
const inspecting = ref(false)
// 采集是同步阻塞请求：给出"采集中"进度提示与失败原因（避免用户反复点、以为没反应）
const collectHint = ref('')
const collectFailures = ref<string[]>([])
const selectedTopology = ref<number | null>(null)
const topologyRequest = useSnapshotRequest('监控拓扑列表')
const topologiesLoading = topologyRequest.loading
const topologyLoadError = topologyRequest.error
const statsRequest = useSnapshotRequest('监控统计')
const statsError = statsRequest.error
const recentAlarmRequest = useSnapshotRequest('最近告警列表')
const recentAlarmError = recentAlarmRequest.error
const inspectionError = ref('')
const topologies = ref<TopologyRecord[]>([])
const recentAlarms = ref<AlarmRecord[]>([])
const inspectionTasks = ref<MonitorTaskRecord[]>([])
const summaryJobId = ref<number | null>(null)
const aiSummaryVisible = ref(false)
const aiSummaryTitle = ref('巡检 AI 总结')
const aiSummary = ref<any>(null)
const trendData = ref<MonitorTrend>({ metrics: {}, alarms: [], summary: {} })
const chartError = ref('')
const streamStatus = ref('连接中')
const latestSampleTime = computed(() => {
  const samples = Object.values(trendData.value.metrics || {}).flat().map(point => point.time || '').filter(Boolean).sort()
  const value = samples[samples.length - 1]
  return value ? formatApiTime(value) : '暂无采样'
})
const chartsHaveData = computed(() => {
  const metrics = trendData.value?.metrics || {}
  return ['cpu_usage', 'memory_usage', 'interface_up', 'ospf_neighbor_count']
    .some((key) => Array.isArray(metrics[key]) && metrics[key].length > 0)
})

// 统计数据
const stats = ref<MonitorStats | null>(null)

// 图表引用
const cpuChart = ref<HTMLElement>()
const memoryChart = ref<HTMLElement>()
const interfaceChart = ref<HTMLElement>()
const ospfChart = ref<HTMLElement>()

// 图表实例
let cpuChartInstance: ECharts | null = null
let memoryChartInstance: ECharts | null = null
let interfaceChartInstance: ECharts | null = null
let ospfChartInstance: ECharts | null = null

// SSE连接（fetch 版，支持 Authorization 头；断线自动重连）
let sseHandle: { close: () => void } | null = null
let sseTimer: number | null = null
// 触发采集/巡检后的"稍后刷新"定时器：必须在卸载时清理，
// 否则离开页面后仍会发起 4 个请求并在失败时弹 Toast
let refreshTimer: number | null = null
let sseClosed = false
let chartReqSeq = 0
let inspectReqSeq = 0
let chartResizeHandler: (() => void) | null = null
let chartResizeObserver: ResizeObserver | null = null
let chartResizeFrame: number | null = null

// 加载拓扑列表
const loadTopologies = async () => {
  await topologyRequest.run(() => getTopologies(), value => {
    topologies.value = value
    if (!value.some(item => item.id === selectedTopology.value)) selectedTopology.value = value[0]?.id ?? null
  })
}

// 加载统计数据（silent 由调用方决定：manual=true 时用户主动刷新才提示错误）
const loadStats = async (silent = false) => {
  await statsRequest.run(() => getMonitorStats({ silent }), value => { stats.value = value })
}

// 加载最近告警
const loadRecentAlarms = async (silent = false) => {
  await recentAlarmRequest.run(() => getAlarms({ limit: 10, status: 'active' }, { silent }), value => { recentAlarms.value = value })
}

const loadInspectionTasks = async (silent = false) => {
  if (!selectedTopology.value) return
  const seq = ++inspectReqSeq
  try {
    const params = selectedTopology.value ? { topology_id: selectedTopology.value, job_type: 'inspection', limit: 10 } : { job_type: 'inspection', limit: 10 }
    const rows = await getMonitorTasks(params, { silent })
    if (seq !== inspectReqSeq) return
    inspectionTasks.value = rows
    inspectionError.value = ''
  } catch (err) {
    if (seq !== inspectReqSeq) return
    inspectionError.value = '巡检任务读取失败；已显示记录可能陈旧，请点「刷新数据」重试。'
    notifyRequestError(err, '加载巡检任务失败')
  }
}

// B5：对巡检/采集任务报告做 AI 归因总结
const handleAiSummary = async (row: MonitorTaskRecord) => {
  summaryJobId.value = row.id
  try {
    aiSummary.value = await inspectionSummary(row.id)
    aiSummaryTitle.value = `巡检 AI 总结 · 任务 #${row.id}`
    aiSummaryVisible.value = true
  } catch (err) {
    notifyRequestError(err, 'AI 总结生成失败')
  } finally {
    summaryJobId.value = null
  }
}

// 触发采集：后端是**同步**把所有设备采完才返回（可能几十秒），所以文案要说"采集中"，
// 并用返回值报出成功/失败台数（此前只说"已触发"，用户不知道到底采到没有）
const handleCollect = async () => {
  if (!selectedTopology.value) {
    ElMessage.warning('请选择拓扑')
    return
  }
  collecting.value = true
  collectHint.value = '采集中，逐台 SSH 读取指标，请稍候（约 10~60 秒）…'
  try {
    const res: any = await triggerCollection(selectedTopology.value)
    showCollectionResult(res, '采集')
    refreshTimer = window.setTimeout(refreshData, 500)
  } catch (error) {
    // 超时不代表没采到：后端可能仍在跑，仍然刷新一次
    collectHint.value = '采集请求未在超时前返回；后端可能仍在采集，稍后点「刷新数据」查看结果。'
    notifyRequestError(error, '触发采集失败')
    refreshTimer = window.setTimeout(refreshData, 3000)
  } finally {
    collecting.value = false
  }
}

const handleInspection = async () => {
  if (!selectedTopology.value) {
    ElMessage.warning('请选择拓扑')
    return
  }
  inspecting.value = true
  try {
    const res = await runInspection(selectedTopology.value)
    showCollectionResult(res, '巡检')
    refreshTimer = window.setTimeout(refreshData, 500)
  } catch (error) {
    notifyRequestError(error, '触发巡检失败')
    refreshTimer = window.setTimeout(refreshData, 3000)
  } finally {
    inspecting.value = false
  }
}

const showCollectionResult = (res: any, label: string) => {
  const summary = res?.summary || {}
  const detail = `${label}结束：目标 ${summary.expected ?? 0} 台，成功 ${summary.success ?? 0} 台，失败 ${summary.failed ?? 0} 台，跳过 ${summary.skipped ?? 0} 台`
  collectHint.value = detail
  collectFailures.value = summary.errors || []
  if (res?.task?.status === 'success') ElMessage.success(detail)
  else {
    if (!collectFailures.value.length) collectFailures.value = ['本轮没有完整的采集证据，请核对设备状态后重试。']
    ElMessage.warning(detail)
  }
}

// 刷新数据（silent=true 用于自动刷新：失败不弹 toast，否则一次刷新会叠 4 条）
const refreshData = (silent = false) => {
  loadStats(silent)
  loadRecentAlarms(silent)
  loadInspectionTasks(silent)
  loadChartData(silent)
}

// 加载图表数据
const loadChartData = async (silent = false) => {
  if (!selectedTopology.value) return
  const seq = ++chartReqSeq
  try {
    const params = selectedTopology.value ? { topology_id: selectedTopology.value } : undefined
    const trends = await getMonitorTrends(params, { silent })
    if (seq !== chartReqSeq) return
    trendData.value = trends
    chartError.value = ''
    updateCpuChart(trendData.value.metrics?.cpu_usage || [])
    updateMemoryChart(trendData.value.metrics?.memory_usage || [])
    updateInterfaceChart([
      { status: 'up', value: latestMetricValue(trendData.value.metrics?.interface_up || []) },
      { status: 'down', value: latestMetricValue(trendData.value.metrics?.interface_down || []) }
    ])
    updateOspfChart(trendData.value.metrics?.ospf_neighbor_count || [])
  } catch (err) {
    if (seq !== chartReqSeq) return
    notifyRequestError(err, '加载监控趋势失败')
    chartError.value = '趋势数据加载失败，已显示采样可能陈旧；请点「刷新数据」重试，不能据此判断设备当前正常。'
  }
}

const latestMetricValue = (series: any[]) => {
  const latest = new Map<number, { time: string; value: number }>()
  for (const point of series || []) {
    if (point.device_id == null || typeof point.value !== 'number' || !point.time) continue
    const previous = latest.get(point.device_id)
    if (!previous || point.time >= previous.time) latest.set(point.device_id, point)
  }
  return [...latest.values()].reduce((total, point) => total + point.value, 0)
}

// CPU / 内存 / OSPF 三个时序图表同构，共用一套 option 组装（P2-20）
const renderTimeSeries = (
  instance: ECharts | null,
  data: any[],
  options: { seriesType?: 'line' | 'bar'; max?: number } = {}
) => {
  if (!instance) return
  const { seriesType = 'line', max } = options
  instance.setOption({
    xAxis: { type: 'time' },
    yAxis: max === undefined ? { type: 'value' } : { type: 'value', max },
    legend: { type: 'scroll' },
    series: buildMonitorSeries(data).map(item=>({...item,type:seriesType})),
    tooltip: { trigger: 'axis' }
  }, { replaceMerge: ['series'] })
}

const updateCpuChart = (data: any[]) => renderTimeSeries(cpuChartInstance, data, { max: 100 })

const updateMemoryChart = (data: any[]) => renderTimeSeries(memoryChartInstance, data, { max: 100 })

// 更新接口图表
const updateInterfaceChart = (data: any[]) => {
  if (!interfaceChartInstance) return
  const up = data.find((d: any) => d.status === 'up')?.value ?? 0
  const down = data.find((d: any) => d.status === 'down')?.value ?? 0
  interfaceChartInstance.setOption({
    series: [{
      type: 'pie',
      data: [
        { name: 'Up', value: up },
        { name: 'Down', value: down }
      ]
    }],
    tooltip: { trigger: 'item' }
  })
}

const updateOspfChart = (data: any[]) => renderTimeSeries(ospfChartInstance, data, { seriesType: 'bar' })

const getTaskTypeLabel = (jobType: string) => ({ collection: '采集', inspection: '巡检' }[jobType] || jobType)
const getTaskStatusType = (status: string) => ({ success: 'success', failed: 'danger', running: 'warning', pending: 'info' }[status] || 'info')


const getAlarmStatusLabel = (status?: string) => {
  const map: Record<string, string> = {
    fired: '未处理',
    acknowledged: '已确认',
    resolved: '已解决',
    closed: '已关闭',
  }
  return (status && map[status]) || status || '-'
}

// 初始化图表
const initCharts = () => {
  cpuChartInstance?.dispose()
  memoryChartInstance?.dispose()
  interfaceChartInstance?.dispose()
  ospfChartInstance?.dispose()

  if (cpuChart.value) {
    cpuChartInstance = echarts.init(cpuChart.value)
  }
  if (memoryChart.value) {
    memoryChartInstance = echarts.init(memoryChart.value)
  }
  if (interfaceChart.value) {
    interfaceChartInstance = echarts.init(interfaceChart.value)
  }
  if (ospfChart.value) {
    ospfChartInstance = echarts.init(ospfChart.value)
  }
}

// 连接SSE
const connectSSE = () => {
  sseHandle?.close()
  const scheduleReconnect = () => {
    streamStatus.value = '已断开，正在重连（统计可能陈旧）'
    // 断线或服务端正常关闭后 5 秒重连（fetch 版没有 EventSource 的自动重连）
    if (!sseClosed && sseTimer === null) {
      sseTimer = window.setTimeout(() => {
        sseTimer = null
        connectSSE()
      }, 5000)
    }
  }
  sseHandle = createMonitorStream(
    (data) => {
      if (data.type === 'stats' && data.data) {
        streamStatus.value = '已连接'
        stats.value = data.data
      } else if (data.type === 'alarms' && Array.isArray(data.data)) {
        recentAlarms.value = data.data
      }
    },
    scheduleReconnect,
    scheduleReconnect,
  )
}

onMounted(() => {
  initCharts()
  loadTopologies()
  refreshData()
  connectSSE()
  chartResizeHandler = () => {
    if (chartResizeFrame !== null) return
    chartResizeFrame = requestAnimationFrame(() => {
      chartResizeFrame = null
      cpuChartInstance?.resize()
      memoryChartInstance?.resize()
      interfaceChartInstance?.resize()
      ospfChartInstance?.resize()
    })
  }
  chartResizeObserver = new ResizeObserver(chartResizeHandler)
  for (const element of [cpuChart.value, memoryChart.value, interfaceChart.value, ospfChart.value]) {
    if (element) chartResizeObserver.observe(element)
  }
  window.addEventListener('resize', chartResizeHandler)
})

watch(selectedTopology, (id) => {
  // Old target data must disappear even if the new target is empty or unavailable.
  chartReqSeq++
  inspectReqSeq++
  inspectionTasks.value = []
  inspectionError.value = ''
  trendData.value = { metrics: {}, alarms: [], summary: {} }
  chartError.value = ''
  updateCpuChart([])
  updateMemoryChart([])
  updateInterfaceChart([])
  updateOspfChart([])
  if (!id) return
  const topo = topologies.value.find((t) => t.id === id)
  labCtx.setTopology(id)
  copilot.setSelection({
    kind: 'topology',
    id,
    label: topo?.name || `拓扑 #${id}`,
    detail: '监控采集目标',
  })
  loadInspectionTasks()
  loadChartData()
})

onUnmounted(() => {
  chartReqSeq++
  inspectReqSeq++
  chartResizeObserver?.disconnect()
  chartResizeObserver = null
  if (chartResizeFrame !== null) {
    cancelAnimationFrame(chartResizeFrame)
    chartResizeFrame = null
  }
  cpuChartInstance?.dispose()
  memoryChartInstance?.dispose()
  interfaceChartInstance?.dispose()
  ospfChartInstance?.dispose()
  if (chartResizeHandler) {
    window.removeEventListener('resize', chartResizeHandler)
    chartResizeHandler = null
  }
  sseClosed = true
  if (sseTimer !== null) {
    clearTimeout(sseTimer)
    sseTimer = null
  }
  if (refreshTimer !== null) {
    clearTimeout(refreshTimer)
    refreshTimer = null
  }
  sseHandle?.close()
})
</script>

<style scoped>
.monitor-dashboard {
  min-height: 100%;
  container-type: inline-size;
  display: flex;
  flex-direction: column;
  gap: 0;
}
/* The page scrolls; cards must keep their content height instead of clipping controls. */
.monitor-dashboard > * {
  flex-shrink: 0;
}
.monitor-dashboard :deep(.el-card) {
  overflow: hidden;
  border-color: var(--v7b-line);
}
.stat-card { text-align: center; padding: 8px 0; }
.stat-value { font-size: 30px; font-weight: 700; color: var(--v7b-text); }
.stat-label { font-size: 13px; color: var(--v7b-muted); margin-top: 8px; white-space: nowrap; }
@container (max-width: 760px) {
  .monitor-dashboard > .el-row { row-gap: 16px; }
  .monitor-dashboard > .el-row > .el-col-6 { flex: 0 0 50%; max-width: 50%; }
  .monitor-dashboard > .el-row > .el-col-12 { flex: 0 0 100%; max-width: 100%; }
}
.ai-summary { display: flex; flex-direction: column; gap: 12px; }
.summary-line { margin: 0; color: var(--el-text-color-primary); font-size: 13px; }
.summary-block .block-title { margin-bottom: 4px; color: var(--el-text-color-secondary); font-size: 11px; }
.summary-block ul { margin: 0; padding-left: 18px; }
.summary-block li { font-size: 12px; line-height: 1.7; }
.report-text {
  max-height: 240px;
  margin: 0;
  padding: 10px;
  overflow: auto;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  background: var(--el-fill-color-light);
  font-size: 12px;
  white-space: pre-wrap;
}
/* 采集是同步阻塞请求：把"正在采集"说清楚，避免用户以为按钮没反应 */
.collect-hint { margin-top: 8px; color: var(--v7b-muted); font-size: 12px; }
.collect-fail-list { margin: 4px 0 0; padding-left: 18px; font-size: 12px; }
</style>
