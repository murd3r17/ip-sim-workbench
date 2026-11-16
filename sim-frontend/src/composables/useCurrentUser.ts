import { computed } from 'vue'
import { browserSession } from '../stores/browserSession'

export function useCurrentUser() {
  const user = computed(() => browserSession.value?.user || null)
  const isAdmin = computed(() => user.value?.role === 'admin')
  return { user, isAdmin }
}
