<template>
  <div class="dashboard-shell v7b-page">
    <PageHeader
      title="工作台"
      subtitle="查看设备、拓扑与待处理工作，随时向右侧助手提问。"
    >
      <template #actions>
        <el-button :loading="loading" @click="loadSummary">刷新状态</el-button>
        <el-button @click="router.push('/devices')">去设备</el-button>
        <el-button type="primary" @click="goTraining">进入实训</el-button>
      </template>
    </PageHeader>

    <section class="continue-strip" aria-label="继续工作">
      <button v-if="labCtx.isActive" class="continue-item" @click="goTraining">
        <span>继续实训</span><strong>{{ labCtx.label }}</strong><small>会话 #{{ labCtx.sessionId }} · 不重新开始</small>
      </button>
      <button class="continue-item" @click="copilot.setOpen(true)">
        <span>继续对话</span><strong>右侧助手</strong><small>沿用当前会话，不自动发模型请求</small>
      </button>
      <button class="continue-item" @click="router.push('/approvals')">
        <span>待处理变更</span><strong>{{ summary?.risks.pending_approval ?? '—' }} 项</strong><small>需人工确认，不自动执行</small>
      </button>
      <button class="continue-item" @click="router.push('/devices')">
        <span>只读观察</span><strong>设备与证据</strong><small>先采集事实，再判断是否匹配</small>
      </button>
    </section>

    <div class="command-bar">
      <div>
        <div class="eyebrow">环境与运行状态</div>
        <div class="environment-name">
          {{ summary?.environment_name || 'IP仿真运维管理工作台' }}
          <span class="status-dot" :class="summary?.environment_status || 'unknown'"></span>
        </div>
      </div>
      <div class="service-strip" v-if="summary">
        <div class="service-item">
          <span class="service-label">设备</span>
          <strong :class="summary.devices.online === summary.devices.total ? 'ok-text' : 'warn-text'">
            {{ summary.devices.online }} / {{ summary.devices.total }}
          </strong>
        </div>
        <div class="service-item" style="cursor: pointer" title="点击进入任务中心" @click="router.push({ path: '/deploy', query: { tab: 'tasks' } })">
          <span class="service-label">任务队列</span>
          <strong class="cyan-text">{{ summary.tasks.active }} 运行 · {{ summary.tasks.pending }} 等待</strong>
        </div>
        <div class="service-item" style="cursor: pointer" title="点击进入审批" @click="router.push('/approvals')">
          <span class="service-label">待审批</span>
          <strong :class="summary.risks.pending_approval ? 'warn-text' : ''">{{ summary.risks.pending_approval }} 项</strong>
        </div>
        <div class="service-item" style="cursor: pointer" title="点击进入告警中心" @click="router.push('/alarms?status=active')">
          <span class="service-label">活跃告警</span>
          <strong :class="summary.alarms.active ? 'danger-text' : 'ok-text'">
            {{ summary.alarms.active }} 条
            <small class="kb-count"> · {{ summary.alarms.critical }} 严重</small>
          </strong>
        </div>
        <div class="service-item">
          <span class="service-label">模型</span>
          <strong :title="`${summary.services.llm.model} · 这里只检查服务连接，不验证回答生成`" :class="statusClass(summary.services.llm.status)">{{ summary.services.llm.status === 'healthy' ? '可连接' : serviceLabel(summary.services.llm.status) }}</strong>
        </div>
        <div class="service-item" style="cursor: pointer" title="点击进入知识库管理" @click="router.push('/knowledge')">
          <span class="service-label">知识库</span>
          <strong :class="statusClass(summary.services.knowledge.status)">
            {{
              summary.services.knowledge.available === false
                ? '不可用'
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
        title="自动采集未开启，当前显示已保存的设备与告警记录。可前往监控页手动采集。"
      />
      <section class="kpi-grid" aria-label="运行状态摘要">
        <button class="kpi" @click="router.push('/devices')">
          <span>资产总数</span><strong>{{ summary.devices.total }}</strong><small>台设备</small>
        </button>
        <button class="kpi" @click="router.push('/devices')">
          <span>在线设备</span><strong class="ok-text">{{ summary.devices.online }}</strong><small>最近保存的设备状态</small>
        </button>
        <button class="kpi" @click="router.push('/topology')">
          <span>拓扑链路</span><strong>{{ summary.topology?.link_count || 0 }}</strong><small>{{ summary.topology?.name || '未配置主拓扑' }}</small>
        </button>
        <button class="kpi" @click="router.push({ path: '/deploy', query: { tab: 'tasks' } })">
          <span>运行任务</span><strong class="cyan-text">{{ summary.tasks.active }}</strong><small>{{ summary.tasks.pending }} 项等待</small>
        </button>
        <button class="kpi" @click="router.push('/approvals')">
          <span>待审批</span><strong class="warn-text">{{ summary.risks.pending_approval }}</strong><small>高风险变更</small>
        </button>
        <button class="kpi" @click="router.push('/alarms?status=active')">
          <span>活跃告警</span><strong class="danger-text">{{ summary.alarms.active }}</strong><small>{{ summary.alarms.critical }} 条严重</small>
        </button>
        <button class="kpi" @click="goTraining">
          <span>实训中心</span>
          <strong class="cyan-text">{{ summary.training?.active ?? 0 }}</strong>
          <small>{{ (summary.training?.active ?? 0) ? '进行中会话 · 点此继续' : '开始实验闭环' }}</small>
        </button>
        <button class="kpi" @click="router.push('/system/info')">
          <span>基础服务</span>
          <strong>{{ monitorServiceReady === null ? '—' : `${monitorServiceReady}/3` }}</strong>
          <small>数据库 · LLM · 知识库</small>
        </button>
      </section>

      <div class="primary-grid">
        <div class="topology-column">
          <section class="panel topology-panel">
          <header class="panel-header">
            <div><span class="section-kicker">网络态势</span><h2>{{ summary.topology?.name || '基线拓扑' }}</h2></div>
            <div class="panel-actions">
              <span v-if="summary.topology" class="meta">{{ summary.topology.device_count }} 设备 · {{ summary.topology.link_count }} 链路</span>
              <el-button link type="primary" @click="router.push('/topology')">完整拓扑</el-button>
            </div>
          </header>
          <div v-if="!summary.topology?.nodes.length" class="empty-state">
            暂无主拓扑数据
            <el-button link type="primary" @click="router.push('/topology')">去拓扑页新建或导入</el-button>
          </div>
          <div v-else class="topology-canvas" @click="router.push('/topology')">
            <svg :viewBox="topologyViewBox" role="img" :aria-label="`${summary.topology.name}拓扑图`">
              <g class="topology-links">
                <line
                  v-for="link in topologyLinks"
                  :key="link.id"
                  :x1="link.x1" :y1="link.y1" :x2="link.x2" :y2="link.y2"
                  :class="{ down: link.status !== 'up' }"
                />
              </g>
              <g v-for="node in topologyNodes" :key="node.id" class="topology-node" :class="{ selected: selectedDevice?.id === node.id }" :transform="`translate(${node.x}, ${node.y})`" @click.stop="selectDevice(node)">
                <circle r="24" :class="node.status" />
                <text class="node-type" text-anchor="middle" y="4">{{ deviceMark(node.device_type) }}</text>
                <text class="node-name" text-anchor="middle" y="43">{{ node.hostname }}</text>
                <title>{{ node.hostname }} · {{ statusLabel(node.status) }} · {{ node.network_role }}</title>
              </g>
            </svg>
            <div class="topology-legend">
              <span><i class="legend-dot online"></i>在线</span>
              <span><i class="legend-dot offline"></i>离线</span>
              <span><i class="legend-dot unknown"></i>未知</span>
              <span><i class="legend-line"></i>链路</span>
            </div>
          </div>
          </section>

          <section class="panel trend-panel">
            <header class="panel-header">
              <div><span class="section-kicker">近 7 天</span><h2>告警趋势</h2></div>
              <div class="panel-actions">
                <span class="meta">共 {{ alarmTrendTotal }} 条</span>
                <el-button link type="primary" @click="router.push('/alarms')">告警中心</el-button>
              </div>
            </header>
            <div v-if="!alarmTrendTotal" class="trend-empty">近 7 天没有产生告警</div>
            <div v-else ref="trendChartRef" class="trend-chart"></div>
          </section>

          <!-- 设备即时命令弹窗（居中 el-dialog，可拖动，不遮罩：AI 面板与背景仍可操作） -->
          <el-dialog
            v-model="consoleVisible"
            :width="'min(720px, 94vw)'"
            :modal="false"
            class="device-console"
            destroy-on-close
            draggable
          >
            <template #header>
              <div class="drawer-header">
                <div>
                  <span class="section-kicker">即时命令</span>
                  <h2>{{ selectedDevice?.hostname || '' }}</h2>
                </div>
                <el-button link @click="closeConsole">关闭</el-button>
              </div>
            </template>
            <div v-if="selectedDevice" class="command-panel">
              <div class="device-meta">
                <span>{{ selectedDevice.mgmt_ip || '管理地址加载中' }}</span>
                <span :class="selectedDevice.status === 'online' ? 'ok-text' : 'warn-text'">{{ statusLabel(selectedDevice.status) }}</span>
                <span :class="sshReady ? 'ok-text' : 'muted-text'">SSH {{ sshReady ? '已就绪' : '连接中' }}</span>
                <span v-if="labCtx.sessionId" class="ok-text">记录到实训 #{{ labCtx.sessionId }}</span>
              </div>
              <div class="command-box">
                <span class="box-label">① 命令输入 —— 填好后点「确认下发」，命令会发送到下方终端</span>
                <el-input v-model="commandText" type="textarea" :rows="3" placeholder="输入多行 VRP 命令，例如：display version" />
                <div class="command-actions">
                  <el-button :disabled="!commandText.trim() || !sshReady" type="primary" @click="sendCommand">确认下发</el-button>
                  <el-button link type="primary" @click="router.push(`/webssh/${selectedDevice.id}`)">完整 WebSSH</el-button>
                  <el-button link type="primary" @click="router.push({ path: '/deploy', query: { device_id: String(selectedDevice.id) } })">配置下发</el-button>
                </div>
              </div>
              <div class="console-box">
                <span class="box-label">② 设备回显 —— SSH 会话实时输出（输入请用上面的命令框）</span>
                <div class="console-wrap">
                  <WebSSHConsole ref="terminalRef" :device-id="selectedDevice.id" :auto-connect="true" @ready="sshReady = $event" @command="onTerminalCommand" />
                </div>
              </div>
            </div>
          </el-dialog>
        </div>

        <aside class="operations-column">
          <section class="panel task-panel">
            <header class="panel-header">
              <div><span class="section-kicker">自动化工作流</span><h2>当前任务</h2></div>
              <el-button link type="primary" @click="router.push({ path: '/deploy', query: { tab: 'tasks' } })">任务中心</el-button>
            </header>
            <div v-if="!summary.tasks.items.length" class="empty-state compact">
              当前无运行任务
              <el-button link type="primary" @click="router.push({ path: '/deploy', query: { tab: 'tasks' } })">去配置下发</el-button>
            </div>
            <div v-else class="task-list">
              <button v-for="task in summary.tasks.items.slice(0, 5)" :key="`${task.kind}-${task.id}`" class="task-row" @click="openTask(task)">
                <div class="task-topline">
                  <span class="task-kind">{{ taskKindLabel(task.kind) }}</span>
                  <span class="task-status" :class="task.status">{{ statusLabel(task.status) }}</span>
                </div>
                <strong>{{ task.name }}</strong>
                <div v-if="task.high_risk || task.has_diff" class="task-flags">
                  <span v-if="task.high_risk" class="danger-text">高风险</span>
                  <span v-if="task.has_diff" class="warn-text">配置差异</span>
                </div>
                <div class="progress-track"><i :style="{ width: `${task.progress}%` }"></i></div>
              </button>
            </div>
          </section>

          <section class="panel risk-panel">
            <header class="panel-header">
              <div><span class="section-kicker">AI 建议与风险</span><h2>运维关注项</h2></div>
            </header>
            <div v-if="!summary.risks.items.length" class="healthy-state"><span>✓</span> 当前没有活动风险</div>
            <button v-for="risk in summary.risks.items" :key="risk.title" class="risk-row" @click="router.push(risk.route)">
              <i :class="risk.level"></i><span><strong>{{ risk.title }}</strong><small>{{ risk.detail }}</small><small class="recommendation">建议：{{ risk.recommendation }}</small></span><b aria-hidden="true">›</b>
            </button>
          </section>

          <section class="panel approval-panel" v-if="approvals.length">
            <header class="panel-header">
              <div><span class="section-kicker">变更审批</span><h2>待处理变更 {{ approvals.length }}</h2></div>
              <el-button link type="primary" @click="router.push('/approvals')">审批中心</el-button>
            </header>
            <button v-for="item in approvals.slice(0, 3)" :key="item.id" class="approval-row" @click="router.push('/approvals')">
              <span class="approval-main">
                <strong>{{ item.device_name }}</strong>
                <small>{{ statusLabel(item.status) }}<template v-if="item.high_risk"> · 高风险</template></small>
              </span>
              <span v-if="item.high_risk" class="danger-text">待确认</span>
              <b aria-hidden="true">›</b>
            </button>
          </section>
        </aside>
      </div>

      <section class="panel activity-panel">
        <header class="panel-header">
          <div><span class="section-kicker">配置差异 / 报告 / 操作审计流</span><h2>最近执行记录</h2></div>
          <div class="panel-actions">
            <span class="meta">数据更新于 {{ formatTime(summary.generated_at) }}</span>
            <el-button link type="warning" @click="router.push('/config-versions?tab=compare')">配置差异 {{ summary.tasks.with_diff }}</el-button>
            <el-button link type="primary" @click="router.push('/system/audit')">审计报告</el-button>
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
            <button v-for="item in reports" :key="`report-${item.id}`" class="report-row" @click="router.push('/monitor')">
              <strong>{{ jobTypeLabel(item.job_type) }} #{{ item.id }}</strong>
              <small>
                {{ item.device_count }} 设备 · 成功 {{ item.success_count }}
                <template v-if="item.failure_count"> · 失败 {{ item.failure_count }}</template>
                <template v-if="item.alarm_count != null"> · 告警 {{ item.alarm_count }}</template>
              </small>
              <b aria-hidden="true">›</b>
            </button>
          </div>

          <div class="bottom-column">
            <div class="column-title">操作审计流（命令流替代）</div>
            <div v-if="!summary.activity.length" class="empty-state compact">
              暂无审计记录
              <el-button link type="primary" @click="router.push('/system/audit')">去审计日志</el-button>
            </div>
            <div v-else class="activity-list">
              <div v-for="item in summary.activity.slice(0, 5)" :key="item.id" class="activity-row">
                <time>{{ formatTime(item.created_at, true) }}</time>
                <span class="log-level" :class="item.result">{{ item.result === 'success' ? 'OK' : 'WARN' }}</span>
                <strong>{{ moduleLabel(item.module) }}</strong>
                <span>{{ actionLabel(item.action) }}</span>
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
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { getDashboardSummary, type DashboardLink, type DashboardNode, type DashboardSummary, type DashboardTask } from '../../api/dashboard'
import { ElMessage } from 'element-plus/es/components/message/index'
import { ElMessageBox } from 'element-plus/es/components/message-box/index'
import { getDevice, type DeviceRecord } from '../../api/device'
import WebSSHConsole from '../../components/WebSSHConsole.vue'
import PageHeader from '../../components/v7b/PageHeader.vue'
import { useAutoRefresh } from '../../utils/autoRefresh'
import { useLabContextStore } from '../../stores/labContext'
import { useAiCopilotStore } from '../../stores/aiCopilot'
import { useTrainingCommandLog } from '../../composables/useTrainingCommandLog'

const router = useRouter()
const labCtx = useLabContextStore()
const copilot = useAiCopilotStore()
const { logTerminalCommand } = useTrainingCommandLog()
echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])
const summary = ref<DashboardSummary | null>(null)
const loading = ref(false)
const error = ref('')
const now = ref(new Date())
let clockTimer = 0
const selectedDevice = ref<(DashboardNode & Partial<DeviceRecord>) | null>(null)
const consoleVisible = ref(false)
const commandText = ref('')
const sshReady = ref(false)
const terminalRef = ref<{ send: (content: string) => boolean } | null>(null)
const trendChartRef = ref<HTMLDivElement | null>(null)
let trendChart: echarts.ECharts | null = null
let trendResizeObserver: ResizeObserver | null = null

const currentTime = computed(() => now.value.toLocaleString('zh-CN', { hour12: false }))
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

const renderTrendChart = () => {
  // 没有告警时不渲染空图表（占位文案代替，省下高度给下面的分析区）
  const el = trendChartRef.value
  if (!el) {
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
  return [services.database, services.llm, services.knowledge]
    .filter(s => s && ['healthy', 'operational', 'success', 'online'].includes(s.status))
    .length
})

const layerFor = (node: DashboardNode) => {
  const role = (node.network_role || '').toLowerCase()
  if (/(backbone|external|vpn_rr|骨干)/.test(role)) return 0
  if (/(core|provincial|aggregation|distribution|汇聚)/.test(role)) return 1
  if (/(business|bras|access|接入)/.test(role)) return 2
  if (/(management|switch|edge)/.test(role)) return 3
  if (node.device_type === 'router') return 0
  if (node.device_type === 'switch_l3') return 1
  if (node.device_type === 'switch_l2') return 2
  return 3
}

const topologyNodes = computed(() => {
  const nodes = summary.value?.topology?.nodes || []
  const published = summary.value?.topology?.published_positions || {}
  const layers = [0, 1, 2, 3].map(layer => nodes.filter(node => layerFor(node) === layer))
  return layers.flatMap((items, layer) => items.map((node, index) => {
    const position = published[String(node.id)]
    return {
      ...node,
      x: position ? position.x * 1000 : [110, 360, 640, 890][layer],
      y: position ? position.y * 560 : 55 + (index + 1) * 450 / (items.length + 1),
    }
  }))
})

// Fit the preview to its actual nodes; a fixed large viewBox made six-node labels tiny.
const topologyViewBox = computed(() => {
  const nodes = topologyNodes.value
  if (!nodes.length) return '0 0 1000 560'
  const xs = nodes.map(node => node.x), ys = nodes.map(node => node.y)
  const left = Math.min(...xs) - 80, top = Math.min(...ys) - 60
  return `${left} ${top} ${Math.max(...xs) - left + 80} ${Math.max(...ys) - top + 80}`
})

const topologyLinks = computed(() => {
  const positions = new Map(topologyNodes.value.map(node => [node.id, node]))
  return (summary.value?.topology?.links || []).flatMap((link: DashboardLink) => {
    const source = positions.get(link.source_device_id)
    const target = positions.get(link.target_device_id)
    return source && target ? [{ ...link, x1: source.x, y1: source.y, x2: target.x, y2: target.y }] : []
  })
})

const selectDevice = async (node: DashboardNode) => {
  commandText.value = ''
  sshReady.value = false
  selectedDevice.value = node
  consoleVisible.value = true
  labCtx.setDevice({
    id: node.id,
    hostname: node.hostname,
    mgmt_ip: (node as any).mgmt_ip,
  })
  copilot.setSelection({
    kind: 'device',
    id: node.id,
    label: node.hostname,
    detail: (node as any).mgmt_ip || '',
  })
  try {
    const device = await getDevice(node.id) as DeviceRecord
    if (selectedDevice.value?.id === node.id) {
      selectedDevice.value = { ...node, ...device }
      labCtx.setDevice({
        id: device.id,
        hostname: device.hostname,
        mgmt_ip: device.mgmt_ip,
      })
    }
  } catch {
    // Keep the selected topology node usable even if optional detail lookup fails.
  }
}

const closeConsole = () => {
  consoleVisible.value = false
  selectedDevice.value = null
  commandText.value = ''
  sshReady.value = false
}

// 点弹窗 ✕ 关闭时同样清理选中状态与终端
watch(consoleVisible, (visible) => {
  if (!visible && selectedDevice.value) {
    selectedDevice.value = null
    commandText.value = ''
    sshReady.value = false
  }
})

const onTerminalCommand = (payload: { command: string; success: boolean; result: string }) => {
  logTerminalCommand({
    ...payload,
    hostname: selectedDevice.value?.hostname,
  })
}

const sendCommand = async () => {
  if (!selectedDevice.value || !commandText.value.trim() || !sshReady.value) return
  const commands = commandText.value.trim()
  try {
    await ElMessageBox.confirm(
      `目标设备：${selectedDevice.value.hostname}\n\n以下命令将直接通过 SSH 发送：\n${commands}`,
      '确认即时下发',
      { confirmButtonText: '发送命令', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  const input = commands.split(/\r?\n/).map(line => `${line}\r`).join('')
  if (!terminalRef.value?.send(input)) {
    ElMessage.warning('SSH 尚未就绪，请稍后重试。')
    return
  }
  commandText.value = ''
}

const loadSummary = async () => {
  loading.value = true
  error.value = ''
  try {
    summary.value = await getDashboardSummary()
    await nextTick()
    renderTrendChart()
  } catch (cause: unknown) {
    if (!axios.isAxiosError(cause) || cause.response?.status !== 401) error.value = '总览数据加载失败，请检查后端服务后重试。'
  } finally {
    loading.value = false
  }
}

const deviceMark = (type: string) => ({ router: 'R', switch_l3: 'L3', switch_l2: 'L2', firewall: 'FW', server: 'SV' }[type] || 'IP')
const serviceLabel = (status: string) => ({ healthy: '正常', configured: '已配置', not_configured: '未配置', unavailable: '不可用' }[status] || status)
const statusClass = (status: string) => ['healthy', 'configured', 'operational', 'success', 'online'].includes(status) ? 'ok-text' : status === 'not_configured' ? 'muted-text' : 'warn-text'
const statusLabel = (status: string) => ({ pending: '等待中', validating: '校验中', awaiting_confirmation: '待确认', confirmed: '待执行', deploying: '下发中', verifying: '验证中', running: '运行中', in_progress: '进行中', success: '已完成', completed: '已完成', failed: '失败', cancelled: '已取消', rolled_back: '已回滚', partial_failure: '部分失败', online: '在线', offline: '离线', maintenance: '维护中', unknown: '未知' }[status] || status)
const taskKindLabel = (kind: string) => ({ deploy: '配置', background: '后台', inspection: '巡检', patrol: '巡检', ai: 'AI', llm: 'AI', training: '实训' }[kind] || kind)
const moduleLabel = (module: string) => ({ device: '设备', deploy: '配置', monitor: '监控', ai: 'AI', auth: '认证', system: '系统', training: '实训' }[module] || module)
const actionLabel = (action: string) => ({ health_check: '健康检查', login: '用户登录', create: '创建', update: '更新', delete: '删除', deploy: '配置下发' }[action] || action)
const formatTime = (value: string, onlyTime = false) => formatApiTime(value, onlyTime ? { hour: '2-digit', minute: '2-digit', second: '2-digit' } : {})
const goTraining = () => {
  if (labCtx.sessionId) router.push({ path: '/training', query: { session_id: String(labCtx.sessionId) } })
  else router.push('/training')
}
const openTask = (task: DashboardTask) => {
  if (task.kind === 'training') {
    router.push({ path: '/training', query: { session_id: String(task.id) } })
    return
  }
  if (task.kind === 'deploy') {
    router.push({ path: '/deploy', query: { tab: 'tasks', task_id: String(task.id) } })
    return
  }
  router.push('/system/tasks')
}

onMounted(() => {
  loadSummary()
  clockTimer = window.setInterval(() => { now.value = new Date() }, 1000)
  useAutoRefresh(loadSummary, 20000)
  window.addEventListener('resize', renderTrendChart)
})
onUnmounted(() => {
  window.clearInterval(clockTimer)
  window.removeEventListener('resize', renderTrendChart)
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
.kpi span { display: block; color: var(--v7b-muted); font-size: 12px; }
.kpi strong { display: inline-block; margin: 6px 8px 2px 0; color: var(--v7b-text); font-size: 23px; line-height: 1; }
.kpi small { display: block; color: var(--v7b-muted); font-size: 11px; line-height: 1.35; overflow-wrap: anywhere; }
/* 不再强行把整页压进一屏：面板给足高度，短屏由页面正常滚动（此前压缩导致"挤"） */
.primary-grid {
  align-items: start;
  gap: 14px;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(280px, 360px);
}
.panel { min-width: 0; background: var(--v7b-surface); border: 1px solid var(--v7b-line); border-radius: 10px; }
.topology-column { min-width: 0; display: flex; flex-direction: column; gap: 14px; min-height: 0; }
.topology-panel { min-height: 0; display: flex; flex-direction: column; padding: 16px 20px 12px; }
.panel-header { flex-wrap: wrap; flex-shrink: 0; min-height: 42px; display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.panel-header h2 { margin: 2px 0 0; color: var(--v7b-text); font-size: 15px; line-height: 1.4; }
.panel-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.meta { color: var(--v7b-muted); font-size: 11px; }
.topology-canvas {
  position: relative;
  flex: none;
  height: clamp(300px, 40vh, 440px);
  min-height: 0;
  margin-top: 8px;
  overflow: hidden;
  background-color: #f8fbfe;
  background-image: radial-gradient(#dbe5ef 1px, transparent 1px);
  border-radius: 6px;
  background-size: 28px 28px;
  cursor: pointer;
}
.topology-canvas svg { position: absolute; inset: 0; width: 100%; height: calc(100% - 32px); }
.topology-links line { stroke: #2a8fa8; stroke-width: 1.5; opacity: .7; }
.topology-links line.down { stroke: var(--v7b-danger); stroke-dasharray: 6 5; }
.topology-node circle { fill: #edf2f7; stroke: var(--v7b-accent); stroke-width: 3; }
.topology-node.selected circle { stroke: var(--v7b-warn); stroke-width: 5; }
.topology-node circle.online { fill: #e5f4ec; stroke: var(--v7b-ok); }
.topology-node circle.offline { fill: #fceceb; stroke: var(--v7b-danger); }
.topology-node circle.maintenance { fill: #fff3d6; stroke: var(--v7b-warn); }
.node-type { fill: #233b4c; font-size: 11px; font-weight: 700; }
.node-name { fill: #344054; font-size: 11px; }
.topology-legend { position: absolute; right: 12px; bottom: 10px; display: flex; gap: 14px; padding: 7px 9px; background: rgba(255,255,255,.94); color: var(--v7b-muted); font-size: 10px; }
.topology-legend span { display: flex; align-items: center; gap: 5px; }
.legend-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--v7b-muted); }
.legend-dot.online { background: var(--v7b-ok); }.legend-dot.offline { background: var(--v7b-danger); }.legend-dot.unknown { background: var(--v7b-muted); }
.legend-line { width: 16px; border-top: 1px solid var(--v7b-accent); }
.operations-column { display: flex; flex-direction: column; gap: 14px; min-width: 0; min-height: 0; }
.task-panel, .risk-panel { padding: 16px 18px; }
/* 任务与风险按实际内容定高，不再撑大旁边的拓扑。 */
.task-panel { flex: none; min-height: 132px; overflow: auto; border-bottom: 1px solid var(--v7b-line); }
.risk-panel { flex: none; min-height: 118px; overflow: auto; }
.approval-panel { flex: 0 0 auto; padding: 14px 18px 16px; border-top: 1px solid var(--v7b-line); }
.command-panel { display: flex; flex-direction: column; min-height: 0; }
.drawer-header { display: flex; align-items: center; justify-content: space-between; width: 100%; gap: 12px; }
.drawer-header h2 { margin: 2px 0 0; color: var(--v7b-text); font-size: 15px; line-height: 1.4; }
.device-console :deep(.el-dialog) { background: var(--v7b-surface); border: 1px solid var(--v7b-line); border-radius: 8px; }
.device-console :deep(.el-dialog__header) { margin-right: 0; padding: 14px 18px; border-bottom: 1px solid var(--v7b-line); }
.device-console :deep(.el-dialog__body) { padding: 16px 18px; }
.device-console :deep(.el-dialog__title) { color: var(--v7b-text); }
.device-console :deep(.el-dialog__headerbtn) { top: 14px; }
.device-console :deep(.el-dialog__headerbtn .el-dialog__close) { color: var(--v7b-muted); }
.device-meta { display: flex; flex-wrap: wrap; gap: 7px 10px; margin: 0 0 12px; color: var(--v7b-muted); font-size: 11px; }
.command-box, .console-box { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.command-box { margin-bottom: 14px; }
.box-label { color: var(--v7b-muted); font-size: 11px; line-height: 1.5; }
.command-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; }
.console-wrap { height: 260px; flex: none; min-height: 0; border: 1px solid var(--v7b-line); background: #0d151e; }
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

.continue-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(210px, 100%), 1fr));
  gap: 10px;
}
.continue-item {
  appearance: none;
  border: 1px solid var(--v7b-line);
  border-radius: 9px;
  background: var(--v7b-surface);
  color: var(--v7b-text);
  text-align: left;
  padding: 10px 12px;
  cursor: pointer;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.continue-item:hover { border-color: var(--v7b-line-strong); background: #edf4fc; }
.continue-item span { color: var(--v7b-muted); font-size: 10px; }
.continue-item strong { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.continue-item small { color: var(--v7b-faint); font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
@container (max-width: 1300px) {
  .kpi-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .kpi:nth-child(4n) { border-right: 0; }
  .kpi:nth-child(-n+4) { border-bottom: 1px solid var(--v7b-line); }
}
@container (max-width: 950px) {
  .primary-grid { grid-template-columns: 1fr; }
  .operations-column { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: start; }
  .command-bar { align-items: flex-start; }
}
@container (max-width: 550px) {
  .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .kpi:nth-child(2n) { border-right: 0; }
  .kpi { border-bottom: 1px solid var(--v7b-line); }
  .kpi:nth-last-child(-n+2) { border-bottom: 0; }
  .operations-column, .activity-grid, .bottom-grid { grid-template-columns: 1fr; }
  .topology-panel { padding: 12px; }
  .activity-row { grid-template-columns: 62px 34px 52px minmax(0, 1fr); gap: 6px; }
  .service-strip { gap: 12px 18px; }
}
</style>
