import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/login', name: 'Login', component: () => import('../views/LoginView.vue') },
  {
    path: '/',
    component: () => import('../views/LayoutView.vue'),
    redirect: '/dashboard',
    children: [
      { path: 'dashboard', name: '工作台', component: () => import('../views/dashboard/DashboardView.vue') },
      { path: 'devices', name: '设备', component: () => import('../views/device/DeviceListView.vue') },
      { path: 'environments', name: '环境映射', component: () => import('../views/trust/EnvironmentView.vue') },
      { path: 'topology', name: '拓扑', component: () => import('../views/device/TopologyView.vue') },
      { path: 'webssh/:deviceId?', name: 'WebSSH终端', component: () => import('../views/device/WebSSHView.vue') },
      { path: 'knowledge', name: '知识库管理', component: () => import('../views/ai/KnowledgeView.vue') },
      { path: 'deploy', name: '配置下发', component: () => import('../views/deploy/DeployCenterView.vue') },
      { path: 'approvals', name: '变更审批', component: () => import('../views/deploy/ApprovalsView.vue') },
      { path: 'config-versions', name: '配置管理', component: () => import('../views/deploy/ConfigVersionView.vue') },
      { path: 'monitor', name: '监控大盘', component: () => import('../views/monitor/MonitorDashboardView.vue') },
      { path: 'alarms', name: '告警管理', component: () => import('../views/monitor/AlarmView.vue') },
      { path: 'training', name: '实训', component: () => import('../views/training/TrainingLabView.vue') },
      { path: 'system/info', name: '系统信息', component: () => import('../views/system/SystemInfoView.vue') },
      { path: 'system/config', name: '系统配置', component: () => import('../views/system/SystemConfigView.vue') },
      { path: 'system/audit', name: '审计日志', component: () => import('../views/system/AuditLogView.vue') },
      { path: 'system/tasks', name: '后台任务', component: () => import('../views/system/BackgroundTaskView.vue') },
      { path: 'system/logs', name: '日志文件', component: () => import('../views/system/LogFileView.vue') },
    ]
  },
  // 兜底：未知路径不再白屏（此前 to.matched 为空 → router-view 渲染空白）
  { path: '/:pathMatch(.*)*', name: 'NotFound', component: () => import('../views/NotFoundView.vue') }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem('token')
  if (to.path !== '/login' && !token) {
    next('/login')
    return
  }
  if (to.path.startsWith('/system') || to.path.startsWith('/environments')) {
    let role = ''
    try {
      role = JSON.parse(localStorage.getItem('user') || 'null')?.role || ''
    } catch {
      role = ''
    }
    if (role !== 'admin') {
      next('/dashboard')
      return
    }
  }
  next()
})

export default router
