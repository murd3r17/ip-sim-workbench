import { test, expect } from '@playwright/test'
import { guardFrontendOrSkip, loginAsAdmin } from './helpers'

const OSPF_DRAFT = [
  'system-view',
  'ospf 1 router-id 10.0.1.1',
  'area 0.0.0.0',
  'network 10.0.123.0 0.0.0.255',
  'network 10.0.1.1 0.0.0.0',
  'quit',
  'quit',
].join('\n')

test.beforeAll(async () => {
  await guardFrontendOrSkip()
})

test('校验配置按钮必须带型号，OSPF 草稿不能报 unknown', async ({ page }) => {
  test.setTimeout(45000)
  await loginAsAdmin(page)
  await page.getByRole('menuitem', { name: '配置下发' }).click()
  await expect(page).toHaveURL(/\/deploy/)
  await page.getByPlaceholder('输入VRP配置命令...').fill(OSPF_DRAFT)

  const responsePromise = page.waitForResponse(
    (res) => res.url().includes('/api/v1/deploy/validate') && res.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '校验配置' }).click()
  const response = await responsePromise
  expect(response.ok()).toBeTruthy()

  const requestBody = response.request().postDataJSON() as { config_content?: string; device_model?: string }
  expect(requestBody.device_model, '按钮必须提交 device_model，不能靠后端默认值蒙混').toBeTruthy()
  expect(String(requestBody.device_model).toLowerCase()).not.toBe('unknown')
  expect(requestBody.config_content || '').toContain('ospf 1')

  const payload = await response.json()
  expect(payload.valid, `校验应通过，实际 errors=${JSON.stringify(payload.errors)}`).toBe(true)
  expect(JSON.stringify(payload.errors || [])).not.toContain('unknown')

  await expect(page.getByText(/配置校验通过/)).toBeVisible({ timeout: 10000 })
})
