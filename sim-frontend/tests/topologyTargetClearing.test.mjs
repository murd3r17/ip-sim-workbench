import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'

const view = readFileSync(new URL('../src/views/device/TopologyView.vue', import.meta.url), 'utf8')
const source = view.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
const ast = ts.createSourceFile('topology.ts', source, ts.ScriptTarget.Latest, true)
const statements = ast.statements.filter(n => ts.isVariableStatement(n) && n.declarationList.declarations.some(d => ['loadTopology', 'clearTopologyView'].includes(d.name.getText(ast))))
assert.equal(statements.length, 2)
const code = ts.transpileModule(statements.map(s => s.getText(ast)).join('\n') + '\nexports.load=loadTopology;', { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
function harness(topologies, readFails) {
  const ref = value => ({ value })
  const h = { exports: {}, topologyLoadEpoch: 0, layoutRevision: 0, topologyId: ref(1), nodes: ref([{ id: 'old' }]), edges: ref([{ source: 'old' }]), selectedNode: ref({ id: 'old' }), runtimeCheck: ref({ id: 1 }), draftPositions: ref({ old: { x: 1, y: 1 } }), layoutDirty: ref(true), versionsVisible: ref(true), versionsTarget: ref(1), loading: ref(false), topologyLoadError: ref(''), route: { query: { topology_id: '2' } }, labCtx: { setTopology() {} }, getTopologies: async () => topologies, getDevices: async () => { if (readFails) throw new Error('new target unavailable'); return [] }, getTopologyLinks: async () => [], getLatestRuntimeCheck: async () => null, getTopologyLayout: async () => ({ draft_positions: {} }), notifyRequestError() {} }
  vm.runInNewContext(code, h)
  return h
}
function assertOldTargetGone(h) {
  assert.match(view, /<TopologyCanvas\s+v-if="nodes.length"\s+:key="topologyId"/)
  assert.equal(h.nodes.value.length, 0)
  assert.equal(h.edges.value.length, 0)
  assert.equal(h.selectedNode.value, null)
  assert.equal(h.runtimeCheck.value, null)
  assert.equal(Object.keys(h.draftPositions.value).length, 0)
  assert.equal(h.layoutDirty.value, false)
  assert.equal(h.versionsVisible.value, false)
  assert.equal(h.versionsTarget.value, null)
}
test('switching targets removes previous SVG and selected actions even if new data fails', async () => {
  const h = harness([{ id: 2, device_count: 2 }], true)
  await h.exports.load()
  assertOldTargetGone(h)
  assert.equal(h.topologyId.value, 2)
  assert.match(h.topologyLoadError.value, /读取失败/)
})
test('an empty topology catalog clears the old SVG rather than leaving a false network behind', async () => {
  const h = harness([], false)
  await h.exports.load()
  assertOldTargetGone(h)
  assert.equal(h.topologyId.value, 0)
  assert.equal(h.topologyLoadError.value, '')
})
