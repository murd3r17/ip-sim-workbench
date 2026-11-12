/**
 * V7-A A-07：统一 API 时间解析。
 *
 * 后端历史列不保存时区，读回来的 ISO 字符串没有偏移；`new Date("...")`
 * 会按浏览器本地时区解析，导致同一事件偏 8 小时（UX-09）。
 * 这里把“无偏移”的字符串按 UTC 解释，带偏移/Z 的原样交给 Date。
 */
export function parseApiTime(value?: string | null): Date | null {
  if (!value) return null
  const text = String(value)
  const normalized = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(text) ? text : `${text}Z`
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatApiTime(
  value?: string | null,
  options: Intl.DateTimeFormatOptions = {},
): string {
  const date = parseApiTime(value)
  if (!date) return '-'
  return date.toLocaleString('zh-CN', { hour12: false, ...options })
}
