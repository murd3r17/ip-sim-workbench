<template>
  <div class="log-file v7b-page">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>日志文件</span>
          <el-button :loading="loading" @click="loadFiles">刷新</el-button>
        </div>
      </template>
      <el-alert v-if="loadError" :title="loadError" type="warning" :closable="false" show-icon />
      <el-table :data="files" v-loading="loading">
        <template #empty>
          <el-empty :description="loadError||'暂无日志文件。'" :image-size="72" />
        </template>
        <el-table-column prop="filename" label="文件名" width="200" />
        <el-table-column label="大小" width="120">
          <template #default="{ row }">{{ formatSize(row.size_bytes) }}</template>
        </el-table-column>
        <el-table-column prop="lines" label="行数" width="80" />
        <el-table-column prop="last_modified" label="最后修改" width="180">
          <template #default="{ row }">{{ formatApiTime(row.last_modified) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button size="small" @click="viewLog(row.filename)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="logVisible" class="v7b-record-dialog log-reader" top="4vh" :title="`日志: ${currentFile}`" width="min(1000px,94vw)" draggable>
      <p class="log-scope">最近最多 500 行 · 本次只读结果</p>
      <el-alert v-if="readError" :title="readError" type="warning" :closable="false" show-icon />
      <p v-if="reading" role="status">正在读取所选日志…</p>
      <pre v-else-if="!readError" class="log-content">{{ logContent || '本次返回没有日志内容。' }}</pre>
      <template #footer><el-button v-if="readError" :loading="reading" @click="viewLog(currentFile)">重试读取</el-button><el-button @click="logVisible=false">返回列表</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { notifyRequestError } from '../../utils/requestError'
import { formatApiTime } from '../../utils/datetime'
import { listLogFiles, readLogFile } from '@/api/system'

interface LogFile { filename: string; size_bytes: number; last_modified: string; lines: number }

const files = ref<LogFile[]>([])
const loading = ref(false)
const logVisible = ref(false)
const currentFile = ref('')
const logContent = ref('')
const loadError=ref(''),readError=ref(''),reading=ref(false)
let loadEpoch=0,readEpoch=0
watch(logVisible,visible=>{if(!visible){readEpoch++;reading.value=false}},{flush:'sync'})

const formatSize = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1048576).toFixed(1)} MB`
}
const loadFiles = async () => {
  const epoch=++loadEpoch
  loading.value = true
  try {
    const result=await listLogFiles() as unknown as LogFile[]
    if(epoch!==loadEpoch)return
    files.value=result;loadError.value=''
  } catch (error) {
    if(epoch===loadEpoch){loadError.value='日志列表读取失败；已有列表可能陈旧，请刷新重试。';notifyRequestError(error, '加载日志列表失败')}
  } finally {
    if(epoch===loadEpoch)loading.value = false
  }
}

const viewLog = async (filename: string) => {
  const epoch=++readEpoch
  currentFile.value = filename
  logVisible.value=true;logContent.value='';readError.value='';reading.value=true
  try {
    const res = await readLogFile(filename, 500) as unknown as { content: string }
    if(epoch!==readEpoch)return
    logContent.value = res.content
  } catch (error) {
    if(epoch===readEpoch){readError.value='所选日志未能读取，请重试。';notifyRequestError(error, '读取日志失败')}
  } finally {if(epoch===readEpoch)reading.value=false}
}

onMounted(loadFiles)
onUnmounted(()=>{loadEpoch++;readEpoch++})
</script>

<style scoped>
.card-header { display: flex; justify-content: space-between; align-items: center; gap:12px;flex-wrap:wrap }
.log-scope{font-size:12px;color:var(--v7b-muted)}.log-content{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.8 Consolas,monospace;color:var(--v7b-text);background:var(--v7b-surface-2);padding:12px;border:1px solid var(--v7b-line);border-radius:6px;max-height:65vh;overflow:auto}
</style>
