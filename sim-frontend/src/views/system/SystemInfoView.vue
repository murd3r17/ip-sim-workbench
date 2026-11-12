<template>
  <div class="system-info">
    <el-alert
      v-if="loadError"
      type="error"
      show-icon
      :closable="false"
      :title="loadError"
      style="margin-bottom: 12px"
    >
      <template #default>
        <el-button size="small" type="primary" :loading="loading" @click="loadInfo">重试</el-button>
      </template>
    </el-alert>
    <div class="info-grid" v-loading="loading">
      <el-card shadow="never" class="info-card">
        <template #header><span>系统概览</span></template>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="应用名称">{{ info.app_name }}</el-descriptions-item>
          <el-descriptions-item label="版本">{{ info.app_version }}</el-descriptions-item>
          <el-descriptions-item label="Python版本">{{ info.python_version }}</el-descriptions-item>
          <el-descriptions-item label="运行时间">{{ formatUptime(info.uptime_seconds as number) }}</el-descriptions-item>
          <el-descriptions-item label="日志级别">{{ info.log_level }}</el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card shadow="never" class="info-card">
        <template #header><span>组件状态</span></template>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="数据库">
            <el-tag :type="info.database_status === 'healthy' ? 'success' : 'info'" size="small" :title="String(info.database_status || '未取得状态')">{{ healthLabel(info.database_status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="LLM">
            <el-tag :type="info.llm_status === 'healthy' ? 'success' : 'warning'" size="small" :title="String(info.llm_status || '未取得状态')">{{ healthLabel(info.llm_status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="LLM提供商">{{ info.llm_provider }}</el-descriptions-item>
          <el-descriptions-item label="LLM模型">{{ info.llm_model }}</el-descriptions-item>
          <el-descriptions-item label="Fernet加密">
            <el-tag :type="info.fernet_configured ? 'success' : 'warning'" size="small">{{ info.fernet_configured === true ? '已配置' : info.fernet_configured === false ? '未配置' : '尚未读取' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="JWT密钥">
            <el-tag :type="info.jwt_configured ? 'success' : 'warning'" size="small">{{ info.jwt_configured === true ? '已配置' : info.jwt_configured === false ? '未配置' : '尚未读取' }}</el-tag>
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card shadow="never" class="info-card">
        <template #header><span>资源统计</span></template>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="设备数量">{{ info.device_count ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="用户数量">{{ info.user_count ?? '—' }}</el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card shadow="never" class="info-card hint-card">
        <template #header><span>助手对接</span></template>
        <p>右侧 AI 助手可结合本页解释系统模块用途。配置项请在「系统配置」中维护；密钥状态以本页组件状态为准。</p>
        <div class="hint-actions">
          <el-button link type="primary" @click="$router.push('/system/config')">系统配置</el-button>
          <el-button link type="primary" @click="$router.push('/system/audit')">审计日志</el-button>
          <el-button link type="primary" @click="$router.push('/dashboard')">返回总览</el-button>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { notifyRequestError } from '../../utils/requestError'
import { getSystemInfo } from '@/api/system'

const info = ref<Record<string, unknown>>({
  app_name: '', app_version: '', python_version: '', uptime_seconds: 0,
  log_level: '', database_status: '', llm_status: '', llm_provider: '', llm_model: '',
  fernet_configured: null, jwt_configured: null, device_count: null, user_count: null,
})
const loadError = ref('')
const loading = ref(false)
const healthLabel=(value:unknown)=>({healthy:'连接正常',unavailable:'当前不可用',unhealthy:'检查异常',not_configured:'尚未配置',degraded:'降级',unknown:'状态未知'}[String(value)]||value||'尚未读取')

const formatUptime = (seconds: number) => {
  if (!seconds) return '-'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return h > 0 ? `${h}小时${m}分钟` : `${m}分钟`
}

const loadInfo = async () => {
  loading.value = true
  try {
    info.value = await getSystemInfo() as unknown as Record<string, unknown>
    loadError.value = ''
  } catch (error) {
    loadError.value = '系统信息读取失败；已有显示可能陈旧，请检查后端连接并重试。'
    notifyRequestError(error, '获取系统信息失败')
  } finally {
    loading.value = false
  }
}

onMounted(loadInfo)
</script>

<style scoped>
.system-info {
  min-height: 100%;
  display: flex;
  flex-direction: column;
}
.info-grid {
  flex: 1;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  grid-auto-rows: minmax(180px, auto);
  gap: 16px;
  align-content: stretch;
}
.info-card {
  min-height: 100%;
}
.hint-card p {
  margin: 0;
  color: var(--v7b-muted);
  font-size: 13px;
  line-height: 1.6;
}
.hint-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}
@media (max-width: 960px) {
  .info-grid { grid-template-columns: 1fr; }
}
</style>
