import { test, expect } from '@playwright/test'

test.beforeEach(async () => {
  if (!(process.env.E2E_ADMIN_PASSWORD || process.env.LIVE_ADMIN_PASSWORD)) {
    throw new Error('This test requires an explicitly injected administrator password; it never loads .env or skips.')
  }
})

test('未配置视觉模型时禁止图片但保留文本附件', async ({ page }) => {
  await page.route('**/api/v1/ai/capabilities', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ vision_enabled: false, image_mime_types: [] }),
  }))
  await page.goto('/login')
  await page.getByPlaceholder('用户名', { exact: true }).fill(process.env.E2E_ADMIN_USER || process.env.LIVE_ADMIN_USER || 'admin')
  await page.getByPlaceholder('密码', { exact: true }).fill(process.env.E2E_ADMIN_PASSWORD || process.env.LIVE_ADMIN_PASSWORD || '')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL('**/dashboard')
  const opener = page.locator('.copilot-fab')
  if (await opener.isVisible()) await opener.click()
  await expect(page.locator('.copilot .attach-hint-off')).toContainText('图片功能未启用')
  const fileInput = page.locator('.copilot input[type=file]')
  await expect(fileInput).not.toHaveAttribute('accept', /image\//)
  await fileInput.setInputFiles({ name: 'fixture.png', mimeType: 'image/png', buffer: Buffer.from('image-fixture') })
  await expect(page.getByText('图片功能未启用，请联系管理员配置视觉模型', { exact: true })).toBeVisible()
  await expect(page.locator('.copilot .attach-preview img')).toHaveCount(0)
  await fileInput.setInputFiles({ name: 'fixture.txt', mimeType: 'text/plain', buffer: Buffer.from('only local fixture, never submitted') })
  await expect(page.locator('.copilot .attach-file')).toHaveText('fixture.txt')
})
