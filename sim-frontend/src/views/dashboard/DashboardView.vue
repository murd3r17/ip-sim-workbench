<template>
  <div class="dashboard-shell v7b-page">
    <PageHeader
      title="工作台"
      subtitle="查看设备、拓扑与待处理工作，随时向右侧助手提问。"
    >
      <template #actions>
        <el-button :loading="loading" @click="loadSummary">刷新状态</el-button>
        <el-button @click="router.push('/devices')">去设备</el-button>
        <el-button type="primary" @click="goTraining">{{ labCtx.isActive ? '继续实训' : summary?.training?.intro_lab_id ? '入门巡检' : '进入实训' }}</el-button>
      </template>
    </PageHeader>

    <div class="command-bar">
      <div>
        <div class="eyebrow">环境与运行状态</div>
        <div class="environment-name">
          {{ summary?.environment_name || 'IP仿真运维管理工作台' }}
          <span class="status-dot" :class="summary?.environment_status || 'unknown'"></span>
        </div>
      </div>
      <div class="service-strip" v-if="summary">
        <div v-if="summary.device_mode === 'sim' || summary.device_mode === 'ssh'" class="service-item" role="status" aria-label="设备接入模式">
          <span class="service-label">设备接入</span>
          <strong>{{ summary.device_mode === 'sim' ? '模拟演练' : 'SSH 接入' }}</strong>
          <small v-if="summary.device_mode === 'sim'" class="service-label">模拟连通结果用于实训</small>
        </div>
        <div class="service-item">
          <span class="service-label">上次记录可达</span>
          <strong :class="summary.devices.online === summary.devices.total ? 'ok-text' : 'warn-text'">
            {{ summary.devices.online }} / {{ summary.devices.total }}
          </strong>
        </div>
        <div class="service-item">
          <span class="service-label">模型连通性</span>
          <strong :title="summary.services.llm.model || '模型未配置'" :class="statusClass(summary.services.llm.status)">{{ summary.services.llm.status === 'healthy' ? '可连接' : serviceLabel(summary.services.llm.status) }}</strong>
          <small v-if="summary.services.llm.checked_at" class="service-label" :title="formatApiTime(summary.services.llm.checked_at)">{{ formatTime(summary.services.llm.checked_at, true) }} 探测</small>
          <el-button v-else-if="isAdmin && summary.services.llm.status === 'disabled'" link type="primary" @click="router.push('/system/config')">配置模型</el-button>
          <small v-else-if="summary.services.llm.status === 'disabled'" class="service-label">教材可用 · 模型请联系管理员</small>
        </div>
        <div class="service-item" style="cursor: pointer" title="点击进入知识库管理" @click="router.push('/knowledge')">
          <span class="service-label">知识库</span>
          <strong :class="statusClass(summary.services.knowledge.status)">
            {{
              summary.services.knowledge.available === false
                ? '不可用'
                : summary.services.knowledge.status === 'not_checked'
                  ? '待检查'
                  : summary.services.knowledge.provider || serviceLabel(summary.services.knowledge.status)
            }}
            <template v-if="summary.services.knowledge.document_count != null">
              <small class="kb-count"> · {{ summary.services.knowledge.document_count }} 篇</small>
            </template>
          </strong>
        </div>
        <div class="service-item clock">
          <span class="service-label">系统时间</span>
          <strong>{{ currentTime }}</strong>
        </div>
      </div>
    </div>

    <div v-if="loading && !summary" class="state-panel">
      <span class="spinner"></span> 正在汇总运行状态
    </div>
    <el-alert v-else-if="error" :title="error" type="error" show-icon :closable="false">
      <template #default><el-button link type="primary" @click="loadSummary">重新加载</el-button></template>
    </el-alert>

    <template v-if="summary">
      <el-alert
        v-if="summary.monitor_scheduler_enabled === false"
        class="collect-hint"
        type="info"
        :closable="false"
        show-icon
        :title="isAdmin ? '当前显示已保存的设备状态和告警记录。需要更新时，可到监控页手动采集。' : '当前显示已保存的设备状态和告警记录。需要更新时，请联系管理员采集。'"
      />
      <section class="kpi-grid" aria-label="运行状态摘要">
        <button class="kpi" @click="router.push('/devices')">
          <span>资产总数</span><strong>{{ summary.devices.total }}</strong><small>台设备</small>
        </button>
        <button class="kpi" @click="router.push({ path: '/devices', query: { status: 'online' } })">
          <span>记录可达</span><strong class="ok-text">{{ summary.devices.online }}</strong><small>到设备页检查当前连接</small>
        </button>
        <router-link class="kpi topology-entry" :to="topologyRoute">
          <span>拓扑链路</span><strong>{{ summary.topology?.link_count ?? 0 }}</strong><small>查看拓扑 →</small>
        </router-link>
        <button class="kpi" @click="router.push(deployQueue)">
          <span>配置批次</span><strong class="cyan-text">{{ summary.tasks.deploy_batches ?? '—' }}</strong><small>查看配置任务</small>
        </button>
        <button class="kpi" @click="router.push(confirmationQueue)">
          <span>待确认变更</span><strong class="warn-text">{{ summary.risks.pending_approval }}</strong><small>按设备计数</small>
        </button>
        <button class="kpi" @click="router.push('/alarms?status=active')">
          <span>活跃告警</span><strong class="danger-text">{{ summary.alarms.active }}</strong><small>{{ summary.alarms.critical }} 条严重</small>
        </button>
        <button class="kpi" @click="router.push('/training')">
          <span>实训会话</span>
          <strong class="cyan-text">{{ summary.training?.active ?? 0 }}</strong>
          <small>进行中 · 查看实训</small>
        </button>
        <component :is="isAdmin ? 'button' : 'div'" class="kpi" :class="{ 'kpi-static': !isAdmin }" @click="isAdmin && router.push('/system/info')">
          <span>基础服务</span>
          <strong>{{ monitorServiceReady === null ? '—' : `${monitorServiceReady}/3` }}</strong>
          <small>数据库 · 模型 · 知识库</small>
        </component>
      </section>

      <section class="panel topology-overview" aria-labelledby="topology-overview-title">
        <header class="panel-header overview-header">
          <div>
            <h2 id="topology-overview-title">网络拓扑</h2>
            <div v-if="summary.topology" class="meta">{{ summary.topology.name }}</div>
          </div>
          <router-link class="overview-link" :to="topologyRoute">打开拓扑页 <span aria-hidden="true">→</span></router-link>
        </header>
        <div v-if="topologyError" class="overview-feedback" role="status">
          {{ visibleGraph ? '拓扑更新失败，当前显示上次读取的关系。' : '拓扑读取失败。' }}
          <button type="button" class="overview-link" :disabled="loading" @click="loadSummary">重试</button>
        </div>
        <TopologyCanvas
          v-if="visibleGraph?.nodes.length && summary.topology"
          :key="summary.topology.id"
          :nodes="visibleGraph.nodes" :edges="visibleGraph.edges" :positions="summary.topology.published_positions"
          overview
        />
        <div v-else-if="!topologyError" class="overview-empty">
          {{ !summary.topology ? '暂无主拓扑' : loading ? '正在读取拓扑' : '该拓扑暂无设备' }}
        </div>
      </section>

      <div class="primary-grid">
        <section class="panel task-panel">
          <header class="panel-header">
            <h2>最近工作</h2>
            <el-button link type="primary" @click="router.push(deployQueue)">配置批次</el-button>
          </header>
          <div v-if="!summary.tasks.items.length" class="empty-state compact">
            当前没有可查看的任务或实训记录
            <el-button link type="primary" @click="router.push({ path: '/deploy', query: { tab: 'tasks' } })">去配置下发</el-button>
          </div>
          <div v-else class="task-list">
            <button v-for="task in summary.tasks.items.slice(0, 5)" :key="`${task.kind}-${task.id}`" class="task-row" @click="openTask(task)">
              <div class="task-topline">
                <span class="task-kind">{{ taskKindLabel(task.kind) }}</span>
                <span class="task-status" :class="task.status">{{ task.kind === 'deploy' ? deployTaskStatusLabel(task.status) : taskStatusLabel(task.status) }}</span>
              </div>
              <strong>{{ task.name }}</strong>
              <small v-if="task.device_name">{{ task.device_name }} · 任务 #{{ task.id }}</small>
              <div v-if="task.high_risk || task.has_diff" class="task-flags">
                <span v-if="task.high_risk" class="danger-text">高风险</span>
                <span v-if="task.has_diff" class="warn-text">配置差异</span>
              </div>
              <div v-if="task.kind !== 'deploy' && task.kind !== 'training'" class="progress-track"><i :style="{ width: `${task.progress}%` }"></i></div>
            </button>
          </div>
        </section>

        <section class="panel risk-panel">
          <header class="panel-header">
            <h2>运维关注项</h2>
          </header>
          <div v-if="!summary.risks.items.length && !summary.alarms.items.length" class="healthy-state">已保存记录中没有待跟进事项。要确认当前状态，请在监控页查看最近采样。</div>
          <button v-for="risk in summary.risks.items" :key="risk.title" class="risk-row" @click="router.push(risk.route)">
            <i :class="risk.level"></i><span><strong>{{ risk.title }}</strong><small>{{ risk.detail }}</small><small class="recommendation">建议：{{ risk.recommendation }}</small></span><b aria-hidden="true">›</b>
          </button>
          <button v-for="alarm in summary.alarms.items.slice(0, 3)" :key="alarm.id" class="risk-row" @click="openAlarm(alarm)">
            <i :class="alarm.severity"></i>
            <span>
              <strong>{{ alarm.device_name }} · {{ alarmTitle(alarm) }}</strong>
              <small>{{ severityLabel(alarm.severity) }} · {{ alarmBrief(alarm) }}</small>
            </span>
            <b aria-hidden="true">›</b>
          </button>
        </section>

        <section class="panel trend-panel">
          <header class="panel-header">
            <div><span class="section-kicker">近 7 天</span><h2>告警趋势</h2></div>
            <div class="panel-actions">
              <span class="meta">共 {{ alarmTrendTotal }} 条</span>
              <el-button link type="primary" @click="router.push('/alarms')">告警中心</el-button>
            </div>
          </header>
          <div v-if="!alarmTrendTotal" class="trend-empty">近 7 天没有保存告警记录</div>
          <template v-else>
            <div ref="trendChartRef" class="trend-chart" role="img" aria-label="近七天告警趋势"></div>
            <el-button v-if="trendChartError" link @click="renderTrendChart(true)">图表未加载 · 重试</el-button>
          </template>
        </section>

        <section class="panel approval-panel" v-if="approvals.length">
          <header class="panel-header">
            <h2>待处理变更</h2>
            <el-button link type="primary" @click="router.push('/approvals')">审批中心</el-button>
          </header>
          <button v-for="item in approvals.slice(0, 3)" :key="item.id" class="approval-row" @click="router.push({ path: '/approvals', query: { task_id: String(item.id) } })">
            <span class="approval-main">
              <strong>{{ item.name || item.device_name }}</strong>
              <small>{{ item.device_name }} · {{ deployTaskStatusLabel(item.status) }}<template v-if="item.high_risk"> · 高风险</template></small>
            </span>
            <b aria-hidden="true">›</b>
          </button>
        </section>
      </div>

      <section class="panel activity-panel">
        <header class="panel-header">
          <div><span class="section-kicker">配置差异 / 报告 / 操作审计流</span><h2>最近执行记录</h2></div>
          <div class="panel-actions">
            <span class="meta">数据更新于 {{ formatTime(summary.generated_at) }}</span>
            <el-button link type="warning" @click="router.push('/config-versions?tab=compare')">配置差异 {{ summary.tasks.with_diff }}</el-button>
            <el-button v-if="isAdmin" link type="primary" @click="router.push('/system/audit')">审计日志</el-button>
          </div>
        </header>

        <div class="bottom-grid">
          <div class="bottom-column">
            <div class="column-title">配置差异（最近变更）</div>
            <div v-if="!diffTasks.length" class="empty-state compact">近期没有产生差异的下发任务</div>
            <button v-for="task in diffTasks" :key="`diff-${task.id}`" class="diff-row" @click="openTask(task)">
              <strong>{{ task.name }}</strong>
              <small class="warn-text">存在配置差异</small>
              <b aria-hidden="true">›</b>
            </button>

            <div class="column-title spaced">巡检 / 验证报告</div>
            <div v-if="!reports.length" class="empty-state compact">
              暂无巡检报告
              <el-button link type="primary" @click="router.push('/monitor')">去监控页采集</el-button>
            </div>
            <button v-for="item in reports" :key="`report-${item.id}`" class="report-row"
              @click="router.push({ path: '/monitor', query: { topology_id: item.topology_id ?? undefined, task_id: item.job_type === 'inspection' ? item.id : undefined } })">
              <strong>{{ jobTypeLabel(item.job_type) }} #{{ item.id }}</strong>
              <small>
                <template v-if="['pending', 'running'].includes(item.status)">{{ taskStatusLabel(item.status) }}</template>
                <template v-else>
                  覆盖 {{ item.success_count ?? '—' }}/{{ item.device_count ?? '—' }} 台
                  <template v-if="item.failure_count"> · 失败 {{ item.failure_count }}</template>
                  <template v-if="item.skipped_count"> · 跳过 {{ item.skipped_count }}</template>
                  <template v-if="item.success_count === 0"> · 健康状态未知</template>
                  <template v-else-if="item.alarm_count != null"> · 已覆盖设备告警 {{ item.alarm_count }}</template>
                </template>
              </small>
              <b aria-hidden="true">›</b>
            </button>
          </div>

          <div v-if="isAdmin" class="bottom-column">
            <div class="column-title">操作记录</div>
            <div v-if="!summary.activity.length" class="empty-state compact">
              暂无审计记录
              <el-button link type="primary" @click="router.push('/system/audit')">去审计日志</el-button>
            </div>
            <div v-else class="activity-list">
              <div v-for="item in summary.activity.slice(0, 5)" :key="item.id" class="activity-row">
                <time>{{ formatTime(item.created_at, true) }}</time>
                <span class="log-level" :class="item.result">{{ auditResultLabel(item.result) }}</span>
                <strong>{{ auditModuleLabel(item.module) }}</strong>
                <span>{{ auditActionLabel(item.action) }}</span>
              </div>
            </div>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { formatApiTime } from '../../utils/datetime'
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import type { ECharts } from 'echarts/core'
import { getDashboardServices, getDashboardSummary, type DashboardSummary, type DashboardTask } from '../../api/dashboard'
import { getDevices, getTopologyLinks } from '../../api/device'
import TopologyCanvas from '../../components/TopologyCanvas.vue'
import PageHeader from '../../components/v7b/PageHeader.vue'
import { useAutoRefresh } from '../../utils/autoRefresh'
import { useLabContextStore } from '../../stores/labContext'
import { useCurrentUser } from '../../composables/useCurrentUser'
import { alarmMeasurementLabel, alarmTypeLabel, auditActionLabel, auditModuleLabel, auditResultLabel, deployTaskStatusLabel, severityLabel, taskStatusLabel } from '../../utils/display'
import { toTopologyGraph } from '../../utils/topologyCanvas'

const router = useRouter()
const labCtx = useLabContextStore()
const { isAdmin } = useCurrentUser()
const deployQueue = { path: '/deploy', query: { tab: 'tasks' } }
const confirmationQueue = { path: '/approvals', query: { status: 'awaiting_review' } }
type DashboardAlarm = DashboardSummary['alarms']['items'][number]
function openAlarm(alarm: DashboardAlarm) {
  void router.push({ path: '/alarms', query: { alarm_id: alarm.id, device_id: alarm.device_id, status: 'active' } })
}
function alarmTitle(alarm: DashboardAlarm) {
  const label = alarmTypeLabel(alarm.alarm_type || undefined)
  return alarm.alarm_type && label !== alarm.alarm_type ? label : '设备告警'
}
function alarmBrief(alarm: DashboardAlarm) {
  if (alarmTitle(alarm) === '设备告警') return alarm.message
  if (alarm.metric_value == null || alarm.threshold == null || alarm.alarm_type?.startsWith('interface_')) return formatApiTime(alarm.fired_at)
  return `采样 ${alarmMeasurementLabel(alarm.metric_value, alarm.alarm_type)} · 阈值 ${alarmMeasurementLabel(alarm.threshold, alarm.alarm_type)}`
}
const summary = ref<DashboardSummary | null>(null)
const loading = ref(false)
const error = ref('')
const topologyGraph = shallowRef<(ReturnType<typeof toTopologyGraph> & { id: number }) | null>(null)
const topologyError = ref(false)
let checkingServices = false
let dashboardActive = true
const now = ref(new Date())
let clockTimer = 0
const trendChartRef = ref<HTMLDivElement | null>(null)
const trendChartError = ref(false)
let trendChart: ECharts | null = null
let trendResizeObserver: ResizeObserver | null = null
let trendVisibility: IntersectionObserver | null = null
let charts: Promise<typeof import('../../charts')> | undefined

const currentTime = computed(() => now.value.toLocaleString('zh-CN', { hour12: false }))
const resizeTrendChart = () => { trendChart?.resize() }
const topologyRoute = computed(() => {
  const id = summary.value?.topology?.id
  return { path: '/topology', query: id ? { topology_id: String(id) } : {} }
})
const visibleGraph = computed(() => {
  const graph = topologyGraph.value
  return graph?.id === summary.value?.topology?.id ? graph : null
})
const alarmTrend = computed(() => summary.value?.alarms.trend || [])
const alarmTrendTotal = computed(() => alarmTrend.value.reduce((sum, item) => sum + item.count, 0))
const diffTasks = computed(() => (summary.value?.tasks.items || []).filter(task => task.has_diff).slice(0, 3))
const approvals = computed(() => summary.value?.approvals || [])
const reports = computed(() => (summary.value?.reports || []).slice(0, 3))

const jobTypeLabel = (type: string) => ({
  inspection: '巡检任务',
  collection: '指标采集',
  aggregation: '指标聚合',
  cleanup: '数据清理',
} as Record<string, string>)[type] || type || '巡检任务'

const renderTrendChart = async (visible = false) => {
  // 没有告警时不渲染空图表（占位文案代替，省下高度给下面的分析区）
  const el = trendChartRef.value
  if (!el) {
    trendVisibility?.disconnect()
    trendVisibility = null
    trendResizeObserver?.disconnect()
    trendResizeObserver = null
    trendChart?.dispose()
    trendChart = null
    return
  }
  if (trendChart && trendChart.getDom() !== el) {
    // 容器被 v-if 销毁后重建：旧实例还指着已卸载的 DOM，必须换新
    trendChart.dispose()
    trendResizeObserver?.disconnect()
    trendChart = null
  }
  if (!trendChart) {
    if (!visible && !charts) {
      trendVisibility?.disconnect()
      trendVisibility = new IntersectionObserver(entries => {
        if (!entries.some(entry => entry.isIntersecting)) return
        trendVisibility?.disconnect()
        trendVisibility = null
        void renderTrendChart(true)
      })
      trendVisibility.observe(el)
      return
    }
    charts ??= import('../../charts')
    let echarts
    try {
      echarts = await charts
      trendChartError.value = false
    } catch {
      trendChartError.value = true
      charts = undefined
      return
    }
    if (!dashboardActive || trendChartRef.value !== el) return
    if (trendChart) return
    trendChart = echarts.init(el, undefined, { renderer: 'canvas' })
    trendResizeObserver = new ResizeObserver(() => trendChart?.resize())
    trendResizeObserver.observe(el)
  }
  const data = alarmTrend.value
  trendChart.setOption({
    grid: { left: 36, right: 12, top: 18, bottom: 24 },
    tooltip: { trigger: 'axis', renderMode: 'richText', confine: true, valueFormatter: (value: number) => `${value} 条` },
    xAxis: {
      type: 'category',
      data: data.map(item => item.date.slice(5)),
      axisLine: { lineStyle: { color: '#cbd6e2' } },
      axisLabel: { color: '#52606d', fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: '#e5ebf2' } },
      axisLabel: { color: '#52606d', fontSize: 10 },
    },
    series: [{
      type: 'line',
      smooth: true,
      symbolSize: 6,
      data: data.map(item => item.count),
      itemStyle: { color: '#2f6fba' },
      lineStyle: { color: '#2f6fba', width: 2 },
      areaStyle: { color: 'rgba(47, 111, 186, 0.12)' },
    }],
  })
}
// 监控大盘 KPI：展示采集相关服务健康数（数据库/模型/知识库），避免与"活跃告警"重复展示告警数
const monitorServiceReady = computed(() => {
  const services = summary.value?.services
  if (!services) return null
  if (['not_checked', 'configured'].includes(services.llm.status) || services.knowledge.status === 'not_checked') return null
  return [services.database, services.llm, services.knowledge]
    .filter(s => s && ['healthy', 'operational', 'success', 'online'].includes(s.status))
    .length
})

async function loadTopologyOverview(id: number | undefined) {
  if (!id) {
    topologyGraph.value = null
    topologyError.value = false
    return
  }
  const options = { silent: true, timeout: 10000 }
  try {
    const [devices, links] = await Promise.all([
      getDevices({ topology_id: id }, options),
      getTopologyLinks(id, options),
    ])
    topologyGraph.value = { id, ...toTopologyGraph(devices, links) }
    topologyError.value = false
  } catch {
    topologyError.value = true
  }
}

async function loadServiceHealth() {
  if (checkingServices) return
  checkingServices = true
  try {
    const services = await getDashboardServices()
    if (dashboardActive && summary.value) summary.value.services = services
  } catch {
    // The dashboard and its saved topology remain usable during health checks.
  } finally {
    checkingServices = false
  }
}

const loadSummary = async () => {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    const data = await getDashboardSummary()
    if (!dashboardActive) return
    if (summary.value) data.services = summary.value.services
    summary.value = data
    await nextTick()
    renderTrendChart()
    await loadTopologyOverview(summary.value.topology?.id)
    if (dashboardActive) void loadServiceHealth()
  } catch (cause: unknown) {
    if (!axios.isAxiosError(cause) || cause.response?.status !== 401) error.value = '总览数据加载失败，请检查后端服务后重试。'
  } finally {
    loading.value = false
  }
}

const serviceLabel = (status: string) => ({ healthy: '正常', configured: '已配置', not_configured: '未配置', disabled: '未启用', unavailable: '不可用' }[status] || status)
const statusClass = (status: string) => ['healthy', 'configured', 'operational', 'success', 'online'].includes(status) ? 'ok-text' : ['not_configured', 'disabled'].includes(status) ? 'muted-text' : 'warn-text'
const taskKindLabel = (kind: string) => ({ deploy: '配置', background: '后台', inspection: '巡检', patrol: '巡检', ai: 'AI', llm: 'AI', training: '实训' }[kind] || kind)
const formatTime = (value: string, onlyTime = false) => formatApiTime(value, onlyTime ? { hour: '2-digit', minute: '2-digit', second: '2-digit' } : {})
const goTraining = () => {
  if (labCtx.isActive && labCtx.sessionId) router.push({ path: '/training', query: { session_id: String(labCtx.sessionId) } })
  else if (summary.value?.training?.intro_lab_id) router.push({ path: '/training', query: { lab_id: String(summary.value.training.intro_lab_id) } })
  else router.push('/training')
}
const openTask = (task: DashboardTask) => {
  if (task.kind === 'training') {
    router.push({ path: '/training', query: { session_id: String(task.id) } })
    return
  }
  if (task.kind === 'deploy') {
    if (task.batch_id === null || ['pending', 'awaiting_confirmation', 'confirmed', 'deploying'].includes(task.status)) {
      router.push({ path: '/approvals', query: { task_id: String(task.id) } })
    } else {
      router.push({ path: '/deploy', query: { tab: 'tasks', task_id: String(task.id) } })
    }
    return
  }
  router.push('/system/tasks')
}

onMounted(() => {
  loadSummary()
  clockTimer = window.setInterval(() => { now.value = new Date() }, 1000)
  useAutoRefresh(loadSummary, 20000)
  window.addEventListener('resize', resizeTrendChart)
})
onUnmounted(() => {
  dashboardActive = false
  window.clearInterval(clockTimer)
  window.removeEventListener('resize', resizeTrendChart)
  trendVisibility?.disconnect()
  trendResizeObserver?.disconnect()
  trendResizeObserver = null
  trendChart?.dispose()
  trendChart = null
})
</script>

<style scoped>
.dashboard-shell {
  margin: 0;
  min-height: 0;
  height: auto;
  display: block;
  container-type: inline-size;
  color: var(--v7b-text);
  letter-spacing: 0;
  overflow: auto;
}
.dashboard-shell > * + * { margin-top: 14px; }
.dashboard-shell :deep(.el-button:not(.el-button--primary):not(.is-link)) {
  --el-button-bg-color: var(--v7b-surface);
  --el-button-text-color: var(--v7b-text);
  --el-button-border-color: var(--v7b-line-strong);
  --el-button-hover-bg-color: #eaf2fc;
  --el-button-hover-text-color: var(--v7b-accent);
  --el-button-hover-border-color: var(--v7b-accent);
}
.command-bar { flex-wrap: wrap; background: var(--v7b-surface); border-radius: 10px; flex-shrink: 0; min-height: 66px; display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 12px 18px 14px; border-bottom: 1px solid var(--v7b-line); }
.eyebrow, .section-kicker, .service-label { display: block; color: var(--v7b-muted); font-size: 11px; line-height: 1.4; }
.environment-name { overflow-wrap: anywhere; margin-top: 3px; font-size: 17px; font-weight: 700; }
.status-dot { display: inline-block; width: 8px; height: 8px; margin-left: 8px; border-radius: 50%; background: var(--v7b-muted); box-shadow: 0 0 0 4px rgba(127,147,166,.12); }
.status-dot.operational { background: var(--v7b-ok); box-shadow: 0 0 0 4px rgba(85,217,140,.12); }
.status-dot.degraded { background: var(--v7b-warn); box-shadow: 0 0 0 4px rgba(240,180,91,.12); }
.service-strip { display: flex; align-items: center; gap: 20px; min-width: 0; flex-wrap: wrap; row-gap: 10px; }
.service-item { min-width: 0; }
.service-item strong { display: block; margin-top: 3px; max-width: 170px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12.5px; }
.kb-count { font-size: 10.5px; color: var(--v7b-muted); font-weight: 500; }
.clock { min-width: 150px; }
.state-panel { min-height: 240px; display: grid; place-items: center; color: var(--v7b-muted); }
.spinner { width: 18px; height: 18px; border: 2px solid var(--v7b-line-strong); border-top-color: var(--v7b-accent); border-radius: 50%; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.kpi-grid { background: var(--v7b-surface); border: 1px solid var(--v7b-line); border-radius: 10px; overflow: hidden; flex-shrink: 0; display: grid; grid-template-columns: repeat(8, minmax(0, 1fr)); border-bottom: 1px solid var(--v7b-line); }
.kpi { min-width: 0; min-height: 82px; height: auto; padding: 12px 18px 14px; text-align: left; border: 0; border-right: 1px solid var(--v7b-line); background: transparent; color: inherit; cursor: pointer; }
.kpi:last-child { border-right: 0; }
.kpi:hover { background: var(--v7b-surface-2); }
.kpi-static { cursor: default; }
.kpi-static:hover { background: transparent; }
.topology-entry { display: block; box-sizing: border-box; text-decoration: none; }
.topology-entry small { color: var(--v7b-accent); }
.topology-entry:focus-visible { outline: 2px solid var(--v7b-accent); outline-offset: -2px; }
.kpi span { display: block; color: var(--v7b-muted); font-size: 12px; }
.kpi strong { display: inline-block; margin: 6px 8px 2px 0; color: var(--v7b-text); font-size: 23px; line-height: 1; }
.kpi small { display: block; color: var(--v7b-muted); font-size: 11px; line-height: 1.35; overflow-wrap: anywhere; }
/* 不再强行把整页压进一屏：面板给足高度，短屏由页面正常滚动（此前压缩导致"挤"） */
.primary-grid {
  align-items: start;
  gap: 14px;
  min-height: 0;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.panel { min-width: 0; background: var(--v7b-surface); border: 1px solid var(--v7b-line); border-radius: 10px; }
.topology-overview { overflow: hidden; }
.panel-header.overview-header { min-height: auto; align-items: center; padding: 12px 18px; }
.overview-header .meta { margin-top: 3px; overflow-wrap: anywhere; }
.overview-link { font: inherit; font-size: 13px; font-weight: 600; color: var(--v7b-accent); background: none; border: 0; padding: 4px; cursor: pointer; text-decoration: none; }
.overview-link:hover { text-decoration: underline; }
.overview-link:focus-visible { outline: 2px solid var(--v7b-accent); border-radius: 4px; }
.overview-link:disabled { opacity: .5; cursor: default; }
.overview-feedback { padding: 8px 18px; font-size: 12px; color: var(--v7b-warn); }
.overview-empty { min-height: 96px; display: grid; place-items: center; border-top: 1px solid var(--v7b-line); font-size: 13px; color: var(--v7b-muted); }
.panel-header { flex-wrap: wrap; flex-shrink: 0; min-height: 42px; display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.panel-header h2 { margin: 2px 0 0; color: var(--v7b-text); font-size: 15px; line-height: 1.4; }
.panel-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.meta { color: var(--v7b-muted); font-size: 11px; }
.task-panel, .risk-panel { padding: 16px 18px; }
.task-panel { flex: none; min-height: 132px; overflow: auto; border-bottom: 1px solid var(--v7b-line); }
.risk-panel { flex: none; min-height: 118px; overflow: auto; }
.approval-panel { flex: 0 0 auto; padding: 14px 18px 16px; border-top: 1px solid var(--v7b-line); }
.task-list { margin-top: 12px; }
.task-row { display: block; width: 100%; padding: 10px 0; text-align: left; border: 0; border-bottom: 1px solid var(--v7b-line); background: transparent; color: inherit; cursor: pointer; }
.task-row:hover strong { color: var(--v7b-accent); }
.task-row strong { display: block; margin: 5px 0 8px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.task-flags { display: flex; gap: 8px; margin: -2px 0 8px; font-size: 9px; }
.task-topline { display: flex; justify-content: space-between; color: var(--v7b-muted); font-size: 10px; }
.task-status.failed { color: var(--v7b-danger); }.task-status.success, .task-status.completed { color: var(--v7b-ok); }.task-status.pending { color: var(--v7b-warn); }
.progress-track { height: 3px; overflow: hidden; background: var(--v7b-line); }
.progress-track i { display: block; height: 100%; background: var(--v7b-accent); }
.risk-row { display: grid; grid-template-columns: 8px minmax(0, 1fr) auto; align-items: center; gap: 10px; width: 100%; padding: 10px 0; text-align: left; border: 0; border-bottom: 1px solid var(--v7b-line); background: transparent; color: inherit; cursor: pointer; }
.risk-row i { width: 7px; height: 28px; background: var(--v7b-warn); }.risk-row i.critical { background: var(--v7b-danger); }
.risk-row strong, .risk-row small { display: block; }.risk-row strong { font-size: 12px; }.risk-row small { margin-top: 3px; color: var(--v7b-muted); font-size: 10px; }.risk-row .recommendation { color: var(--v7b-muted); }
.risk-row b { color: var(--v7b-muted); font-size: 18px; }
.healthy-state { padding: 14px 0; color: var(--v7b-ok); font-size: 12px; }.healthy-state span { margin-right: 7px; }
.activity-panel { flex-shrink: 0; padding: 14px 20px 18px; }
/* 底部两栏：左栏（配置差异 + 报告）与右栏（操作审计流）各占一半，行高更宽松 */
.bottom-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px 28px; margin-top: 10px; }
.bottom-column { min-width: 0; }
.bottom-column .column-title { margin-bottom: 6px; color: var(--v7b-muted); font-size: 10px; letter-spacing: .08em; }
.bottom-column .column-title.spaced { margin-top: 14px; }
.diff-row, .report-row { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; align-items: center; gap: 10px; width: 100%; padding: 8px 0; text-align: left; border: 0; border-bottom: 1px solid var(--v7b-line); background: transparent; color: inherit; cursor: pointer; }
.diff-row strong, .report-row strong { overflow: hidden; font-size: 11.5px; text-overflow: ellipsis; white-space: nowrap; }
.diff-row small, .report-row small { color: var(--v7b-muted); font-size: 10px; }
.report-row { grid-template-columns: minmax(0, 1fr) minmax(0, 2fr) auto; }
.diff-row b, .report-row b { color: var(--v7b-muted); font-size: 15px; }
.trend-panel { flex: none; padding: 12px 18px 10px; }
.trend-chart { width: 100%; height: 128px; }
.trend-empty { display: grid; place-items: center; height: 56px; color: var(--v7b-muted); font-size: 12px; }
.strip-extra { margin-left: 4px; color: var(--v7b-muted); font-size: 10px; }
.approval-row { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; align-items: center; gap: 10px; width: 100%; padding: 8px 0; text-align: left; border: 0; border-bottom: 1px solid var(--v7b-line); background: transparent; color: inherit; cursor: pointer; }
.approval-row:last-child { border-bottom: 0; padding-bottom: 0; }
.approval-main strong, .approval-main small { display: block; }
.approval-main strong { font-size: 12px; }
.approval-main small { margin-top: 2px; color: var(--v7b-muted); font-size: 10px; }
.approval-row b { color: var(--v7b-muted); font-size: 16px; }
.activity-list { margin-top: 2px; }
.activity-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 28px; margin-top: 8px; }
.activity-row { display: grid; grid-template-columns: 72px 38px 64px minmax(0, 1fr); align-items: center; gap: 10px; min-width: 0; padding: 7px 0; border-bottom: 1px solid var(--v7b-line); font-size: 11px; }
.activity-row time { color: var(--v7b-muted); }.activity-row strong { color: var(--v7b-text); }.activity-row > span:last-child { overflow: hidden; color: var(--v7b-muted); text-overflow: ellipsis; white-space: nowrap; }
.log-level { color: var(--v7b-warn); font-size: 9px; font-weight: 700; }.log-level.success { color: var(--v7b-ok); }
.empty-state { flex: 1; min-height: 200px; display: grid; place-items: center; color: var(--v7b-muted); font-size: 12px; }.empty-state.compact { min-height: 80px; flex: 0; }
/* 采集提示条：压成单行，别占掉面板高度 */
.collect-hint { margin-bottom: 0; }
.collect-hint :deep(.el-alert__content) { padding: 2px 0; }
.collect-hint :deep(.el-alert__title) { font-size: 11.5px; line-height: 1.5; }
.ok-text { color: var(--v7b-ok) !important; }.cyan-text { color: var(--v7b-accent) !important; }.warn-text { color: var(--v7b-warn) !important; }.danger-text { color: var(--v7b-danger) !important; }.muted-text { color: var(--v7b-muted) !important; }

@container (max-width: 1300px) {
  .kpi-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .kpi:nth-child(4n) { border-right: 0; }
  .kpi:nth-child(-n+4) { border-bottom: 1px solid var(--v7b-line); }
}
@container (max-width: 950px) {
  .primary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .command-bar { align-items: flex-start; }
}
@container (max-width: 550px) {
  .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .kpi:nth-child(2n) { border-right: 0; }
  .kpi { border-bottom: 1px solid var(--v7b-line); }
  .kpi:nth-last-child(-n+2) { border-bottom: 0; }
  .primary-grid, .activity-grid, .bottom-grid { grid-template-columns: 1fr; }
  .activity-row { grid-template-columns: 62px 34px 52px minmax(0, 1fr); gap: 6px; }
  .service-strip { gap: 12px 18px; }
}
</style>
