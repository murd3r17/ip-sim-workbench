import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

// Execute the actual <script setup> with mocked UI/network dependencies, on Node >= 20.
const vue = await readFile(new URL('../src/components/AiCopilotPanel.vue', import.meta.url), 'utf8')
const script = vue.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
const { outputText } = ts.transpileModule(script + '\nexport { send, applyDraft, stopGenerating, onNewChat, streamingStarted, progressStatus, toolStatus, recoverReply, recoveryNotice, openCitation, closeCitation, citation };', {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
})
const deferred = () => {
  let resolve, reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}
async function until(check) {
  for (let i = 0; i < 30 && !check(); i++) await Promise.resolve()
  assert.ok(check(), 'expected asynchronous step reached')
}

test('recovery permission denial is distinct from temporary network failure and does not retry', async () => {
  const h=harness();const message={id:'old',requestId:'r1',content:'saved',requestState:'failed'}
  h.store.messages.push(message)
  const pending=h.recoverReply(message);h.recoveries[0].reject({response:{status:403}});await pending
  assert.match(h.recoveryNotice.value.text,/权限/);assert.doesNotMatch(h.recoveryNotice.value.text,/稍后再查/)
  assert.equal(h.requests.length,0);assert.equal(message.content,'saved')
})
function harness(snapshot = async () => '', cancel = async () => ({ cancelled: true, upstream: 'abort_requested' })) {
  let sequence = 0
  const requests = []
  const recoveries = []
  const citations = []
  const navigations = []
  const drafts = []
  const labCtx = {}
  const store = {
    loading: false, messages: [], activeId: 'chat-1', routePath: '/devices', notes: '',
    pushMessage(message) { const id = String(++sequence); this.messages.push({ ...message, id }); return id },
    patchMessage(id, patch) { Object.assign(this.messages.find(m => m.id === id) || {}, patch) },
    appendContent(id, text) { const msg = this.messages.find(m => m.id === id); if (msg) msg.content += text },
    appendReasoning(id, text) { const msg = this.messages.find(m => m.id === id); if (msg) msg.reasoning = (msg.reasoning || '') + text },
    syncActiveToList() {},
    async flushConversation() { return true },
    saveDraftToDeploy(...args) { drafts.push(args) },
    newChat() { this.activeId = 'chat-' + (++sequence); this.messages = [] },
  }
  const stubs = {
    vue: { ref: value => ({ value }), computed: get => ({ get value() { return get() } }), nextTick: async () => {}, watch() {}, onMounted() {}, onUnmounted() {} },
    'vue-router': { useRoute: () => ({ path: '/devices' }), useRouter: () => ({ push: async value => navigations.push(value) }) },
    'element-plus/es/components/message/index': { ElMessage: { info() {}, warning() {}, success() {} } },
    '../api/ai': {
      copilotChatStream(data, onEvent, signal) { const d = deferred(); requests.push({ ...d, data, onEvent, signal }); return d.promise },
      cancelCopilotRequest: cancel,
      getAICapabilities: async () => ({ vision_enabled: false, image_mime_types: [] }),
      getCopilotRequest(requestId) { const d = deferred(); recoveries.push({ ...d, requestId }); return d.promise },
    },
    '../stores/aiCopilot': { useAiCopilotStore: () => store },
    '../stores/labContext': { useLabContextStore: () => labCtx },
    '../utils/markdownLite': { renderMarkdown: value => value },
    '../utils/copilotContext': { resolvePageMeta: () => ({ title: 'Devices' }) },
    '../utils/pageDataContext': { buildPageDataContext: snapshot },
    '../utils/deviceModel': { resolveWorkbenchDeviceModel: () => 'NE40E' },
  }
  const module = { exports: {} }
  new Function('require', 'module', 'exports', 'fetch', 'localStorage', outputText)(name => {
    assert.ok(stubs[name], `unexpected dependency ${name}`)
    return stubs[name]
  }, module, module.exports, url => { const d = deferred(); citations.push({ ...d, url }); return d.promise }, { getItem: () => 'offline-token' })
  return { ...module.exports, store, labCtx, requests, recoveries, citations, drafts, navigations }
}

test('a delayed page snapshot cannot combine the old evidence with a newly selected object', async () => {
  const snapshot = deferred()
  let started = false
  const h = harness(async () => { started = true; return snapshot.promise })
  Object.assign(h.store, { selection: { kind: 'device', id: 2, label: 'R2' }, selectionText: 'device | R2 | id=2', evidenceId: 102 })
  h.labCtx.device = { id: 2, hostname: 'R2' }
  const pending = h.send('核对刚采集的证据', true)
  await until(() => started)
  Object.assign(h.store, { selection: { kind: 'device', id: 3, label: 'R3' }, selectionText: 'device | R3 | id=3', evidenceId: 103, routePath: '/alarms' })
  h.labCtx.device = { id: 3, hostname: 'R3' }
  snapshot.resolve('R2 snapshot')
  await until(() => h.requests.length === 1)
  assert.equal(h.requests[0].data.context.selection, 'device | R2 | id=2')
  assert.equal(h.requests[0].data.context.route, '/devices')
  assert.equal(JSON.parse(h.requests[0].data.page_data).evidence_id, 102)
  assert.equal(h.store.messages.at(-1).draftTarget, null)
  h.requests[0].onEvent({ type: 'meta', draft_target: { device_id: 2, hostname: 'R2' } })
  assert.equal(h.store.messages.at(-1).draftTarget.deviceId, 2)
  h.requests[0].onEvent({ type: 'done', status: 'ok' }); h.requests[0].resolve(); await pending
})

test('applying an old draft keeps its original device and does not adopt the current selection', async () => {
  const h = harness()
  h.labCtx.device = { id: 3, hostname: 'R3' }
  h.store.selection = { kind: 'device', id: 3, label: 'R3' }
  await h.applyDraft({ draftCommands: ['display version'], draftTarget: { deviceId: 2, label: 'R2', verifiedByServer: true } })
  assert.deepEqual(h.drafts[0], [['display version'], { deviceId: 2, label: 'R2', verifiedByServer: true }])
  assert.equal(h.navigations[0].query.device_id, '2')
  await h.applyDraft({ draftCommands: ['display clock'] })
  assert.equal(h.navigations[1].query.device_id, undefined)
  assert.equal(h.drafts[1][1], null)
  await h.applyDraft({ draftCommands: ['display clock'], draftTarget: { deviceId: 2, label: 'legacy-unverified' } })
  assert.equal(h.drafts[2][1], null)
})

test('a question naming R3 cannot bind its draft to selected R2 before server resolution', async () => {
  const h = harness()
  Object.assign(h.store, { selection: { kind: 'device', id: 2, label: 'R2' }, selectionText: 'device | R2 | id=2' })
  h.labCtx.device = { id: 2, hostname: 'R2' }
  const pending = h.send('请给R3的LoopBack0添加描述，只生成草稿，不执行', true)
  await until(() => h.requests.length === 1)
  try {
    assert.equal(h.store.messages.at(-1).draftTarget, null)
    h.requests[0].onEvent({ type: 'meta', draft_target: { device_id: 3, hostname: 'R3' } })
    assert.deepEqual(h.store.messages.at(-1).draftTarget, { deviceId: 3, label: 'R3', verifiedByServer: true })
  } finally {
    h.requests[0].onEvent({ type: 'done', status: 'ok' }); h.requests[0].resolve(); await pending
  }
})

test('server progress is visible without saving deliberation as answer or history', async () => {
  const h = harness()
  const pending = h.send('这个页面怎么用？')
  await until(() => h.requests.length === 1)
  h.requests[0].onEvent({ type: 'progress', stage: 'generating', message: '正在生成回答' })
  assert.equal(h.streamingStarted.value, false)
  assert.equal(h.progressStatus.value, '正在生成回答…')
  assert.equal(h.store.messages.at(-1).content, '')
  assert.equal(h.store.messages.at(-1).reasoning || '', '')
  h.requests[0].onEvent({ type: 'token', text: '已生成正文' })
  h.requests[0].onEvent({ type: 'done', status: 'ok' })
  h.requests[0].resolve()
  await pending
  assert.equal(h.store.messages.at(-1).content, '已生成正文')
})

test('environment invalidation removes the verified draft target before completion', async () => {
  const h = harness()
  const pending = h.send('给R3生成草稿', true)
  await until(() => h.requests.length === 1)
  h.requests[0].onEvent({ type: 'meta', draft_target: { device_id: 3, hostname: 'R3' } })
  assert.equal(h.store.messages.at(-1).draftTarget.deviceId, 3)
  h.requests[0].onEvent({ type: 'token', text: '已按提问生成草稿' })
  h.requests[0].onEvent({ type: 'policy', draft_target: null, draft_refused_reason: '环境修订已变化', replace_answer: '环境修订已变化，未提供草稿。' })
  assert.equal(h.store.messages.at(-1).draftTarget, null)
  assert.equal(h.store.messages.at(-1).content, '环境修订已变化，未提供草稿。')
  assert.deepEqual(h.store.messages.at(-1).draftCommands, [])
  assert.equal(h.store.messages.at(-1).draftRefused, '环境修订已变化')
  h.requests[0].onEvent({ type: 'done', status: 'blocked_environment' })
  h.requests[0].resolve(); await pending
  assert.equal(h.store.messages.at(-1).draftTarget, null)
})

test('citation uses server request identity and ignores a late previous source', async () => {
  const h = harness()
  const message = { requestId: 'original', sources: [
    { source_id: 'a', filename: 'a.md', content: 'untrusted client copy' },
    { source_id: 'b', filename: 'b.md', content: 'untrusted client copy' },
  ] }
  const first = h.openCitation(message, 0)
  const second = h.openCitation(message, 1)
  assert.match(h.citations[1].url, /request_id=original&source_id=b/)
  h.citations[1].resolve({ ok: true, status: 200, json: async () => ({ content: 'server excerpt B', scope: 'answer_excerpt' }) })
  await second
  h.citations[0].resolve({ ok: true, status: 200, json: async () => ({ content: 'old A' }) })
  await first
  assert.equal(h.citation.value.content, 'server excerpt B')
  const revoked = h.openCitation(message, 0)
  h.citations[2].resolve({ ok: false, status: 410 })
  await revoked
  assert.equal(h.citation.value.content, '')
  assert.equal(h.citation.value.status, 'revoked')
})

test('old aborted request cannot clear new loading, consume tokens or lose the new controller', { timeout: 1000 }, async () => {
  const h = harness()
  const first = h.send('first')
  await until(() => h.requests.length === 1)
  h.stopGenerating()
  const second = h.send('second')
  await until(() => h.requests.length === 2)
  h.requests[1].onEvent({ type: 'tool', name: 'query_devices', status: 'running' })
  h.requests[0].onEvent({ type: 'token', text: 'late stale output' })
  h.requests[0].reject(Object.assign(new Error('aborted'), { name: 'AbortError' }))
  await first
  assert.equal(h.store.loading, true)
  assert.ok(h.toolStatus.value)
  assert.ok(h.store.messages.every(m => !m.content.includes('stale')))
  h.stopGenerating()
  await until(() => h.requests[1].signal.aborted)
  h.requests[1].resolve()
  await second
})

test('stop invalidates callbacks immediately but gives cancellation acknowledgement priority over disconnect', async () => {
  const acknowledgement = deferred()
  const h = harness(undefined, () => acknowledgement.promise)
  const first = h.send('first')
  await until(() => h.requests.length === 1)
  h.stopGenerating()
  assert.equal(h.store.loading, false)
  assert.equal(h.requests[0].signal.aborted, false)
  const second = h.send('second')
  await until(() => h.requests.length === 2)
  h.requests[0].onEvent({ type: 'token', text: 'late discarded token' })
  assert.ok(h.store.messages.every(m => !m.content.includes('late discarded')))
  acknowledgement.resolve({ cancelled: true })
  await until(() => h.requests[0].signal.aborted)
  assert.equal(h.requests[1].signal.aborted, false)
  h.requests[0].resolve()
  await first
  assert.equal(h.store.loading, true)
  h.requests[1].onEvent({ type: 'done', status: 'ok' })
  h.requests[1].resolve()
  await second
})

test('an unreachable cancellation endpoint cannot keep the old stream open', { timeout: 2500 }, async () => {
  const h = harness(undefined, () => new Promise(() => {}))
  const pending = h.send('first')
  await until(() => h.requests.length === 1)
  h.stopGenerating()
  assert.equal(h.store.loading, false)
  await new Promise(resolve => h.requests[0].signal.addEventListener('abort', resolve, { once: true }))
  assert.equal(h.requests[0].signal.aborted, true)
  h.requests[0].resolve()
  await pending
})

test('stopping while the recovery anchor is saving prevents model submission', async () => {
  const anchor = deferred()
  const h = harness()
  let saving = false
  h.store.flushConversation = async () => { saving = true; return anchor.promise }
  const pending = h.send('question before close')
  await until(() => saving)
  assert.equal(h.requests.length, 0)
  assert.ok(h.store.messages.find(m => m.role === 'assistant').requestId)
  h.stopGenerating()
  anchor.resolve(true)
  await pending
  assert.equal(h.requests.length, 0)
  assert.equal(h.store.loading, false)
})

test('stopping while page snapshot is pending prevents the old network request', { timeout: 1000 }, async () => {
  const snapshot = deferred()
  let snapshotStarted = false
  const h = harness(() => { snapshotStarted = true; return snapshot.promise })
  const pending = h.send('first')
  await until(() => snapshotStarted)
  h.stopGenerating()
  snapshot.resolve('old snapshot')
  await pending
  assert.equal(h.requests.length, 0)
  assert.equal(h.store.loading, false)
})

test('snapshot failure finalizes its own placeholder and loading', { timeout: 1000 }, async () => {
  const h = harness(async () => { throw new Error('snapshot failed') })
  await h.send('first')
  assert.equal(h.store.loading, false)
  assert.equal(h.store.messages[1].streaming, false)
  assert.match(h.store.messages[1].content, /失败/)
})

test('partial answer followed by server error is visibly marked incomplete', { timeout: 1000 }, async () => {
  const h = harness()
  const pending = h.send('first')
  await until(() => h.requests.length === 1)
  h.requests[0].onEvent({ type: 'token', text: 'partial answer' })
  h.requests[0].onEvent({ type: 'error', message: '流式生成失败，请稍后重试' })
  h.requests[0].onEvent({ type: 'done', status: 'failed' })
  h.requests[0].resolve()
  await pending
  assert.match(h.store.messages[1].content, /^partial answer[\s\S]*失败/)
})

test('EOF without done does not present a partial answer as a completed reply', { timeout: 1000 }, async () => {
  const h = harness()
  const pending = h.send('first')
  await until(() => h.requests.length === 1)
  h.requests[0].onEvent({ type: 'token', text: 'partial answer' })
  h.requests[0].resolve()
  await pending
  assert.match(h.store.messages[1].content, /^partial answer[\s\S]*(中断|失败)/)
})

test('new conversation ignores old tokens and finally while its own reply completes', { timeout: 1000 }, async () => {
  const h = harness()
  const first = h.send('first')
  await until(() => h.requests.length === 1)
  h.onNewChat()
  const second = h.send('second')
  await until(() => h.requests.length === 2)
  h.requests[0].onEvent({ type: 'token', text: 'old answer' })
  h.requests[0].resolve()
  await first
  assert.equal(h.store.loading, true)
  h.requests[1].onEvent({ type: 'token', text: 'new answer' })
  h.requests[1].onEvent({ type: 'done', status: 'ok' })
  h.requests[1].resolve()
  await second
  assert.equal(h.store.messages[1].content, 'new answer')
  assert.equal(h.store.messages[1].streaming, false)
  assert.equal(h.store.loading, false)
})

test('recovering replaces partial text without a second generation request', async () => {
  const h = harness()
  const pending = h.send('first')
  await until(() => h.requests.length === 1)
  h.requests[0].onEvent({ type: 'token', text: 'partial' })
  h.requests[0].resolve()
  await pending
  const message = h.store.messages[1]
  assert.ok(message.requestId)
  const recovery = h.recoverReply(message)
  h.recoveries[0].resolve({ state: 'completed', response: { answer: 'complete original answer', knowledge_status: 'ok', sources: [{ version: 'hash', content: 'source' }] } })
  await recovery
  assert.equal(message.content, 'complete original answer')
  assert.equal(message.requestState, 'completed')
  assert.equal(message.sources[0].version, 'hash')
  assert.equal(message.knowledgeStatus, 'ok')
  assert.equal(h.requests.length, 1)
})

test('retrieval state follows its own field instead of overall request status', async () => {
  const h = harness()
  const pending = h.send('explain this page')
  await until(() => h.requests.length === 1)
  h.requests[0].onEvent({ type: 'meta', status: 'ok', knowledge_status: 'not_requested', sources: [] })
  h.requests[0].onEvent({ type: 'token', text: 'page explanation' })
  h.requests[0].onEvent({ type: 'done', status: 'ok' })
  h.requests[0].resolve()
  await pending
  assert.equal(h.store.messages[1].knowledgeStatus, 'not_requested')
})

test('a recovery response after switching conversations never changes the new chat', async () => {
  const h = harness()
  h.store.messages.push({ id: 'old', role: 'assistant', content: 'partial', requestId: 'req-old', requestState: 'interrupted' })
  const pending = h.recoverReply(h.store.messages[0])
  h.onNewChat()
  h.recoveries[0].resolve({ state: 'completed', response: { answer: 'late original answer' } })
  await pending
  assert.equal(h.store.messages.length, 0)
  assert.equal(h.requests.length, 0)
})

test('unknown running recovery remains uncertain and never retries generation', async () => {
  const h = harness()
  h.store.messages.push({ id: 'old', role: 'assistant', content: 'partial', requestId: 'req-old', requestState: 'interrupted' })
  const pending = h.recoverReply(h.store.messages[0])
  h.recoveries[0].resolve({ state: 'running', response: null })
  await pending
  assert.equal(h.store.messages[0].content, 'partial')
  assert.equal(h.store.messages[0].requestState, 'unconfirmed')
  assert.match(h.recoveryNotice.value.text, /没有重跑/)
  assert.equal(h.requests.length, 0)
})
