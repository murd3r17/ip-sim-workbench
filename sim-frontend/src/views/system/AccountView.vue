<template>
  <div class="v7b-page">
    <PageHeader title="账号管理" subtitle="发放账号，或为忘记密码的学员重置密码。">
      <template #actions><el-button type="primary" @click="openCreate">创建账号</el-button></template>
    </PageHeader>
    <el-card shadow="never">
      <div class="account-toolbar">
        <el-input v-model="search" aria-label="搜索账号" placeholder="搜索用户名或显示名称" clearable @keyup.enter="searchAccounts" />
        <el-button @click="searchAccounts">搜索</el-button>
      </div>
      <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" />
      <el-table :data="accounts" v-loading="loading" row-key="id" empty-text="没有匹配的账号">
        <el-table-column prop="username" label="用户名" min-width="140" />
        <el-table-column prop="display_name" label="显示名称" min-width="120" />
        <el-table-column label="角色" width="100"><template #default="{ row }">{{ row.role === 'admin' ? '管理员' : '普通用户' }}</template></el-table-column>
        <el-table-column label="状态" width="90"><template #default="{ row }">{{ row.is_active ? '启用' : '已停用' }}</template></el-table-column>
        <el-table-column label="最近登录" width="170"><template #default="{ row }">{{ row.last_login_at ? formatApiTime(row.last_login_at) : '尚未登录' }}</template></el-table-column>
        <el-table-column label="操作" width="124"><template #default="{ row }">
          <el-button v-if="row.role === 'user'" link type="primary" :aria-label="`重置 ${row.username} 的密码`" @click="openReset(row)">重置密码</el-button>
        </template></el-table-column>
      </el-table>
      <div v-if="offset || accounts.length === 50" class="account-toolbar pages">
        <el-button :disabled="!offset || loading" @click="changePage(-50)">上一页</el-button>
        <el-button :disabled="accounts.length !== 50 || loading" @click="changePage(50)">下一页</el-button>
      </div>
    </el-card>
    <el-dialog v-model="editorOpen" :title="selected ? `重置 ${selected.username} 的密码` : '创建账号'"
      class="v7b-record-dialog" top="4vh" width="min(520px, 94vw)" :show-close="!saving"
      :close-on-click-modal="!saving" :close-on-press-escape="!saving" @closed="clearInputs">
      <el-form label-position="top" @submit.prevent="save">
        <template v-if="!selected">
          <el-form-item label="用户名"><el-input v-model="form.username" :maxlength="64" autocomplete="off" :disabled="saving" /></el-form-item>
          <el-form-item label="显示名称（选填）"><el-input v-model="form.display_name" :maxlength="128" :disabled="saving" /></el-form-item>
          <el-form-item label="角色">
            <el-radio-group v-model="form.role" :disabled="saving">
              <el-radio value="user">普通用户</el-radio><el-radio value="admin">管理员</el-radio>
            </el-radio-group>
          </el-form-item>
        </template>
        <el-form-item :label="selected ? '新密码' : '初始密码'">
          <el-input v-model="form.password" type="password" autocomplete="new-password" :disabled="saving" />
        </el-form-item>
        <p class="account-hint">至少 8 个字符，包含大小写字母和数字。</p>
        <p v-if="selected" class="account-hint">保存后，此账号之前的登录会失效。请把新密码发给账号使用人。</p>
        <p v-else class="account-hint">把用户名和初始密码交给使用人。他们登录后可从右上角修改密码。</p>
        <el-alert v-if="saveError" :title="saveError" type="error" :closable="false" />
      </el-form>
      <template #footer>
        <el-button :disabled="saving" @click="editorOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">{{ selected ? '重置密码' : '创建账号' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus/es/components/message/index'
import PageHeader from '../../components/v7b/PageHeader.vue'
import { createAccount, listAccounts, resetTraineePassword, type Account } from '../../api/auth'
import { useSnapshotRequest } from '../../composables/useSnapshotRequest'
import { formatApiTime } from '../../utils/datetime'
import { requestErrorMessage } from '../../utils/requestError'

const search = ref('')
const appliedSearch = ref('')
const offset = ref(0)
const accounts = ref<Account[]>([])
const { run, loading, error: loadError } = useSnapshotRequest('账号列表')
const editorOpen = ref(false)
const selected = ref<Account | null>(null)
const saving = ref(false)
const saveError = ref('')
const blank = () => ({ username: '', display_name: '', password: '', role: 'user' as Account['role'] })
const form = ref(blank())

function load() {
  return run(() => listAccounts({ q: appliedSearch.value, offset: offset.value }), result => { accounts.value = result })
}
function searchAccounts() {
  appliedSearch.value = search.value.trim()
  offset.value = 0
  void load()
}
function changePage(step: number) {
  offset.value = Math.max(0, offset.value + step)
  void load()
}
function clearInputs() {
  form.value = blank()
  saveError.value = ''
}
function openCreate() {
  selected.value = null
  clearInputs()
  editorOpen.value = true
}
function openReset(account: Account) {
  selected.value = account
  clearInputs()
  editorOpen.value = true
}
async function save() {
  if (saving.value) return
  if (!form.value.password || (!selected.value && !form.value.username.trim())) {
    saveError.value = selected.value ? '请填写新密码。' : '请填写用户名和初始密码。'
    return
  }
  saving.value = true
  saveError.value = ''
  try {
    if (selected.value) {
      await resetTraineePassword(selected.value.id, form.value.password)
      ElMessage.success('密码已重置，原登录凭据已失效')
    } else {
      const created = await createAccount({ ...form.value, username: form.value.username.trim() })
      search.value = created.username
      searchAccounts()
      ElMessage.success(`已创建账号 ${created.username}`)
    }
    editorOpen.value = false
    clearInputs()
  } catch (error) {
    saveError.value = requestErrorMessage(error, '操作未完成，请稍后重试。')
  } finally {
    saving.value = false
  }
}
onMounted(load)
</script>

<style scoped>
.account-toolbar { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.account-toolbar .el-input { width: min(100%, 280px); }
.pages { justify-content: flex-end; margin: 12px 0 0; }
.account-hint { color: var(--v7b-muted); line-height: 1.6; margin: 8px 0; }
</style>
