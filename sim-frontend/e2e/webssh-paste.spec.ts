import { test, expect, type Page } from '@playwright/test'
import {
  attachGuards,
  FRONTEND_URL,
  guardFrontendOrSkip,
  loginAsAdmin,
  openMenu,
  pickSelectOption,
  requireAdminCredentials,
} from './helpers'

/**
 * WebSSH 粘贴（2026-10-05 用户反馈"敲字太麻烦"）。
 *
 * 断言方式说明：xterm 的 DOM 只保留**可视区**的行，命令输出一多，提示与回显就会被滚出 DOM，
 * 所以这里以「发往设备的 WebSocket 帧」为主要证据（这也正是问题本质：粘贴内容必须带 \r 才会执行），
 * 再用终端可视文本做一次端到端补充确认。
 */

function captureSentFrames(page: Page): string[] {
  const frames: string[] = []
  page.on('websocket', (socket) => {
    socket.on('framesent', (frame) => {
      const payload = typeof frame.payload === 'string' ? frame.payload : ''
      if (payload.includes('"type": "input"') || payload.includes('"type":"input"')) frames.push(payload)
    })
  })
  return frames
}

/** 在终端容器上派发真实结构的 paste 事件（Chromium 支持在构造函数里带 clipboardData）。 */
async function pasteText(page: Page, text: string) {
  await page.evaluate((payload: string) => {
    const host = document.querySelector('.webssh-console') as HTMLElement | null
    if (!host) throw new Error('未找到终端容器')
    const dt = new DataTransfer()
    dt.setData('text/plain', payload)
    const target = (document.querySelector('.xterm-helper-textarea') as HTMLElement | null) ?? host
    target.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }))
  }, text)
}

const inputData = (frame: string) => {
  try {
    return JSON.parse(frame).data as string
  } catch {
    return ''
  }
}

test.describe('WebSSH 粘贴', () => {
  test.beforeEach(async () => {
    await guardFrontendOrSkip()
    requireAdminCredentials()
  })

  test('单行粘贴：带上回车直接执行并看到设备回显', async ({ page }) => {
    test.setTimeout(120000)
    const guards = attachGuards(page)
    const frames = captureSentFrames(page)
    await loginAsAdmin(page)
    await openMenu(page, 'WebSSH终端')
    await pickSelectOption(page, /^R-?1(?:\s|[（(]|$)/)
    await page.getByRole('button', { name: '连接' }).click()
    await expect(page.getByText('SSH 已就绪')).toBeVisible({ timeout: 40000 })
    frames.length = 0

    await pasteText(page, 'display version')

    await expect.poll(() => frames.map(inputData).join(''), { timeout: 10000 }).toContain('display version\r')
    // 设备真的执行了：终端出现版本信息（VRP 字样）
    await expect(page.locator('.webssh-console')).toContainText(/VRP|Versatile Routing Platform/i, { timeout: 40000 })

    guards.assertClean()
  })

  test('多行粘贴：逐行下发、每行都带回车', async ({ page }) => {
    test.setTimeout(120000)
    const guards = attachGuards(page)
    const frames = captureSentFrames(page)
    await loginAsAdmin(page)
    await openMenu(page, 'WebSSH终端')
    await pickSelectOption(page, /^R-?1(?:\s|[（(]|$)/)
    await page.getByRole('button', { name: '连接' }).click()
    await expect(page.getByText('SSH 已就绪')).toBeVisible({ timeout: 40000 })
    frames.length = 0

    await pasteText(page, 'display version\ndisplay clock')

    await expect.poll(() => frames.map(inputData), { timeout: 15000 }).toEqual(['display version\r', 'display clock\r'])
    // 两行都被设备执行：版本信息 + 时钟输出（clock 行的日期分隔）
    await expect(page.locator('.webssh-console')).toContainText(/VRP|Versatile Routing Platform/i, { timeout: 40000 })

    guards.assertClean()
  })

  test('未连接时粘贴给出明确提示且不发帧', async ({ page }) => {
    const guards = attachGuards(page)
    const frames = captureSentFrames(page)
    await loginAsAdmin(page)
    await openMenu(page, 'WebSSH终端')
    // 终端容器在选中设备后才渲染
    await pickSelectOption(page, /^R-?1(?:\s|[（(]|$)/)
    await expect(page.locator('.webssh-console')).toBeVisible({ timeout: 20000 })

    await pasteText(page, 'display version')

    await expect(page.locator('.el-message').filter({ hasText: /SSH 未就绪/ }).first()).toBeVisible({ timeout: 15000 })
    expect(frames).toHaveLength(0)

    guards.assertClean()
  })

  test('键盘 Ctrl+V 也能粘贴（真实按键路径）', async ({ page, context }) => {
    test.setTimeout(120000)
    const guards = attachGuards(page)
    await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: new URL(FRONTEND_URL).origin })
    const frames = captureSentFrames(page)
    await loginAsAdmin(page)
    await openMenu(page, 'WebSSH终端')
    await pickSelectOption(page, /^R-?1(?:\s|[（(]|$)/)
    await page.getByRole('button', { name: '连接' }).click()
    await expect(page.getByText('SSH 已就绪')).toBeVisible({ timeout: 40000 })
    frames.length = 0

    await page.evaluate(() => navigator.clipboard.writeText('display clock'))
    await page.locator('.xterm').click()
    await page.keyboard.press('Control+V')

    await expect.poll(() => frames.map(inputData).join(''), { timeout: 15000 }).toContain('display clock\r')

    guards.assertClean()
  })
})
