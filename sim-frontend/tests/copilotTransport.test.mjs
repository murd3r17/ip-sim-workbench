import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/api/ai.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText

function harness(chunks, status = 200) {
  let cancelled = false, locked = true, fetches = 0, cleared = false
  const window = { location: { pathname: '/devices', search: '?id=2', href: '' } }
  const reader = { async read() { return chunks.length ? { value: new TextEncoder().encode(chunks.shift()), done: false } : { done: true } },
    async cancel() { cancelled = true }, releaseLock() { locked = false } }
  const module = { exports: {} }
  const fetch = async () => { fetches++; return { ok: status === 200, status, json: async () => ({detail:'无效Token'}), body: { getReader: () => reader } } }
  new Function('require', 'module', 'exports', 'fetch', 'localStorage', 'window', compiled)(
    () => ({ default: {}, clearClientSession: () => { cleared = true } }), module, module.exports, fetch, { getItem: () => 'isolated-token' }, window)
  return { run: module.exports.copilotChatStream, window, cleared: () => cleared, state: () => ({ cancelled, locked, fetches }) }
}

test('CRLF, split chunks and final frame work; no data after done is delivered', async () => {
  const h = harness(['data: {"type":"token","text":"hi"}\r', '\n\r\ndata: {"type":"done"}\n\n', 'data: {"type":"token","text":"late"}\n\n'])
  const events = []
  await h.run({ message: 'test' }, e => events.push(e))
  assert.deepEqual(events.map(e => e.type), ['token', 'done'])
  assert.deepEqual(h.state(), { cancelled: true, locked: false, fetches: 1 })
})

test('EOF cannot silently succeed or automatically resubmit', async () => {
  const h = harness(['data: {"type":"token","text":"partial"}\n\n'])
  await assert.rejects(h.run({ message: 'test' }, () => {}), /完成确认/)
  assert.deepEqual(h.state(), { cancelled: true, locked: false, fetches: 1 })
})

test('consumer errors propagate and close the stream', async () => {
  const h = harness(['data: {"type":"token","text":"hi"}\n\n'])
  await assert.rejects(h.run({ message: 'test' }, () => { throw new Error('consumer failed') }), /consumer failed/)
  assert.equal(h.state().cancelled, true)
})

test('malformed frames are reported instead of hiding a missing answer', async () => {
  const h = harness(['data: {malformed}\n\n'])
  await assert.rejects(h.run({ message: 'test' }, () => {}), /格式异常/)
  assert.equal(h.state().fetches, 1)
})

test('expired SSE login clears the account and explains expiry while preserving return path', async () => {
  const h=harness([],401)
  await assert.rejects(h.run({message:'test'},()=>{}))
  const target=new URL(h.window.location.href,'http://localhost')
  assert.equal(target.pathname,'/login');assert.equal(target.searchParams.get('expired'),'1')
  assert.equal(target.searchParams.get('redirect'),'/devices?id=2');assert.equal(h.cleared(),true)
  assert.equal(h.state().fetches,1)
})
