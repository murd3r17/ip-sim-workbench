import { defineStore } from 'pinia'
import { browserSession } from './browserSession'
import type { ConfigValidateResult } from '../api/deploy'

export interface TrainingWorkspaceDraft {
  revision: number
  notes: string
  steps: Record<string, unknown>[]
}

export function emptyDeployDraft() {
  return {
    form: { name: '', device_ids: [] as number[], engine: 'netmiko', config_content: '' },
    intent: '',
    submitting: false,
    submitError: '',
    validation: null as { config: string; model: string; targets: string; result: ConfigValidateResult } | null,
  }
}

export type DeployDraft = ReturnType<typeof emptyDeployDraft>
export type SavedDeployDraft = Pick<DeployDraft, 'form' | 'intent'> & { savedAt: number }

const DEPLOY_DRAFT_LIFETIME_MS = 2 * 60 * 60 * 1000
const CREDENTIAL_TEXT = /\b(?:password|passwd|secret|shared[-_]key|pre[-_]shared[-_]key|key|string-secret|community(?:-name)?|authentication[-_]key|authentication-mode|privacy-mode|api[-_ ]?key|authorization|bearer|access[-_]token|refresh[-_]token)\b|\bsk-[\w-]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|口令|密码|密钥/i

export function currentDraftOwner(): string | null {
  const user = browserSession.value?.user
  return user ? `${user.id}:${user.username}` : null
}

function draftStorageKey(owner: string) {
  return `workbench:deploy-draft:${owner}`
}

export function clearSavedDeployDraft(owner: string | null) {
  if (!owner) return
  try { sessionStorage.removeItem(draftStorageKey(owner)) } catch { /* storage unavailable */ }
}

export function readSavedDeployDraft(owner: string | null): SavedDeployDraft | null {
  if (!owner || owner !== currentDraftOwner()) return null
  try {
    const saved = JSON.parse(sessionStorage.getItem(draftStorageKey(owner)) || 'null') as SavedDeployDraft | null
    if (!saved) return null
    const age = Date.now() - saved.savedAt
    if (Number.isFinite(age) && age >= 0 && age < DEPLOY_DRAFT_LIFETIME_MS &&
      typeof saved.intent === 'string' && typeof saved.form?.name === 'string' &&
      typeof saved.form.config_content === 'string' && typeof saved.form.engine === 'string' &&
      Array.isArray(saved.form.device_ids) && saved.form.device_ids.every(id => Number.isSafeInteger(id) && id > 0)) {
      return saved
    }
  } catch { /* invalid or unavailable storage */ }
  clearSavedDeployDraft(owner)
  return null
}

export function saveDeployDraft(owner: string | null, draft: DeployDraft): SavedDeployDraft {
  if (!owner || owner !== currentDraftOwner()) throw new Error('登录状态已变化，暂时无法保存此草稿。')
  const inputs = [draft.form.name, draft.form.config_content, draft.intent]
  if (inputs.some(value => CREDENTIAL_TEXT.test(value))) {
    throw new Error('草稿可能含口令、密钥或认证配置。移除相关内容后可暂存，其余内容仍在当前编辑区。')
  }
  const saved = { form: { ...draft.form, device_ids: [...draft.form.device_ids] }, intent: draft.intent, savedAt: Date.now() }
  sessionStorage.setItem(draftStorageKey(owner), JSON.stringify(saved))
  return saved
}

export function deployDraftMatches(draft: Pick<DeployDraft, 'form' | 'intent'>, saved: SavedDeployDraft | null): boolean {
  return saved !== null && saved.intent === draft.intent && JSON.stringify(saved.form) === JSON.stringify(draft.form)
}

// In-progress validation and submission state stays in memory.
export const useWorkbenchDraftsStore = defineStore('workbenchDrafts', {
  state: () => ({
    deploy: emptyDeployDraft(),
    training: {} as Partial<Record<number, TrainingWorkspaceDraft>>,
  }),
})
