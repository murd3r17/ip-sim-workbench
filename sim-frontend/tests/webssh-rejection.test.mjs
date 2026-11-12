import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'
import ts from 'typescript'

function consoleComponent() {
  const source = readFileSync(new URL('../src/components/WebSSHConsole.vue', import.meta.url), 'utf8')
    .match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  const events = [], lines = [], sockets = []
  class Socket { constructor() { sockets.push(this) } close() {} }
  class Terminal { loadAddon() {} open() {} onData() {} attachCustomKeyEventHandler() {} dispose() {} writeln(value) { lines.push(value) } }
  class ResizeObserver { observe() {} disconnect() {} }
  const modules = {
    vue: { nextTick: async () => {}, ref: () => ({ value: {} }), watch() {}, onMounted() {}, onBeforeUnmount() {} },
    xterm: { Terminal }, 'xterm-addon-fit': { FitAddon: class { fit() {} } }, 'xterm/css/xterm.css': {},
  }
  const code = ts.transpileModule(source + '\nexport { connect };', {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const sandbox = { exports: {}, require: name => modules[name], defineProps: () => ({ deviceId: 1 }),
    defineEmits: () => (...args) => events.push(args), defineExpose() {}, WebSocket: Socket, ResizeObserver,
    localStorage: { getItem: () => '' }, window: { location: { protocol: 'http:', host: 'owned.invalid' } } }
  vm.runInNewContext(code, sandbox)
  return { ...sandbox.exports, sockets, lines, errors: () => events.filter(([name]) => name === 'error').map(([, value]) => value) }
}

test('one rejected connection reports the error frame and matching close reason once', async () => {
  const c = consoleComponent(); await c.connect()
  c.sockets[0].onmessage({ data: JSON.stringify({ type: 'error', message: '设备被占用' }) })
  c.sockets[0].onclose({ code: 4009, reason: '设备被占用' })
  assert.deepEqual(c.errors(), ['设备被占用'])
  assert.equal(c.lines.filter(line => line.includes('设备被占用')).length, 1)
})

test('a close-only rejection still shows its reason', async () => {
  const c = consoleComponent(); await c.connect()
  c.sockets[0].onclose({ code: 4001, reason: '登录已过期' })
  assert.deepEqual(c.errors(), ['登录已过期'])
})

test('a different final reason is retained and a new connection reports errors again', async () => {
  const c = consoleComponent(); await c.connect()
  c.sockets[0].onmessage({ data: JSON.stringify({ type: 'error', message: '连接失败' }) })
  c.sockets[0].onclose({ code: 4009, reason: '设备被占用' })
  await c.connect()
  c.sockets[1].onmessage({ data: JSON.stringify({ type: 'error', message: '设备被占用' }) })
  c.sockets[1].onclose({ code: 4009, reason: '设备被占用' })
  assert.deepEqual(c.errors(), ['连接失败', '设备被占用', '设备被占用'])
})

test('an empty close reason does not replace the explicit server error', async () => {
  const c = consoleComponent(); await c.connect()
  c.sockets[0].onmessage({ data: JSON.stringify({ type: 'error', message: '连接数上限' }) })
  c.sockets[0].onclose({ code: 4006, reason: '' })
  assert.deepEqual(c.errors(), ['连接数上限'])
})
