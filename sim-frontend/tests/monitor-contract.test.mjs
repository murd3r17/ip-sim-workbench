import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'
import ts from 'typescript'

const source = readFileSync(new URL('../src/views/monitor/MonitorDashboardView.vue', import.meta.url), 'utf8')
  .match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
const parsed = ts.createSourceFile('monitor.ts', source, ts.ScriptTarget.Latest, true)
const names = ['latestMetricValue', 'renderTimeSeries']
const statements = parsed.statements.filter(statement => ts.isVariableStatement(statement)
  && statement.declarationList.declarations.some(item => names.includes(item.name.getText(parsed))))
const code = ts.transpileModule(statements.map(item => item.getText(parsed)).join('\n') + `\nexport { ${names.join(',')} };`, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const modules = new Map()
function load(relative) {
  const url = new URL(relative, import.meta.url)
  if (modules.has(url.href)) return modules.get(url.href)
  const compiled = ts.transpileModule(readFileSync(url, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const exports = {}
  vm.runInNewContext(compiled, { exports, require(name) {
    return load(new URL(name + '.ts', url).href)
  } })
  modules.set(url.href, exports)
  return exports
}
const sandbox = { exports: {}, ...load('../src/utils/monitorSeries.ts') }
vm.runInNewContext(code, sandbox)

test('interleaved device samples render separate named time series', () => {
  let option
  sandbox.exports.renderTimeSeries({ setOption(value) { option = value } }, [
    { device_id: 1, time: '2026-10-11T00:00:00', value: 10 },
    { device_id: 2, time: '2026-10-11T00:00:01', value: 90 },
    { device_id: 1, time: '2026-10-11T00:00:02', value: 20 },
  ])
  assert.equal(option.series.length, 2)
  assert.equal(option.series[0].name, '设备 #1')
  assert.deepEqual(Array.from(option.series[0].data, item => item[1]), [10, 20])
  assert.equal(option.series[1].name, '设备 #2')
})

test('interface totals sum the newest sample from each device', () => {
  assert.equal(sandbox.exports.latestMetricValue([
    { device_id: 1, time: '2026-10-11T00:00:02', value: 2 },
    { device_id: 2, time: '2026-10-11T00:00:02', value: 3 },
    { device_id: 1, time: '2026-10-11T00:00:00', value: 99 },
  ]), 5)
})

test('alarm close action matches the backend resolved/acknowledged contract', () => {
  const template = readFileSync(new URL('../src/views/monitor/AlarmView.vue', import.meta.url), 'utf8')
  const condition = template.match(/<el-button v-if="([^"]+)"[^>]*@click\.stop="handleClose\(row\)"/)[1]
  for (const status of ['fired', 'acknowledged', 'resolved', 'closed']) {
    assert.equal(vm.runInNewContext(condition, { row: { status } }), ['acknowledged', 'resolved'].includes(status))
  }
})
