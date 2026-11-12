import { test, expect } from '@playwright/test'
import {
  attachGuards,
  cancelBox,
  closeDialog,
  guardFrontendOrSkip,
  loginAsAdmin,
  openMenu,
  requireAdminCredentials,
} from './helpers'

/**
 * A7 / B1 / B2 / B5 / B6 维护轮新增界面的冒烟验收。
 *
 * 只断言"入口存在且可点开"，不真正触发耗时/有副作用的动作：
 * - AI 生成类按钮不点击（真实模型调用慢且不确定；端点本身由 pytest mock 覆盖 + 全链路校验实测）；
 * - 回滚按钮只打开确认框后取消（不生成任务）；
 * - 知识库检索在 provider 不可用时跳过（AnythingLLM 未启动的环境不应判失败）。
 */

test.describe('维护轮界面验收', () => {
  test.beforeEach(async () => {
    await guardFrontendOrSkip()
    requireAdminCredentials()
  })

  test('首页：状态栏字段 / 告警趋势 / 审批状态 / 操作审计流', async ({ page }) => {
    const guards = attachGuards(page)
    await loginAsAdmin(page)

    // 先直查接口：A7 新增字段必须真的在响应里。
    // （/dashboard/summary 有 response_model，未登记的字段会被 FastAPI 静默裁掉 —— 曾经踩过。）
    const token = await page.evaluate(() => localStorage.getItem('token'))
    const summaryResp = await page.request.get('/api/v1/dashboard/summary', {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(summaryResp.ok()).toBeTruthy()
    const payload = await summaryResp.json()
    expect(Array.isArray(payload.alarms?.trend), 'alarms.trend 缺失（response_model 未登记？）').toBe(true)
    expect(payload.alarms.trend.length).toBe(7)
    expect(Array.isArray(payload.approvals), 'approvals 缺失（response_model 未登记？）').toBe(true)
    expect(Array.isArray(payload.reports), 'reports 缺失（response_model 未登记？）').toBe(true)

    await openMenu(page, '运维总览')

    const strip = page.locator('.service-strip')
    await expect(strip).toBeVisible({ timeout: 20000 })
    // 顶部状态栏（2026-10-05 精简："数据库"移入 KPI「基础服务」，任务/告警合并计数）
    for (const label of ['设备', '任务队列', '待审批', '活跃告警', '模型', '知识库', '系统时间']) {
      await expect(strip.getByText(label, { exact: true })).toBeVisible()
    }

    // A7：近 7 天告警趋势（有数据时必须是真的图表，不能退化成空态）
    await expect(page.locator('.trend-panel')).toBeVisible()
    const trendTotal = payload.alarms.trend.reduce((sum: number, p: { count: number }) => sum + p.count, 0)
    if (trendTotal > 0) {
      await expect(page.locator('.trend-chart canvas'), '有告警数据却没渲染趋势图').toBeVisible({ timeout: 20000 })
    } else {
      await expect(page.locator('.trend-empty')).toBeVisible({ timeout: 20000 })
    }

    // A7：右侧审批状态（仅在有待处理变更时出现）与底部操作审计流
    const approvalPanel = page.locator('.approval-panel')
    if (await approvalPanel.count()) {
      await expect(approvalPanel).toBeVisible()
    }

    // A7：底部分析区两栏（配置差异+报告 / 操作审计流）
    await expect(page.locator('.bottom-grid')).toBeVisible()
    await expect(page.getByText('操作审计流（命令流替代）')).toBeVisible()
    await expect(page.getByText('配置差异（最近变更）')).toBeVisible()
    await expect(page.getByText('巡检 / 验证报告')).toBeVisible()

    // 全局头部：环境名 + 时钟
    await expect(page.locator('.env-clock')).toContainText('IP仿真运维管理工作台')

    guards.assertClean()
  })

  test('变更审批页：可从导航进入并展示待处理任务', async ({ page }) => {
    const guards = attachGuards(page)
    await loginAsAdmin(page)
    await openMenu(page, '变更审批')

    await expect(page).toHaveURL(/\/approvals/)
    await expect(page.getByText('变更审批', { exact: true }).first()).toBeVisible({ timeout: 20000 })
    await expect(page.getByRole('button', { name: '去下发中心' })).toBeVisible()
    // 表格或空态必须有一个（不允许白屏）
    const table = page.locator('.el-table')
    const empty = page.getByText('没有待审批的变更任务。')
    await expect(table.or(empty).first()).toBeVisible({ timeout: 20000 })

    guards.assertClean()
  })

  test('首页审批入口可跳转到审批页', async ({ page }) => {
    const guards = attachGuards(page)
    await loginAsAdmin(page)
    await openMenu(page, '运维总览')

    const approvalPanel = page.locator('.approval-panel')
    if (await approvalPanel.count()) {
      // 有待处理变更：右侧面板与其「审批中心」按钮必须可见可用
      await expect(approvalPanel).toBeVisible({ timeout: 20000 })
      await approvalPanel.getByRole('button', { name: '审批中心' }).click()
    } else {
      // 没有待处理变更时右侧面板整体不渲染（避免占位挤压），改走顶部状态栏「待审批」入口
      await page.locator('.service-strip .service-item').filter({ hasText: '待审批' }).click()
    }
    await expect(page).toHaveURL(/\/approvals/)
    guards.assertClean()
  })

  test('配置管理：回滚按钮打开确认框（取消，不产生任务）', async ({ page }) => {
    test.setTimeout(120000)
    const guards = attachGuards(page)
    await loginAsAdmin(page)
    await openMenu(page, '配置管理')

    // 等快照表渲染完（count() 不会等待，表格加载中会误判为"没有快照"）
    await page.locator('.el-table__row').first().waitFor({ state: 'visible', timeout: 20000 }).catch(() => {})
    const rollbackButtons = page.getByRole('button', { name: '回滚' })
    const count = await rollbackButtons.count()
    if (count === 0) {
      test.skip(true, '当前没有配置快照，跳过回滚入口检查（先到配置管理采集一次快照再跑）')
    }
    await rollbackButtons.first().click()
    await expect(page.getByText(/生成一个高风险回滚任务/)).toBeVisible({ timeout: 15000 })
    await cancelBox(page)
    await expect(page.getByText(/生成一个高风险回滚任务/)).toBeHidden()

    guards.assertClean()
  })

  test('配置管理：AI 差异说明入口存在', async ({ page }) => {
    const guards = attachGuards(page)
    await loginAsAdmin(page)
    await openMenu(page, '配置管理')
    await page.getByRole('tab', { name: '配置差异比对' }).click()
    await expect(page.getByRole('button', { name: 'AI 说明差异' })).toBeVisible()
    guards.assertClean()
  })

  test('配置下发：任务详情有 5 步进度与「下一步」提示', async ({ page }) => {
    test.setTimeout(120000)
    const guards = attachGuards(page)
    await loginAsAdmin(page)
    await openMenu(page, '配置下发')
    await page.getByRole('tab', { name: '任务管理' }).click()

    // 任务列表本身要有「下一步」列
    await expect(page.getByRole('columnheader', { name: '下一步' })).toBeVisible({ timeout: 20000 })

    const detailBtn = page.getByRole('button', { name: '详情' }).first()
    if (!(await detailBtn.isVisible().catch(() => false))) {
      test.skip(true, '当前没有下发任务，跳过流程提示检查（先创建一条任务再跑）')
    }
    await detailBtn.click()
    const dialog = page.getByRole('dialog', { name: '任务详情' })
    await expect(dialog).toBeVisible({ timeout: 20000 })

    // 5 步流程名 + 「下一步：点…」提示
    for (const step of ['创建任务', '确认下发', '执行', '验证', '完成']) {
      await expect(dialog.getByText(step, { exact: true }).first()).toBeVisible()
    }
    await expect(dialog.getByText(/下一步：点|已完成：|已失败：|正在回读|已取消|已回滚/).first()).toBeVisible()

    await closeDialog(page, '任务详情')
    guards.assertClean()
  })

  test('监控大盘：巡检任务有 AI 总结入口', async ({ page }) => {
    const guards = attachGuards(page)
    await loginAsAdmin(page)
    await openMenu(page, '监控大盘')

    await expect(page.getByText('巡检任务', { exact: true })).toBeVisible({ timeout: 20000 })
    const jobs = page.locator('.el-table').last()
    await expect(jobs).toBeVisible()
    // 有巡检记录时才有按钮；无记录时该列不存在也应视为通过
    const aiButtons = page.getByRole('button', { name: 'AI 总结' })
    if (await aiButtons.count()) {
      await expect(aiButtons.first()).toBeVisible()
    }
    guards.assertClean()
  })

  test('知识库：检索结果的引用详情抽屉', async ({ page }) => {
    test.setTimeout(120000)
    const guards = attachGuards(page)
    await loginAsAdmin(page)
    await openMenu(page, '知识库管理')

    // 状态标签在健康检查返回前会短暂显示"降级"，因此等"可用"出现；15s 内不出现才判定降级。
    const healthCard = page.locator('.el-card').filter({ hasText: '知识库状态' }).first()
    await expect(healthCard).toBeVisible({ timeout: 20000 })
    const degraded = await page
      .getByText('可用', { exact: true })
      .first()
      .waitFor({ state: 'visible', timeout: 15000 })
      .then(() => false)
      .catch(() => true)
    if (degraded) {
      test.skip(true, '知识库 provider 当前不可用（状态显示降级），跳过引用详情检查')
    }

    await page.getByRole('tab', { name: '检索测试' }).click()
    await page.getByPlaceholder('输入检索关键词...').fill('OSPF 邻居')
    await page.getByRole('button', { name: '检索', exact: true }).click()
    const card = page.locator('.el-card').filter({ hasText: '相关度' }).first()
    // 注意：locator.isVisible() 不接受 timeout、不会等待，必须用 waitFor
    const hasResult = await card.waitFor({ state: 'visible', timeout: 30000 }).then(() => true).catch(() => false)
    if (!hasResult) {
      test.skip(true, '检索无结果，跳过引用详情检查')
    }
    await card.click()
    // 抽屉断言用容器（'引用详情' 文本在每张卡片的按钮上也出现，直接 getByText 会命中多个）
    const drawer = page.locator('.el-drawer').last()
    await expect(drawer).toBeVisible({ timeout: 15000 })
    await expect(drawer).toContainText('引用详情')
    await expect(drawer).toContainText('引用片段')
    await expect(drawer).toContainText('完整原文见语料目录')
    guards.assertClean()
  })
})
