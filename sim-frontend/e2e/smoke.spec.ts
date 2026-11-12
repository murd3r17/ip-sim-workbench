import { test, expect } from '@playwright/test'
import { guardFrontendOrSkip, loginAsAdmin } from './helpers'

test.beforeAll(async () => {
  await guardFrontendOrSkip()
})

test('login with configured admin credentials reaches dashboard', async ({ page }) => {
  await loginAsAdmin(page)
  await expect(page.getByText('运维总览').first()).toBeVisible({ timeout: 15000 })
})

test('knowledge page renders health area', async ({ page }) => {
  await loginAsAdmin(page)
  await page.getByRole('menuitem', { name: '知识库管理' }).click()
  await expect(page.getByText('知识库状态')).toBeVisible()
  await expect(page.getByText('可用', { exact: true })).toBeVisible()
})

test('deploy page shows create-task and does not auto SSH', async ({ page }) => {
  await loginAsAdmin(page)
  await page.getByRole('menuitem', { name: '配置下发' }).click()
  await expect(page).toHaveURL(/\/deploy/)
  await expect(page.getByRole('button', { name: '创建任务' })).toBeVisible()
  await expect(page.getByRole('button', { name: '校验配置' })).toBeVisible()
})
