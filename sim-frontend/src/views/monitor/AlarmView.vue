<template>
  <div class="alarm-view">
    <el-card>
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px">
          <span>告警管理</span>
          <div style="display: flex; gap: 16px; align-items: center; flex-wrap: wrap">
            <el-button @click="$router.push('/devices')">返回设备</el-button>
            <el-button @click="$router.push('/monitor')">去监控大盘</el-button>
            <el-select v-model="filterStatus" placeholder="告警状态" clearable style="width: 120px">
              <el-option label="活跃告警" value="active" />
              <el-option label="未处理" value="fired" />
              <el-option label="已接手" value="acknowledged" />
              <el-option label="已解除" value="resolved" />
              <el-option label="已关闭" value="closed" />
            </el-select>
            <el-select v-model="filterDevice" placeholder="选择设备" clearable style="width: 200px">
              <el-option v-for="device in devices" :key="device.id" :label="device.hostname" :value="device.id" />
            </el-select>
            <span v-if="!loading && !devices.length && !deviceLoadError" style="color: #7f93a6; font-size: 12px">暂无设备，请先导入拓扑基线</span>
            <el-button @click="loadAlarms">刷新</el-button>
          </div>
        </div>
      </template>

      <el-alert v-if="deviceLoadError" :title="deviceLoadError" type="warning" :closable="false" show-icon><el-button @click="loadDevices">重试设备列表</el-button></el-alert>
      <el-alert v-if="loadError" :title="loadError" type="warning" :closable="false" show-icon />
      <el-alert v-if="linkedAlarmError" :title="linkedAlarmError" type="warning" :closable="false" show-icon>
        <el-button link type="primary" @click="loadLinkedAlarm">重新打开指定告警</el-button>
      </el-alert>
      <p class="alarm-help">先核对触发依据和最近采样。接手和关闭只更新这条记录的处理状态。</p>
      <el-table :data="pagedAlarms" v-loading="loading" @row-click="onAlarmRowClick">
        <template #empty>
          <el-empty :description="loadError || (filterStatus || filterDevice ? '当前筛选没有匹配告警。' : '暂无告警记录')" :image-size="72">
            <el-button v-if="filterStatus || filterDevice" type="primary" @click="clearFilters">查看全部告警</el-button>
            <el-button v-else type="primary" @click="$router.push('/monitor')">去监控大盘</el-button>
          </el-empty>
        </template>
        <el-table-column label="设备" min-width="110"><template #default="{ row }">{{ row.device_name || `设备 #${row.device_id}` }}</template></el-table-column>
        <el-table-column label="告警类型" min-width="160"><template #default="{ row }">{{ alarmTypeLabel(row.alarm_type) }}</template></el-table-column>
        <el-table-column prop="severity" label="严重程度" width="100">
          <template #default="{ row }">
            <el-tag :type="getSeverityType(row.severity)">{{ reviewOnly(row.alarm_type) ? '需核对' : getSeverityLabel(row.severity) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="触发依据" min-width="235"><template #default="{ row }">{{ alarmTriggerLabel(row) }}</template></el-table-column>
        <el-table-column prop="status" label="处理状态" width="125">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)">{{ getStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="触发时间" width="180">
          <template #default="{ row }">{{ formatApiTime(row.fired_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'fired'" type="warning" link @click.stop="handleAcknowledge(row)">接手</el-button>
            <el-button v-if="['resolved', 'acknowledged'].includes(row.status)" type="success" link @click.stop="handleClose(row)">关闭</el-button>
            <el-button type="primary" link @click.stop="handleViewDetail(row)">详情</el-button>
            <el-button v-if="row.device_id" type="primary" link @click.stop="openWebSSH(row)">终端</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="alarms.length" style="margin-top: 12px; display: flex; justify-content: flex-end">
        <el-pagination
        v-if="!loadError || alarms.length"
          v-model:current-page="alarmPage"
          v-model:page-size="alarmPageSize"
          :total="alarms.length"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
        />
      </div>
    </el-card>

    <!-- 告警详情对话框 -->
    <el-dialog v-model="detailDialogVisible" title="告警详情" width="min(600px, 92vw)" draggable>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="告警ID">{{ currentAlarm?.id }}</el-descriptions-item>
        <el-descriptions-item label="设备">{{ currentAlarm?.device_name || '设备' }} #{{ currentAlarm?.device_id }}</el-descriptions-item>
        <el-descriptions-item label="告警类型">{{ alarmTypeLabel(currentAlarm?.alarm_type) }}</el-descriptions-item>
        <el-descriptions-item label="严重程度">
          <el-tag :type="getSeverityType(currentAlarm?.severity)">{{ reviewOnly(currentAlarm?.alarm_type) ? '需核对' : getSeverityLabel(currentAlarm?.severity) }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="getStatusType(currentAlarm?.status)">{{ getStatusLabel(currentAlarm?.status) }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="触发依据" :span="2">{{ alarmTriggerLabel(currentAlarm || {}) }}</el-descriptions-item>
        <el-descriptions-item label="触发时间">{{ formatApiTime(currentAlarm?.fired_at) }}</el-descriptions-item>
        <el-descriptions-item label="确认时间">{{ formatApiTime(currentAlarm?.acknowledged_at) }}</el-descriptions-item>
        <el-descriptions-item label="解决时间">{{ formatApiTime(currentAlarm?.resolved_at) }}</el-descriptions-item>
        <el-descriptions-item label="关闭时间">{{ formatApiTime(currentAlarm?.closed_at) }}</el-descriptions-item>
      </el-descriptions>
      <el-alert :title="alarmMeaning(currentAlarm?.alarm_type)" type="info" :closable="false" show-icon style="margin-top: 12px" />
      <p class="alarm-help">这是保存的告警记录。确认、解决、关闭时间各有含义；当前设备状态请核对新的观察。</p>
      <div style="margin-top: 16px">
        <details><summary>原始告警记录</summary><p>{{ currentAlarm?.message }}</p><code>{{ currentAlarm?.alarm_type }}</code></details>
      </div>
      <div v-if="currentAlarm?.device_id" class="v7b-actions" style="margin-top: 12px">
        <el-button type="primary" @click="openDeviceObservation(currentAlarm)">{{ ospfAlarm(currentAlarm?.alarm_type) ? '查看 OSPF 邻居' : '观察该设备' }}</el-button>
        <el-button @click="openWebSSH(currentAlarm)">打开 WebSSH</el-button>
        <el-button @click="$router.push('/monitor')">去监控大盘</el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { formatApiTime } from '../../utils/datetime'
import { ref, computed, onMounted, watch } from 'vue'
import { useSnapshotRequest } from '../../composables/useSnapshotRequest'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus/es/components/message/index'
import { ElMessageBox } from 'element-plus/es/components/message-box/index'
import { getDevices, type DeviceRecord } from '../../api/device'
import { acknowledgeAlarm, closeAlarm, getAlarms, type AlarmRecord } from '../../api/monitor'
import { useAutoRefresh } from '../../utils/autoRefresh'
import {
  alarmStatusLabel as getStatusLabel,
  alarmStatusTagType as getStatusType,
  severityLabel as getSeverityLabel,
  severityTagType as getSeverityType,
  alarmTypeLabel, alarmMeaning, alarmTriggerLabel,
} from '../../utils/display'
import { useLabContextStore } from '../../stores/labContext'

const labCtx = useLabContextStore()
const route = useRoute()
const router = useRouter()
const alarmRequest = useSnapshotRequest('告警列表')
const loading = alarmRequest.loading
const loadError = alarmRequest.error
const deviceRequest = useSnapshotRequest('设备列表')
const deviceLoadError = deviceRequest.error
const filterStatus = ref<string | null>(null)
const filterDevice = ref<number | null>(null)
const devices = ref<DeviceRecord[]>([])
const alarms = ref<AlarmRecord[]>([])
const reviewOnly = (kind?: string) => kind === 'interface_review' || kind === 'ospf_neighbor_count_review'
const ospfAlarm = (kind?: string) => Boolean(kind?.startsWith('ospf_neighbor_count_'))
const alarmPage = ref(1)
const alarmPageSize = ref(20)
const pagedAlarms = computed(() => {
  const start = (alarmPage.value - 1) * alarmPageSize.value
  const rank = (item: AlarmRecord) => {
    if (!['fired', 'acknowledged'].includes(item.status)) return 0
    if (reviewOnly(item.alarm_type)) return 1
    return ({ warning: 2, minor: 3, major: 4, critical: 5 })[item.severity as 'warning' | 'minor' | 'major' | 'critical'] || 2
  }
  return [...alarms.value].sort((a, b) => rank(b) - rank(a)).slice(start, start + alarmPageSize.value)
})

// 详情对话框
const detailDialogVisible = ref(false)
const currentAlarm = ref<any>(null)
const linkedAlarmError = ref('')
let linkedAlarmEpoch = 0

const bindAlarmSelection = (alarm: any) => {
  const device = devices.value.find((entry) => entry.id === alarm.device_id)
  const deviceName = alarm.device_name || device?.hostname || (alarm.device_id ? `设备 #${alarm.device_id}` : '未关联设备')
  const label = `${deviceName} · ${alarmTypeLabel(alarm.alarm_type)}`
  const detail = [
    alarm.fired_at ? formatApiTime(alarm.fired_at) : '',
    alarm.message,
  ].filter(Boolean).join(' · ').slice(0, 160)
  if (device) {
    labCtx.setDevice({ id: device.id, hostname: device.hostname, mgmt_ip: device.mgmt_ip, model: device.model })
  }
  labCtx.setAlarm({ id: alarm.id, label, detail, device_id: alarm.device_id })
}

const onAlarmRowClick = (row: any) => {
  bindAlarmSelection(row)
}

const openWebSSH = (alarm: any) => {
  bindAlarmSelection(alarm)
  if (alarm.device_id) router.push(`/webssh/${alarm.device_id}`)
  else router.push('/webssh')
}

function openDeviceObservation(alarm: AlarmRecord) {
  bindAlarmSelection(alarm)
  detailDialogVisible.value = false
  const action = ospfAlarm(alarm.alarm_type) ? 'ospf_peer' : 'interface_brief'
  void router.push({ path: '/devices', query: { observe_device: alarm.device_id, observe_action: action } })
}

function clearFilters() {
  filterStatus.value = null
  filterDevice.value = null
  void router.replace({ path: '/alarms' })
}

// 加载设备列表
const loadDevices = async () => {
  await deviceRequest.run(() => getDevices(), value => { devices.value = value })
}

// 加载告警列表（翻页/轮询都走这里：**不要重置页码**，否则 15s 轮询会把用户正在看的第 2 页打回第 1 页）
// silent：轮询失败不弹 toast，避免每 15 秒弹一条
const loadAlarms = async (opts?: { silent?: boolean }) => {
  const params: { status?: string; device_id?: number; limit?: number } = { limit: 1000 }
  if (filterStatus.value) params.status = filterStatus.value
  if (filterDevice.value) params.device_id = filterDevice.value
  await alarmRequest.run(() => getAlarms(params, { silent: opts?.silent }), value => {
    alarms.value = value
    alarmPage.value = Math.min(alarmPage.value, Math.max(1, Math.ceil(alarms.value.length / alarmPageSize.value)))
  })
}

// 确认告警
const handleAcknowledge = async (alarm: AlarmRecord) => {
  try {
    await ElMessageBox.confirm('确认表示已接手处理；告警仍然活跃，不会修复设备或结束故障。', '确认告警', { type: 'warning' })
    await acknowledgeAlarm(alarm.id)
    ElMessage.success('告警已确认')
    loadAlarms()
  } catch (error: any) {
    if (error !== 'cancel') { /* 拦截器已提示 */ }
  }
}

// 关闭告警
const handleClose = async (alarm: AlarmRecord) => {
  try {
    await ElMessageBox.confirm('关闭仅结束这条告警记录，不修复设备；如条件仍异常，后续采集可再次产生告警。', '关闭告警', { type: 'warning' })
    await closeAlarm(alarm.id)
    ElMessage.success('告警已关闭')
    loadAlarms()
  } catch (error: any) {
    if (error !== 'cancel') { /* 拦截器已提示 */ }
  }
}

// 查看详情
const handleViewDetail = (alarm: AlarmRecord) => {
  linkedAlarmEpoch++
  linkedAlarmError.value = ''
  currentAlarm.value = alarm
  detailDialogVisible.value = true
  bindAlarmSelection(alarm)
}

async function loadLinkedAlarm() {
  const epoch = ++linkedAlarmEpoch
  linkedAlarmError.value = ''
  const id = Number(route.query.alarm_id)
  if (route.path !== '/alarms' || !Number.isSafeInteger(id) || id < 1) return
  const stillCurrent = () => epoch === linkedAlarmEpoch && route.path === '/alarms' && Number(route.query.alarm_id) === id
  try {
    const [alarm] = await getAlarms({ alarm_id: id, limit: 1 }, { silent: true })
    if (!stillCurrent()) return
    if (alarm?.id === id) handleViewDetail(alarm)
    else linkedAlarmError.value = '找不到这条告警。可查看列表中的其他记录。'
  } catch {
    if (stillCurrent()) linkedAlarmError.value = '暂时无法读取这条告警，请重试。'
  }
}

watch(() => route.query.alarm_id, loadLinkedAlarm)

onMounted(() => {
  const qid = Number(route.query.device_id || 0)
  if (qid) filterDevice.value = qid
  // 首页/大盘传 active，包含未处理和已确认；单独 fired 筛选仍可用。
  const qstatus = String(route.query.status || '').trim()
  if (qstatus) filterStatus.value = qstatus
  loadDevices()
  loadAlarms()
  void loadLinkedAlarm()
  // 轮询静默：失败不弹 toast（页面顶部仍有数据提示），否则后端一挂每 15s 弹一条
  useAutoRefresh(() => loadAlarms({ silent: true }), 15000)
})

// 筛选条件变化才回到第 1 页（轮询不动页码）
watch([filterStatus, filterDevice], () => {
  alarmPage.value = 1
  loadAlarms()
})
</script>

<style scoped>
/* page-root 已有 16px 内边距，不再叠加 */
.alarm-view { padding: 0; }
.alarm-help {color:var(--v7b-muted);line-height:1.65}
</style>
