import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'
import ts from 'typescript'
const source = readFileSync(new URL('../src/utils/topologyLabel.ts', import.meta.url), 'utf8')
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
const sandbox = { exports: {} }; vm.runInNewContext(code, sandbox)
const { compactTopologyLabel: compact } = sandbox.exports
test('short device identifiers stay intact; long labels retain distinct suffixes in bounded SVG space', () => {
  assert.equal(compact('R1', 60), 'R1')
  const a = compact('D05-1793994460294-R1', 84), b = compact('D05-1793994460294-R2', 84)
  assert.match(a, /….*R1$/); assert.match(b, /….*R2$/)
  assert.notEqual(a, b); assert.ok(a.length <= 11)
  const chinese = compact('华北研发中心核心交换机甲', 84)
  assert.ok(chinese.length <= 6); assert.ok(chinese.endsWith('甲'))
})
