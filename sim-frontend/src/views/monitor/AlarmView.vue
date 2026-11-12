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
              <el-option label="已确认" value="acknowledged" />
              <el-option label="已解决" value="resolved" />
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
      <p class="alarm-help">确认表示已接手；关闭表示结束记录。处理状态不等于设备或业务恢复；请核对监控中的最近采样。</p>
      <el-table :data="pagedAlarms" v-loading="loading" @row-click="onAlarmRowClick">
        <template #empty>
          <el-empty :description="loadError || '暂无告警记录'" :image-size="72">
            <el-button type="primary" @click="$router.push('/monitor')">去监控大盘</el-button>
          </el-empty>
        </template>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="device_id" label="设备ID" width="80" />
        <el-table-column label="告警类型" min-width="160"><template #default="{ row }">{{ alarmTypeLabel(row.alarm_type) }}</template></el-table-column>
        <el-table-column prop="severity" label="严重程度" width="100">
          <template #default="{ row }">
            <el-tag :type="getSeverityType(row.severity)">{{ getSeverityLabel(row.severity) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="告警信息" min-width="230" show-overflow-tooltip />
        <el-table-column prop="metric_value" label="指标值" width="100" />
        <el-table-column prop="threshold" label="阈值" width="80" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)">{{ getStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="触发时间" width="180">
          <template #default="{ row }">{{ formatApiTime(row.fired_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'fired'" type="warning" link @click.stop="handleAcknowledge(row)">确认</el-button>
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
          <el-tag :type="getSeverityType(currentAlarm?.severity)">{{ getSeverityLabel(currentAlarm?.severity) }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="getStatusType(currentAlarm?.status)">{{ getStatusLabel(currentAlarm?.status) }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="指标值">{{ currentAlarm?.metric_value }}</el-descriptions-item>
        <el-descriptions-item label="阈值">{{ currentAlarm?.threshold }}</el-descriptions-item>
        <el-descriptions-item label="触发时间">{{ formatApiTime(currentAlarm?.fired_at) }}</el-descriptions-item>
        <el-descriptions-item label="确认时间">{{ formatApiTime(currentAlarm?.acknowledged_at) }}</el-descriptions-item>
        <el-descriptions-item label="解决时间">{{ formatApiTime(currentAlarm?.resolved_at) }}</el-descriptions-item>
        <el-descriptions-item label="关闭时间">{{ formatApiTime(currentAlarm?.closed_at) }}</el-descriptions-item>
      </el-descriptions>
      <el-alert :title="alarmMeaning(currentAlarm?.alarm_type)" type="info" :closable="false" show-icon style="margin-top: 12px" />
      <p class="alarm-help">这是保存的告警记录。确认、解决、关闭时间各有含义；当前设备状态请核对新的观察。</p>
      <div style="margin-top: 16px">
        <h4>告警信息</h4>
        <p>{{ currentAlarm?.message }}</p>
        <details><summary>原始动作类型</summary>{{ currentAlarm?.alarm_type }}</details>
      </div>
      <div v-if="currentAlarm?.device_id" style="margin-top: 12px">
        <el-button type="primary" @click="openWebSSH(currentAlarm)">打开 WebSSH</el-button>
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
  alarmTypeLabel, alarmMeaning,
} from '../../utils/display'
import { useAiCopilotStore } from '../../stores/aiCopilot'
import { useLabContextStore } from '../../stores/labContext'

const copilot = useAiCopilotStore()
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
const alarmPage = ref(1)
const alarmPageSize = ref(20)
const pagedAlarms = computed(() => {
  const start = (alarmPage.value - 1) * alarmPageSize.value
  return alarms.value.slice(start, start + alarmPageSize.value)
})

// 详情对话框
const detailDialogVisible = ref(false)
const currentAlarm = ref<any>(null)

const bindAlarmSelection = (alarm: any) => {
  labCtx.setAlarm({
    id: alarm.id,
    label: alarm.alarm_type || `告警#${alarm.id}`,
    detail: `${alarm.severity || ''} ${alarm.message || ''}`.trim().slice(0, 120),
    device_id: alarm.device_id,
  })
  if (alarm.device_id) {
    const d = devices.value.find((x) => x.id === alarm.device_id)
    if (d) {
      labCtx.setDevice({ id: d.id, hostname: d.hostname, mgmt_ip: d.mgmt_ip })
    }
  }
  copilot.setSelection({
    kind: 'alarm',
    id: alarm.id,
    label: alarm.alarm_type || `告警#${alarm.id}`,
    detail: `${alarm.severity || ''} ${alarm.message || ''}`.trim().slice(0, 120),
  })
  if (!copilot.open) copilot.setOpen(true)
}

const onAlarmRowClick = (row: any) => {
  bindAlarmSelection(row)
}

const openWebSSH = (alarm: any) => {
  bindAlarmSelection(alarm)
  if (alarm.device_id) router.push(`/webssh/${alarm.device_id}`)
  else router.push('/webssh')
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
const handleViewDetail = (alarm: any) => {
  currentAlarm.value = alarm
  detailDialogVisible.value = true
  bindAlarmSelection(alarm)
}


onMounted(() => {
  const qid = Number(route.query.device_id || 0)
  if (qid) filterDevice.value = qid
  // 首页/大盘传 active，包含未处理和已确认；单独 fired 筛选仍可用。
  const qstatus = String(route.query.status || '').trim()
  if (qstatus) filterStatus.value = qstatus
  loadDevices()
  loadAlarms()
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
