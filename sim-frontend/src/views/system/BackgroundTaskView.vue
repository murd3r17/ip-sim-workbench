<template>
  <div class="background-task v7b-page">
    <div class="v7b-card task-entry-help"><strong>按任务类型进入对应页面</strong><p>这里展示接入后台任务表的记录；网络下发、巡检与实训各有独立进度入口。</p><div><el-button @click="$router.push({path:'/deploy',query:{tab:'tasks'}})">下发任务管理</el-button><el-button @click="$router.push('/monitor')">采集与巡检</el-button><el-button @click="$router.push('/training')">实训会话</el-button></div></div>
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>后台任务</span>
          <div class="filters">
            <el-select v-model="filterStatus" placeholder="状态" clearable style="width: 120px; margin-right: 8px">
              <el-option label="等待中" value="pending" />
              <el-option label="运行中" value="running" />
              <el-option label="成功" value="success" />
              <el-option label="失败" value="failed" />
              <el-option label="已取消" value="cancelled" />
            </el-select>
            <el-button @click="loadTasks">刷新</el-button>
          </div>
        </div>
      </template>
      <RecordOriginFilter v-model="originFilter" :records="tasks" :unavailable="!!loadError" />
      <el-alert v-if="loadError" :title="loadError" type="warning" :closable="false" show-icon />
      <p class="source-note">旧后台表没有来源字段；只有明确测试类型归为测试，其余保留为来源未明。名称和模拟模式不决定分类。</p>
      <el-table :data="pagedTasks" v-loading="loading">
        <template #empty>
          <el-empty :description="loadError || (tasks.length ? '当前来源筛选没有匹配记录，可恢复全部来源。' : '暂无后台任务')" :image-size="72" />
        </template>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="task_name" label="任务名称" width="200" />
        <el-table-column prop="task_type" label="类型" width="100">
          <template #default="{ row }">
            <el-tag size="small">{{ row.task_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="记录来源" min-width="130"><template #default="{row}">{{ recordOriginLabel(row.record_origin) }}</template></el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="120">
          <template #default="{ row }">
            <el-progress :percentage="row.progress" :status="row.status === 'failed' ? 'exception' : row.status === 'success' ? 'success' : undefined" :stroke-width="10" />
          </template>
        </el-table-column>
        <el-table-column prop="error_message" label="错误信息" show-overflow-tooltip />
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
      <div v-if="tasks.length" style="margin-top: 12px; display: flex; justify-content: flex-end">
        <el-pagination
          v-model:current-page="taskPage"
          v-model:page-size="taskPageSize"
          :total="visibleTasks.length"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { formatApiTime } from '../../utils/datetime'
import { ref, computed, onMounted, watch } from 'vue'
import { listBackgroundTasks } from '@/api/system'
import { taskStatusLabel as statusLabel, taskStatusTagType as statusType } from '../../utils/display'
import RecordOriginFilter from '../../components/RecordOriginFilter.vue'
import {filterByRecordOrigin,recordOriginLabel} from '../../utils/recordOrigin'

interface TaskItem {
  id: number; task_type: string; task_name: string; status: string
  progress: number; result: string | null; error_message: string | null
  created_at: string
  record_origin?: string
}

const tasks = ref<TaskItem[]>([])
const loading = ref(false)
const loadError = ref('')
const filterStatus = ref('')
const originFilter=ref('all')
const visibleTasks=computed(()=>filterByRecordOrigin(tasks.value,originFilter.value))
let loadEpoch=0
const taskPage = ref(1)
const taskPageSize = ref(20)
const pagedTasks = computed(() => {
  const start = (taskPage.value - 1) * taskPageSize.value
  return visibleTasks.value.slice(start, start + taskPageSize.value)
})

const formatTime = (iso: string) => formatApiTime(iso)

const loadTasks = async () => {
  const epoch=++loadEpoch
  loading.value = true
  try {
    const res = await listBackgroundTasks(filterStatus.value || undefined) as unknown as { items: TaskItem[] }
    if(epoch!==loadEpoch)return
    tasks.value = res.items || []
    loadError.value = ''
    taskPage.value = 1
  } catch {
    if(epoch===loadEpoch)loadError.value = '后台任务加载失败；保留的记录可能陈旧，请刷新重试。'
  } finally {
    if(epoch===loadEpoch)loading.value = false
  }
}

watch(filterStatus, loadTasks)
watch([originFilter,taskPageSize],()=>{taskPage.value=1})

onMounted(loadTasks)
</script>

<style scoped>
.card-header { display: flex; justify-content: space-between; align-items: center; flex-wrap:wrap;gap:12px }
.filters { display: flex; align-items: center;flex-wrap:wrap }
.task-entry-help{padding:16px}.task-entry-help p,.source-note{font-size:12px;color:var(--v7b-muted);line-height:1.8}.task-entry-help>div{display:flex;gap:10px;flex-wrap:wrap}.task-entry-help .el-button{margin-left:0}
</style>
