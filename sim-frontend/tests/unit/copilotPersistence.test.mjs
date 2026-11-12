import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'
import { setImmediate as yieldLoop } from 'node:timers/promises'
import ts from 'typescript'

const datetimeExports = {}
vm.runInNewContext(ts.transpileModule(
  fs.readFileSync(new URL('../../src/utils/datetime.ts', import.meta.url), 'utf8'),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } },
).outputText, { exports: datetimeExports })

function harness(overrides = {}) {
  const data = new Map(), timers = new Map(), images = [], saves = [], notices = []
  let timerId = 0
  const api = {
    getCopilotSessions: async () => [],
    getCopilotSession: async (id) => ({ id, exists: false, revision: 0, messages: [] }),
    saveCopilotSession: async (id, payload) => {
      saves.push({ id, payload: structuredClone(payload) })
      return { success: true, revision: (payload.revision || 0) + 1 }
    },
    deleteCopilotSession: async () => ({ success: true }),
    ...overrides,
  }
  class ImageStub {
    constructor() { this.complete = false; this.naturalWidth = 600; this.naturalHeight = 600; images.push(this) }
  }
  const context = {
    exports: {},
    localStorage: { getItem: (key) => data.get(key) || null, setItem: (key, value) => data.set(key, String(value)), removeItem: (key) => data.delete(key) },
    window: { setTimeout: (fn) => { timers.set(++timerId, fn); return timerId }, clearTimeout: (id) => timers.delete(id) },
    Image: ImageStub,
    document: { createElement: () => ({ getContext: () => ({ drawImage() {} }), toDataURL: () => 'data:image/jpeg,small' }) },
    require: (name) => {
      if (name === '../utils/datetime') return datetimeExports
      if (name === 'pinia') return { defineStore: (_id, setup) => setup }
      if (name === 'vue') return { ref: (value) => ({ value }), computed: (fn) => ({ get value() { return fn() } }), watch() {} }
      if (name.startsWith('element-plus/')) return { ElMessage: { warning: (message) => notices.push(message) } }
      if (name === '../api/ai') return api
      throw new Error(`Unexpected dependency ${name}`)
    },
  }
  const source = fs.readFileSync(new URL('../../src/stores/aiCopilot.ts', import.meta.url), 'utf8')
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  vm.runInNewContext(compiled, context)
  return {
    store: context.exports.useAiCopilotStore(), data, images, saves, notices,
    async runTimers() {
      const ready = [...timers.values()]; timers.clear()
      for (const fn of ready) fn()
      await yieldLoop()
    },
  }
}

test('draft origin survives message creation, history persistence and transfer', async () => {
  const h = harness()
  const target = { deviceId: 2, label: 'R2', alarmId: 17 }
  h.store.pushMessage({ role: 'assistant', content: '未执行', draftCommands: ['display version'], draftTarget: target })
  await h.runTimers()
  const saved = JSON.parse(h.data.get('ai_copilot_sessions_v1'))
  assert.deepEqual(saved[0].messages[0].draftTarget, target)
  h.store.saveDraftToDeploy(['display version'], target)
  assert.deepEqual(JSON.parse(h.data.get('deploy_ai_draft_context')), { text: 'display version', target })
})

test('late attachment compression cannot replace a newer reply', async () => {
  const h = harness()
  h.store.pushMessage({ role: 'user', content: 'first', attachments: [{ contentString: `data:image/png,${'x'.repeat(5000)}` }] })
  const old = h.images.filter((image) => image.onload).at(-1)
  h.store.pushMessage({ role: 'assistant', content: 'latest reply' })
  const current = h.images.filter((image) => image.onload).at(-1)
  current.onload()
  await yieldLoop()
  old.onload()
  await yieldLoop()
  const saved = JSON.parse(h.data.get('ai_copilot_sessions_v1'))
  assert.equal(saved[0].messages.length, 2)
  assert.equal(saved[0].messages[1].content, 'latest reply')
})

test('switching chats before debounce saves both conversation IDs', async () => {
  const h = harness()
  h.store.pushMessage({ role: 'user', content: 'conversation A' })
  const first = h.store.activeId.value
  h.store.newChat()
  h.store.pushMessage({ role: 'user', content: 'conversation B' })
  const second = h.store.activeId.value
  await h.runTimers()
  assert.deepEqual(new Set(h.saves.map((item) => item.id)), new Set([first, second]))
})

test('conflicted saves keep local content and expose a sync error', async () => {
  const h = harness({ saveCopilotSession: async () => { throw { response: { status: 409 } } } })
  h.store.pushMessage({ role: 'user', content: 'keep local text' })
  await h.runTimers()
  assert.equal(h.store.conversations.value[0].messages[0].content, 'keep local text')
  assert.match(h.store.conversations.value[0].syncError || '', /冲突/)
})

function deferred() {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

test('pending request identity is in the first recoverable conversation snapshot', async () => {
  const h = harness()
  h.store.pushMessage({ role:'user', content:'question' })
  h.store.pushMessage({ role:'assistant', content:'', streaming:true,
    requestId:'original-request', requestState:'pending' })
  await h.runTimers()
  const assistant=h.saves.at(-1).payload.messages[1]
  assert.equal(assistant.requestId,'original-request')
  assert.equal(assistant.requestState,'pending')
})

test('request anchor flush waits for older saves and retains the new pending identity', async () => {
  const first=deferred(), calls=[]
  const h=harness({saveCopilotSession:async(id,payload)=>{
    calls.push(structuredClone(payload));return calls.length===1?first.promise:{success:true,revision:2}
  }})
  h.store.pushMessage({role:'user',content:'question'})
  await h.runTimers()
  h.store.pushMessage({role:'assistant',content:'',streaming:true,requestId:'pending-2',requestState:'pending'})
  let ready=false
  const flushed=h.store.flushConversation().then(result=>{ready=result})
  await yieldLoop();assert.equal(ready,false)
  first.resolve({success:true,revision:1});await flushed
  assert.equal(ready,true)
  assert.equal(calls.at(-1).messages[1].requestId,'pending-2')
  assert.equal(h.store.conversations.value[0].pendingSync,false)
})

test('failed anchor save keeps local identity without an immediate retry loop', async () => {
  let attempts=0
  const h=harness({saveCopilotSession:async()=>{attempts++;throw {response:{status:503}}}})
  h.store.pushMessage({role:'assistant',content:'',streaming:true,requestId:'kept-locally',requestState:'pending'})
  assert.equal(await h.store.flushConversation(),false)
  assert.equal(attempts,1)
  assert.equal(h.store.conversations.value[0].messages[0].requestId,'kept-locally')
  assert.equal(h.store.conversations.value[0].pendingSync,true)
  assert.ok(h.store.conversations.value[0].syncError)
})

test('a save acknowledgement cannot drop edits made while the save was pending', async () => {
  const first = deferred(), calls = []
  const h = harness({ saveCopilotSession: async (id, payload) => {
    calls.push({ id, payload: structuredClone(payload) })
    return calls.length === 1 ? first.promise : { success: true, revision: 2 }
  } })
  h.store.pushMessage({ role: 'user', content: 'first message' })
  await h.runTimers()
  h.store.pushMessage({ role: 'assistant', content: 'new message during save' })
  await h.runTimers()
  assert.equal(calls.length, 1)
  first.resolve({ success: true, revision: 1 })
  await yieldLoop()
  assert.equal(h.store.conversations.value[0].pendingSync, true)
  assert.equal(h.store.conversations.value[0].messages.length, 2)
  await h.runTimers()
  assert.equal(calls.length, 2)
  assert.equal(calls[1].payload.revision, 1)
  assert.equal(calls[1].payload.messages[1].content, 'new message during save')
  assert.equal(h.store.conversations.value[0].pendingSync, false)
})

test('logout invalidates pending remote reads and attachment compression', async () => {
  const read = deferred()
  const h = harness({ getCopilotSession: async () => read.promise })
  h.store.pushMessage({ role: 'user', content: 'old account', attachments: [{ contentString: `data:image/png,${'x'.repeat(5000)}` }] })
  await h.runTimers()
  h.store.resetSession()
  read.resolve({ exists: false, revision: 0, messages: [] })
  for (const image of h.images) image.onload?.()
  await yieldLoop()
  assert.equal(h.saves.length, 0)
  assert.equal(h.store.conversations.value.length, 0)
  assert.equal(h.data.has('ai_copilot_sessions_v1'), false)
})

test('conflicted local content can be saved under a new ID without overwriting the original', async () => {
  const calls = []
  let conflictId
  const h = harness({ saveCopilotSession: async (id, payload) => {
    calls.push({ id, payload: structuredClone(payload) })
    if (id === conflictId) throw { response: { status: 409 } }
    return { success: true, revision: 1 }
  } })
  h.store.pushMessage({ role: 'user', content: 'local version to preserve' })
  conflictId = h.store.activeId.value
  await h.runTimers()
  h.store.saveConflictAsNew()
  const copiedId = h.store.activeId.value
  await h.runTimers()
  assert.notEqual(copiedId, conflictId)
  assert.equal(calls.filter((call) => call.id === conflictId).length, 1)
  assert.equal(calls[1].payload.revision, undefined)
  assert.equal(calls[1].payload.messages[0].content, 'local version to preserve')
  assert.equal(h.store.conversations.value.find((item) => item.id === copiedId).pendingSync, false)
  assert.equal(h.store.conversations.value.find((item) => item.id === conflictId).conflicted, true)
})

test('a matching legacy cache adopts the revision regardless of JSON key order', async () => {
  let remote
  const h = harness({ getCopilotSession: async () => remote })
  h.store.pushMessage({ role: 'user', content: 'same history' })
  const local = h.store.conversations.value[0]
  remote = { exists: true, revision: 7, title: local.title, messages: local.messages.map((message) =>
    Object.fromEntries(Object.entries(message).reverse())) }
  await h.runTimers()
  assert.equal(h.saves.length, 1)
  assert.equal(h.saves[0].payload.revision, 7)
  assert.equal(h.store.activeSyncError.value, '')
})

test('deletion waits for an already sent save so its acknowledgement cannot resurrect history', async () => {
  const save = deferred(), events = []
  const h = harness({
    saveCopilotSession: async () => { events.push('save'); await save.promise; events.push('saved'); return { revision: 1 } },
    deleteCopilotSession: async () => { events.push('delete') },
  })
  h.store.pushMessage({ role: 'user', content: 'to delete' })
  const id = h.store.activeId.value
  await h.runTimers()
  h.store.deleteConversation(id)
  await yieldLoop()
  assert.deepEqual(events, ['save'])
  save.resolve()
  await yieldLoop()
  assert.deepEqual(events, ['save', 'saved', 'delete'])
  assert.equal(h.store.conversations.value.some((item) => item.id === id), false)
})
