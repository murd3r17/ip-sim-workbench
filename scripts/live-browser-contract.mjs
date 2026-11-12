// Pure report assertions. Never return model text or authentication material.
import crypto from 'node:crypto'

export const digest = value => crypto.createHash('sha256').update(String(value)).digest('hex')
const fallback = /当前AI服务不可用|当前知识库不可用|生成失败|请求失败|连接中断|暂无回答|已停止生成|回答未完成/
export const goodAnswer = value => typeof value === 'string' && value.trim().length > 0 && !fallback.test(value)

export function parseSse(text) {
  return text.split(/\r?\n/).filter(line => line.startsWith('data:')).map(line => line.slice(5).trim())
    .filter(value => value && value !== '[DONE]').map(value => {
      const event = JSON.parse(value)
      if (!event || typeof event !== 'object' || Array.isArray(event)) throw new Error('invalid_sse_event')
      return event
    })
}

export function streamEvidence(events, marker, answer = '95') {
  const text = events.filter(e => e.type === 'token').map(e => e.text || '').join('')
  const done = events.flatMap((e, i) => e.type === 'done' ? [i] : [])
  const terminal = done.length === 1 && done[0] === events.length - 1 && events.at(-1)?.status === 'ok'
  const failed = events.some(e => e.type === 'error' || ['error', 'failed', 'degraded'].includes(e.status))
  const tools = events.filter(e => e.type === 'tool').length
  const ok = terminal && !failed && tools === 0 && goodAnswer(text) && text.includes(marker) && text.includes(answer)
  return { ok, content_characters: text.length, terminal_ok: terminal, fallback_used: !goodAnswer(text),
    tool_events: tools, response_sha256: digest(text), marker_matched: text.includes(marker), answer_matched: text.includes(answer) }
}

export function sameRuntime(expected, actual) {
  return ['schema', 'database_fingerprint', 'root_fingerprint', 'device_mode', 'deploy_simulate_only', 'knowledge_provider']
    .every(key => key in expected && key in (actual || {}) && expected[key] === actual[key])
}

export function sameBinding(start, finish) {
  return sameRuntime(start, finish) && start.source_fingerprint === finish.source_fingerprint
}

export function aiLogEvidence(rows, { cursor, marker, model, responseMarker = marker }) {
  const row = rows.find(row => row.id > cursor && row.request_type === 'copilot_chat' && row.model_used === model
    && String(row.prompt || '').includes(marker) && goodAnswer(row.response) && String(row.response).includes(responseMarker))
  return row ? { ai_log_id: row.id, model_used: row.model_used, latency_ms: row.latency_ms } : null
}
