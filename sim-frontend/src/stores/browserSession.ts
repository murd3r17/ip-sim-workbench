import { readonly, shallowRef } from 'vue'
import type { Account } from '../api/auth'

export interface BrowserSession {
  user: Account
  session_id: string
  csrf_token: string
}

const identity = shallowRef<BrowserSession | null>(null)
export const browserSession = readonly(identity)
let revision = 0
let hydration: Promise<BrowserSession | null> | null = null
export const SESSION_CHANGE_KEY = 'workbench:session-changed'

export function acceptBrowserSession(value: BrowserSession | null) {
  if (value && (!value.session_id || !value.csrf_token || !value.user?.id || !value.user?.username)) {
    throw new Error('登录响应不完整，请联系管理员检查后端版本。')
  }
  if (identity.value?.session_id !== value?.session_id) revision++
  identity.value = value
}

export function browserSessionRevision() {
  return revision
}

export function browserSessionHeaders(mutating = false): Record<string, string> {
  const session = identity.value
  if (!session) return {}
  return {
    'X-Workbench-Session': session.session_id,
    ...(mutating ? { 'X-Workbench-CSRF': session.csrf_token } : {}),
  }
}

export function accountStorageKey(key: string): string {
  const owner = identity.value?.user
  if (!owner) throw new Error('需要登录才能读取本机工作记录。')
  return `workbench:${owner.id}:${owner.username}:${key}`
}

export function publishSessionChange() {
  try { localStorage.setItem(SESSION_CHANGE_KEY, String(Date.now()) + Math.random()) } catch { /* storage unavailable */ }
}

export function expireBrowserSession(expectedRevision: number) {
  if (expectedRevision !== revision || window.location.pathname === '/login') return
  acceptBrowserSession(null)
  const url = new URL('/login', window.location.origin)
  url.searchParams.set('expired', '1')
  url.searchParams.set('redirect', window.location.pathname + window.location.search + window.location.hash)
  window.location.replace(url)
}

export async function hydrateBrowserSession(force = false): Promise<BrowserSession | null> {
  if (identity.value && !force) return identity.value
  if (hydration) return hydration
  const observedRevision = revision
  hydration = (async () => {
    const result = await fetch('/api/v1/auth/session', { credentials: 'same-origin', cache: 'no-store' })
    if (observedRevision !== revision) return identity.value
    if (result.status === 401) {
      if (identity.value) expireBrowserSession(observedRevision)
      return null
    }
    if (!result.ok) throw new Error('无法核对登录状态')
    const value = await result.json() as BrowserSession
    if (observedRevision !== revision) return identity.value
    if (identity.value && identity.value.session_id !== value.session_id) {
      acceptBrowserSession(null)
      window.location.reload()
      return null
    }
    acceptBrowserSession(value)
    return value
  })()
  try {
    return await hydration
  } finally {
    hydration = null
  }
}

export async function sessionFetch(url: string, options: RequestInit = {}) {
  const observedRevision = revision
  const method = options.method?.toUpperCase() || 'GET'
  const headers = new Headers(options.headers)
  for (const [key, value] of Object.entries(browserSessionHeaders(!['GET', 'HEAD', 'OPTIONS'].includes(method)))) {
    headers.set(key, value)
  }
  const response = await fetch(url, { ...options, headers, credentials: 'same-origin' })
  if (response.status === 401) expireBrowserSession(observedRevision)
  if (observedRevision !== revision) throw new Error('登录状态已变化，请重新打开当前操作。')
  return response
}
