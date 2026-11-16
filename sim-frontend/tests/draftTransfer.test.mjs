import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const vue = await readFile(new URL('../src/views/deploy/DeployCenterView.vue', import.meta.url), 'utf8')
const source = vue.slice(vue.indexOf('async function loadAiDraft()'), vue.indexOf('function maybeAutoLoadDraft()'))
const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
async function load(text, metadata, acceptReplacement = true) {
  const transferKey = 'workbench:1:learner:copilot:transfer:'
  const data = new Map([[transferKey + 'text', text], [transferKey + 'context', metadata]])
  const form = { value: { device_ids: [3, 4], config_content: 'old' } }
  const tab = { value: 'tasks' }
  const deps = {
    transferKey, localStorage: { getItem: key => data.get(key) }, deployForm: form,
    devices: { value: [{ id: 2 }, { id: 3 }] }, activeTab: tab, ElMessage: { success() {} },
    refreshDraftState() {}, drafts: { deploy: { form: form.value, submitting: false } },
    hasDraft: { value: true }, confirmDraftReplacement: async () => acceptReplacement, viewActive: true,
  }
  const run = new Function(...Object.keys(deps), js + ';return loadAiDraft()')
  await run(...Object.values(deps))
  return { form: form.value, tab: tab.value }
}
test('load replaces an unrelated multi-device target with the original device after confirmation', async () => {
  assert.deepEqual(await load('new', JSON.stringify({ text: 'new', target: { deviceId: 2, verifiedByServer: true } })), {
    form: { device_ids: [2], config_content: 'new' }, tab: 'deploy',
  })
})
test('declining replacement preserves the original text and devices', async () => {
  assert.deepEqual(await load('new', undefined, false), { form: { device_ids: [3, 4], config_content: 'old' }, tab: 'tasks' })
})
for (const [label, metadata] of [
  ['legacy', undefined], ['corrupt', '{'], ['mismatched text', JSON.stringify({ text: 'old', target: { deviceId: 2 } })],
  ['deleted device', JSON.stringify({ text: 'new', target: { deviceId: 99 } })],
  ['string device', JSON.stringify({ text: 'new', target: { deviceId: '2' } })],
  ['unverified old metadata', JSON.stringify({ text: 'new', target: { deviceId: 2 } })],
]) test(`${label} draft never inherits the previous target`, async () => assert.deepEqual((await load('new', metadata)).form.device_ids, []))
