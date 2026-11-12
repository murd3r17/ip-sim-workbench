import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'
import ts from 'typescript'

const source = readFileSync(new URL('../src/views/device/TopologyView.vue', import.meta.url), 'utf8')
  .match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
const parsed = ts.createSourceFile('topology.ts', source, ts.ScriptTarget.Latest, true)
const names = ['canConfirmRuntimeBaseline', 'runtimeStatusText', 'runDiscover']
const statements = parsed.statements.filter(statement => ts.isVariableStatement(statement)
  && statement.declarationList.declarations.some(item => names.includes(item.name.getText(parsed))))
const code = ts.transpileModule(statements.map(item => item.getText(parsed)).join('\n') + `\nexport { ${names.join(',')} };`, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText

function component(result) {
  const messages = []
  const sandbox = {
    exports: {}, computed: fn => ({ get value() { return fn() } }),
    runtimeCheck: { value: result }, nodes: { value: [{}, {}, {}] }, topologyId: { value: 1 },
    discovering: { value: false }, discoverResult: { value: '' },
    discoverTopologyLinks: async () => result, loadTopology: async () => {},
    ElMessage: { warning: text => messages.push(['warning', text]), success: text => messages.push(['success', text]) },
    notifyRequestError: error => { throw error },
  }
  vm.runInNewContext(code, sandbox)
  return { ...sandbox.exports, messages }
}

const complete = { status: 'matched', errors: [], ssh_success: 3, ssh_failed: 0, links: [{}], discovered: 1,
  evidence_stale: false, mode_changed: false, coverage: { version: 'lldp-brief-d05.1' } }

test('all SSH success does not allow confirmation of partial or diagnostic-bearing evidence', () => {
  assert.equal(component(complete).canConfirmRuntimeBaseline.value, true)
  for (const change of [{ status: 'partial' }, { errors: ['库存外邻居'] }, { evidence_stale: true },
    { coverage: null }, { mode_changed: true }, { is_stale: true }]) {
    assert.equal(component({ ...complete, ...change }).canConfirmRuntimeBaseline.value, false)
  }
})

test('partial discovery shows an incomplete warning without a simultaneous success message', async () => {
  const view = component({ ...complete, status: 'partial', errors: ['R1: 库存外邻居 2 条：HUAWEI'] })
  assert.match(view.runtimeStatusText.value, /不完整/)
  await view.runDiscover()
  assert.deepEqual(view.messages.map(item => item[0]), ['warning'])
  assert.match(view.messages[0][1], /不完整/)
})

test('complete discovery retains the success message', async () => {
  const view = component(complete)
  await view.runDiscover()
  assert.deepEqual(view.messages.map(item => item[0]), ['success'])
})

test('zero baseline and unknown historic coverage cannot claim network completeness', async () => {
  const view = component({ ...complete, status: 'no_baseline', links: [] })
  assert.equal(view.canConfirmRuntimeBaseline.value, false)
  assert.match(view.runtimeStatusText.value, /无链路基线/)
  await view.runDiscover()
  assert.deepEqual(view.messages.map(item => item[0]), ['warning'])
  assert.match(view.messages[0][1], /仅记录 LLDP 邻接/)
  assert.match(component({ ...complete, evidence_stale: true }).runtimeStatusText.value, /已过期或覆盖未知/)
})
