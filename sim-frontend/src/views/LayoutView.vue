<template>
  <div class="app-layout" @keydown.esc="closeNarrowPanel">
    <a class="skip-link" href="#main-content">跳到主要内容</a>
    <aside id="workbench-navigation" ref="navigation" class="app-aside" :class="{ narrow: collapsed, open: navOpen }" aria-label="主导航">
      <div class="logo">
        <span class="logo-mark">IP</span>
        <span v-if="!collapsed" class="logo-text">仿真运维工作台<small>Operations Center</small></span>
      </div>
      <el-menu
        :default-active="activePath"
        router
        class="nav-menu"
        @select="closeNavigation"
        @keydown="activateNavigationItem"
      >
        <el-menu-item-group title="总览">
          <el-menu-item index="/dashboard" tabindex="0">工作台</el-menu-item>
          <el-menu-item index="/topology" tabindex="0">拓扑</el-menu-item>
        </el-menu-item-group>
        <el-menu-item-group title="设备与变更">
          <el-menu-item index="/devices" tabindex="0">设备</el-menu-item>
          <el-menu-item index="/webssh" tabindex="0">终端</el-menu-item>
          <el-menu-item index="/deploy" tabindex="0">配置下发</el-menu-item>
          <el-menu-item index="/approvals" tabindex="0">变更审批</el-menu-item>
          <el-menu-item index="/config-versions" tabindex="0">配置版本</el-menu-item>
          <el-menu-item v-if="isAdmin" index="/environments" tabindex="0">环境映射</el-menu-item>
        </el-menu-item-group>
        <el-menu-item-group title="观测">
          <el-menu-item index="/monitor" tabindex="0">监控</el-menu-item>
          <el-menu-item index="/alarms" tabindex="0">告警</el-menu-item>
        </el-menu-item-group>
        <el-menu-item-group title="工具">
          <el-menu-item index="/training" tabindex="0">实训</el-menu-item>
          <el-menu-item index="/knowledge" tabindex="0">知识库</el-menu-item>
        </el-menu-item-group>
        <el-menu-item-group v-if="isAdmin" title="系统">
          <el-sub-menu index="system" tabindex="0">
            <template #title>系统管理</template>
            <el-menu-item index="/system/info" tabindex="0">系统信息</el-menu-item>
            <el-menu-item index="/system/config" tabindex="0">系统配置</el-menu-item>
            <el-menu-item index="/system/accounts" tabindex="0">账号管理</el-menu-item>
            <el-menu-item index="/system/audit" tabindex="0">审计日志</el-menu-item>
            <el-menu-item index="/system/tasks" tabindex="0">后台任务</el-menu-item>
            <el-menu-item index="/system/logs" tabindex="0">日志文件</el-menu-item>
          </el-sub-menu>
        </el-menu-item-group>
      </el-menu>
      <button class="collapse-btn" type="button" :title="navCollapsed ? '展开导航' : '收起导航'" @click="toggleNav">
        {{ navCollapsed ? '»' : '«' }}
      </button>
    </aside>
    <button v-if="navOpen" class="nav-scrim" aria-label="关闭导航" tabindex="-1" @click="closeNavigation"></button>

    <div class="center-wrap">
      <header class="app-header">
        <div class="header-title">
          <button ref="navToggle" class="mobile-nav-toggle" type="button" aria-label="打开导航" aria-controls="workbench-navigation" :aria-expanded="navOpen" @click="navOpen = !navOpen">☰</button>
          <div class="title-block">
            <span class="page-title">{{ route.name }}</span>
            <span class="page-context">{{ contextLabel }}</span>
          </div>
        </div>
        <div class="header-right">
          <span class="env-clock" :title="`${environmentName} · 当前时间`">
            <span class="env-dot"></span>
            <span class="env-name">{{ environmentName }}</span>
            <time>{{ currentTime }}</time>
          </span>
          <button
            v-if="labCtx.isActive"
            class="lab-resume"
            type="button"
            aria-haspopup="dialog"
            :title="`在当前页打开「${labCtx.label}」的实训会话`"
            @click="resumeTraining"
          >实训进行中 · {{ labCtx.label }}</button>
          <button ref="assistantToggle" class="ai-toggle" type="button" :class="{ on: copilot.open }" :aria-expanded="copilot.open" aria-controls="workbench-assistant" title="展开或收起 AI 助手" @click="copilot.toggle()">
            AI 助手
          </button>
          <el-dropdown trigger="click" @command="handleCommand">
            <span class="user-trigger"><i></i>{{ user?.username || '用户' }}</span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="password">修改密码</el-dropdown-item>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>
      <main id="main-content" class="app-main" :inert="narrowWindow && (copilot.open || navOpen)">
        <el-alert v-if="route.query.access === 'denied'" title="该页面需要管理员权限。你可以从左侧继续使用学员功能。"
          type="warning" show-icon :closable="false" />
        <router-view v-slot="{ Component }">
          <component :is="Component" class="page-root" />
        </router-view>
      </main>
    </div>
    <AiCopilotPanel />
    <TrainingSessionOverlay
      v-if="trainingOverlaySessionId !== null"
      :key="trainingOverlaySessionId"
      :overlay-session-id="trainingOverlaySessionId"
      @overlay-closed="trainingOverlaySessionId = null"
    />
    <el-dialog v-model="passwordOpen" title="修改密码" class="v7b-record-dialog" top="4vh" width="min(480px, 94vw)"
      :close-on-click-modal="!changingPassword" :close-on-press-escape="!changingPassword" :show-close="!changingPassword">
      <el-form label-position="top" @submit.prevent="savePassword">
        <el-form-item label="当前密码">
          <el-input v-model="passwordForm.old_password" type="password" autocomplete="current-password" :disabled="changingPassword" />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="passwordForm.new_password" type="password" autocomplete="new-password" :disabled="changingPassword" />
        </el-form-item>
        <p class="page-context">至少 8 个字符，包含大小写字母和数字。修改后请用新密码重新登录。</p>
        <el-alert v-if="passwordError" type="error" :title="passwordError" :closable="false" />
      </el-form>
      <template #footer>
        <el-button :disabled="changingPassword" @click="passwordOpen = false">取消</el-button>
        <el-button type="primary" :loading="changingPassword" @click="savePassword">修改并重新登录</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AiCopilotPanel from '../components/AiCopilotPanel.vue'
import { useAiCopilotStore } from '../stores/aiCopilot'
import { useLabContextStore } from '../stores/labContext'
import { useCurrentUser } from '../composables/useCurrentUser'
import { useWorkbenchDraftsStore } from '../stores/workbenchDrafts'
import { ElMessageBox } from 'element-plus/es/components/message-box/index'
import { changePassword, logout } from '../api/auth'
import { requestErrorMessage } from '../utils/requestError'
import { acceptBrowserSession, browserSession, publishSessionChange, SESSION_CHANGE_KEY } from '../stores/browserSession'

const route = useRoute()
const navOpen = ref(false)
const navigation = ref<HTMLElement | null>(null)
const navToggle = ref<HTMLButtonElement | null>(null)
const assistantToggle = ref<HTMLButtonElement | null>(null)
const navCollapsed = ref(localStorage.getItem('v7b_nav_collapsed') === '1')
const narrowQuery = window.matchMedia('(max-width: 1100px)')
const narrowWindow = ref(narrowQuery.matches)
const collapsed = computed(() => navCollapsed.value && !narrowWindow.value)
const copilot = useAiCopilotStore()
const labCtx = useLabContextStore()
const drafts = useWorkbenchDraftsStore()
const passwordOpen = ref(false)
const passwordError = ref('')
const changingPassword = ref(false)
const passwordForm = ref({ old_password: '', new_password: '' })
const { user, isAdmin } = useCurrentUser()
const TrainingSessionOverlay = defineAsyncComponent(() => import('./training/TrainingLabView.vue'))
const trainingOverlaySessionId = ref<number | null>(null)

watch(() => route.fullPath, () => { trainingOverlaySessionId.value = null })
watch(navOpen, async open => {
  if (!open) return
  await nextTick()
  if (navOpen.value) navigation.value?.querySelector<HTMLElement>('.el-menu-item[tabindex="0"]')?.focus()
})

const environmentName = 'IP仿真运维管理工作台'
const activePath = computed(() => {
  if (route.path.startsWith('/system')) return route.path
  if (route.path.startsWith('/webssh')) return '/webssh'
  return route.path
})
const contextLabel = computed(() => {
  if (labCtx.isActive) return `实训上下文 · ${labCtx.label}`
  if (route.path.startsWith('/devices')) return '设备与只读观察'
  if (route.path.startsWith('/deploy') || route.path.startsWith('/approvals')) return '变更与审批'
  return '统一工作台'
})

const now = ref(new Date())
let clockTimer = 0
function syncNarrowWindow() {
  narrowWindow.value = narrowQuery.matches
  if (!narrowWindow.value) navOpen.value = false
}
const hasUnsentWork = computed(() =>
  !!(drafts.deploy.form.config_content.trim() || drafts.deploy.form.name.trim() || drafts.deploy.intent.trim()) ||
  Object.keys(drafts.training).length > 0)
function confirmLeaving(event: BeforeUnloadEvent) {
  if (!browserSession.value || !hasUnsentWork.value) return
  event.preventDefault()
  event.returnValue = ''
}
function onAccountStorageChange(event: StorageEvent) {
  if (event.storageArea !== localStorage || event.key !== SESSION_CHANGE_KEY) return
  acceptBrowserSession(null)
  window.location.reload()
}
const currentTime = computed(() => now.value.toLocaleTimeString('zh-CN', { hour12: false }))
onMounted(() => {
  clockTimer = window.setInterval(() => { now.value = new Date() }, 1000)
  narrowQuery.addEventListener('change', syncNarrowWindow)
  window.addEventListener('beforeunload', confirmLeaving)
  window.addEventListener('storage', onAccountStorageChange)
  // 首次在窄窗口进入时默认收起助手，避免一进来就把主任务挤到很窄；用户仍可一键展开。
  if (localStorage.getItem('ai_copilot_open') === null && window.innerWidth < 1280) {
    copilot.setOpen(false)
  }
})
onUnmounted(() => {
  window.clearInterval(clockTimer)
  narrowQuery.removeEventListener('change', syncNarrowWindow)
  window.removeEventListener('beforeunload', confirmLeaving)
  window.removeEventListener('storage', onAccountStorageChange)
})

function toggleNav() {
  navCollapsed.value = !navCollapsed.value
  localStorage.setItem('v7b_nav_collapsed', navCollapsed.value ? '1' : '0')
}

function closeNavigation() {
  if (!navOpen.value) return
  navOpen.value = false
  navToggle.value?.focus()
}

function activateNavigationItem(event: KeyboardEvent) {
  if (event.defaultPrevented || (event.key !== 'Enter' && event.key !== ' ')) return
  const item = event.target
  if (!(item instanceof HTMLElement) || item.classList.contains('is-disabled')) return
  const control = item.matches('.el-menu-item') ? item : item.querySelector<HTMLElement>(':scope > .el-sub-menu__title')
  if (!control) return
  event.preventDefault()
  control.click()
}

function closeNarrowPanel(event: KeyboardEvent) {
  if (!narrowWindow.value || event.defaultPrevented || (event.target as HTMLElement | null)?.closest('[role="dialog"]')) return
  if (navOpen.value) {
    closeNavigation()
  } else if (copilot.open) {
    copilot.setOpen(false)
    assistantToggle.value?.focus()
  }
}

async function handleCommand(cmd: string) {
  if (cmd === 'password') {
    passwordForm.value = { old_password: '', new_password: '' }
    passwordError.value = ''
    passwordOpen.value = true
    return
  }
  if (cmd === 'logout') {
    if (hasUnsentWork.value) {
      try {
        await ElMessageBox.confirm('退出会清除此标签页中未保存的笔记和配置草稿。要继续退出吗？', '退出登录', {
          confirmButtonText: '退出', cancelButtonText: '返回保存', type: 'warning',
        })
      } catch { return }
    }
    try {
      await logout()
      acceptBrowserSession(null)
      publishSessionChange()
      window.location.replace('/login')
    } catch { /* the request interceptor reports failure */ }
  }
}

async function savePassword() {
  if (changingPassword.value) return
  if (!passwordForm.value.old_password || !passwordForm.value.new_password) {
    passwordError.value = '请填写当前密码和新密码。'
    return
  }
  changingPassword.value = true
  passwordError.value = ''
  try {
    await changePassword(passwordForm.value)
    passwordOpen.value = false
    passwordForm.value = { old_password: '', new_password: '' }
    const previousPage = route.fullPath
    acceptBrowserSession(null)
    publishSessionChange()
    window.location.replace(`/login?password_changed=1&redirect=${encodeURIComponent(previousPage)}`)
  } catch (error) {
    passwordError.value = requestErrorMessage(error, '修改未完成，请核对当前密码和新密码要求。')
  } finally {
    changingPassword.value = false
  }
}

function resumeTraining() {
  const id = labCtx.sessionId
  if (!id || !labCtx.isActive) return
  if (route.name === '实训') {
    window.dispatchEvent(new CustomEvent('training-open-session', { detail: { sessionId: id } }))
    return
  }
  trainingOverlaySessionId.value = id
}
</script>

<style scoped>
.app-layout {
  height: 100vh;
  display: flex;
  flex-direction: row;
  overflow: hidden;
  background: var(--v7b-bg);
  color: var(--v7b-text);
}
.skip-link {
  position: absolute;
  left: -999px;
  top: 0;
  z-index: 100;
  padding: 8px 12px;
  background: var(--v7b-accent);
  color: #041016;
}
.skip-link:focus { left: 8px; top: 8px; }
.app-aside {
  width: 220px;
  flex: 0 0 220px;
  height: 100vh;
  background: #0c141d;
  border-right: 1px solid var(--v7b-line);
  display: flex;
  flex-direction: column;
  transition: width .16s ease, flex-basis .16s ease;
  z-index: 30;
}
.app-aside.narrow { width: 64px; flex-basis: 64px; }
.logo {
  height: 60px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 14px;
  color: var(--v7b-text);
  font-size: 13px;
  font-weight: 700;
  border-bottom: 1px solid var(--v7b-line);
  flex-shrink: 0;
  overflow: hidden;
  white-space: nowrap;
}
.logo-mark {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  border: 1px solid var(--v7b-accent);
  border-radius: 7px;
  color: var(--v7b-accent);
  font-size: 11px;
}
.logo-text small { display: block; margin-top: 2px; color: var(--v7b-faint); font-size: 9px; font-weight: 500; }
.nav-menu {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  border-right: 0;
  background: transparent;
  --el-menu-bg-color: transparent;
  --el-menu-text-color: #9db0c0;
  --el-menu-active-color: var(--v7b-accent);
  --el-menu-hover-bg-color: #111e29;
}
.collapse-btn {
  height: 34px;
  border: 0;
  border-top: 1px solid var(--v7b-line);
  background: transparent;
  color: var(--v7b-faint);
  cursor: pointer;
  font-size: 13px;
}
.collapse-btn:hover { color: var(--v7b-accent); }
.center-wrap { flex: 1; min-width: 0; display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  height: 54px;
  flex-shrink: 0;
  padding: 0 16px;
  border-bottom: 1px solid var(--v7b-line);
  background: rgba(12, 20, 29, .96);
  color: var(--v7b-text);
}
.header-title { display: flex; align-items: center; gap: 10px; min-width: 0; }
.title-block { display: flex; flex-direction: column; min-width: 0; }
.page-title { font-size: 13px; font-weight: 650; white-space: nowrap; }
.page-context { color: var(--v7b-faint); font-size: 10px; margin-top: 1px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.header-right { display: flex; align-items: center; gap: 10px; min-width: 0; }
.env-clock {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--v7b-muted);
  font-size: 11px;
  white-space: nowrap;
}
.env-clock time { color: var(--v7b-faint); font-variant-numeric: tabular-nums; }
.env-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--v7b-ok); box-shadow: 0 0 6px rgba(79, 209, 139, .65); }
.lab-resume {
  height: 28px;
  max-width: min(280px, 30vw);
  padding: 0 10px;
  border-radius: 6px;
  border: 1px solid rgba(55, 198, 216, .55);
  background: var(--v7b-accent-soft);
  color: var(--v7b-accent);
  font-size: 11px;
  font-weight: 650;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ai-toggle {
  height: 28px;
  padding: 0 10px;
  border-radius: 6px;
  border: 1px solid var(--v7b-line-strong);
  background: transparent;
  color: var(--v7b-muted);
  font-size: 11px;
  font-weight: 650;
  cursor: pointer;
  white-space: nowrap;
}
.ai-toggle.on { border-color: var(--v7b-accent); color: var(--v7b-accent); background: var(--v7b-accent-soft); }
.user-trigger { display: flex; align-items: center; gap: 7px; color: var(--v7b-muted); font-size: 12px; cursor: pointer; }
.user-trigger i { width: 7px; height: 7px; border-radius: 50%; background: var(--v7b-ok); }
.mobile-nav-toggle { display: none; width: 30px; height: 30px; border: 1px solid var(--v7b-line-strong); background: transparent; color: var(--v7b-muted); cursor: pointer; }
.nav-scrim { display: none; }
.app-main {
  flex: 1;
  min-height: 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--v7b-bg);
}
.page-root {
  --workspace-content-max: clamp(1760px, 74vw, 2160px);
  flex: 1;
  min-height: 0;
  min-width: 0;
  width: 100%;
  overflow: auto;
  padding: 18px max(20px, calc((100% - var(--workspace-content-max)) / 2)) 24px;
}
.app-aside :deep(.el-menu-item),
.app-aside :deep(.el-sub-menu__title) {
  height: 38px;
  line-height: 38px;
  font-size: 12px;
  margin: 2px 8px;
  border-radius: 6px;
}
.app-aside :deep(.el-menu-item-group__title) {
  padding: 14px 16px 4px !important;
  color: var(--v7b-faint);
  font-size: 10px;
  letter-spacing: .08em;
}
.app-aside :deep(.el-menu-item.is-active) {
  background: #263445 !important;
  color: #409eff !important;
  box-shadow: inset 2px 0 0 #409eff;
}
.app-aside :deep(.el-menu-item:focus-visible),
.app-aside :deep(.el-sub-menu:focus-visible > .el-sub-menu__title) {
  outline: 2px solid #9bc6ff;
  outline-offset: -2px;
}
.app-aside :deep(.el-menu-item:hover),
.app-aside :deep(.el-sub-menu__title:hover) { background: #111e29 !important; }
.app-aside.narrow :deep(.el-menu-item-group__title) { display: none; }
.app-aside.narrow :deep(.el-menu-item),
.app-aside.narrow :deep(.el-sub-menu__title) {
  justify-content: center;
  padding: 0 !important;
  margin: 3px 4px;
  font-size: 11px;
}
.app-aside.narrow :deep(.el-sub-menu__icon-arrow) { display: none; }
.app-aside.narrow :deep(.el-menu-item-group) { padding-top: 6px; }

@media (max-width: 1280px) {
  .env-name { display: none; }
}
@media (max-width: 1100px) {
  .app-layout { height: 100dvh; flex-direction: column; }
  .center-wrap { flex: 1 1 0; height: auto; min-height: 0; }
  .app-aside { position: fixed; inset: 0 auto 0 0; width: 220px !important; flex-basis: 220px; visibility: hidden; transform: translateX(-100%); transition: transform .18s ease; }
  .app-aside.open { visibility: visible; transform: translateX(0); }
  .nav-scrim { position: fixed; inset: 0; z-index: 25; display: block; border: 0; background: rgba(0,0,0,.55); }
  .mobile-nav-toggle { display: inline-grid; place-items: center; }
  .collapse-btn { display: none; }
  .page-root { padding: 12px; }
  .page-context, .env-name { display: none; }
}
@media (max-height: 620px) {
  .page-root { padding-top: 10px; }
}
@media (max-width: 600px) {
  .env-clock { display: none; }
  .lab-resume { max-width: 40vw; }
}
</style>
