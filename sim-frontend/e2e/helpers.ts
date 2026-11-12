import fs from 'node:fs'
import path from 'node:path'
import { expect, test, type Page } from '@playwright/test'

export const FRONTEND_URL = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173'

/** 读取仓库根 .env（gitignored）。口令只从本地配置取，禁止写进测试代码。 */
function readRootEnv(): Record<string, string> {
  const candidates = [
    path.resolve(process.cwd(), '..', '.env'),
    path.resolve(process.cwd(), '.env'),
  ]
  for (const file of candidates) {
    try {
      const text = fs.readFileSync(file, 'utf8')
      const out: Record<string, string> = {}
      for (const line of text.split(/\r?\n/)) {
        const m = /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/.exec(line)
        if (!m) continue
        let value = m[2].trim()
        if (
          (value.startsWith('"') && value.endsWith('"')) ||
          (value.startsWith("'") && value.endsWith("'"))
        ) {
          value = value.slice(1, -1)
        }
        out[m[1]] = value
      }
      return out
    } catch {
      /* 试下一个候选路径 */
    }
  }
  return {}
}

const ROOT_ENV = readRootEnv()
export const ADMIN_USER = process.env.E2E_ADMIN_USER || ROOT_ENV.ADMIN_USERNAME || 'admin'
export const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || ROOT_ENV.ADMIN_PASSWORD || ''

export function requireAdminCredentials(): void {
  if (!ADMIN_PASSWORD) {
    throw new Error(
      '未配置管理员口令：请在仓库根 .env 设置 ADMIN_PASSWORD（或导出 E2E_ADMIN_PASSWORD）。' +
        '测试不再内置明文口令。',
    )
  }
}

export async function frontendIsUp(): Promise<boolean> {
  try {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 1500)
    const res = await fetch(FRONTEND_URL, { signal: controller.signal })
    clearTimeout(timer)
    return res.ok || res.status < 500
  } catch {
    return false
  }
}

/**
 * 前端未启动时的处理。
 *
 * 默认跳过（本地没起服务时不至于满屏红）；但设置 E2E_REQUIRE_UP=1 后改为**抛错**，
 * 避免"全绿但一条都没执行"——CI / 验收必须用这个模式。
 */
export async function guardFrontendOrSkip(): Promise<void> {
  if (await frontendIsUp()) return
  if (process.env.E2E_REQUIRE_UP === '1') {
    throw new Error(
      `前端未在 ${FRONTEND_URL} 运行，且 E2E_REQUIRE_UP=1：按失败处理（不要静默跳过）。` +
        '请先启动服务：scripts\\start-local-windows.ps1 或 scripts\\bootstrap-local.ps1',
    )
  }
  test.skip(true, `frontend is not running at ${FRONTEND_URL}`)
}

export async function loginAsAdmin(page: Page) {
  requireAdminCredentials()
  await page.goto('/login')
  await page.getByPlaceholder('用户名').fill(ADMIN_USER)
  await page.getByPlaceholder('密码').fill(ADMIN_PASSWORD)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByText('运维总览').first()).toBeVisible({ timeout: 15000 })
  await ensureCopilotClosed(page)
}

export async function ensureCopilotClosed(page: Page) {
  const collapse = page.locator('button.icon-btn[title="收起"]')
  if (await collapse.isVisible().catch(() => false)) {
    await collapse.click()
  }
  const toggleOn = page.locator('button.ai-toggle.on')
  if (await toggleOn.isVisible().catch(() => false)) {
    await toggleOn.click()
  }
}

export async function confirmBox(page: Page, buttonName = '确定') {
  const box = page.locator('.el-message-box, [role="alertdialog"]').last()
  await expect(box).toBeVisible({ timeout: 15000 })
  const re = buttonName === '确定' ? /确定|OK|确认/ : new RegExp(buttonName)
  await box.locator('button').filter({ hasText: re }).last().click({ force: true })
}

export async function cancelBox(page: Page) {
  const box = page.locator('.el-message-box:visible, .el-overlay-message-box:visible .el-message-box').last()
  await expect(box).toBeVisible({ timeout: 15000 })
  const cancel = box.locator('button').filter({ hasText: /取消|Cancel/ })
  if (await cancel.count()) {
    await cancel.last().click({ force: true })
  } else {
    await page.keyboard.press('Escape')
  }
}

export async function pickSelectOption(page: Page, optionText: string | RegExp, nearText?: string) {
  const select = nearText
    ? page.locator('.el-form-item').filter({ hasText: nearText }).locator('.el-select').first()
    : page.locator('.el-select').first()
  await select.click({ force: true })
  const item = page
    .locator('.el-select-dropdown.el-popper:visible, .el-popper.is-pure:visible')
    .last()
    .locator('.el-select-dropdown__item')
    .filter({ hasText: optionText })
    .first()
  await expect(item).toBeVisible({ timeout: 10000 })
  await item.click({ force: true })
  if (nearText === '目标设备') {
    await expect(select).toContainText(optionText, { timeout: 5000 })
  }
}

export function attachGuards(page: Page) {
  const pageErrors: string[] = []
  const apiFails: string[] = []
  page.on('pageerror', (err) => pageErrors.push(String(err)))
  page.on('response', (res) => {
    const url = res.url()
    if (!url.includes('/api/v1/')) return
    if (res.status() >= 500) {
      apiFails.push(`${res.status()} ${res.request().method()} ${url.replace(FRONTEND_URL, '')}`)
    }
  })
  return {
    assertClean() {
      expect(pageErrors, `页面脚本错误:\n${pageErrors.join('\n')}`).toEqual([])
      expect(apiFails, `接口 5xx:\n${apiFails.join('\n')}`).toEqual([])
    },
  }
}

export async function openMenu(page: Page, name: string) {
  await page.getByRole('menuitem', { name, exact: true }).click()
}

export async function openSystemMenu(page: Page, name: string) {
  const item = page.getByRole('menuitem', { name, exact: true })
  if (!(await item.isVisible().catch(() => false))) {
    await page.getByText('系统管理', { exact: true }).click()
  }
  await item.click()
}

export async function expectToast(page: Page, pattern: RegExp, timeout = 30000) {
  await expect(page.locator('.el-message').filter({ hasText: pattern }).first()).toBeVisible({ timeout })
}

export function visibleDialog(page: Page, title: string | RegExp) {
  return page.getByRole('dialog', { name: title }).filter({ visible: true })
}

/** 点对话框页脚按钮。exact 避免「关闭」命中标题栏「关闭此对话框」。 */
export async function clickDialogFooter(page: Page, title: string | RegExp, buttonName: string) {
  const dlg = visibleDialog(page, title)
  await expect(dlg).toBeVisible({ timeout: 15000 })
  const btn = dlg.locator('.el-dialog__footer').getByRole('button', { name: buttonName, exact: true })
  // 先显式等按钮出现（失败时 15s 内给出明确报错），再等可用，最后点击；
  // 点击失败退回 force（侧栏遮挡等场景），否则会一直等到用例超时。
  await expect(btn, `「${title}」弹窗底部应有按钮「${buttonName}」`).toBeVisible({ timeout: 15000 })
  await expect(btn).toBeEnabled({ timeout: 15000 })
  try {
    await btn.click({ timeout: 10000 })
  } catch {
    await btn.click({ force: true, timeout: 10000 })
  }
}

export async function closeDialog(page: Page, title?: string | RegExp) {
  const dlg = title ? page.getByRole('dialog', { name: title }) : page.getByRole('dialog').last()
  if (!(await dlg.isVisible().catch(() => false))) return
  const footerClose = dlg.locator('.el-dialog__footer').getByRole('button', { name: /^(关闭|取消)$/ })
  if (await footerClose.count()) {
    await footerClose.last().click({ force: true })
    return
  }
  await dlg.locator('.el-dialog__headerbtn').click({ force: true })
}
