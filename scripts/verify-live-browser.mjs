// Live browser acceptance. Credentials and response bodies never enter reports.
import { createRequire } from 'node:module'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'
import fs from 'node:fs/promises'
import crypto from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { digest, goodAnswer, parseSse, streamEvidence, sameRuntime, sameBinding, aiLogEvidence } from './live-browser-contract.mjs'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(path.join(root, 'sim-frontend', 'package.json'))
const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds))
async function withDeadline(promise, milliseconds) {
  let timer
  try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(Object.assign(new Error('stream_timeout'), { failureCode: 'stream_timeout' })), milliseconds) })]) }
  finally { clearTimeout(timer) }
}
function ensure(value, code) {
  if (!value) { const error = new Error(code); error.failureCode = code; throw error }
}
async function poll(read, condition, milliseconds = 15000, code = 'condition_timeout') {
  const deadline = Date.now() + milliseconds
  do { const result = await read(); if (condition(result)) return result; await sleep(350) } while (Date.now() < deadline)
  ensure(false, code)
}

function captureBinding() {
  const python = process.env.LIVE_PYTHON || path.join(root, 'backend/.venv/Scripts/python.exe')
  const result = spawnSync(python, [path.join(root, 'backend/scripts/capture_live_browser.py')], {
    cwd: path.join(root, 'backend'), env: process.env, encoding: 'utf8', windowsHide: true, timeout: 30000,
  })
  ensure(result.status === 0, 'binding_capture_failed')
  const captured = JSON.parse(result.stdout)
  ensure(captured.ok === true, 'binding_capture_failed')
  return captured
}

async function authJson(page, route) {
  return page.evaluate(async route => {
    const response = await fetch('/api/v1' + route, { headers: { Authorization: 'Bearer ' + localStorage.getItem('token') } })
    return { status: response.status, data: await response.json() }
  }, route)
}
async function login(page, base, username, password) {
  await page.goto(base + '/login')
  await page.getByPlaceholder('用户名', { exact: true }).fill(username)
  await page.getByPlaceholder('密码', { exact: true }).fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL('**/dashboard', { timeout: 20000 })
}
async function newChat(page) {
  const open = page.locator('.copilot-fab')
  if (await open.isVisible()) await open.click()
  await page.locator('.copilot button[title="新对话"]').click()
  await page.locator('.copilot .composer textarea').waitFor({ state: 'visible' })
}
async function submit(page, prompt) {
  await page.locator('.copilot .composer textarea').fill(prompt)
  await page.locator('.copilot .send-btn').click()
}
async function waitIdle(page) {
  await page.waitForFunction(() => {
    const input = document.querySelector('.copilot .composer textarea')
    return input && !input.disabled && !document.querySelector('.copilot .bubble.streaming')
  }, undefined, { timeout: 180000 })
}
async function retainedConversation(page, marker) {
  const id = await page.evaluate(() => localStorage.getItem('ai_copilot_active_id'))
  ensure(id, 'conversation_identity_missing')
  const result = await poll(() => authJson(page, '/ai/copilot/sessions/' + encodeURIComponent(id)), result =>
    result.status === 200 && result.data.exists !== false && result.data.messages?.some(m => m.role === 'assistant' && String(m.content).includes(marker)), 20000, 'conversation_save_timeout')
  return { id, revision: result.data.revision }
}

async function liveChat(page, captured, runId, label) {
  await newChat(page)
  const marker = runId + '-' + label
  const prompt = `不要调用任何工具，不要连接、检查或操作设备。只根据本消息回答：37+58等于多少？请用一句中文回答，并原样包含校验标记 ${marker}。本题无需工作台数据或知识库检索。`
  const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/v1/ai/copilot/chat/stream') && response.request().method() === 'POST', { timeout: 180000 })
  await submit(page, prompt)
  const response = await responsePromise
  ensure(response.status() === 200, 'copilot_http_failed')
  const events = parseSse((await withDeadline(response.body(), 180000)).toString('utf8'))
  await waitIdle(page)
  const stream = streamEvidence(events, marker)
  ensure(stream.ok, 'copilot_stream_not_real_success')
  const visible = await page.locator('.copilot .msg.assistant .md-body').last().innerText()
  ensure(goodAnswer(visible) && visible.includes(marker) && visible.includes('95'), 'copilot_rendered_answer_mismatch')
  const logged = await poll(() => authJson(page, '/ai/logs?page_size=100'), result =>
    result.status === 200 && aiLogEvidence(result.data.items || [], { cursor: captured.max_ai_log_id, marker, model: captured.llm.model }), 15000, 'text_ai_log_binding_timeout')
  const log = aiLogEvidence(logged.data.items, { cursor: captured.max_ai_log_id, marker, model: captured.llm.model })
  const saved = await retainedConversation(page, marker)
  return { ...stream, ...log, conversation_id: saved.id, conversation_revision: saved.revision }
}

async function liveVision(page, captured, runId, out) {
  ensure(captured.vision.model, 'vision_model_not_configured')
  await newChat(page)
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
  const challenge = 'V6-' + [...crypto.randomBytes(6)].map(byte => alphabet[byte % alphabet.length]).join('')
  const image = path.join(out, 'vision-challenge.png')
  const canvas = await page.context().newPage()
  try {
    await canvas.setViewportSize({ width: 680, height: 240 })
    await canvas.setContent('<html><body style="margin:0;background:white;display:flex;align-items:center;justify-content:center;height:240px;font:bold 68px monospace;color:black">' + challenge + '</body></html>')
    await canvas.screenshot({ path: image })
  } finally { await canvas.close() }
  await page.locator('.copilot input[type="file"]').setInputFiles(image)
  await page.locator('.copilot .attach-preview img').waitFor({ state: 'visible' })
  const requestMarker = runId + '-vision-request'
  const prompt = '不要调用任何工具，不要查看或操作设备。只读取附件图片中唯一一行字符，并逐字原样输出。不要根据本消息或历史猜测。请求编号 ' + requestMarker
  ensure(!prompt.includes(challenge), 'vision_challenge_leaked_into_prompt')
  const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/v1/ai/copilot/chat/stream') && response.request().method() === 'POST', { timeout: 180000 })
  await submit(page, prompt)
  const response = await responsePromise
  ensure(response.status() === 200, 'vision_http_failed')
  const events = parseSse((await withDeadline(response.body(), 180000)).toString('utf8'))
  await waitIdle(page)
  const stream = streamEvidence(events, challenge, challenge)
  ensure(stream.ok, 'vision_challenge_or_stream_failed')
  const visible = await page.locator('.copilot .msg.assistant .md-body').last().innerText()
  ensure(goodAnswer(visible) && visible.includes(challenge), 'vision_rendered_challenge_mismatch')
  const options = { cursor: captured.max_ai_log_id, marker: requestMarker, responseMarker: challenge, model: captured.vision.model }
  const logged = await poll(() => authJson(page, '/ai/logs?page_size=100'), result => result.status === 200 && aiLogEvidence(result.data.items || [], options), 15000, 'vision_ai_log_binding_timeout')
  const evidence = aiLogEvidence(logged.data.items, options)
  const saved = await retainedConversation(page, challenge)
  return { ...stream, ...evidence, conversation_id: saved.id, challenge_not_in_prompt: true,
    source_image_sha256: crypto.createHash('sha256').update(await fs.readFile(image)).digest('hex'),
    challenge_sha256: digest(challenge), image_uploaded: true }
}

async function injectedFailure(page, runId) {
  await newChat(page)
  const marker = runId + '-injected-failure'
  const route = '**/api/v1/ai/copilot/chat/stream'
  const events = [{ type: 'token', text: '验收注入：部分回答 ' + marker }, { type: 'error', message: '验收注入：流式生成失败' }, { type: 'done', status: 'failed' }]
  await page.route(route, handler => handler.fulfill({ status: 200, contentType: 'text/event-stream', body: events.map(e => 'data: ' + JSON.stringify(e) + '\n\n').join('') }))
  try {
    await submit(page, '验收注入 SSE 失败，仅验证浏览器错误状态，不调用模型或设备。' + marker)
    await waitIdle(page)
    const visible = await page.locator('.copilot .msg.assistant .md-body').last().innerText()
    ensure(visible.includes('流式生成失败') && visible.includes('回答未完成'), 'injected_failure_not_visible')
    const saved = await retainedConversation(page, marker)
    return { error_visible: true, composer_reenabled: true, conversation_id: saved.id, real_service_outage: false }
  } finally { await page.unroute(route) }
}

async function injectedCancellation(page, runId) {
  await newChat(page)
  const marker = runId + '-injected-cancel'
  // Only this page's fetch transport is replaced. Backend and system networking
  // are untouched; this proves UI abort handling, not cancellation at the model.
  await page.evaluate(marker => {
    const original = window.fetch.bind(window)
    window.__liveBrowserCancel = { original, aborted: false }
    window.fetch = async (input, init = {}) => {
      const url = typeof input === 'string' ? input : input.url
      if (!url.endsWith('/api/v1/ai/copilot/chat/stream')) return original(input, init)
      const body = new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode('data: ' + JSON.stringify({ type: 'token', text: '验收注入：尚未完成的回答 ' + marker }) + '\n\n'))
          init.signal.addEventListener('abort', () => {
            window.__liveBrowserCancel.aborted = true
            controller.error(new DOMException('Aborted', 'AbortError'))
          }, { once: true })
        },
      })
      return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
    }
  }, marker)
  try {
    await submit(page, '验收注入取消，仅验证浏览器停止按钮，不调用模型或设备。' + marker)
    await page.locator('.copilot .stop-btn').waitFor({ state: 'visible', timeout: 15000 })
    await page.locator('.copilot .stop-btn').click()
    await waitIdle(page)
    const visible = await page.locator('.copilot .msg.assistant .md-body').last().innerText()
    const aborted = await page.evaluate(() => window.__liveBrowserCancel.aborted)
    ensure(aborted && visible.includes('已停止生成') && visible.includes('内容未完成'), 'cancellation_not_honest')
    const saved = await retainedConversation(page, marker)
    return { abort_observed: true, incomplete_visible: true, composer_reenabled: true, conversation_id: saved.id, backend_cancellation_verified: false }
  } finally {
    await page.evaluate(() => { window.fetch = window.__liveBrowserCancel.original; delete window.__liveBrowserCancel })
  }
}

async function deviceActionVisibility(page) {
  const row = page.locator('.device-table .el-table__body-wrapper .el-table__row').first()
  await row.waitFor({ state: 'visible' })
  const scroll = page.locator('.device-table .el-scrollbar__wrap').first()
  const metrics = await scroll.evaluate(element => {
    const before = element.scrollLeft
    element.scrollLeft = element.scrollWidth
    return { scrollable: element.scrollWidth > element.clientWidth, before, after: element.scrollLeft }
  })
  // Opening and cancelling edit exercises the far-right action without writing.
  await row.getByRole('button', { name: '编辑', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '编辑设备' })
  await dialog.waitFor({ state: 'visible' })
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await dialog.waitFor({ state: 'hidden' })
  return { ...metrics, edit_opened: true, cancelled_without_save: true }
}

export async function run() {
  const base = (process.env.LIVE_BASE_URL || 'http://127.0.0.1:18080').replace(/\/$/, '')
  const parsed = new URL(base)
  ensure(['http:', 'https:'].includes(parsed.protocol) && !parsed.username && !parsed.password && !parsed.search && !parsed.hash && parsed.pathname === '/', 'invalid_base_url')
  const runId = crypto.randomUUID().replaceAll('-', '')
  const out = path.resolve(process.env.LIVE_BROWSER_OUTPUT || path.join(root, '.runtime', 'live-browser-' + runId))
  await fs.mkdir(out, { recursive: true })
  const report = { schema: 2, producer: 'verify_live_browser', scope: 'live_browser_interaction', run_id: runId,
    checks: [], errors: [], ok: false, full_delivery: false,
    limitations: ['浏览器内 SSE 故障与取消注入不代表真实断网、模型取消或设备锁验证。'] }
  let browser, context, page, captured
  const add = (name, ok, evidence = {}, mode = 'live', required = true) => report.checks.push({ name, ok: Boolean(ok), evidence, mode, required })
  try {
    ensure(process.env.LIVE_ADMIN_PASSWORD && process.env.LIVE_EXPECTED_DATABASE_FINGERPRINT, 'explicit_credentials_and_database_required')
    captured = captureBinding()
    report.binding = { start: captured.binding }
    report.started_at = captured.binding.captured_at
    report.source_fingerprint = captured.binding.source_fingerprint
    report.llm = captured.llm
    report.vision = captured.vision
    report.targets = captured.targets
    ensure(captured.binding.device_mode === 'ssh' && captured.binding.knowledge_provider === 'anythingllm' && captured.binding.database_fingerprint === process.env.LIVE_EXPECTED_DATABASE_FINGERPRINT, 'clone_configuration_mismatch')
    const { chromium } = require('playwright')
    browser = await chromium.launch({ headless: true })
    context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    page = await context.newPage()
    page.on('pageerror', error => report.errors.push({ type: 'pageerror', digest: digest(error) }))
    page.on('console', message => { if (message.type() === 'error') report.errors.push({ type: 'console', digest: digest(message.text()) }) })
    page.on('response', response => {
      if (response.url().startsWith(base + '/api/') && response.status() >= 400) report.errors.push({ type: 'api', path: new URL(response.url()).pathname, status: response.status() })
    })
    await login(page, base, process.env.LIVE_ADMIN_USER || 'admin', process.env.LIVE_ADMIN_PASSWORD)
    const identity = await authJson(page, '/system/runtime-identity')
    ensure(identity.status === 200 && sameRuntime(captured.binding, identity.data), 'runtime_identity_mismatch')
    report.runtime_identity = identity.data
    const profile = await authJson(page, '/auth/me')
    ensure(profile.status === 200 && profile.data.role === 'admin', 'admin_role_required')
    const inventory = await authJson(page, '/devices')
    ensure(inventory.status === 200 && captured.targets.every(target => inventory.data.some(row => row.id === target.id && row.mgmt_ip === target.mgmt_ip && row.ssh_port === target.ssh_port)), 'api_targets_mismatch')
    add('login', true, { authenticated_role: 'admin', runtime_bound: true })
    const routes = [
      ['dashboard', '/dashboard', true], ['devices', '/devices', true], ['topology', '/topology', true],
      ['deployment', '/deploy', true], ['config_versions', '/config-versions', false], ['monitor', '/monitor', true],
      ['alarms', '/alarms', false], ['knowledge', '/knowledge', true], ['training', '/training', true],
      ['system', '/system/info', true], ['system_config', '/system/config', false],
      ['system_audit', '/system/audit', false], ['system_tasks', '/system/tasks', false],
    ]
    for (const [name, route, screenshot] of routes) {
      const before = report.errors.length
      await page.goto(base + route)
      await page.waitForSelector('.el-main, main', { timeout: 15000 })
      await page.waitForTimeout(1200)
      const content = await page.locator('.el-main, main').first().innerText()
      const ok = new URL(page.url()).pathname === route && content.trim().length > 20 && !content.includes('应用发生错误') && report.errors.length === before
      add(name, ok, { content_characters: content.length, api_errors: report.errors.length - before })
      if (name === 'devices') add('device_actions_visible', true, await deviceActionVisibility(page))
      if (screenshot) await page.screenshot({ path: path.join(out, name + '.png'), fullPage: true })
    }
    await page.goto(base + '/dashboard')
    await page.waitForTimeout(1000)
    const first = await liveChat(page, captured, runId, 'live')
    add('copilot', true, first)
    await page.screenshot({ path: path.join(out, 'copilot.png'), fullPage: true })
    add('copilot_sse_failure_visible', true, await injectedFailure(page, runId), 'injected')
    add('copilot_cancel_visible', true, await injectedCancellation(page, runId), 'injected')
    const recovered = await liveChat(page, captured, runId, 'recovery')
    add('copilot_real_recovery', true, recovered)
    // Verify the real saved answer survives reload; no conversation is deleted.
    await page.reload()
    await poll(() => page.locator('.copilot .msg.assistant .md-body').last().innerText().catch(() => ''), value => value.includes(runId + '-recovery'), 15000)
    add('copilot_reload_persistence', true, { conversation_id: recovered.conversation_id })
    add('copilot_vision', true, await liveVision(page, captured, runId, out))
    await page.screenshot({ path: path.join(out, 'copilot-vision.png'), fullPage: true })
    const anonymous = await browser.newContext()
    try {
      const visitor = await anonymous.newPage()
      await visitor.goto(base + '/system/config')
      await visitor.waitForURL('**/login', { timeout: 15000 })
      const response = await anonymous.request.get(base + '/api/v1/system/runtime-identity')
      const stream = await anonymous.request.post(base + '/api/v1/ai/copilot/chat/stream', { data: { message: '匿名访问验收，应在模型调用前拒绝。' } })
      ensure(response.status() === 401 && stream.status() === 401, 'anonymous_backend_access_not_rejected')
      add('permissions_anonymous', true, { protected_route_redirected: true, backend_status: response.status(), copilot_sse_status: stream.status() })
    } finally { await anonymous.close() }
    if (process.env.LIVE_READONLY_USER && process.env.LIVE_READONLY_PASSWORD) {
      const limited = await browser.newContext()
      try {
        const visitor = await limited.newPage()
        await login(visitor, base, process.env.LIVE_READONLY_USER, process.env.LIVE_READONLY_PASSWORD)
        const me = await authJson(visitor, '/auth/me')
        ensure(me.status === 200 && me.data.role !== 'admin', 'readonly_account_is_admin')
        await visitor.goto(base + '/system/config')
        await visitor.waitForURL('**/dashboard', { timeout: 15000 })
        const response = await authJson(visitor, '/system/runtime-identity')
        const conversation = await authJson(visitor, '/ai/copilot/sessions/' + encodeURIComponent(first.conversation_id))
        // Cross-owner reads deliberately use the same empty response as an
        // unknown conversation, so neither its existence nor contents leak.
        ensure(response.status === 403 && conversation.status === 200 && conversation.data.exists === false && conversation.data.messages?.length === 0, 'readonly_admin_api_not_forbidden')
        add('permissions_readonly', true, { frontend_redirected: true, backend_status: response.status, other_owner_conversation_status: conversation.status, other_owner_conversation_hidden: true })
      } finally { await limited.close() }
    } else {
      add('permissions_readonly', false, { state: 'SKIP', reason: 'explicit_readonly_credentials_not_provided' }, 'not_run', false)
    }
    const finalIdentity = await authJson(page, '/system/runtime-identity')
    ensure(finalIdentity.status === 200 && sameRuntime(report.runtime_identity, finalIdentity.data) && finalIdentity.data.pid === report.runtime_identity.pid && finalIdentity.data.launch_id === report.runtime_identity.launch_id, 'runtime_changed_during_browser_run')
    add('runtime_unchanged', true)
    add('no_console_errors', report.errors.length === 0)
  } catch (error) {
    report.errors.push({ type: 'runner', name: error.name, code: error.failureCode || 'browser_action_failed', digest: digest(error) })
  } finally {
    if (context) await context.close()
    if (browser) await browser.close()
    try {
      if (captured) {
        const finish = captureBinding()
        report.binding.finish = finish.binding
        report.finished_at = finish.binding.captured_at
        add('build_runtime_unchanged', sameBinding(captured.binding, finish.binding)
          && JSON.stringify(captured.llm) === JSON.stringify(finish.llm) && JSON.stringify(captured.vision) === JSON.stringify(finish.vision) && JSON.stringify(captured.targets) === JSON.stringify(finish.targets))
      }
    } catch (error) { report.errors.push({ type: 'binding_finish', name: error.name, digest: digest(error) }) }
    report.ok = report.checks.some(c => c.name === 'copilot' && c.ok) && report.checks.filter(c => c.required).every(c => c.ok) && report.errors.length === 0
    await fs.writeFile(path.join(out, 'report.json'), JSON.stringify(report, null, 2))
    console.log(JSON.stringify({ ok: report.ok, checks: report.checks, errors: report.errors, output: out }))
  }
  return report.ok ? 0 : 1
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) process.exitCode = await run()
