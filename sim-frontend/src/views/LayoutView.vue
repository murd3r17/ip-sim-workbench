<template>
  <div class="app-layout">
    <a class="skip-link" href="#main-content">跳到主要内容</a>
    <aside class="app-aside" :class="{ narrow: navCollapsed, open: navOpen }" aria-label="主导航">
      <div class="logo">
        <span class="logo-mark">IP</span>
        <span v-if="!navCollapsed" class="logo-text">仿真运维工作台<small>Operations Center</small></span>
      </div>
      <el-menu
        :default-active="activePath"
        :collapse="navCollapsed"
        :collapse-transition="false"
        router
        class="nav-menu"
        @select="navOpen = false"
      >
        <el-menu-item-group v-if="!navCollapsed" title="总览">
          <el-menu-item index="/dashboard">工作台</el-menu-item>
          <el-menu-item index="/topology">拓扑</el-menu-item>
        </el-menu-item-group>
        <el-menu-item v-else index="/dashboard" title="工作台">⌂</el-menu-item>
        <el-menu-item-group v-if="!navCollapsed" title="设备与变更">
          <el-menu-item index="/devices">设备</el-menu-item>
          <el-menu-item index="/webssh">终端</el-menu-item>
          <el-menu-item index="/deploy">配置下发</el-menu-item>
          <el-menu-item index="/approvals">变更审批</el-menu-item>
          <el-menu-item index="/config-versions">配置版本</el-menu-item>
          <el-menu-item v-if="isAdmin" index="/environments">环境映射</el-menu-item>
        </el-menu-item-group>
        <el-menu-item v-else index="/devices" title="设备">▤</el-menu-item>
        <el-menu-item-group v-if="!navCollapsed" title="观测">
          <el-menu-item index="/monitor">监控</el-menu-item>
          <el-menu-item index="/alarms">告警</el-menu-item>
        </el-menu-item-group>
        <el-menu-item-group v-if="!navCollapsed" title="工具">
          <el-menu-item index="/training">实训</el-menu-item>
          <el-menu-item index="/knowledge">知识库</el-menu-item>
        </el-menu-item-group>
        <el-menu-item-group v-if="!navCollapsed && isAdmin" title="系统">
          <el-sub-menu index="system">
            <template #title>系统管理</template>
            <el-menu-item index="/system/info">系统信息</el-menu-item>
            <el-menu-item index="/system/config">系统配置</el-menu-item>
            <el-menu-item index="/system/audit">审计日志</el-menu-item>
            <el-menu-item index="/system/tasks">后台任务</el-menu-item>
            <el-menu-item index="/system/logs">日志文件</el-menu-item>
          </el-sub-menu>
        </el-menu-item-group>
      </el-menu>
      <button class="collapse-btn" type="button" :title="navCollapsed ? '展开导航' : '收起导航'" @click="toggleNav">
        {{ navCollapsed ? '»' : '«' }}
      </button>
    </aside>
    <button v-if="navOpen" class="nav-scrim" aria-label="关闭导航" @click="navOpen = false"></button>

    <div class="center-wrap">
      <header class="app-header">
        <div class="header-title">
          <button class="mobile-nav-toggle" title="打开导航" @click="navOpen = true">☰</button>
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
            :title="`正在实训 ${labCtx.label}。关闭窗口不会结束实验，点这里即可再打开。`"
            @click="resumeTraining"
          >实训进行中 · {{ labCtx.label }}</button>
          <button class="ai-toggle" :class="{ on: copilot.open }" title="AI 助手（可收起，不遮挡主任务）" @click="copilot.toggle()">
            AI 助手
          </button>
          <el-dropdown trigger="click" @command="handleCommand">
            <span class="user-trigger"><i></i>{{ user?.username || '用户' }}</span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>
      <main id="main-content" class="app-main">
        <router-view v-slot="{ Component }">
          <component :is="Component" class="page-root" />
        </router-view>
      </main>
    </div>
    <AiCopilotPanel />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AiCopilotPanel from '../components/AiCopilotPanel.vue'
import { useAiCopilotStore } from '../stores/aiCopilot'
import { useLabContextStore } from '../stores/labContext'
import { useCurrentUser } from '../composables/useCurrentUser'
import { clearClientSession } from '../utils/session'

const route = useRoute()
const router = useRouter()
const navOpen = ref(false)
const navCollapsed = ref(localStorage.getItem('v7b_nav_collapsed') === '1')
const copilot = useAiCopilotStore()
const labCtx = useLabContextStore()
const { user, isAdmin } = useCurrentUser()

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
const currentTime = computed(() => now.value.toLocaleTimeString('zh-CN', { hour12: false }))
onMounted(() => {
  clockTimer = window.setInterval(() => { now.value = new Date() }, 1000)
  // 首次在窄窗口进入时默认收起助手，避免一进来就把主任务挤到很窄；用户仍可一键展开。
  if (localStorage.getItem('ai_copilot_open') === null && window.innerWidth < 1280) {
    copilot.setOpen(false)
  }
})
onUnmounted(() => window.clearInterval(clockTimer))

function toggleNav() {
  navCollapsed.value = !navCollapsed.value
  localStorage.setItem('v7b_nav_collapsed', navCollapsed.value ? '1' : '0')
}

function handleCommand(cmd: string) {
  if (cmd === 'logout') {
    clearClientSession()
    router.push('/login')
  }
}

function resumeTraining() {
  const id = labCtx.sessionId
  if (!id) {
    router.push('/training')
    return
  }
  if (route.path === '/training' && String(route.query.session_id || '') === String(id)) {
    window.dispatchEvent(new CustomEvent('training-open-session', { detail: { sessionId: id } }))
    return
  }
  router.push({ path: '/training', query: { session_id: String(id) } })
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
  flex: 1;
  min-height: 0;
  min-width: 0;
  width: 100%;
  overflow: auto;
  padding: 18px 20px 24px;
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
.app-aside :deep(.el-menu-item:hover),
.app-aside :deep(.el-sub-menu__title:hover) { background: #111e29 !important; }
.app-aside.narrow :deep(.el-menu-item) { justify-content: center; padding: 0 !important; margin: 3px 8px; }

@media (max-width: 1280px) {
  .env-name { display: none; }
}
@media (max-width: 900px) {
  .app-aside { position: fixed; inset: 0 auto 0 0; width: 220px !important; flex-basis: 220px; transform: translateX(-100%); transition: transform .18s ease; }
  .app-aside.open { transform: translateX(0); }
  .nav-scrim { position: fixed; inset: 0; z-index: 25; display: block; border: 0; background: rgba(0,0,0,.55); }
  .mobile-nav-toggle { display: inline-grid; place-items: center; }
  .collapse-btn { display: none; }
  .page-root { padding: 12px; }
  .page-context, .env-name { display: none; }
}
@media (max-width: 600px) {
  .env-clock { display: none; }
  .lab-resume { max-width: 40vw; }
}
</style>
