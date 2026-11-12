import { test, expect } from '@playwright/test'
import {
  attachGuards,
  guardFrontendOrSkip,
  loginAsAdmin,
  openMenu,
  pickSelectOption,
  requireAdminCredentials,
} from './helpers'

/**
 * A3：WebSSH 的两类"服务端拒绝"必须对用户可见且不无限重连。
 *
 * 后端拒绝时用 WebSocket close code + reason（backend/modules/webssh/router.py）：
 *   4006 并发终端会话数已达上限；4009 设备存在待执行配置写任务。
 * 前端此前只显示"连接已断开"并自动重连 —— 用户看到反复断线却不知原因。
 */

const DRAFT = 'sysname E2EWebSSH'

test.describe('WebSSH 拒绝原因可见性', () => {
  test.beforeEach(async () => {
    await guardFrontendOrSkip()
    requireAdminCredentials()
  })

  test('设备存在写任务时终端显示原因，且不自动重连', async ({ page }) => {
    test.setTimeout(180000)
    const guards = attachGuards(page)
    await loginAsAdmin(page)

    const token = await page.evaluate(() => localStorage.getItem('token'))
    const auth = { Authorization: `Bearer ${token}` }

    const devicesResp = await page.request.get('/api/v1/devices', { headers: auth })
    expect(devicesResp.ok()).toBeTruthy()
    const devices = await devicesResp.json()
    const r1 = (Array.isArray(devices) ? devices : devices.items || []).find((d: { hostname: string }) => /^R-?1$/.test(d.hostname))
    expect(r1, '需要 R1 或 R-1 设备存在').toBeTruthy()

    // 造一个"已确认"任务占住设备写锁（不执行）
    const createResp = await page.request.post('/api/v1/deploy', {
      headers: auth,
      data: { device_ids: [r1.id], config_content: DRAFT, change_level: 'daily' },
    })
    expect(createResp.ok()).toBeTruthy()
    const created = await createResp.json()
    const taskId = created?.details?.[0]?.task_id ?? created?.task_id
    expect(taskId, '应创建出下发任务').toBeTruthy()
    const confirmResp = await page.request.post(`/api/v1/deploy/tasks/${taskId}/confirm`, {
      headers: auth,
      data: { risk_confirm: true },
    })
    expect([200, 422]).toContain(confirmResp.status())

    try {
      await openMenu(page, 'WebSSH终端')
      await pickSelectOption(page, /^R-?1(?:\s|[（(]|$)/)
      await page.getByRole('button', { name: '连接' }).click()

      await expect(page.locator('body')).toContainText('待执行配置写任务', { timeout: 30000 })
      // 拒绝类断开**不应**重连：不出现通用断开文案
      await page.waitForTimeout(3000)
      await expect(page.locator('body')).not.toContainText('连接已断开')
    } finally {
      const cancelResp = await page.request.post(`/api/v1/deploy/tasks/${taskId}/cancel`, { headers: auth })
      expect(cancelResp.ok(), '收尾：取消任务释放写锁').toBeTruthy()
    }
    guards.assertClean()
  })

  test('超过每用户并发上限时返回 4006 并带明确原因', async ({ page }) => {
    test.setTimeout(180000)
    await loginAsAdmin(page)

    const token = await page.evaluate(() => localStorage.getItem('token'))
    const devicesResp = await page.request.get('/api/v1/devices', { headers: { Authorization: `Bearer ${token}` } })
    expect(devicesResp.ok()).toBeTruthy()
    const devices = await devicesResp.json()
    const secondDevice = (Array.isArray(devices) ? devices : devices.items || []).find((d: { hostname: string }) => /^R-?2$/.test(d.hostname))
    expect(secondDevice, '并发测试需要第二台设备 R2 或 R-2').toBeTruthy()
    // 注意：用原生 WebSocket 直接验证 close code/reason，比开 6 个页签更轻，
    // 也不会因为超时等待而拖慢 e2e（前 5 个连上后一直保持 OPEN）。
    const result = await page.evaluate(
      async ({ token, waitMs, deviceId }: { token: string; waitMs: number; deviceId: number }) => {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
        const url = `${protocol}//${window.location.host}/api/v1/ws/ssh/${deviceId}`
        const sockets: WebSocket[] = []
        const closed: Array<{ index: number; code: number; reason: string }> = []
        for (let index = 0; index < 6; index += 1) {
          const ws = new WebSocket(url, [token])
          sockets.push(ws)
          ws.onclose = (event) => closed.push({ index, code: event.code, reason: event.reason })
        }
        await new Promise((resolve) => setTimeout(resolve, waitMs))
        const open = sockets.filter((s) => s.readyState === WebSocket.OPEN).length
        for (const s of sockets) {
          try { s.close() } catch { /* ignore */ }
        }
        return { open, closed }
      },
      { token: token as string, waitMs: 8000, deviceId: secondDevice.id },
    )

    const rejected = result.closed.find((item) => item.code === 4006)
    expect(rejected, `应有一个连接因并发上限被拒（实际 ${JSON.stringify(result.closed)}）`).toBeTruthy()
    expect(rejected?.reason).toContain('并发终端会话数已达上限')
    expect(result.open).toBeGreaterThan(0)
  })
})
