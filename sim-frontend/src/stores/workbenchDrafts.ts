import { defineStore } from 'pinia'
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

// Keep unsent work within the signed-in tab without writing it to browser storage.
export const useWorkbenchDraftsStore = defineStore('workbenchDrafts', {
  state: () => ({
    deploy: emptyDeployDraft(),
    training: {} as Partial<Record<number, TrainingWorkspaceDraft>>,
  }),
})
