import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'
import * as vue from 'vue'

const snapshotModule = { exports: {} }
const snapshotCode = ts.transpileModule(readFileSync(new URL('../src/composables/useSnapshotRequest.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
new Function('require', 'module', 'exports', snapshotCode)(name => { if (name === 'vue') return vue; throw new Error(name) }, snapshotModule, snapshotModule.exports)

const source = readFileSync(new URL('../src/views/device/DeviceListView.vue', import.meta.url), 'utf8')
const script = source.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
const compiled = ts.transpileModule(script + '\nexport { devices, showObservation, observationDeviceId, observationDevice, observationAction, observing, observation, observationError, recentObservations, openObservation, selectObservationDevice, runObservation, loadRecentObservations, useObservation, invalidateObservation, resetObservation };', {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
function deferred() {
  let resolve, reject
  const promise = new Promise((a, b) => { resolve = a; reject = b })
  return { promise, resolve, reject }
}
function harness() {
  const requests = [], histories = [], hooks = []
  const copilot = { open: true, selection: null, evidenceId: null,
    setSelection(x) { this.selection = x }, setEvidenceId(x) { this.evidenceId = x } }
  const lab = { setDevice() {} }
  const stubs = {
    '../../composables/useSnapshotRequest': snapshotModule.exports,
    vue: { ref: value => ({ value }), computed: get => ({ get value() { return get() } }), onMounted() {}, onBeforeUnmount(fn) { hooks.push(fn) } },
    'vue-router': { useRouter: () => ({}) },
    '../../stores/aiCopilot': { useAiCopilotStore: () => copilot },
    '../../stores/labContext': { useLabContextStore: () => lab },
    '../../api/trust': {
      getEnvironments: async () => [],
      getObservations(args) { const d = deferred(); histories.push({ ...d, args }); return d.promise },
      createObservation(args) { const d = deferred(); requests.push({ ...d, args }); return d.promise },
    },
  }
  const mod = { exports: {} }
  new Function('require', 'module', 'exports', compiled)(name => stubs[name] || {}, mod, mod.exports)
  const h = { ...mod.exports, copilot, requests, histories, hooks }
  h.devices.value = [{ id: 2, hostname: 'R2', model: 'NE40E' }, { id: 3, hostname: 'R3', model: 'CE6800' }]
  return h
}
const record = (device_id, id = 21) => ({ id, device_id, action_id: 'interface_brief', environment_id: null })

test('row observation and history reuse bind exact device and model', async () => {
  const h = harness()
  await h.openObservation(h.devices.value[0])
  assert.deepEqual([h.copilot.selection.id, h.copilot.selection.model], [2, 'NE40E'])
  h.useObservation(record(2))
  assert.equal(h.copilot.evidenceId, 21)
  h.observationDeviceId.value = 3; h.selectObservationDevice()
  assert.equal(h.observationDevice.value.hostname, 'R3')
  assert.equal(h.copilot.evidenceId, null)
  h.useObservation(record(2))
  assert.equal(h.copilot.evidenceId, null)
})

for (const action of ['switch', 'reopen', 'change_action', 'unmount']) {
  test(`late observation cannot commit after ${action}`, async () => {
    const h = harness()
    await h.openObservation(h.devices.value[0])
    const pending = h.runObservation()
    if (action === 'switch') { h.observationDeviceId.value = 3; h.selectObservationDevice() }
    if (action === 'reopen') { h.showObservation.value = false; h.invalidateObservation(); await h.openObservation(h.devices.value[0]) }
    if (action === 'change_action') { h.observationAction.value = 'ospf_peer'; h.resetObservation() }
    if (action === 'unmount') h.hooks[0]()
    h.requests[0].resolve(record(2))
    await pending
    assert.equal(h.observation.value, null)
    assert.equal(h.copilot.evidenceId, null)
    assert.equal(h.observing.value, false)
  })
}

test('late failure cannot erase newer loading or evidence', async () => {
  const h = harness()
  await h.openObservation(h.devices.value[0])
  const old = h.runObservation()
  h.observationDeviceId.value = 3; h.selectObservationDevice()
  const current = h.runObservation()
  h.requests[0].reject(new Error('old request'))
  await old
  assert.equal(h.observing.value, true)
  assert.equal(h.observationError.value, '')
  h.requests[1].resolve(record(3, 30))
  // Let collection start the latest history refresh, then complete it.
  await Promise.resolve()
  h.histories.at(-1).resolve([record(3, 30)])
  await current
  assert.equal(h.copilot.evidenceId, 30)
  assert.equal(h.copilot.selection.id, 3)
})

test('late history cannot replace the new target list', async () => {
  const h = harness()
  await h.openObservation(h.devices.value[0])
  h.observationDeviceId.value = 3; h.selectObservationDevice()
  h.histories[1].resolve([record(3, 30)]); await Promise.resolve()
  h.histories[0].resolve([record(2)]); await Promise.resolve()
  assert.equal(h.recentObservations.value[0].device_id, 3)
})
