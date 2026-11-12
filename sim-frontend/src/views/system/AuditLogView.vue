<template>
  <div class="audit-log v7b-page">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>审计日志</span>
          <div class="filters">
            <el-select v-model="filterModule" placeholder="模块" clearable style="width: 120px; margin-right: 8px">
              <el-option label="认证" value="auth" />
              <el-option label="设备" value="device" />
              <el-option label="下发" value="deploy" />
              <el-option label="监控" value="monitor" />
              <el-option label="AI" value="ai" />
              <el-option label="训练" value="training" />
            </el-select>
            <el-button @click="loadLogs">刷新</el-button>
          </div>
        </div>
      </template>
      <el-alert v-if="loadError" :title="loadError" type="warning" :closable="false" show-icon />
      <el-table :data="logs" v-loading="loading">
        <template #empty>
          <el-empty :description="loadError || '暂无审计日志。'" :image-size="72" />
        </template>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="username" label="用户" width="100" />
        <el-table-column prop="module" label="模块" width="110">
          <template #default="{ row }">
            <el-tag size="small" :title="row.module">{{ auditModuleLabel(row.module) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="150"><template #default="{row}">{{ auditActionLabel(row.action) }}</template></el-table-column>
        <el-table-column prop="resource_type" label="资源类型" width="100" />
        <el-table-column prop="resource_id" label="资源ID" min-width="160" show-overflow-tooltip />
        <el-table-column prop="detail" label="摘要" min-width="220" show-overflow-tooltip />
        <el-table-column label="详情" width="85" fixed="right"><template #default="{row}"><el-button type="primary" link @click="currentLog=row; detailVisible=true">查看</el-button></template></el-table-column>
        <el-table-column prop="ip_address" label="IP地址" width="130" />
        <el-table-column prop="result" label="结果" width="80">
          <template #default="{ row }">
            <el-tag :type="row.result === 'success' ? 'success' : ['failed','error'].includes(row.result) ? 'danger' : 'info'" size="small" :title="row.result">{{ auditResultLabel(row.result) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-if="!loadError || logs.length"
        v-model:current-page="page"
        :page-size="20"
        :total="total"
        layout="total, prev, pager, next"
        style="margin-top: 16px; justify-content: flex-end"
        @current-change="loadLogs"
      />
    </el-card>
    <el-dialog v-model="detailVisible" class="v7b-record-dialog" top="4vh" title="审计记录详情" width="min(820px, 94vw)">
      <template v-if="currentLog"><el-descriptions :column="2" border><el-descriptions-item label="记录">#{{ currentLog.id }}</el-descriptions-item><el-descriptions-item label="用户">{{ currentLog.username }}</el-descriptions-item><el-descriptions-item label="操作">{{ auditActionLabel(currentLog.action) }}</el-descriptions-item><el-descriptions-item label="原始动作码">{{ currentLog.action }}</el-descriptions-item><el-descriptions-item label="对象">{{ currentLog.resource_type }} #{{ currentLog.resource_id }}</el-descriptions-item><el-descriptions-item label="记录时间">{{ formatTime(currentLog.created_at) }}</el-descriptions-item></el-descriptions><p>审计记录说明谁在何时进行了操作；审批记录不等于设备已执行，执行及恢复以任务结果为准。</p><pre class="audit-detail">{{ formatDetail(currentLog.detail) }}</pre></template>
      <template #footer><el-button @click="detailVisible=false">返回</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { formatApiTime } from '../../utils/datetime'
import { ref, onMounted, watch } from 'vue'
import { useSnapshotRequest } from '../../composables/useSnapshotRequest'
import { getAuditLogs } from '@/api/system'
import { auditActionLabel, auditModuleLabel, auditResultLabel } from '../../utils/display'

interface AuditLog {
  id: number; user_id: number; username: string; module: string; action: string
  resource_type: string | null; resource_id: string | null; detail: string | null
  ip_address: string | null; result: string; created_at: string
}

const logs = ref<AuditLog[]>([])
const auditRequest = useSnapshotRequest('审计列表')
const loading = auditRequest.loading
const loadError = auditRequest.error
const detailVisible=ref(false),currentLog=ref<AuditLog|null>(null)
const formatDetail=(value:string|null)=>{try{return JSON.stringify(JSON.parse(value||''),null,2)}catch{return value||'无附加详情'}}
const page = ref(1)
const total = ref(0)
const filterModule = ref('')

const formatTime = (iso: string) => formatApiTime(iso)

const loadLogs = async () => {
  const params: Record<string, unknown> = { page: page.value, page_size: 20 }
  if (filterModule.value) params.module = filterModule.value
  await auditRequest.run(async () => await getAuditLogs(params as Parameters<typeof getAuditLogs>[0]) as unknown as { items: AuditLog[]; total: number }, res => {
    logs.value = res.items
    total.value = res.total
  })
}

watch(filterModule, () => { page.value = 1; loadLogs() })

onMounted(loadLogs)
</script>

<style scoped>
.card-header { display: flex; justify-content: space-between; align-items: center; flex-wrap:wrap;gap:12px }
.filters { display: flex; align-items: center; }
.audit-detail { max-height:50vh;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:var(--v7b-surface-2);padding:12px;color:var(--v7b-text);font-size:13px;line-height:1.7 }
</style>
