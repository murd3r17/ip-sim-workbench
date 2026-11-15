import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'
import ts from 'typescript'

// Execute the actual component script with only its UI/network dependencies replaced.
function component(routeId = '1') {
  const source = readFileSync(new URL('../src/views/device/WebSSHView.vue', import.meta.url), 'utf8')
    .match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  const route = { params: { deviceId: routeId } }
  const context = { device: null, setDevice(value) { this.device = value } }
  const copilot = { selection: null, setSelection(value) { this.selection = value } }
  const watchers = []
  const vue = {
    ref: value => ({ value }), computed: getter => ({ get value() { return getter() } }),
    onMounted() {}, onBeforeUnmount() {}, watch: (...args) => watchers.push(args),
  }
  const modules = {
    vue,
    'vue-router': { useRoute: () => route, useRouter: () => ({}) },
    'element-plus/es/components/message/index': { ElMessage: { error() {} } },
    '../../api/device': { getDevices: async () => [{ id: 1, hostname: 'A' }, { id: 2, hostname: 'B' }] },
    '../../utils/requestError': { notifyRequestError: error => { throw error } },
    '../../utils/autoRefresh': { useAutoRefresh() {} },
    '../../components/WebSSHConsole.vue': {},
    '../../stores/aiCopilot': { useAiCopilotStore: () => copilot },
    '../../stores/labContext': { useLabContextStore: () => context },
    '../../composables/useTrainingCommandLog': { useTrainingCommandLog: () => ({ logTerminalCommand() {} }) },
  }
  const code = ts.transpileModule(source + '\nexport { loadDevices, selectedDeviceId, connectRequested, disconnect, onPhase, syncSelection };', {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const sandbox = { exports: {}, require: name => modules[name], requestAnimationFrame: fn => fn() }
  vm.runInNewContext(code, sandbox)
  return { ...sandbox.exports, route, watchers, copilot }
}

test('device refresh preserves an explicitly selected terminal target', async () => {
  const view = component()
  await view.loadDevices()
  assert.equal(view.selectedDeviceId.value, 1)
  view.selectedDeviceId.value = 2
  view.syncSelection()
  await view.loadDevices()
  await view.loadDevices()
  assert.equal(view.selectedDeviceId.value, 2)
})

test('refresh does not reconnect a manually disconnected terminal', async () => {
  const view = component()
  await view.loadDevices()
  view.disconnect()
  await view.loadDevices()
  assert.equal(view.connectRequested.value, false)
})

test('an explicit route change selects the requested target and connects', async () => {
  const view = component()
  await view.loadDevices()
  const routeWatcher = view.watchers.find(([source]) => typeof source === 'function')
  view.route.params.deviceId = '2'
  routeWatcher[1]('2')
  assert.equal(view.selectedDeviceId.value, 2)
  assert.equal(view.connectRequested.value, true)
})

test('refresh and terminal status updates respect a cleared assistant selection', async () => {
  const view = component()
  await view.loadDevices()
  assert.equal(view.copilot.selection.id, 1)
  view.onPhase('ready')
  assert.match(view.copilot.selection.detail, /终端已就绪/)
  view.copilot.setSelection(null)
  view.onPhase('idle')
  await view.loadDevices()
  assert.equal(view.copilot.selection, null)
})
