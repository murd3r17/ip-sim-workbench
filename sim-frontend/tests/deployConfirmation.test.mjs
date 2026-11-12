import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

// Use the already-declared compiler, including on Node 20 (no strip-types flag).
const source = await readFile(new URL('../src/utils/deployConfirmation.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } })
const { confirmWithRisk } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
const challenge = { response: { status: 422, data: { detail: '高风险任务需要二次确认' } } }

test('ordinary confirmation makes one request and no risk dialog', async () => {
  const calls = []
  assert.equal(await confirmWithRisk(async value => calls.push(value), async () => assert.fail()), false)
  assert.deepEqual(calls, [false])
})

test('risk challenge waits for human approval before the second request', async () => {
  const calls = []
  let approve
  const answer = new Promise(resolve => { approve = resolve })
  const result = confirmWithRisk(async value => {
    calls.push(value)
    if (!value) throw challenge
  }, () => answer)
  await Promise.resolve()
  assert.deepEqual(calls, [false])
  approve()
  assert.equal(await result, true)
  assert.deepEqual(calls, [false, true])
})

test('cancelled risk dialog never confirms the task', async () => {
  const calls = []
  await assert.rejects(confirmWithRisk(async value => {
    calls.push(value)
    throw challenge
  }, async () => { throw new Error('cancelled') }), /cancelled/)
  assert.deepEqual(calls, [false])
})

test('unrelated 422 errors are not treated as permission to retry', async () => {
  const error = { response: { status: 422, data: { detail: '任务状态不允许确认' } } }
  await assert.rejects(confirmWithRisk(async () => { throw error }, async () => assert.fail()), value => value === error)
})

test('second request errors are reported rather than swallowed', async () => {
  await assert.rejects(confirmWithRisk(async risk => {
    if (!risk) throw challenge
    throw new Error('lock conflict')
  }, async () => {}), /lock conflict/)
})
