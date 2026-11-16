import { useAiCopilotStore } from '../stores/aiCopilot'
import { useLabContextStore } from '../stores/labContext'
import { clearSavedDeployDraft, currentDraftOwner, useWorkbenchDraftsStore } from '../stores/workbenchDrafts'

const PREFIXES = ['lab_ctx_', 'ai_copilot_', 'deploy_ai_draft']

export function clearLocalAuth() {
  const toRemove: string[] = ['token', 'user']
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i)
    if (key && PREFIXES.some((prefix) => key.startsWith(prefix))) toRemove.push(key)
  }
  for (const key of toRemove) localStorage.removeItem(key)
}

export function clearClientSession(reason: 'expired' | 'logout' = 'expired') {
  if (reason === 'logout') clearSavedDeployDraft(currentDraftOwner())
  clearLocalAuth()
  try {
    useLabContextStore().clearAll()
    useWorkbenchDraftsStore().$reset()
  } catch {
    /* pinia 未就绪时只清 localStorage */
  }
  try {
    useAiCopilotStore().resetSession()
  } catch {
    /* ignore */
  }
}

export function loginRedirectTarget(raw: unknown): string {
  if (typeof raw !== 'string' || !raw.startsWith('/') || raw.startsWith('//') || raw.startsWith('/\\')) {
    return '/'
  }
  if (raw.startsWith('/login')) return '/'
  return raw
}
