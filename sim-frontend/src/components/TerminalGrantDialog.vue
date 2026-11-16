<template>
  <el-dialog :model-value="true" :title="`${account.username} 的终端授权`"
    class="v7b-record-dialog" top="4vh" width="min(720px, 94vw)"
    :show-close="!saving" :close-on-click-modal="!saving" :close-on-press-escape="!saving" @close="$emit('close')">
    <p>授权后，学员可以修改所选设备的配置。请选择实训设备和有效期。未授权的学员可以从设备页做只读观察。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false">
      <el-button link @click="load">重新读取</el-button>
    </el-alert>
    <el-form v-loading="loading" label-position="top" @submit.prevent="save">
      <el-form-item label="授权设备">
        <el-select v-model="deviceId" aria-label="授权设备" filterable :disabled="saving || loading">
          <el-option v-for="device in devices" :key="device.id" :value="device.id"
            :label="`${device.hostname} · ${device.mgmt_ip}:${device.ssh_port ?? 22}`" />
        </el-select>
      </el-form-item>
      <el-form-item label="有效期（分钟）">
        <el-input-number v-model="minutes" aria-label="有效期（分钟）"
          :min="5" :max="1440" :step="5" :precision="0" :disabled="saving" />
      </el-form-item>
      <el-form-item label="授权说明（选填）">
        <el-input v-model="note" aria-label="授权说明" :maxlength="240" :disabled="saving" />
      </el-form-item>
      <el-button native-type="submit" type="primary" :loading="saving"
        :disabled="!deviceId || !minutes || loading || !loaded">{{ selectedGrant ? '重新授权' : '授予终端权限' }}</el-button>
    </el-form>
    <el-table :data="grants" empty-text="暂无终端授权" aria-label="该账号的终端授权">
      <el-table-column label="授权设备" min-width="170">
        <template #default="{ row }">{{ deviceName(row) }} · {{ row.management_address }}:{{ row.ssh_port }}</template>
      </el-table-column>
      <el-table-column label="到期时间" min-width="156">
        <template #default="{ row }">{{ formatApiTime(row.expires_at) }}</template>
      </el-table-column>
      <el-table-column label="状态" min-width="108">
        <template #default="{ row }">
          <span v-if="row.revoked_at">已撤销</span>
          <span v-else-if="Date.parse(row.expires_at) <= now">已到期</span>
          <el-button v-else link type="danger" :disabled="saving" @click="revoke(row)">撤销授权</el-button>
        </template>
      </el-table-column>
    </el-table>
    <template #footer><el-button :disabled="saving" @click="$emit('close')">关闭</el-button></template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus/es/components/message/index'
import { issueTerminalGrant, listTerminalGrants, revokeTerminalGrant, type Account, type TerminalGrant } from '../api/auth'
import { getDevices, type DeviceRecord } from '../api/device'
import { formatApiTime } from '../utils/datetime'
import { requestErrorMessage } from '../utils/requestError'

const { account } = defineProps<{ account: Account }>()
defineEmits<{ close: [] }>()
const grants = ref<TerminalGrant[]>([])
const devices = ref<DeviceRecord[]>([])
const deviceId = ref<number>()
const minutes = ref<number | undefined>(60)
const note = ref('')
const loading = ref(false)
const loaded = ref(false)
const saving = ref(false)
const error = ref('')
const now = ref(Date.now())
const selectedGrant = computed(() => grants.value.find(grant => grant.device_id === deviceId.value))
const clock = window.setInterval(() => { now.value = Date.now() }, 1000)
onUnmounted(() => window.clearInterval(clock))

function deviceName(grant: TerminalGrant) {
  return devices.value.find(device => device.id === grant.device_id)?.hostname || `设备 #${grant.device_id}`
}

async function load() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    const [inventory, permissions] = await Promise.all([getDevices(), listTerminalGrants(account.id)])
    devices.value = inventory
    grants.value = permissions
    loaded.value = true
  } catch (cause) {
    error.value = requestErrorMessage(cause, '无法读取设备和授权，请重试。')
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!loaded.value || !deviceId.value || !minutes.value || saving.value) return
  saving.value = true
  error.value = ''
  try {
    await issueTerminalGrant(account.id, deviceId.value, minutes.value, note.value.trim())
    ElMessage.success('已授予终端权限')
    await load()
  } catch (cause) {
    error.value = requestErrorMessage(cause, '授予权限失败，请重试。')
  } finally {
    saving.value = false
  }
}

async function revoke(grant: TerminalGrant) {
  if (saving.value) return
  saving.value = true
  error.value = ''
  try {
    await revokeTerminalGrant(account.id, grant)
    ElMessage.success('已撤销。学员的该设备连接将断开。')
    await load()
  } catch (cause) {
    error.value = requestErrorMessage(cause, '撤销失败，请刷新后核对。')
  } finally {
    saving.value = false
  }
}
onMounted(load)
</script>
