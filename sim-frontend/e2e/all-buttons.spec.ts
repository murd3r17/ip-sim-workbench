import { test, expect, type Response } from '@playwright/test'
import {
  attachGuards,
  cancelBox,
  clickDialogFooter,
  closeDialog,
  confirmBox,
  expectToast,
  guardFrontendOrSkip,
  loginAsAdmin,
  openMenu,
  openSystemMenu,
  pickSelectOption,
  requireAdminCredentials,
  ADMIN_USER,
  ADMIN_PASSWORD,
} from './helpers'

test.beforeAll(async () => {
  await guardFrontendOrSkip()
})

test.describe.configure({ timeout: 180000 })

const OSPF_DRAFT = [
  'system-view',
  'ospf 1 router-id 10.0.1.1',
  'area 0.0.0.0',
  'network 10.0.123.0 0.0.0.255',
  'network 10.0.1.1 0.0.0.0',
  'quit',
  'quit',
].join('\n')

test.describe('全页面真实按钮验收', () => {
  test('登录页：空提交提示，正确账号进入总览', async ({ page }) => {
    requireAdminCredentials()
    const guards = attachGuards(page)
    await page.goto('/login')
    await page.getByRole('button', { name: '登录' }).click()
    await expectToast(page, /请输入用户名和密码/)
    await page.getByPlaceholder('用户名').fill(ADMIN_USER)
    await page.getByPlaceholder('密码').fill(ADMIN_PASSWORD)
    await page.getByRole('button', { name: '登录' }).click()
    await expect(page.getByText('运维总览').first()).toBeVisible({ timeout: 15000 })
    guards.assertClean()
  })

  test('总览：刷新、KPI 跳转、拓扑节点即时命令、display version', async ({ page }) => {
    const guards = attachGuards(page)
    await loginAsAdmin(page)
    await page.getByRole('button', { name: '↻' }).click()
    await expect(page.getByRole('button', { name: /资产总数/ })).toBeVisible()

    await page.getByRole('button', { name: /资产总数/ }).click()
    await expect(page).toHaveURL(/\/devices/)
    await openMenu(page, '运维总览')

    await page.getByRole('button', { name: /在线设备/ }).click()
    await expect(page).toHaveURL(/\/devices/)
    await openMenu(page, '运维总览')

    await page.getByRole('button', { name: /拓扑链路/ }).click()
    await expect(page).toHaveURL(/\/topology/)
    await openMenu(page, '运维总览')

    await page.getByRole('button', { name: /运行任务/ }).click()
    await expect(page).toHaveURL(/\/deploy/)
    await openMenu(page, '运维总览')

    // 待审批 → 审批页（与用户手册一致：审批动作在变更审批页，不在下发任务列表）
    await page.getByRole('button', { name: /待审批/ }).click()
    await expect(page).toHaveURL(/\/approvals/)
    await openMenu(page, '运维总览')

    // 活跃告警 → 告警页并带上"未处理"筛选
    await page.getByRole('button', { name: /活跃告警/ }).click()
    await expect(page).toHaveURL(/\/alarms/)
    await expect(page).toHaveURL(/status=active/)
    await openMenu(page, '运维总览')

    await page.getByRole('button', { name: /实训中心/ }).click()
    await expect(page).toHaveURL(/\/training/)
    await openMenu(page, '运维总览')

    await page.getByRole('button', { name: /基础服务/ }).click()
    await expect(page).toHaveURL(/\/system\/info/)
    await openMenu(page, '运维总览')

    await page.getByRole('button', { name: '完整拓扑' }).click()
    await expect(page).toHaveURL(/\/topology/)
    await openMenu(page, '运维总览')

    await page.getByRole('button', { name: '任务中心' }).click()
    await expect(page).toHaveURL(/\/deploy/)
    await openMenu(page, '运维总览')
    const goDeploy = page.getByRole('button', { name: '去配置下发' })
    if (await goDeploy.isVisible().catch(() => false)) {
      await goDeploy.click()
      await expect(page).toHaveURL(/\/deploy/)
      await openMenu(page, '运维总览')
    }
    const taskRow = page.locator('button.task-row').first()
    if (await taskRow.isVisible().catch(() => false)) {
      await taskRow.click()
      await expect(page).toHaveURL(/\/deploy|\/system\/tasks/)
      await openMenu(page, '运维总览')
    }
    await page.getByRole('button', { name: /配置差异/ }).click()
    await expect(page).toHaveURL(/\/config-versions/)
    await openMenu(page, '运维总览')
    await page.getByRole('button', { name: '审计报告' }).click()
    await expect(page).toHaveURL(/\/system\/audit/)
    await openMenu(page, '运维总览')
    const riskRow = page.locator('button.risk-row').first()
    if (await riskRow.isVisible().catch(() => false)) {
      await riskRow.click()
      await openMenu(page, '运维总览')
    }

    const node = page.locator('.topology-node').first()
    if (await node.count()) {
      await node.click()
      await expect(page.getByText('即时命令')).toBeVisible({ timeout: 15000 })
      await page.getByPlaceholder('输入多行 VRP 命令，例如：display version').fill('display version')
      const sendBtn = page.getByRole('button', { name: '确认下发' })
      await expect(sendBtn).toBeEnabled({ timeout: 30000 })
      await sendBtn.click()
      await confirmBox(page, '发送命令')
      await page.getByRole('button', { name: '完整 WebSSH' }).click()
      await expect(page).toHaveURL(/\/webssh\//)
      await openMenu(page, '运维总览')
      if (await page.locator('.topology-node').first().count()) {
        await page.locator('.topology-node').first().click()
        await page.getByRole('button', { name: '配置下发' }).click()
        await expect(page).toHaveURL(/\/deploy/)
        await openMenu(page, '运维总览')
        await page.locator('.topology-node').first().click()
        await page.getByRole('button', { name: '关闭' }).click()
      }
    }
    guards.assertClean()
  })

  test('设备管理：健康检查、行内终端/下发/告警、删除取消、添加取消', async ({ page }) => {
    const guards = attachGuards(page)
    await loginAsAdmin(page)
    await openMenu(page, '设备管理')
    await expect(page.getByText(/^R-?1$/).first()).toBeVisible({ timeout: 15000 })

    await page.getByRole('button', { name: '健康检查' }).click()
    await expectToast(page, /健康检查完成/, 60000)

    await page.getByRole('button', { name: '添加设备' }).click()
    await expect(page.getByText('添加设备').first()).toBeVisible()
    await page.getByRole('button', { name: '取消' }).click()

    const r1 = page.locator('.el-table__row').filter({ has: page.getByText(/^R-?1$/) }).first()
    await r1.getByRole('button', { name: '编辑' }).click()
    await expect(page.getByText('编辑设备').first()).toBeVisible()
    await page.getByRole('button', { name: '取消' }).click()
    await r1.getByRole('button', { name: '告警' }).click()
    await expect(page).toHaveURL(/\/alarms/)
    await openMenu(page, '设备管理')
    await r1.getByRole('button', { name: '下发' }).click()
    await expect(page).toHaveURL(/\/deploy/)
    await openMenu(page, '设备管理')
    await r1.getByRole('button', { name: '删除' }).click()
    await cancelBox(page)
    await r1.getByRole('button', { name: '终端' }).click()
    await expect(page).toHaveURL(/\/webssh\/\d+(?:[/?#]|$)/)
    guards.assertClean()
  })

  test('WebSSH：连接、断开、返回设备', async ({ page }) => {
    const guards = attachGuards(page)
    await loginAsAdmin(page)
    await openMenu(page, 'WebSSH终端')
    await pickSelectOption(page, /^R-?1(?:\s|[（(]|$)/)
    await page.getByRole('button', { name: '连接' }).click()
    await expect(page.getByText('已连接', { exact: true })).toBeVisible({ timeout: 30000 })
    await page.getByRole('button', { name: '断开' }).click()
    await page.getByRole('button', { name: '返回设备' }).click()
    await expect(page).toHaveURL(/\/devices/)
    guards.assertClean()
  })

  test('拓扑：刷新、运行态校验、版本记录、保存草稿、发布取消、新建取消、导入文件选择器', async ({ page }) => {
    const guards = attachGuards(page)
    await loginAsAdmin(page)
    await openMenu(page, '拓扑可视化')
    await page.getByRole('button', { name: '刷新' }).click()
    await expect(page.getByText(/设备 \d+/)).toBeVisible({ timeout: 15000 })

    await page.getByRole('button', { name: '运行态校验' }).click()
    await expectToast(page, /运行态校验完成|部分设备发现失败/, 90000)

    const baseline = page.getByRole('button', { name: '确认eNSP基线' })
    if (await baseline.isVisible().catch(() => false)) {
      await baseline.click()
      await cancelBox(page)
    }

    await page.getByRole('button', { name: '版本记录' }).click()
    await expect(page.getByText('拓扑基线版本')).toBeVisible()
    const rollback = page.getByRole('button', { name: '回滚' }).first()
    if (await rollback.isVisible().catch(() => false)) {
      await rollback.click()
      await cancelBox(page)
    }
    await page.locator('.el-dialog').filter({ hasText: '拓扑基线版本' }).locator('.el-dialog__headerbtn').click()

    await page.getByRole('button', { name: '保存草稿' }).click()
    await expectToast(page, /拓扑草稿已保存/, 20000)

    await page.getByRole('button', { name: '恢复已发布布局' }).click()
    await expectToast(page, /已恢复已发布布局/, 20000)

    await page.getByRole('button', { name: '发布到运维总览' }).click()
    await cancelBox(page)

    await page.getByRole('button', { name: '新建拓扑' }).click()
    await page.getByRole('button', { name: '取消' }).click()

    const [chooser] = await Promise.all([
      page.waitForEvent('filechooser'),
      page.getByRole('button', { name: '导入Excel基线' }).click(),
    ])
    expect(chooser).toBeTruthy()

    const selected = page.locator('.topology-node, canvas, .graph-container').first()
    await selected.click({ position: { x: 80, y: 80 } }).catch(() => {})
    if (await page.getByRole('button', { name: '开终端' }).isVisible().catch(() => false)) {
      await page.getByRole('button', { name: '开终端' }).click()
      await expect(page).toHaveURL(/\/webssh/)
      await openMenu(page, '拓扑可视化')
    }
    await selected.click({ position: { x: 80, y: 80 } }).catch(() => {})
    if (await page.getByRole('button', { name: '去下发' }).isVisible().catch(() => false)) {
      await page.getByRole('button', { name: '去下发' }).click()
      await expect(page).toHaveURL(/\/deploy/)
      await openMenu(page, '拓扑可视化')
    }
    guards.assertClean()
  })

  test('配置下发：校验、AI 审查、创建任务、确认、执行模拟、验证、模板', async ({ page }) => {
    test.setTimeout(300000)
    const minimal = process.env.E2E_PROFILE === 'minimal'
    const pageErrors: string[] = []
    const apiFailures: Response[] = []
    const expectedFailures = new Set<Response>()
    page.on('pageerror', error => pageErrors.push(String(error)))
    page.on('response', response => {
      if (response.url().includes('/api/v1/') && response.status() >= 500) apiFailures.push(response)
    })
    const guards = { assertClean() {
      expect(pageErrors, '页面脚本错误').toEqual([])
      expect(expectedFailures.size).toBe(minimal ? 2 : 0)
      expect(apiFailures.filter(response => !expectedFailures.has(response)).map(response =>
        `${response.status()} ${response.request().method()} ${new URL(response.url()).pathname}`), '非预期接口 5xx').toEqual([])
    } }
    await loginAsAdmin(page)
    await openMenu(page, '配置下发')

    // 记录基线任务 id：收尾时只清理本次用例新建、且仍处于非终态的任务
    // （不能用 created_at 判断——后端返回的是无时区 UTC 字符串，按本地时间解析会差时区）
    const e2eToken = await page.evaluate(() => localStorage.getItem('token'))
    const e2eAuth = { Authorization: `Bearer ${e2eToken}` }
    const tasksBefore = await page.request.get('/api/v1/deploy/tasks', { headers: e2eAuth })
    expect(tasksBefore.ok(), '应成功读取任务基线，避免误清理已有任务').toBeTruthy()
    const baselineIds = new Set<number>(
      (await tasksBefore.json()).map((t: { id: number }) => t.id),
    )

    await page.getByPlaceholder('输入本次配置任务名称').fill(`e2e验收 ${Date.now()}`)
    await pickSelectOption(page, /^R-?1(?:\s|[（(]|$)/, '目标设备')
    await page.getByPlaceholder('输入VRP配置命令...').fill(OSPF_DRAFT)

    const validateResp = page.waitForResponse((r) => r.url().includes('/deploy/validate') && r.request().method() === 'POST')
    await page.getByRole('button', { name: '校验配置' }).click()
    const vres = await validateResp
    const vbody = vres.request().postDataJSON() as { device_model?: string }
    expect(vbody.device_model).toBeTruthy()
    expect(String(vbody.device_model).toLowerCase()).not.toBe('unknown')
    expect((await vres.json()).valid).toBe(true)
    await expectToast(page, /配置校验通过/)

    await page.getByPlaceholder('用自然语言描述要生成的配置').fill('只生成一行命令：sysname E2EProbe')
    const generateResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/ai/generate-and-validate' && response.request().method() === 'POST')
    await page.getByRole('button', { name: 'AI 生成并校验' }).click()
    const generated = await generateResponse
    expect(generated.status()).toBe(minimal ? 500 : 200)
    if (minimal) {
      expect((await generated.json()).detail).toMatch(/配置生成失败/)
      expectedFailures.add(generated)
    }
    await expectToast(page, minimal ? /配置生成失败/ : /已填入配置文本框/, 90000)

    await page.getByPlaceholder('输入VRP配置命令...').fill('sysname E2EProbe')
    const reviewResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/ai/review-config' && response.request().method() === 'POST')
    await page.getByRole('button', { name: 'AI 审查配置' }).click()
    const reviewed = await reviewResponse
    expect(reviewed.status()).toBe(minimal ? 500 : 200)
    if (minimal) {
      expect((await reviewed.json()).detail).toMatch(/配置审查失败/)
      expectedFailures.add(reviewed)
    }
    await expectToast(page, minimal ? /配置审查失败/ : /审查完成/, 90000)

    await page.getByPlaceholder('输入VRP配置命令...').fill('sysname E2EProbe')
    await page.getByRole('button', { name: '创建任务' }).click()
    await expectToast(page, /配置任务已创建/)

    await page.getByRole('tab', { name: '任务管理' }).click()
    await page.getByRole('button', { name: '详情' }).first().click()
    await expect(page.getByText('任务详情')).toBeVisible()
    const confirmBtn = page.getByRole('button', { name: '确认' }).first()
    if (await confirmBtn.isVisible()) {
      // 用 HTTP 响应断言而不是只等 Toast：ElMessage 约 3 秒消失，而"是否为高风险、要不要
      // 二次确认"的判断本身要等 2 秒，容易偶发地"点了却没看到提示"（实测命中过一次）。
      const confirmPath = /\/deploy\/tasks\/\d+\/confirm$/
      const firstConfirm = page.waitForResponse(
        (r) => confirmPath.test(new URL(r.url()).pathname) && r.request().method() === 'POST',
      )
      await confirmBtn.click()
      // 200=直接确认；422=高风险，需二次确认（下面弹窗里再确认一次）
      expect([200, 422]).toContain((await firstConfirm).status())

      const risk = page.locator('.el-message-box').filter({ hasText: '高风险' })
      if (await risk.isVisible({ timeout: 2000 }).catch(() => false)) {
        const secondConfirm = page.waitForResponse(
          (r) => confirmPath.test(new URL(r.url()).pathname) && r.request().method() === 'POST',
        )
        await risk.getByRole('button', { name: /我确认/ }).click()
        expect((await secondConfirm).status()).toBe(200)
      }
    }
    const execBtn = page.getByRole('button', { name: '执行', exact: true }).first()
    if (await execBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      const execResp = page.waitForResponse(
        (r) => /\/deploy\/tasks\/\d+\/execute$/.test(new URL(r.url()).pathname) && r.request().method() === 'POST',
      )
      await execBtn.click()
      expect((await execResp).status()).toBe(200)
      await expectToast(page, /模拟执行完成/)
    }
    const verifyBtn = page.getByRole('button', { name: /验证报告|查看结果/ }).first()
    if (await verifyBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await verifyBtn.click()
      await expect(page.getByRole('dialog', { name: '验证报告' })).toBeVisible()
      await closeDialog(page, '验证报告')
      await expect(page.getByRole('dialog', { name: '验证报告' })).toBeHidden({ timeout: 10000 })
    }
    const detailDlg = page.getByRole('dialog', { name: '任务详情' })
    if (await detailDlg.isVisible().catch(() => false)) {
      await detailDlg.getByRole('button', { name: '刷新' }).click({ force: true })
      await clickDialogFooter(page, '任务详情', '关闭')
      await expect(detailDlg).toBeHidden({ timeout: 10000 })
    }
    await page.keyboard.press('Escape')
    await page.getByRole('tab', { name: '配置模板' }).click({ force: true })
    await page.getByRole('button', { name: '新建模板' }).click()
    await clickDialogFooter(page, '新建配置模板', '取消')
    await page.getByRole('button', { name: '新建模板' }).click()
    await page.getByPlaceholder('输入模板名称').fill(`e2e模板${Date.now()}`)
    await page.getByPlaceholder('输入分类').fill('e2e')
    await page.getByPlaceholder('输入配置模板...').fill('sysname {{hostname}}')
    await page.getByPlaceholder('JSON格式，如 {"hostname": {"required": true}}').fill('{"hostname":{"required":true}}')
    await page.getByPlaceholder('JSON格式，如 {"hostname": "Router01"}').fill('{"hostname":"E2E"}')
    await page.getByRole('button', { name: '渲染预览' }).click()
    await expect(page.getByRole('dialog', { name: '渲染预览' })).toBeVisible()
    await closeDialog(page, '渲染预览')
    await expect(page.getByRole('dialog', { name: '渲染预览' })).toBeHidden()
    await expect(page.getByRole('dialog', { name: '新建配置模板' })).toBeVisible()
    await clickDialogFooter(page, '新建配置模板', '确定')
    await expectToast(page, /模板创建成功/)
    const useBtn = page.getByRole('button', { name: '使用' }).first()
    if (await useBtn.isVisible()) {
      await useBtn.click()
      await expect(page.getByPlaceholder('输入VRP配置命令...')).toHaveValue(/sysname/)
    }
    const loadDraft = page.getByRole('button', { name: '载入草稿' })
    if (await loadDraft.isVisible().catch(() => false)) {
      await loadDraft.click()
      await page.getByRole('button', { name: '清除草稿' }).click()
    }
    await page.getByRole('button', { name: '配置管理' }).click()
    await expect(page).toHaveURL(/\/config-versions/)

    // 收尾只处理本次新增任务：已执行的任务必须验证，执行前的任务才允许取消。
    // 在途验证或仍在执行的设备写入不能靠取消释放锁；接口拒绝必须让验收失败。
    const tasksAfter = await page.request.get('/api/v1/deploy/tasks', { headers: e2eAuth })
    expect(tasksAfter.ok(), '收尾必须成功读取任务，不能将请求失败当成无残留').toBeTruthy()
    const allTasks: Array<{ id: number; status: string }> = await tasksAfter.json()
    const terminal = ['success', 'failed', 'rolled_back', 'cancelled']
    const stale = allTasks.filter((t) => !baselineIds.has(t.id) && !terminal.includes(t.status))
    for (const t of stale) {
      expect(['pending', 'awaiting_confirmation', 'confirmed', 'deploying'],
        `任务 ${t.id} 处于 ${t.status}，不能收尾在途执行或验证`).toContain(t.status)
      const action = t.status === 'deploying' ? 'verify' : 'cancel'
      const resp = await page.request.post(`/api/v1/deploy/tasks/${t.id}/${action}`, { headers: e2eAuth })
      expect(resp.ok(), `任务 ${t.id} (${t.status}) 收尾 ${action} 应成功；在途执行不得取消`).toBeTruthy()
    }
    guards.assertClean()
  })

  test('配置管理：选设备采集、查看、比对、变更日志', async ({ page }) => {
    const guards = attachGuards(page)
    await loginAsAdmin(page)
    await openMenu(page, '配置管理')
    await page.getByRole('button', { name: '返回下发' }).click()
    await expect(page).toHaveURL(/\/deploy/)
    await openMenu(page, '配置管理')

    await page.getByRole('button', { name: '全量设备' }).click()
    await page.getByRole('button', { name: '选择采集设备' }).first().click()
    await page.getByRole('button', { name: '全选', exact: true }).click()
    await page.getByRole('button', { name: '取消全选' }).click()
    await page.getByRole('button', { name: '全选', exact: true }).click()
    await page.getByRole('button', { name: /确定选择/ }).click()
    // 设备终端可能被"人"占着（例如验收时自己开着 R1 的 WebSSH）：后端现在回 409 + 明确原因，
    // 这种情况按环境依赖跳过，而不是判失败。
    const captureResp = page.waitForResponse(
      (r) => r.url().includes('/config-versions/capture'), { timeout: 120000 },
    ).catch(() => null)
    await page.getByRole('button', { name: '采集并保存配置' }).click()
    const capture = await captureResp
    if (capture && capture.status() === 409) {
      await expectToast(page, /设备终端被占用/, 15000)
      test.skip(true, '设备终端被占用（有人正开着该设备 WebSSH），跳过采集相关断言')
    }
    await expectToast(page, /已保存/, 120000)

    await page.getByRole('button', { name: '查看' }).first().click()
    await expect(page.getByRole('heading', { name: '配置快照' })).toBeVisible()
    await closeDialog(page, '配置快照')

    const exportOne = page.getByRole('button', { name: '导出', exact: true }).first()
    if (await exportOne.isEnabled().catch(() => false)) {
      await Promise.all([
        page.waitForEvent('download', { timeout: 15000 }).catch(() => null),
        exportOne.click(),
      ])
    }
    const rowCheck = page.locator('.el-table__body .el-table__row').first().locator('.el-checkbox')
    if (await rowCheck.isVisible().catch(() => false)) {
      await rowCheck.click()
      const exportSel = page.getByRole('button', { name: '导出已选快照' })
      if (await exportSel.isEnabled().catch(() => false)) {
        await Promise.all([
          page.waitForEvent('download', { timeout: 15000 }).catch(() => null),
          exportSel.click(),
        ])
      }
    }
    await page.getByRole('button', { name: /选择采集设备/ }).first().click()
    await clickDialogFooter(page, '选择需要保存配置的设备', '取消')

    await page.getByRole('button', { name: '比对' }).first().click()
    await page.getByRole('tab', { name: '配置差异比对' }).click()
    await page.getByRole('button', { name: '比对快照' }).click()
    const exportDiff = page.getByRole('button', { name: '导出差异' })
    if (await exportDiff.isEnabled().catch(() => false)) {
      await Promise.all([
        page.waitForEvent('download', { timeout: 10000 }).catch(() => null),
        exportDiff.click(),
      ])
    }
    const localFiles = page.locator('.local-compare input[type="file"]')
    if ((await localFiles.count()) >= 2) {
      await localFiles.nth(0).setInputFiles({ name: 'a.cfg', mimeType: 'text/plain', buffer: Buffer.from('sysname A\n') })
      await localFiles.nth(1).setInputFiles({ name: 'b.cfg', mimeType: 'text/plain', buffer: Buffer.from('sysname B\n') })
      await page.getByRole('button', { name: '比对本地文件' }).click()
    }

    await page.getByRole('tab', { name: '配置变更日志' }).click()
    await page.getByRole('button', { name: '查询' }).click()
    const changeBtn = page.getByRole('button', { name: '查看变更' }).first()
    if (await changeBtn.isVisible().catch(() => false)) {
      await changeBtn.click()
      await expect(page.getByText('配置变更详情')).toBeVisible()
      await closeDialog(page, '配置变更详情')
    }
    guards.assertClean()
  })

  test('监控大盘：刷新、采集、巡检、跳转告警', async ({ page }) => {
    const guards = attachGuards(page)
    await loginAsAdmin(page)
    const token = await page.evaluate(() => localStorage.getItem('token'))
    const auth = { Authorization: `Bearer ${token}` }
    const [topologyResp, devicesResp] = await Promise.all([
      page.request.get('/api/v1/topologies', { headers: auth }),
      page.request.get('/api/v1/devices', { headers: auth }),
    ])
    expect(topologyResp.ok()).toBeTruthy()
    expect(devicesResp.ok()).toBeTruthy()
    const topologies: Array<{ id: number; name: string }> = await topologyResp.json()
    const devices: Array<{ id: number; topology_id: number }> = await devicesResp.json()
    const topology = topologies.find(t => devices.some(d => d.topology_id === t.id))
    expect(topology, '监控验收需要一个实际包含设备的拓扑').toBeTruthy()
    const target = topology!
    const expectedIds = devices.filter(d => d.topology_id === target.id).map(d => d.id).sort((a, b) => a - b)
    await openMenu(page, '监控大盘')
    await expect(page.getByRole('button', { name: '触发采集' })).toBeVisible()
    const refresh = page.getByRole('button', { name: '刷新数据' })
    await expect(refresh).toBeEnabled()
    await refresh.click()
    const toTopo = page.getByRole('button', { name: '去拓扑可视化' })
    if (await toTopo.isVisible().catch(() => false)) {
      await toTopo.click()
      await expect(page).toHaveURL(/\/topology/)
      await openMenu(page, '监控大盘')
    }
    const topologySelect = page.locator('.monitor-dashboard .el-select').first()
    await topologySelect.click()
    const option = page.locator('.el-select-dropdown:visible').getByText(target.name, { exact: true })
    await expect(option, '等待 mounted 加载实际拓扑选项').toBeVisible({ timeout: 15000 })
    await option.click()
    await expect(topologySelect).toContainText(target.name)

    const assertCompleteCollection = (result: any, jobType: string) => {
      expect(result.task).toMatchObject({ status: 'success', job_type: jobType, topology_id: target.id })
      expect(result.summary).toMatchObject({ expected: expectedIds.length, success: expectedIds.length, failed: 0, skipped: 0 })
      expect(result.summary.devices.map((d: { device_id: number }) => d.device_id).sort((a: number, b: number) => a - b)).toEqual(expectedIds)
      expect(result.summary.devices.every((d: { status: string }) => d.status === 'success')).toBe(true)
    }
    const collect = page.getByRole('button', { name: '触发采集' })
    await expect(collect).toBeEnabled({ timeout: 15000 })
    const collectResp = page.waitForResponse((r) => new URL(r.url()).pathname === `/api/v1/monitor/collect/${target.id}` && r.request().method() === 'POST', { timeout: 150000 })
    await collect.click()
    const collected = await collectResp
    expect(collected.ok()).toBeTruthy()
    assertCompleteCollection(await collected.json(), 'collection')
    await expectToast(page, new RegExp(`采集结束：目标 ${expectedIds.length} 台，成功 ${expectedIds.length} 台，失败 0 台，跳过 0 台`), 30000)
    const inspect = page.getByRole('button', { name: '触发巡检' })
    await expect(inspect).toBeEnabled({ timeout: 15000 })
    const inspectResp = page.waitForResponse((r) => new URL(r.url()).pathname === `/api/v1/monitor/inspections/${target.id}` && r.request().method() === 'POST', { timeout: 60000 })
    await inspect.click()
    const inspected = await inspectResp
    expect(inspected.ok()).toBeTruthy()
    const inspection = await inspected.json()
    assertCompleteCollection(inspection, 'inspection')
    expect(inspection.report).toMatchObject({ job_id: inspection.task.id, topology_id: target.id, evidence_scope: 'current_job' })
    expect(inspection.report.summary.metric_points).toBeGreaterThan(0)
    await expectToast(page, new RegExp(`巡检结束：目标 ${expectedIds.length} 台，成功 ${expectedIds.length} 台，失败 0 台，跳过 0 台`), 30000)
    const monTerm = page.getByRole('button', { name: '终端' }).first()
    if (await monTerm.isVisible().catch(() => false)) {
      await expect(monTerm).toBeEnabled()
      await monTerm.click()
      await expect(page).toHaveURL(/\/webssh/)
      await openMenu(page, '监控大盘')
    }
    const allAlarms = page.getByRole('button', { name: '查看全部' })
    await expect(allAlarms).toBeEnabled()
    await allAlarms.click()
    await expect(page).toHaveURL(/\/alarms/)
    guards.assertClean()
  })

  test('告警：刷新、详情、确认取消、跳转', async ({ page }) => {
    const guards = attachGuards(page)
    await loginAsAdmin(page)
    await openMenu(page, '告警管理')
    await page.getByRole('button', { name: '刷新' }).click()
    await page.getByRole('button', { name: '返回设备' }).click()
    await expect(page).toHaveURL(/\/devices/)
    await openMenu(page, '告警管理')
    await page.getByRole('button', { name: '去监控大盘' }).first().click()
    await expect(page).toHaveURL(/\/monitor/)
    await openMenu(page, '告警管理')

    const detail = page.getByRole('button', { name: '详情' }).first()
    if (await detail.isVisible().catch(() => false)) {
      await detail.click()
      await expect(page.getByText('告警详情')).toBeVisible()
      const sshFromDetail = page.getByRole('button', { name: '打开 WebSSH' })
      if (await sshFromDetail.isVisible().catch(() => false)) {
        await sshFromDetail.click()
        await expect(page).toHaveURL(/\/webssh/)
        await openMenu(page, '告警管理')
      } else {
        await closeDialog(page, '告警详情')
      }
    }
    const ack = page.getByRole('button', { name: '确认' }).first()
    if (await ack.isVisible().catch(() => false)) {
      await ack.click()
      await cancelBox(page)
    }
    const closeAlarm = page.getByRole('button', { name: '关闭', exact: true }).first()
    if (await closeAlarm.isVisible().catch(() => false)) {
      await closeAlarm.click()
      await cancelBox(page)
    }
    const alarmTerm = page.getByRole('button', { name: '终端' }).first()
    if (await alarmTerm.isVisible().catch(() => false)) {
      await alarmTerm.click()
      await expect(page).toHaveURL(/\/webssh/)
      await openMenu(page, '告警管理')
    }
    guards.assertClean()
  })

  test('知识库：健康检查、检索、删除取消', async ({ page }) => {
    const guards = attachGuards(page)
    await loginAsAdmin(page)
    await openMenu(page, '知识库管理')
    await expect(page.getByText('知识库状态')).toBeVisible()
    await page.getByRole('button', { name: '刷新健康检查' }).click()
    await expect(page.getByText('可用', { exact: true })).toBeVisible({ timeout: 20000 })

    const del = page.getByRole('button', { name: '删除' }).first()
    if (await del.isVisible().catch(() => false)) {
      await del.click()
      await cancelBox(page)
    }

    await page.getByRole('tab', { name: '检索测试' }).click()
    await page.getByPlaceholder('输入检索关键词...').fill('OSPF Silent-Interface')
    await page.getByRole('button', { name: '检索' }).click()
    await expect(
      page.getByRole('heading', { name: '检索结果' }).or(page.getByText('未检索到相关内容')),
    ).toBeVisible({ timeout: 40000 })
    guards.assertClean()
  })

  test('实训：刷新、创建 Lab、开始、记录、注入、提示、复盘、参考汇总、结束', async ({ page }) => {
    test.setTimeout(360000)
    const guards = attachGuards(page)
    await loginAsAdmin(page)
    await openMenu(page, '实训中心')
    await page.getByRole('button', { name: '刷新' }).first().click()

    const stepsBtn = page.getByRole('button', { name: /步$/ }).first()
    if (await stepsBtn.isVisible()) {
      await stepsBtn.click()
      await expect(page.getByRole('heading', { name: '实验步骤' })).toBeVisible()
      await closeDialog(page, '实验步骤')
    }

    await page.getByRole('button', { name: '创建Lab' }).click()
    await page.getByRole('button', { name: '取消' }).click()

    const stamp = `e2e验收${Date.now()}`
    await page.getByRole('button', { name: '创建Lab' }).click()
    await page.getByPlaceholder('输入Lab名称').fill(stamp)
    await page.getByPlaceholder('Lab描述').fill('按钮验收用，可删')
    await page.getByRole('button', { name: '确定' }).click()
    await expectToast(page, /创建成功/)

    const sessionDlg = () => page.locator('[role="dialog"][aria-label*="实训会话"]:visible')
    const labRow = page
      .locator('.el-card')
      .filter({ has: page.getByRole('columnheader', { name: 'Lab名称' }) })
      .locator('.el-table__row')
      .filter({ hasText: stamp })
      .last()
    await expect(labRow).toBeVisible()
    const resumeLab = () => labRow.getByRole('button', { name: '继续实训' })
    const ensureSessionOpen = async () => {
      if (await sessionDlg().count()) return
      const bar = page.getByRole('button', { name: /正在实训/ })
      if (await bar.isVisible().catch(() => false)) {
        await bar.click({ force: true })
      } else {
        await resumeLab().evaluate((el) => (el as HTMLButtonElement).click())
      }
      await expect(sessionDlg()).toBeVisible({ timeout: 10000 })
    }

    await labRow.getByRole('button', { name: '开始实训' }).click()
    await confirmBox(page)
    await expectToast(page, /实训已开始/)

    await expect(sessionDlg().getByRole('button', { name: '记录操作' })).toBeVisible({ timeout: 10000 })
    await page.getByPlaceholder('输入执行的命令，如 display interface brief').fill('display version')
    await page.getByPlaceholder('目标设备(可选)').fill('R1')
    await sessionDlg().getByRole('button', { name: '记录操作' }).click()
    await expectToast(page, /操作已记录/)

    await sessionDlg().getByRole('button', { name: '注入故障' }).click()
    await expectToast(page, /已记录故障场景/)
    await sessionDlg().getByRole('button', { name: '标记已解决' }).first().click()
    await expectToast(page, /已标记为解决/)
    await sessionDlg().getByRole('button', { name: '注入故障' }).click()
    await expectToast(page, /已记录故障场景/)
    await sessionDlg().getByRole('button', { name: '标记未解决' }).first().click()
    await expectToast(page, /已标记为未解决/)

    await sessionDlg().getByRole('button', { name: '获取训练提示' }).click()
    await expectToast(page, /训练提示已生成/, 90000)

    await sessionDlg().getByRole('button', { name: '生成复盘报告' }).click()
    await expectToast(page, /复盘报告已生成/, 90000)

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      sessionDlg().getByRole('button', { name: '导出JSONL日志' }).click(),
    ])
    expect(download.suggestedFilename()).toMatch(/jsonl|log/i)

    await sessionDlg().getByRole('button', { name: '看拓扑' }).click()
    await expect(page).toHaveURL(/\/topology/)
    const backFromTopo = page.getByRole('button', { name: '返回实训' })
    if (await backFromTopo.isVisible().catch(() => false)) {
      await backFromTopo.click()
    } else {
      await openMenu(page, '实训中心')
    }
    await ensureSessionOpen()
    await expect(sessionDlg().getByRole('button', { name: '去设备' })).toBeVisible()
    await sessionDlg().getByRole('button', { name: '去设备' }).click()
    await expect(page).toHaveURL(/\/devices/)
    const backFromDev = page.getByRole('button', { name: '返回实训' })
    if (await backFromDev.isVisible().catch(() => false)) {
      await backFromDev.click()
    } else {
      await openMenu(page, '实训中心')
    }
    await ensureSessionOpen()
    await sessionDlg().getByRole('button', { name: '开终端' }).click()
    await expect(page).toHaveURL(/\/webssh/)
    const backFromSsh = page.getByRole('button', { name: '返回实训' })
    if (await backFromSsh.isVisible().catch(() => false)) {
      await backFromSsh.click()
    } else {
      await openMenu(page, '实训中心')
    }
    await ensureSessionOpen()

    const trainingBar = page.getByRole('button', { name: /正在实训/ })
    if (await trainingBar.isVisible().catch(() => false)) {
      await sessionDlg().locator('.el-dialog__headerbtn').click({ force: true })
      await expect(sessionDlg()).toBeHidden({ timeout: 10000 })
      await trainingBar.click({ force: true })
      await expect(sessionDlg()).toBeVisible({ timeout: 15000 })
    }

    // 整套运行时偶发"用顶部实训条重开后弹窗又被收起"，此处兜底：点不到页脚就先重开一次。
    // （弹窗本身稳定：单独诊断连续 25 秒保持可见、页脚始终有「关闭」。）
    try {
      await clickDialogFooter(page, '实训会话', '关闭')
    } catch {
      await labRow.getByRole('button', { name: '继续实训' }).click()
      await expect(sessionDlg()).toBeVisible({ timeout: 15000 })
      await clickDialogFooter(page, '实训会话', '关闭')
    }
    await expect(sessionDlg()).toBeHidden()
    await labRow.getByRole('button', { name: '新开会话' }).evaluate((el) => (el as HTMLButtonElement).click())
    await confirmBox(page)
    await expectToast(page, /实训已开始/)
    await expect(sessionDlg()).toBeVisible({ timeout: 10000 })
    await clickDialogFooter(page, /实训会话/, '结束实训')
    await confirmBox(page)
    await expectToast(page, /实训已结束/, 30000)
    await expect(sessionDlg()).toBeHidden({ timeout: 10000 })

    await resumeLab().evaluate((el) => (el as HTMLButtonElement).click())
    await expect(sessionDlg()).toBeVisible({ timeout: 10000 })
    const summaryResponse = page.waitForResponse(
      r => /\/api\/v1\/training\/sessions\/\d+\/score$/.test(new URL(r.url()).pathname) && r.request().method() === 'POST',
    )
    await clickDialogFooter(page, /实训会话/, '生成参考结果并结束')
    await expect(page.locator('.el-message-box').last()).toContainText('不会生成技能成绩或通过判定')
    await confirmBox(page, '生成并结束')
    const summary = await summaryResponse
    expect(summary.ok()).toBeTruthy()
    const result = await summary.json()
    expect(result.score).toBeNull()
    expect(result.passed).toBeNull()
    expect(result.detail.verification_status).toBe('unverified')
    await expectToast(page, /未验证/, 30000)
    await expect(sessionDlg().getByText('未验证', { exact: true })).toBeVisible()
    await expect(sessionDlg().getByText('已完成', { exact: true })).toBeVisible()
    await expect(sessionDlg().getByText(/^(合格|满分)$/)).toHaveCount(0)
    // 结束后保持只读，不能继续上报记录或注入故障，也不显示再次结束入口。
    for (const name of ['记录操作', '注入故障', '结束实训', '生成参考结果并结束']) {
      await expect(sessionDlg().getByRole('button', { name, exact: true })).toHaveCount(0)
    }
    const sessionToken = await page.evaluate(() => localStorage.getItem('token'))
    const persisted = await page.request.get(`/api/v1/training/sessions/${result.session_id}`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
    })
    expect(persisted.ok()).toBeTruthy()
    expect(await persisted.json()).toMatchObject({ status: 'completed', score: null, passed: null })
    await clickDialogFooter(page, '实训会话', '关闭')
    await expect(sessionDlg()).toBeHidden({ timeout: 10000 })

    await labRow.getByRole('button', { name: '沙箱模式' }).evaluate((el) => (el as HTMLButtonElement).click())
    await expectToast(page, /沙箱模式已启动/)
    await expect(sessionDlg()).toBeVisible({ timeout: 10000 })
    await clickDialogFooter(page, '实训会话', '关闭')
    await expect(sessionDlg()).toBeHidden({ timeout: 10000 })

    await page.locator('.el-card').filter({ hasText: '我的实训会话' }).getByRole('button', { name: '刷新' }).click({ force: true })
    const viewBtn = page.locator('.el-table__row').filter({ hasText: stamp }).filter({ hasText: '已完成' }).getByRole('button', { name: '查看' }).first()
    if (await viewBtn.isVisible().catch(() => false)) {
      await viewBtn.click({ force: true })
      await expect(sessionDlg()).toBeVisible({ timeout: 10000 })
      await clickDialogFooter(page, '实训会话', '关闭')
      await expect(sessionDlg()).toBeHidden({ timeout: 10000 })
    }
    const contBtn = page.locator('.el-card').filter({ hasText: '我的实训会话' }).getByRole('button', { name: '继续', exact: true }).first()
    if (await contBtn.isVisible().catch(() => false)) {
      await contBtn.click({ force: true })
      await expect(sessionDlg()).toBeVisible({ timeout: 10000 })
      await clickDialogFooter(page, '实训会话', '关闭')
      await expect(sessionDlg()).toBeHidden({ timeout: 10000 })
    }

    // 先验证"取消删除"路径，再真正删掉，避免每次 e2e 都在实训列表里留一条记录。
    // 会话是 NOT NULL 外键且无级联，必须先在「我的实训会话」里删会话，否则后端拒绝删实验。
    await labRow.getByRole('button', { name: '删除' }).click({ force: true })
    await cancelBox(page)

    const sessionCard = page.locator('.el-card').filter({ hasText: '我的实训会话' })
    const sessionRows = sessionCard.locator('.el-table__row').filter({ hasText: stamp })
    expect(await sessionRows.count(), '刚创建的实验应至少有一条会话').toBeGreaterThan(0)
    while ((await sessionRows.count()) > 0) {
      const before = await sessionRows.count()
      // 不加 force：让 Playwright 做 actionability 校验并在元素移动时重试，
      // 否则列表刷新期间的点击会落到别的行（曾误点到"删除实验"按钮）。
      await sessionRows.first().getByRole('button', { name: '删除' }).click()
      // 必须确认弹的是"删除会话"框，而不是实验行的删除框 —— 弹错框时给出明确失败信息
      await expect(
        page.locator('.el-message-box').last(),
        '点击会话行「删除」后应弹出「删除会话」确认框',
      ).toContainText('删除会话', { timeout: 10000 })
      await confirmBox(page)
      await expectToast(page, /会话已删除/)
      // 等列表真正刷新（行数下降）再进入下一轮，避免对已删除的行重复点击
      await expect.poll(async () => sessionRows.count(), { timeout: 15000 }).toBeLessThan(before)
    }

    await labRow.getByRole('button', { name: '删除' }).click()
    await expect(page.locator('.el-message-box').last()).toContainText('确认删除', { timeout: 10000 })
    await confirmBox(page)
    await expectToast(page, /已删除/)
    await expect(labRow).toHaveCount(0, { timeout: 15000 })
    guards.assertClean()
  })

  test('系统管理：信息、配置增删、审计、后台任务、日志查看', async ({ page }) => {
    const guards = attachGuards(page)
    await loginAsAdmin(page)
    await openSystemMenu(page, '系统信息')
    await expect(page.getByText('系统概览')).toBeVisible()
    await page.getByRole('button', { name: '系统配置' }).click()
    await expect(page).toHaveURL(/\/system\/config/)
    await openSystemMenu(page, '系统信息')
    await page.getByRole('button', { name: '审计日志' }).click()
    await expect(page).toHaveURL(/\/system\/audit/)
    await openSystemMenu(page, '系统信息')
    await page.getByRole('button', { name: '返回总览' }).click()
    await expect(page).toHaveURL(/\/dashboard/)

    await openSystemMenu(page, '系统配置')
    const key = `e2e.button_probe.${Date.now()}`
    await page.getByRole('button', { name: '新增配置' }).click()
    await page.getByPlaceholder('例如: app.maintenance_mode').fill(key)
    await page.getByPlaceholder('配置值').fill('1')
    await page.getByPlaceholder('配置说明').fill('playwright验收')
    await page.getByRole('button', { name: '保存' }).click()
    await expectToast(page, /保存成功/)
    const row = page.locator('.el-table__row').filter({ hasText: key }).first()
    await row.getByRole('button', { name: '编辑' }).click()
    await page.getByRole('button', { name: '取消' }).click()
    await row.getByRole('button', { name: '删除' }).click()
    await page.locator('.el-popconfirm').locator('button').filter({ hasText: /确定|Yes/ }).last().click({ force: true })
    await expectToast(page, /删除成功/)

    await openSystemMenu(page, '审计日志')
    await page.getByRole('button', { name: '刷新' }).click()

    await openSystemMenu(page, '后台任务')
    await page.getByRole('button', { name: '刷新' }).click()

    await openSystemMenu(page, '日志文件')
    await page.getByRole('button', { name: '刷新' }).click()
    const view = page.getByRole('button', { name: '查看' }).first()
    if (await view.isVisible().catch(() => false)) {
      await view.click()
      await expect(page.getByText(/日志:/)).toBeVisible()
      await page.keyboard.press('Escape')
    }
    guards.assertClean()
  })

  test('Copilot：打开、发送、新对话、历史、收起', async ({ page }) => {
    const guards = attachGuards(page)
    await loginAsAdmin(page)
    const toggle = page.locator('button.ai-toggle')
    await toggle.click()
    await expect(page.getByRole('button', { name: '发送' })).toBeVisible()
    const shotBtn = page.getByRole('button', { name: '发截图解读' })
    if (await shotBtn.isVisible().catch(() => false)) {
      const [chooser] = await Promise.all([
        page.waitForEvent('filechooser'),
        shotBtn.click(),
      ])
      expect(chooser).toBeTruthy()
    }
    const fileBtn = page.getByRole('button', { name: '文件' })
    if (await fileBtn.isVisible().catch(() => false)) {
      const [chooser] = await Promise.all([
        page.waitForEvent('filechooser'),
        fileBtn.click(),
      ])
      expect(chooser).toBeTruthy()
    }
    await page.locator('aside textarea').fill('只回复三个字：验收OK。不要调用工具。')
    const stream = page.waitForResponse((r) => r.url().includes('/ai/copilot/chat') && r.status() === 200, { timeout: 120000 })
    await page.getByRole('button', { name: '发送' }).click()
    const streamResponse = await stream
    const events = (await streamResponse.text()).split(/\r?\n/)
      .filter(line => line.startsWith('data:'))
      .map(line => JSON.parse(line.slice(5).trim()))
    // 只断言最后一条助手消息：首页右侧新增的"最近操作"面板同样含 OK 文本，
    // 直接 aside.getByText(/OK/) 会命中多元素（strict mode 报错）。
    if (process.env.E2E_PROFILE === 'minimal') {
      // 隔离最小栈没有模型服务：明确验证失败契约，不把降级文案视为成功。
      expect(events.some(event => event.type === 'error')).toBe(true)
      expect(events[events.length - 1]).toMatchObject({ type: 'done', status: 'failed' })
      await expect(page.locator('aside .msg.assistant').last()).toContainText(/生成失败|流式对话失败/, { timeout: 15000 })
    } else {
      expect(events.filter(event => event.type === 'error')).toHaveLength(0)
      expect(events[events.length - 1]).toMatchObject({ type: 'done', status: 'ok' })
      await expect(page.locator('aside .msg.assistant').last()).toContainText(/验收OK|OK|好的|收到/, { timeout: 120000 })
    }
    await page.getByRole('button', { name: '＋' }).click()
    await expect(page.locator('aside .msg.assistant')).toHaveCount(0)
    await expect(page.locator('aside textarea')).toBeEnabled()
    await page.getByRole('button', { name: '☰' }).click()
    await page.getByRole('button', { name: '关闭' }).click()
    // 精确指向 AI 面板的收起按钮：首页卡片里的装饰性箭头/同类按钮不应参与匹配
    await page.locator('button.icon-btn[title="收起"]').click()
    guards.assertClean()
  })

  test('退出登录回到登录页', async ({ page }) => {
    await loginAsAdmin(page)
    await page.locator('.user-trigger').click()
    await page.getByRole('menuitem', { name: '退出登录' }).click()
    await expect(page).toHaveURL(/\/login/)
    await expect(page.getByRole('button', { name: '登录' })).toBeVisible()
  })
})
