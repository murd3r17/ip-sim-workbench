import { randomBytes } from 'node:crypto'
import { expect, test, type Page, type WebSocket } from '@playwright/test'
import { ADMIN_PASSWORD, ADMIN_USER, ensureCopilotClosed, guardFrontendOrSkip } from './helpers'

test.beforeEach(async () => { await guardFrontendOrSkip() })

const publicPages = [
  ['/dashboard', '工作台'], ['/devices', '设备'], ['/topology', '拓扑'],
  ['/webssh', '终端'], ['/knowledge', '知识库'], ['/deploy', '配置下发'],
  ['/approvals', '变更审批'], ['/config-versions', '配置版本'],
  ['/monitor', '监控'], ['/alarms', '告警'], ['/training', '实训'],
] as const
const adminPages = [
  ['/environments', '环境映射'], ['/system/accounts', '账号管理'], ['/system/info', '系统信息'], ['/system/config', '系统配置'],
  ['/system/audit', '审计日志'], ['/system/tasks', '后台任务'], ['/system/logs', '日志文件'],
] as const

async function login(page: Page, username = ADMIN_USER, password = ADMIN_PASSWORD) {
  expect(process.env.E2E_PROFILE, 'Use the isolated delivery browser runner').toBe('minimal')
  expect(process.env.E2E_ROOT_FINGERPRINT).toMatch(/^[a-f0-9]{64}$/)
  expect(password, 'Use a fresh disposable minimal instance with explicit credentials').toBeTruthy()
  await page.goto('/login')
  await page.getByPlaceholder('用户名', { exact: true }).fill(username)
  await page.getByPlaceholder('密码', { exact: true }).fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).toHaveURL(/\/dashboard$/)
  const identity = await page.request.get('/api/v1/system/runtime-identity', { headers: await sessionHeaders(page) })
  expect(identity.ok()).toBeTruthy()
  expect(await identity.json()).toMatchObject({ root_fingerprint: process.env.E2E_ROOT_FINGERPRINT, device_mode: 'sim', deploy_simulate_only: true })
  await ensureCopilotClosed(page)
}

async function sessionHeaders(page: Page) {
  const origin = new URL(page.url()).origin
  const response = await page.request.get(origin + '/api/v1/auth/session')
  expect(response.ok()).toBeTruthy()
  const session = await response.json()
  expect(session.csrf_token).toBeTruthy()
  return { Origin: origin, 'X-Workbench-CSRF': session.csrf_token, 'X-Workbench-Session': session.session_id }
}

test('管理员可从导航打开 V7 的 18 个页面', async ({ page }) => {
  await login(page)
  await expect(page.locator('#main-content')).toBeVisible()
  for (const [path, label] of [...publicPages, ...adminPages]) {
    if (path.startsWith('/system') && !(await page.getByRole('menuitem', { name: label, exact: true }).isVisible())) {
      await page.getByText('系统管理', { exact: true }).click()
    }
    await page.getByRole('menuitem', { name: label, exact: true }).click()
    await expect(page).toHaveURL(new RegExp(path + '$'))
    await expect(page.locator('#main-content > *').first()).toBeVisible()
  }
})

test('普通学员保留 11 个入口，管理路由和接口均拒绝访问', async ({ page, browser }) => {
  await login(page)
  const username = 'e07-learner-' + randomBytes(4).toString('hex')
  // Guarantee all required character classes in the disposable password.
  const password = 'Qa4-' + randomBytes(24).toString('base64url')
  const create = await page.request.post('/api/v1/auth/users', {
    headers: await sessionHeaders(page), data: { username, password, role: 'user' },
  })
  expect(create.status(), '创建普通学员账号').toBe(200)
  const context = await browser.newContext()
  try {
    const learner = await context.newPage()
    // The browser fixture's separate context needs an explicit origin.
    const origin = new URL(page.url()).origin
    await learner.goto(origin + '/login')
    await learner.getByPlaceholder('用户名', { exact: true }).fill(username)
    await learner.getByPlaceholder('密码', { exact: true }).fill(password)
    await learner.getByRole('button', { name: '登录', exact: true }).click()
    await expect(learner).toHaveURL(/\/dashboard$/)
    await ensureCopilotClosed(learner)
    await expect(learner.getByRole('status', { name: '设备接入模式' })).toContainText('模拟演练')
    for (const [path, label] of publicPages) {
      await learner.getByRole('menuitem', { name: label, exact: true }).click()
      await expect(learner).toHaveURL(new RegExp(path + '$'))
    }
    for (const [path] of adminPages) {
      await learner.goto(origin + path)
      await expect(learner).toHaveURL(/\/dashboard\?access=denied$/)
    }
    const headers = await sessionHeaders(learner)
    for (const path of ['/system/info', '/system/config', '/system/audit-logs', '/system/tasks', '/system/logs']) {
      const response = await learner.request.get(origin + '/api/v1' + path, { headers })
      expect(response.status(), path).toBe(403)
    }
    const mappingRead = await learner.request.get(origin + '/api/v1/trust/environments', { headers })
    expect(mappingRead.ok()).toBeTruthy()
  } finally {
    await context.close()
  }
})

test('设备列表遇到 503 可重试，恢复后可采集只读事实', async ({ page }) => {
  await login(page)
  let fail = true
  await page.route(/\/api\/v1\/devices(?:\?|$)/, route => fail
    ? route.fulfill({ status: 503, json: { detail: 'E07 controlled device-list outage' } })
    : route.continue())
  await page.getByRole('menuitem', { name: '设备', exact: true }).click()
  const retry = page.getByRole('button', { name: '重试设备列表' })
  await expect(retry).toBeVisible()
  fail = false
  await retry.click()
  const row = page.getByRole('row').filter({ hasText: 'R-1' }).first()
  await row.getByRole('button', { name: '只读观察', exact: true }).click()
  const drawer = page.locator('.el-drawer').filter({ hasText: '只读观察' })
  await drawer.getByRole('button', { name: '采集只读事实' }).click()
  await expect(drawer.locator('.obs-result')).toContainText('工作台采集')
  await expect(drawer.locator('.obs-result')).toContainText('输出完整')
})

test('首页展示只读拓扑全局，同一拓扑的详情页可检查链路和打开终端', async ({ page }) => {
  await login(page)
  const overview = page.getByRole('region', { name: '网络拓扑', exact: true })
  await expect(overview.locator('.canvas-node')).toHaveCount(6)
  await expect(overview.locator('.canvas-edge')).toHaveCount(5)
  await expect(overview.getByRole('button')).toHaveCount(0)
  const detailLink = overview.getByRole('link', { name: '打开拓扑页' })
  await expect(detailLink).toHaveAttribute('href', /^\/topology\?topology_id=\d+$/)
  await detailLink.click()
  const canvas = page.getByRole('region', { name: '拓扑画布' })
  await expect(canvas.locator('.canvas-node')).toHaveCount(6)
  await expect(canvas.locator('.canvas-edge')).toHaveCount(5)
  await canvas.getByRole('button', { name: '适应画布' }).click()
  await canvas.getByRole('checkbox', { name: '接口标签' }).check()
  await expect(canvas.locator('.edge-label text').first()).toBeVisible()
  await canvas.locator('.canvas-edge').first().press('Enter')
  await expect(canvas.locator('.link-detail')).toContainText('链路详情')
  await canvas.getByRole('button', { name: /^R-1，/ }).press('Enter')
  await expect(page.getByRole('button', { name: '开终端', exact: true })).toBeVisible()
})

test('知识库目录可打开当前教材资料', async ({ page }) => {
  await login(page)
  const response = await page.request.get('/api/v1/ai/knowledge/catalog')
  expect(response.ok()).toBeTruthy()
  const catalog = await response.json()
  const loadedCount = catalog.active_edition
    ? `${catalog.documents.filter((document: { catalog_kind?: string }) => document.catalog_kind === 'chapter').length} 个教材章节`
    : `${catalog.count} 篇资料`
  await page.getByRole('menuitem', { name: '知识库', exact: true }).click()
  await expect(page.locator('.knowledge-health')).toContainText(loadedCount)
  const readingAction = catalog.active_edition ? '阅读正文' : '阅读资料'
  await page.getByRole('button', { name: readingAction, exact: true }).first().click()
  const reader = page.getByRole('dialog', { name: catalog.active_edition ? '教材正文' : '阅读资料' })
  await expect(reader.locator('.reader-body')).toBeVisible()
  await reader.getByRole('button', { name: '返回原页面', exact: true }).click()
  await expect(reader).not.toBeVisible()
})

test('最小模式健康和教材检索能指导下一步', async ({ page }) => {
  await login(page)
  const health = await page.request.get('/api/v1/health')
  expect(health.ok()).toBeTruthy()
  const body = await health.json()
  expect(body).toMatchObject({
    status: 'healthy', ready: true, profile: 'minimal',
    components: { database: { backend: 'sqlite', status: 'healthy' }, llm: { status: 'disabled' } },
  })
  expect(body.components).not.toHaveProperty('mysql')
  expect((await page.request.get('/docs')).status()).toBe(404)
  await page.getByRole('menuitem', { name: '知识库', exact: true }).click()
  await page.getByRole('tab', { name: '检索资料' }).click()
  await page.getByRole('textbox', { name: '检索关键词' }).fill('OSPF')
  await page.getByRole('button', { name: '检索', exact: true }).click()
  const firstResult = page.locator('.search-result').first()
  await expect(firstResult.locator('header')).toContainText('OSPF')
  await expect(firstResult.locator('.search-excerpt')).toContainText(/链路状态|SPF.{0,12}链路成本/)
  await firstResult.getByRole('button', { name: '片段详情' }).click()
  const details = page.getByRole('dialog', { name: '检索片段' })
  await details.getByRole('button', { name: /阅读同版正文|查看随包整理稿/ }).click()
  await expect(page.getByRole('dialog', { name: /教材正文|阅读资料/ }).getByRole('heading', { name: /OSPF/ }).first()).toBeVisible()
})

test('浏览器凭据随服务器会话退出，刷新可以重新核对登录', async ({ page }) => {
  await login(page)
  const origin = new URL(page.url()).origin
  const cookies = await page.context().cookies(origin + '/api/v1')
  expect(cookies.some(cookie => cookie.name.startsWith('ip_sim_session_') && cookie.httpOnly)).toBeTruthy()
  expect(await page.evaluate(() => localStorage.getItem('token'))).toBeNull()
  const headers = await sessionHeaders(page)
  expect((await page.request.delete('/api/v1/auth/session', { headers: { Origin: origin } })).status()).toBe(403)
  const isLoginRedirect = (url: URL) => url.origin === origin && url.pathname === '/login'
    && url.searchParams.get('redirect') === '/dashboard'
    && !url.searchParams.has('unavailable')

  // Let an actual request from the mounted dashboard observe the revoked session.
  let releaseServices!: () => void
  const afterLogout = new Promise<void>(resolve => { releaseServices = resolve })
  await page.route('**/api/v1/dashboard/services', async route => {
    await afterLogout
    await route.continue()
  }, { times: 1 })
  try {
    await page.reload()
    await expect(page.locator('#main-content')).toBeVisible()
    expect((await page.request.delete('/api/v1/auth/session', { headers })).status()).toBe(204)
    expect((await page.request.get('/api/v1/dashboard/summary')).status()).toBe(401)
  } finally {
    releaseServices()
  }
  // Poll the committed address so an interrupted intermediate navigation does
  // not cause a navigation waiter to reject before the final page settles.
  await expect.poll(() => isLoginRedirect(new URL(page.url()))).toBe(true)

  // A fresh document exercises the route guard without competing with that redirect.
  const reopened = await page.context().newPage()
  await reopened.goto(origin + '/dashboard')
  await expect(reopened).toHaveURL(isLoginRedirect)
  await expect(reopened.getByRole('button', { name: '登录', exact: true })).toBeEnabled()
  await expect(reopened.locator('#main-content')).toBeHidden()
})

test('模拟配置任务确认后才能执行，报告说明为何没有设备回读', async ({ page }) => {
  await login(page)
  const headers = await sessionHeaders(page)
  const devices = await page.request.get('/api/v1/devices', { headers })
  expect(devices.ok()).toBeTruthy()
  const device = (await devices.json()).find((item: { hostname: string }) => item.hostname === 'R-1')
  expect(device).toBeTruthy()
  const queued = await page.request.post('/api/v1/deploy', { headers, data: {
    device_ids: [device.id], config_content: 'interface LoopBack0\n description E07_SIM_FIXTURE\nquit',
  } })
  expect(queued.ok()).toBeTruthy()
  await page.getByRole('menuitem', { name: '变更审批', exact: true }).click()
  const row = page.locator('.el-table__row').filter({ hasText: 'R-1' }).first()
  await expect(row.getByRole('button', { name: '执行', exact: true })).toHaveCount(0)
  await row.getByRole('button', { name: '确认变更', exact: true }).click()
  await row.getByRole('button', { name: '执行', exact: true }).click()
  await row.getByRole('button', { name: '确认演练结果', exact: true }).click()
  await expect(page.getByRole('dialog', { name: /验证报告/ })).toContainText('未回读（模拟模式）')
})

test('顶部实训入口打开同一会话并保留终端连接', async ({ page }) => {
  await login(page)
  await page.getByRole('menuitem', { name: '实训', exact: true }).click()
  const lab = page.getByRole('row').filter({ hasText: '模拟网络巡检实训' }).first()
  const started = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/training/sessions'
    && response.request().method() === 'POST' && response.ok())
  await lab.getByRole('button', { name: '开始巡检', exact: true }).click()
  const { id } = await (await started).json()
  expect(Number(id)).toBeGreaterThan(0)
  const session = page.getByRole('dialog', { name: new RegExp(`实训会话 #${id} ·`) })
  await expect(session).toBeVisible()
  const note = '已核对模拟拓扑，下一步观察设备接口'
  const notes = session.getByPlaceholder('记录当前现象、判断和下一步。保存后刷新页面也能继续。')
  await notes.fill(note)
  await session.getByRole('button', { name: '保存笔记/步骤', exact: true }).click()
  await expect(session.getByText('已保存', { exact: true })).toBeVisible()
  await session.locator('button.el-dialog__headerbtn').click()
  await expect(session).not.toBeVisible()
  const resume = page.getByRole('button', { name: /^实训进行中/ })
  await resume.click()
  await expect(session).toBeVisible()
  await expect(page).toHaveURL(/\/training$/)
  await session.locator('button.el-dialog__headerbtn').click()
  await lab.getByRole('button', { name: '继续实训', exact: true }).click()
  await expect(session).toBeVisible()

  const sockets: WebSocket[] = []
  page.on('websocket', socket => {
    if (new URL(socket.url()).pathname.startsWith('/api/v1/ws/ssh/')) sockets.push(socket)
  })
  await session.getByRole('button', { name: '开终端', exact: true }).click()
  await page.getByRole('button', { name: '连接', exact: true }).click()
  const ready = page.getByRole('status').filter({ hasText: '终端已就绪' })
  await expect(ready).toBeVisible()
  const terminalUrl = page.url()
  const input = page.locator('.xterm-helper-textarea')
  await input.focus()
  await page.keyboard.type('display ')

  await resume.click()
  await expect(session).toBeVisible()
  await expect(page).toHaveURL(terminalUrl)
  await session.locator('button.el-dialog__headerbtn').click()
  await expect(session).not.toBeVisible()
  await expect(page).toHaveURL(terminalUrl)
  await expect(ready).toBeVisible()

  await input.focus()
  await page.keyboard.type('version')
  await page.keyboard.press('Enter')
  await expect(page.locator('.xterm-rows')).toContainText(/Versatile|VRP/)
  expect(sockets).toHaveLength(1)
  expect(sockets[0].isClosed()).toBeFalsy()

  const revisit = await page.context().newPage()
  try {
    await revisit.goto(`/training?session_id=${id}`)
    const savedSession = revisit.getByRole('dialog', { name: new RegExp(`实训会话 #${id} ·`) })
    await expect(savedSession.getByPlaceholder('记录当前现象、判断和下一步。保存后刷新页面也能继续。')).toHaveValue(note)
  } finally {
    await revisit.close()
  }
})

test('受控挂起的助手请求及时出现停止入口并可取消', async ({ page }) => {
  await login(page)
  await page.locator('.ai-toggle').click()
  const composer = page.locator('.copilot')
  let release!: () => void
  const hold = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/v1/ai/copilot/chat/stream', async route => {
    await hold
    await route.abort().catch(() => {})
  })
  try {
    await composer.locator('textarea').fill('E07 本地受控请求')
    await composer.getByRole('button', { name: '发送', exact: true }).click()
    await expect(composer.getByRole('button', { name: '停止', exact: true })).toBeVisible({ timeout: 1000 })
    await composer.getByRole('button', { name: '停止', exact: true }).click()
    await expect(composer.getByRole('button', { name: '发送', exact: true })).toBeVisible()
  } finally {
    release()
  }
})

test('未配置模型时可返回教材，失败回答没有引用入口', async ({ page }) => {
  await login(page)
  await page.locator('.ai-toggle').click()
  const composer = page.locator('.copilot')
  await composer.locator('textarea').fill('请查本地教材，解释 OSPF 邻居的 Full 状态。')
  await composer.getByRole('button', { name: '发送', exact: true }).click()
  await expect(composer.getByText(/模型服务(?:暂|当前)?不可用|未配置模型|模型尚未配置/, { exact: false }).first()).toBeVisible()
  await expect(composer.locator('.source-link')).toHaveCount(0)
  await expect(composer.getByText('已检索资料，正文没有引用检索片段。', { exact: true })).toHaveCount(0)
  await composer.getByRole('button', { name: '打开知识库', exact: true }).click()
  await expect(page.getByRole('textbox', { name: '筛选资料' })).toBeVisible()
})
