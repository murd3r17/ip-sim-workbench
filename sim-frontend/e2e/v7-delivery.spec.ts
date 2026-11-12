import { randomBytes } from 'node:crypto'
import { expect, test, type Page } from '@playwright/test'
import { ADMIN_PASSWORD, ADMIN_USER, confirmBox, ensureCopilotClosed } from './helpers'

const publicPages = [
  ['/dashboard', '工作台'], ['/devices', '设备'], ['/topology', '拓扑'],
  ['/webssh', '终端'], ['/knowledge', '知识库'], ['/deploy', '配置下发'],
  ['/approvals', '变更审批'], ['/config-versions', '配置版本'],
  ['/monitor', '监控'], ['/alarms', '告警'], ['/training', '实训'],
] as const
const adminPages = [
  ['/environments', '环境映射'], ['/system/info', '系统信息'], ['/system/config', '系统配置'],
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
  const identity = await page.request.get('/api/v1/system/runtime-identity', { headers: await readToken(page) })
  expect(identity.ok()).toBeTruthy()
  expect(await identity.json()).toMatchObject({ root_fingerprint: process.env.E2E_ROOT_FINGERPRINT, device_mode: 'sim', deploy_simulate_only: true })
  await ensureCopilotClosed(page)
}

async function readToken(page: Page) {
  const token = await page.evaluate(() => localStorage.getItem('token'))
  expect(token).toBeTruthy()
  return { Authorization: 'Bearer ' + token }
}

test('管理员可从导航打开 V7 的 17 个页面', async ({ page }) => {
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
  const password = randomBytes(24).toString('base64url')
  const create = await page.request.post('/api/v1/auth/users', {
    headers: await readToken(page), data: { username, password, role: 'user' },
  })
  expect(create.ok()).toBeTruthy()
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
    for (const [path, label] of publicPages) {
      await learner.getByRole('menuitem', { name: label, exact: true }).click()
      await expect(learner).toHaveURL(new RegExp(path + '$'))
    }
    for (const [path] of adminPages) {
      await learner.goto(origin + path)
      await expect(learner).toHaveURL(/\/dashboard$/)
    }
    const headers = await readToken(learner)
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
  await expect(drawer.locator('.obs-result')).toContainText('服务端观察')
  await expect(drawer.locator('.obs-result')).toContainText('解析器')
})

test('拓扑呈现已保存设备、链路证据和终端入口', async ({ page }) => {
  await login(page)
  await page.getByRole('menuitem', { name: '拓扑', exact: true }).click()
  const canvas = page.getByRole('region', { name: '拓扑画布' })
  await expect(canvas.locator('.canvas-node')).toHaveCount(6)
  await canvas.getByRole('button', { name: '适应画布' }).click()
  await canvas.getByRole('checkbox', { name: '接口标签' }).check()
  await expect(canvas.locator('.edge-label text').first()).toBeVisible()
  await canvas.locator('.canvas-edge').first().press('Enter')
  await expect(canvas.locator('.link-detail')).toContainText('链路详情')
  await canvas.getByRole('button', { name: /^R-1，/ }).press('Enter')
  await expect(page.getByRole('button', { name: '开终端', exact: true })).toBeVisible()
})

test('知识库目录可打开 135 篇语料中的持久原文', async ({ page }) => {
  await login(page)
  await page.getByRole('menuitem', { name: '知识库', exact: true }).click()
  await expect(page.locator('.knowledge-health')).toContainText('135 篇资料')
  await page.getByRole('button', { name: '阅读全文', exact: true }).first().click()
  const reader = page.getByRole('dialog', { name: '资料全文' })
  await expect(reader.locator('.reader-body')).toBeVisible()
  await reader.getByRole('button', { name: '返回原页面', exact: true }).click()
  await expect(reader).not.toBeVisible()
})

test('模拟配置任务确认后才能执行，并可查看回读报告', async ({ page }) => {
  await login(page)
  const headers = await readToken(page)
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
  await row.getByRole('button', { name: '确认', exact: true }).click()
  await row.getByRole('button', { name: '执行', exact: true }).click()
  await row.getByRole('button', { name: '验证', exact: true }).click()
  await expect(page.getByRole('dialog').filter({ hasText: '验证结果' })).toContainText('模拟')
})

test('实训会话关闭后能重新打开同一会话', async ({ page }) => {
  await login(page)
  await page.getByRole('menuitem', { name: '实训', exact: true }).click()
  const lab = page.getByRole('row').filter({ hasText: '模拟网络巡检实训' }).first()
  await lab.getByRole('button', { name: '开始实训', exact: true }).click()
  const started = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/training/sessions'
    && response.request().method() === 'POST' && response.ok())
  await confirmBox(page)
  const { id } = await (await started).json()
  expect(Number(id)).toBeGreaterThan(0)
  const session = page.getByRole('dialog').filter({ hasText: '会话ID' })
  await expect(session).toBeVisible()
  await expect(session.getByText(String(id), { exact: true }).first()).toBeVisible()
  await session.locator('button.el-dialog__headerbtn').click()
  await expect(session).not.toBeVisible()
  await lab.getByRole('button', { name: '继续实训', exact: true }).click()
  await expect(session).toBeVisible()
  await expect(session.getByText(String(id), { exact: true }).first()).toBeVisible()
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
