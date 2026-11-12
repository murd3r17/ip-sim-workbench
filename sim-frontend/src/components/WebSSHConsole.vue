<template>
  <div ref="terminalEl" class="webssh-console"></div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Terminal } from 'xterm'
import { FitAddon } from 'xterm-addon-fit'
import 'xterm/css/xterm.css'

const props = defineProps<{ deviceId: number; autoConnect?: boolean }>()
const emit = defineEmits<{
  status: [connected: boolean]
  output: [value: string]
  ready: [ready: boolean]
  error: [message: string]
  command: [payload: { command: string; success: boolean; result: string }]
  reconnectExhausted: []
}>()

const terminalEl = ref<HTMLElement>()
let ws: WebSocket | null = null
let terminal: Terminal | null = null
let fitAddon: FitAddon | null = null
let resizeObserver: ResizeObserver | null = null
let connected = false
let sshReady = false
let manualClose = false
let reconnectTimer: number | null = null
let reconnectAttempts = 0
const MAX_RECONNECT_DELAY_MS = 15000
const MAX_RECONNECT_ATTEMPTS = 5
// 服务端拒绝类关闭码（见 backend/modules/webssh/router.py）：重连无意义，直接展示原因
const REJECT_CLOSE_CODES = new Set([4001, 4004, 4005, 4006, 4009])

let lineBuffer = ''
let lastOutputTail = ''
let echoTimer: number | null = null
let echoCommand = ''
let echoBuf = ''

const VRP_ERROR = /Error:|Unrecognized command|Incomplete command|Too many parameters|\^\s*$/im
const PAGE_KEYS = new Set([' ', 'f', 'q', 'n'])

const setStatus = (value: boolean) => {
  connected = value
  emit('status', value)
}

const setReady = (value: boolean) => {
  sshReady = value
  emit('ready', value)
}

function resetCommandCapture() {
  lineBuffer = ''
  lastOutputTail = ''
  echoCommand = ''
  echoBuf = ''
  if (echoTimer !== null) {
    clearTimeout(echoTimer)
    echoTimer = null
  }
}

function isPasswordPrompt() {
  return /password\s*:\s*$/i.test(lastOutputTail.replace(/\s+$/, '') + (lastOutputTail.endsWith(' ') ? ' ' : ''))
}

function shouldSkipCommand(command: string) {
  const trimmed = command.trim()
  if (!trimmed) return true
  if (PAGE_KEYS.has(trimmed) && trimmed.length === 1) return true
  if (isPasswordPrompt()) return true
  return false
}

function looksLikeError(text: string) {
  return VRP_ERROR.test(text)
}

function flushEcho() {
  if (!echoCommand) return
  const result = echoBuf.slice(0, 800)
  const success = !looksLikeError(echoBuf)
  emit('command', { command: echoCommand, success, result })
  echoCommand = ''
  echoBuf = ''
  echoTimer = null
}

function submitCommand(raw: string) {
  const command = raw.replace(/\r/g, '').trim()
  if (shouldSkipCommand(command)) return
  if (echoTimer !== null) {
    clearTimeout(echoTimer)
    flushEcho()
  }
  echoCommand = command
  echoBuf = ''
  echoTimer = window.setTimeout(flushEcho, 1200)
}

function handleLocalInput(data: string) {
  for (const ch of data) {
    if (ch === '\r' || ch === '\n') {
      submitCommand(lineBuffer)
      lineBuffer = ''
    } else if (ch === '\x7f' || ch === '\b') {
      lineBuffer = lineBuffer.slice(0, -1)
    } else if (ch === '\x03') {
      lineBuffer = ''
      if (echoTimer !== null) {
        clearTimeout(echoTimer)
        echoTimer = null
        echoCommand = ''
        echoBuf = ''
      }
    } else if (ch === '\x1b') {
      /* CSI / arrows: ignore for line buffer */
    } else if (ch >= ' ' || ch === '\t') {
      lineBuffer += ch
    }
  }
}

function noteOutput(chunk: string) {
  lastOutputTail = (lastOutputTail + chunk).slice(-400)
  if (echoCommand) echoBuf += chunk
}

const initTerminal = async () => {
  await nextTick()
  if (!terminalEl.value || terminal) return

  terminal = new Terminal({
    theme: {
      background: '#0d151e', foreground: '#dce8f2', cursor: '#35c7d7', cursorAccent: '#0d151e',
      red: '#ff7b7b', brightRed: '#ff9d9d', green: '#87d79a', brightGreen: '#a2edb3',
      yellow: '#e8c573', brightYellow: '#f4d892', cyan: '#74d8e3', brightCyan: '#9aebf3',
    },
    fontFamily: 'monospace', fontSize: 13, cursorBlink: true, scrollback: 10000, convertEol: true,
  })
  fitAddon = new FitAddon()
  terminal.loadAddon(fitAddon)
  terminal.open(terminalEl.value)
  fitAddon.fit()

  resizeObserver = new ResizeObserver(() => {
    if (!fitAddon || !terminal) return
    fitAddon.fit()
    if (ws && connected) ws.send(JSON.stringify({ type: 'resize', cols: terminal.cols, rows: terminal.rows }))
  })
  resizeObserver.observe(terminalEl.value)

  terminal.onData((data: string) => {
    if (ws && connected && sshReady) {
      handleLocalInput(data)
      ws.send(JSON.stringify({ type: 'input', data }))
    }
  })

  // 粘贴（用户反馈"敲字太麻烦"）：
  // 1) 放行 Ctrl/Cmd+V 与 Shift+Insert，交给浏览器触发 paste 事件（xterm 默认会吞掉部分组合键）；
  // 2) paste 监听在容器上（见 bindPasteListener），支持"还没连接就粘贴"时给出明确提示。
  terminal.attachCustomKeyEventHandler((event: KeyboardEvent) => {
    if (event.type !== 'keydown') return true
    const key = event.key?.toLowerCase()
    if ((event.ctrlKey || event.metaKey) && (key === 'v' || key === 'insert')) return false
    if (event.shiftKey && key === 'insert') return false
    return true
  })
}

let pasteBound = false

/** 粘贴监听绑在容器上（容器在 v-if 下可能晚于组件出现，所以挂在 watch 里）。
 *
 * 必须用**捕获阶段**并 stopPropagation：xterm 的隐藏 textarea 自己也会处理 paste 并
 * 通过 onData 把原文整块发出去，结果是"原文一次 + 逐行一次"重复下发（实测设备上拼成了
 * `display versiondisplay version`，命令直接失败）。在捕获阶段截住事件，xterm 就收不到。
 */
const bindPasteListener = () => {
  const el = terminalEl.value
  if (!el || pasteBound) return
  el.addEventListener('paste', handlePaste as EventListener, true)
  pasteBound = true
}

watch(terminalEl, (el) => {
  if (!el) {
    // 容器被 v-if 销毁（如首页弹窗 destroy-on-close），下次出现时要重新绑定
    pasteBound = false
    return
  }
  void nextTick(bindPasteListener)
})

const PASTE_LINE_DELAY_MS = 150

/** 逐行下发粘贴内容；每行补 \r 才会被设备执行（只发文字只会被回显，不回车）。 */
const sendPastedText = async (text: string) => {
  const lines = text
    .replace(/\r\n?/g, '\n')
    .split('\n')
    .map((line) => line.replace(/\r/g, '').trim())
    .filter(Boolean)
  if (!lines.length) return
  for (const line of lines) {
    if (!send(`${line}\r`)) return
    // 单行无需等待；多行之间留间隔，等设备把上一行执行完
    if (lines.length > 1) await new Promise((resolve) => { window.setTimeout(resolve, PASTE_LINE_DELAY_MS) })
  }
}

const handlePaste = (event: ClipboardEvent) => {
  const text = event.clipboardData?.getData('text') ?? ''
  if (!text.trim()) return
  event.preventDefault()
  // 捕获阶段截断：避免 xterm 自己再发一遍原文（见 bindPasteListener 注释）
  event.stopPropagation()
  const lineCount = text.replace(/\r\n?/g, '\n').split('\n').filter((line) => line.trim()).length
  if (!ws || !connected || !sshReady) {
    // 未连接时终端可能还没创建，写进 xterm 会看不到；用页面提示通道告知
    emit('error', `SSH 未就绪，粘贴的 ${lineCount} 行未发送（请先点「连接」）`)
    return
  }
  if (lineCount > 1) terminal?.writeln(`\x1b[36m（粘贴 ${lineCount} 行，逐行下发中…）\x1b[0m`)
  void sendPastedText(text)
}

const scheduleReconnect = () => {
  if (manualClose || reconnectTimer !== null) return
  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
    terminal?.writeln('\x1b[33m已停止自动重连。请检查设备连通后点「重新连接」。\x1b[0m')
    emit('reconnectExhausted')
    return
  }
  const delay = Math.min(2000 * Math.pow(2, reconnectAttempts), MAX_RECONNECT_DELAY_MS)
  reconnectAttempts += 1
  terminal?.writeln(`\x1b[33m连接断开，${Math.round(delay / 1000)} 秒后重试（${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS}）...\x1b[0m`)
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null
    connect()
  }, delay)
}

const disconnect = () => {
  manualClose = true
  resetCommandCapture()
  if (reconnectTimer !== null) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  if (ws) ws.close(1000)
  ws = null
  resizeObserver?.disconnect()
  resizeObserver = null
  terminal?.dispose()
  terminal = null
  fitAddon = null
  setReady(false)
  setStatus(false)
}

const connect = async () => {
  if (connected || ws) return
  manualClose = false
  resetCommandCapture()
  await initTerminal()
  const token = localStorage.getItem('token') || ''
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const url = `${protocol}://${window.location.host}/api/v1/ws/ssh/${props.deviceId}`
  const connection = token ? new WebSocket(url, [token]) : new WebSocket(url)
  ws = connection
  let reportedConnectionError = ''

  connection.onopen = () => {
    if (ws !== connection) return
    setStatus(true)
    setReady(false)
    terminal?.writeln('正在连接设备，请稍候...')
  }
  connection.onmessage = (event) => {
    if (ws !== connection) return
    try {
      const message = JSON.parse(event.data)
      if (message.type === 'output') {
        terminal?.write(message.data)
        noteOutput(String(message.data || ''))
        emit('output', message.data)
      } else if (message.type === 'connected') {
        reconnectAttempts = 0
        setReady(true)
        terminal?.writeln(message.message)
        terminal?.writeln('\x1b[32mSSH 已就绪，可以输入命令\x1b[0m')
      } else if (message.type === 'error') {
        setReady(false)
        reportedConnectionError = message.message || '设备未接入或凭据为空'
        terminal?.writeln(`\x1b[31m${reportedConnectionError}\x1b[0m`)
        emit('error', reportedConnectionError)
      }
    } catch {
      terminal?.write(event.data)
      noteOutput(String(event.data || ''))
      emit('output', event.data)
    }
  }
  connection.onclose = (event) => {
    if (ws !== connection) return
    ws = null
    setReady(false)
    setStatus(false)
    // 服务端"拒绝类"关闭码带了明确原因（并发上限 4006 / 设备有写任务 4009 / 认证 4001 等）。
    // 这类断开重连也不会成功，必须把原因显示给用户并停止重连（设计 §16"超过上限需明确提示"）。
    if (REJECT_CLOSE_CODES.has(event.code)) {
      const reason = (event.reason || '').trim() || reportedConnectionError || '连接被服务端拒绝'
      // The server sends an error frame before closing; keep one visible copy of the same reason.
      if (reason !== reportedConnectionError) {
        terminal?.writeln(`\x1b[31m${reason}\x1b[0m`)
        emit('error', reason)
      }
      return
    }
    if (event.code !== 1000) {
      terminal?.writeln('\x1b[33m连接已断开\x1b[0m')
      scheduleReconnect()
    }
  }
  connection.onerror = () => {
    if (ws !== connection) return
    setReady(false)
    setStatus(false)
    terminal?.writeln('\x1b[31m连接错误\x1b[0m')
  }
}

const send = (content: string) => {
  if (!ws || !connected || !sshReady || !content) return false
  ws.send(JSON.stringify({ type: 'input', data: content }))
  const lines = content.split(/\r?\n/).map((line) => line.replace(/\r/g, '').trim()).filter(Boolean)
  for (const line of lines) submitCommand(line)
  return true
}

watch(() => [props.deviceId, props.autoConnect] as const, ([deviceId, shouldConnect], previous) => {
  const previousAuto = previous?.[1]
  if (previous && previous[0] !== deviceId) disconnect()
  if (shouldConnect) connect()
  else if (previousAuto) disconnect()
}, { immediate: true })
onBeforeUnmount(disconnect)
onMounted(() => { void nextTick(bindPasteListener) })
defineExpose({ connect, disconnect, send })
</script>

<style scoped>
.webssh-console { width: 100%; height: 100%; min-height: 0; border-radius: 8px; overflow: hidden; }
</style>
