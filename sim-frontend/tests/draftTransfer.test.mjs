import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const vue = await readFile(new URL('../src/views/deploy/DeployCenterView.vue', import.meta.url), 'utf8')
const source = vue.slice(vue.indexOf('function loadAiDraft()'), vue.indexOf('function maybeAutoLoadDraft()'))
const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
function load(text, metadata) {
  const data = new Map([['deploy_ai_draft', text], ['deploy_ai_draft_context', metadata]])
  const form = { value: { device_ids: [3, 4], config_content: 'old' } }
  const tab = { value: 'tasks' }
  const run = new Function('localStorage', 'deployForm', 'devices', 'activeTab', 'ElMessage', 'refreshDraftState', js + ';return loadAiDraft()')
  const result = run({ getItem: key => data.get(key) }, form, { value: [{ id: 2 }, { id: 3 }] }, tab, { success() {} }, () => {})
  return { result, form: form.value, tab: tab.value }
}
test('load replaces an unrelated multi-device target with the original device', () => {
  assert.deepEqual(load('new', JSON.stringify({ text: 'new', target: { deviceId: 2, verifiedByServer: true } })), {
    result: true, form: { device_ids: [2], config_content: 'new' }, tab: 'deploy',
  })
})
for (const [label, metadata] of [
  ['legacy', undefined], ['corrupt', '{'], ['mismatched text', JSON.stringify({ text: 'old', target: { deviceId: 2 } })],
  ['deleted device', JSON.stringify({ text: 'new', target: { deviceId: 99 } })],
  ['string device', JSON.stringify({ text: 'new', target: { deviceId: '2' } })],
  ['unverified old metadata', JSON.stringify({ text: 'new', target: { deviceId: 2 } })],
]) test(`${label} draft never inherits the previous target`, () => assert.deepEqual(load('new', metadata).form.device_ids, []))
