import { test, expect } from '@playwright/test'
import { attachGuards, guardFrontendOrSkip, loginAsAdmin, openMenu, requireAdminCredentials } from './helpers'

/**
 * 首页布局回归（2026-10-05 用户反馈"主页有点挤"后新增）。
 *
 * 断言的是"挤"这类问题的客观表现，而不是具体像素：
 * - 右侧操作区各面板按序堆叠、互不重叠（此前多块面板在固定高度里互相挤压）；
 * - 顶部状态栏各项不重叠；
 * - 页面无横向溢出；
 * - 底部分析区为两栏（配置差异+报告 / 操作审计流）；
 * - 中央拓扑区给足高度（不再被压成一条）。
 * 同时把截图写到 test-results/dashboard-layout-*.png 供人工对照参考图。
 */

type Box = { x: number; y: number; width: number; height: number }

async function boxes(locator: import('@playwright/test').Locator): Promise<Box[]> {
  const count = await locator.count()
  const out: Box[] = []
  for (let i = 0; i < count; i += 1) {
    const box = await locator.nth(i).boundingBox()
    if (box) out.push(box)
  }
  return out
}

function overlaps(a: Box, b: Box, tolerance = 2): boolean {
  const vertical = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y)
  const horizontal = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x)
  return vertical > tolerance && horizontal > tolerance
}

for (const viewport of [{ width: 1440, height: 900 }, { width: 1366, height: 768 }]) {
  test(`首页布局不拥挤（${viewport.width}x${viewport.height}）`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await guardFrontendOrSkip()
    requireAdminCredentials()
    const guards = attachGuards(page)
    await loginAsAdmin(page)
    await openMenu(page, '运维总览')
    await expect(page.locator('.kpi-grid')).toBeVisible({ timeout: 20000 })
    await page.waitForTimeout(1500)

    // 1) 右侧操作区面板互不重叠，且按 y 顺序堆叠
    const panels = await boxes(page.locator('.operations-column > .panel'))
    expect(panels.length, '右侧操作区应至少有任务/风险两块面板').toBeGreaterThanOrEqual(2)
    for (let i = 1; i < panels.length; i += 1) {
      const prev = panels[i - 1]
      const cur = panels[i]
      expect(overlaps(prev, cur), `右侧第 ${i} 与第 ${i + 1} 块面板重叠`).toBe(false)
      expect(cur.y, `右侧第 ${i + 1} 块面板未在上一块下方`).toBeGreaterThanOrEqual(prev.y + prev.height - 2)
    }

    // 2) 顶部状态栏各项不重叠
    const stripItems = await boxes(page.locator('.service-strip > .service-item'))
    expect(stripItems.length).toBeGreaterThanOrEqual(5)
    for (let i = 1; i < stripItems.length; i += 1) {
      expect(
        overlaps(stripItems[i - 1], stripItems[i]),
        `顶部状态栏第 ${i} 与第 ${i + 1} 项重叠`,
      ).toBe(false)
    }

    // 3) 无横向溢出
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow, '页面出现横向溢出').toBeLessThanOrEqual(2)

    // 4) 底部分析区两栏：左栏（配置差异+报告）与右栏（审计流）左右并排
    const bottom = await boxes(page.locator('.bottom-grid > .bottom-column'))
    expect(bottom.length).toBe(2)
    expect(bottom[1].x).toBeGreaterThan(bottom[0].x + bottom[0].width - 2)

    // 5) 趋势面板要么有图要么有空态文案（不允许空白占位）
    const trendChart = await page.locator('.trend-chart canvas').count()
    const trendEmpty = await page.locator('.trend-empty').count()
    expect(trendChart + trendEmpty, '告警趋势区既没有图也没有空态提示').toBeGreaterThan(0)

    // 6) 中央拓扑区不能被压扁（此前被压到 ~215px）
    const topologyCanvas = await page.locator('.topology-canvas').boundingBox()
    expect(topologyCanvas?.height ?? 0, '拓扑画布高度过小，页面被压缩').toBeGreaterThanOrEqual(230)

    await page.screenshot({
      path: `test-results/dashboard-layout-${viewport.width}x${viewport.height}.png`,
      fullPage: true,
    })
    guards.assertClean()
  })
}
