export function retireLegacyLoginStorage() {
  try {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
  } catch { /* storage unavailable */ }
}

export function loginRedirectTarget(raw: unknown): string {
  if (typeof raw !== 'string' || !raw.startsWith('/') || raw.startsWith('//') || raw.startsWith('/\\')) {
    return '/'
  }
  const target = new URL(raw, window.location.origin)
  if (target.origin !== window.location.origin || target.pathname === '/login') return '/'
  return target.pathname + target.search + target.hash
}
