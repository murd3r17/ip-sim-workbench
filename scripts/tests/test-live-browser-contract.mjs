import test from 'node:test'
import assert from 'node:assert/strict'
import { parseSse, streamEvidence, sameRuntime, sameBinding, aiLogEvidence } from '../live-browser-contract.mjs'

const marker = 'acceptance-fixture'
const events = [{ type: 'token', text: '37+58=95 ' + marker }, { type: 'done', status: 'ok' }]
test('real stream requires terminal success, challenge, nonfallback content and no tools', () => {
  assert.equal(streamEvidence(events, marker).ok, true)
  for (const candidate of [events.slice(0, 1), [{ type: 'done', status: 'ok' }],
    [events[0], { type: 'done', status: 'failed' }], [{ type: 'token', text: '当前AI服务不可用' }, events[1]],
    [{ type: 'error' }, ...events], [...events, { type: 'token', text: 'late' }],
    [{ type: 'tool', name: 'run_display_command', status: 'done' }, ...events]]) {
    assert.equal(streamEvidence(candidate, marker).ok, false)
  }
  assert.equal(streamEvidence(events, 'different-marker').ok, false)
  assert.equal(JSON.stringify(streamEvidence(events, marker)).includes(marker), false)
})
test('SSE is parsed strictly', () => {
  assert.deepEqual(parseSse(events.map(e => 'data: ' + JSON.stringify(e) + '\n\n').join('')), events)
  assert.throws(() => parseSse('data: not-json'))
})
test('runtime/build bindings cannot omit or change identity', () => {
  const identity = { schema: 1, database_fingerprint: 'database', root_fingerprint: 'root', device_mode: 'ssh', deploy_simulate_only: false, knowledge_provider: 'anythingllm', source_fingerprint: 'source' }
  assert.equal(sameRuntime(identity, { ...identity, pid: 3 }), true)
  for (const key of ['database_fingerprint', 'root_fingerprint', 'device_mode', 'deploy_simulate_only']) {
    assert.equal(sameRuntime(identity, { ...identity, [key]: 'different' }), false)
  }
  assert.equal(sameRuntime(identity, {}), false)
  assert.equal(sameBinding(identity, { ...identity, source_fingerprint: 'changed' }), false)
})
test('AI logs must be current, marker-bound and from the effective model', () => {
  const row = { id: 5, request_type: 'copilot_chat', model_used: 'deepseek-chat', prompt: marker, response: '95 ' + marker }
  const options = { cursor: 4, marker, model: 'deepseek-chat' }
  assert.equal(aiLogEvidence([row], options).ai_log_id, 5)
  for (const change of [{ id: 4 }, { model_used: 'other' }, { prompt: 'unrelated' }, { response: '当前AI服务不可用' }]) {
    assert.equal(aiLogEvidence([{ ...row, ...change }], options), null)
  }
})
test('vision challenge is matched from response without putting it in request prompt', () => {
  const row = { id: 6, request_type: 'copilot_chat', model_used: 'vision-model', prompt: 'request-id read image', response: 'V6-ABC234' }
  assert.equal(aiLogEvidence([row], { cursor: 5, marker: 'request-id', responseMarker: 'V6-ABC234', model: 'vision-model' }).ai_log_id, 6)
  assert.equal(row.prompt.includes('V6-ABC234'), false)
  assert.equal(aiLogEvidence([row], { cursor: 5, marker: 'request-id', responseMarker: 'V6-ABC234', model: 'text-model' }), null)
})
