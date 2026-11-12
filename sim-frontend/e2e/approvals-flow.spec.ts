import { test, expect } from '@playwright/test'
import {
  attachGuards,
  expectToast,
  guardFrontendOrSkip,
  loginAsAdmin,
  openMenu,
  requireAdminCredentials,
} from './helpers'

/**
 * 变更审批页必须能走完「确认 → 执行 → 验证」。
 *
 * 背景（2026-10-05 UX 审计）：审批页此前只有 详情/确认/取消，确认完就成死路；
 * 而快照回滚生成的任务**没有批次**，在「配置下发」任务管理里根本看不到，
 * 于是"回滚 → 去审批页确认执行"这条路彻底断掉，也永远看不到回滚结果。
 */

/** 用页面内的登录态直接调后端（该用例只关心审批页交互，不重复走创建表单） */
async function apiCall(page: import('@playwright/test').Page, path: string, method = 'GET', body?: unknown) {
  return page.evaluate(async ({ path, method, body }) => {
    const token = localStorage.getItem('token') || ''
    const resp = await fetch(`/api/v1${path}`, {
      method,
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    const text = await resp.text()
    let data: any = null
    try { data = JSON.parse(text) } catch { data = text }
    return { status: resp.status, data }
  }, { path, method, body })
}

test.describe('变更审批：确认后可以继续执行', () => {
  test.beforeEach(async () => {
    await guardFrontendOrSkip()
    requireAdminCredentials()
  })

  test('审批页能执行已确认任务并看到下一步', async ({ page }) => {
    test.setTimeout(180000)
    const guards = attachGuards(page)
    await loginAsAdmin(page)

    // 造一条待确认任务（用第一个在线设备；模拟模式下执行不改真机）
    const devices = await apiCall(page, '/devices')
    expect(devices.status).toBe(200)
    const deviceList = devices.data?.items || devices.data || []
    const device = deviceList.find((item: any) => item.status === 'online')
    expect(device, '需要至少一台在线设备').toBeTruthy()

    const created = await apiCall(page, '/deploy', 'POST', {
      device_ids: [device.id],
      // 必须是能通过下发校验的配置（展示类 display 命令会被后端拦成 422）
      config_content: 'interface LoopBack99\n description e2e-approval\n quit',
    })
    expect([200, 201]).toContain(created.status)
    // 创建接口返回 details[].task_id
    const taskId = created.data?.details?.[0]?.task_id
    expect(taskId, `创建任务返回里没有任务 ID: ${JSON.stringify(created.data)}`).toBeTruthy()

    try {
      await openMenu(page, '变更审批')
      await expect(page).toHaveURL(/\/approvals/)
      const row = page.locator('.el-table__row').filter({ hasText: `#${taskId}` }).first()
      await expect(row).toBeVisible({ timeout: 20000 })

      // 确认
      await row.getByRole('button', { name: /确认/ }).first().click()
      await expectToast(page, /已确认/, 20000)

      // 关键：确认后必须出现「执行」按钮（此前没有 → 死路）
      const execBtn = row.getByRole('button', { name: '执行', exact: true })
      await expect(execBtn).toBeVisible({ timeout: 20000 })
      await execBtn.click()
      await expectToast(page, /已执行/, 40000)

      // 执行后出现「验证」入口
      await expect(row.getByRole('button', { name: /验证/ }).first()).toBeVisible({ timeout: 30000 })
    } finally {
      // Executed tasks must finish verification; cancellation only covers work
      // that has not started (never release a lease beneath an active writer).
      const saved = await apiCall(page, `/deploy/tasks/${taskId}`)
      const action = saved.data?.status === 'deploying' ? 'verify' : 'cancel'
      await apiCall(page, `/deploy/tasks/${taskId}/${action}`, 'POST').catch(() => null)
    }

    guards.assertClean()
  })

  test('审批页能执行并验证，验证报告用中文说明', async ({ page }) => {
    test.setTimeout(180000)
    const guards = attachGuards(page)
    await loginAsAdmin(page)

    // 造一条已确认任务（执行 → 验证都在审批页完成；模拟模式不改真机）
    const devices = await apiCall(page, '/devices')
    const deviceList = devices.data?.items || devices.data || []
    const device = deviceList.find((item: any) => item.status === 'online')
    expect(device, '需要至少一台在线设备').toBeTruthy()
    const created = await apiCall(page, '/deploy', 'POST', {
      device_ids: [device.id],
      config_content: 'interface LoopBack98\n description e2e-verify-report\n quit',
    })
    const taskId = created.data?.details?.[0]?.task_id
    expect(taskId).toBeTruthy()
    await apiCall(page, `/deploy/tasks/${taskId}/confirm`, 'POST', { risk_confirm: true })

    await openMenu(page, '变更审批')
    const row = page.locator('.el-table__row').filter({ hasText: `#${taskId}` }).first()
    await expect(row).toBeVisible({ timeout: 20000 })

    await row.getByRole('button', { name: '执行', exact: true }).click()
    await expectToast(page, /已执行/, 40000)
    const verifyBtn = row.getByRole('button', { name: '验证', exact: true })
    await expect(verifyBtn).toBeVisible({ timeout: 30000 })
    await verifyBtn.click()

    const dialog = page.getByRole('dialog', { name: /验证报告/ })
    await expect(dialog).toBeVisible({ timeout: 30000 })
    // 不应出现原始 token，必须是中文说明
    await expect(dialog).not.toContainText('not_performed')
    await expect(dialog).not.toContainText('no_readback')
    await expect(dialog.getByText(/模拟执行|真实执行/).first()).toBeVisible()
    await expect(dialog.getByText(/未回读|已回读/).first()).toBeVisible()

    guards.assertClean()
  })
})
