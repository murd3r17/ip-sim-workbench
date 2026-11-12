import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'
import ts from 'typescript'

function snapshotBuilder(logCount, labs = []) {
  const source = fs.readFileSync(new URL('../../src/utils/pageDataContext.ts', import.meta.url), 'utf8')
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  const api = {
    listLabs: async () => labs,
    getSession: async () => ({ status: 'in_progress', score: null }),
    getOperationLogs: async () => Array.from({ length: logCount }, () => ({ command: 'self report', success: true })),
    getSessionFaults: async () => [{ resolved_correctly: null }, { resolved_correctly: false }, { resolved_correctly: true }],
  }
  const context = { exports: {}, require: () => api }
  vm.runInNewContext(compiled, context)
  return context.exports.buildPageDataContext
}

for (const [mode, expected] of [['sim', '模拟设备'], ['ssh', '真实设备'], [undefined, '设备连接方式未知']]) {
  test(`training context uses actual server mode ${mode ?? 'missing'}, never a fixed real-device claim`, async () => {
    const snapshot = await snapshotBuilder(0, [{ title: 'owned lesson', status: 'ready', topology_id: 1,
      mode_facts: mode ? { device_mode: mode } : undefined }])('/training')
    assert.ok(snapshot.includes(expected))
    if (mode !== 'ssh') assert.doesNotMatch(snapshot, /真实设备/)
  })
}

for (const logCount of [0, 12, 120]) {
  test(`training progress stays unverified with ${logCount} client records`, async () => {
    const snapshot = await snapshotBuilder(logCount)('/training', { sessionId: 1, labSteps: [{}, {}, {}] })
    assert.match(snapshot, /技能达标未验证/)
    assert.match(snapshot, /步骤总数 3；当前步骤及完成进度未验证/)
    assert.match(snapshot, /未解决故障 2 条/)
    assert.doesNotMatch(snapshot, /步骤 [1-3]\/3/)
    if (logCount) assert.match(snapshot, /客户端报告成功（未验证）/)
  })
}
