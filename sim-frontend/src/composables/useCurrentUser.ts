import { computed } from 'vue'

export function useCurrentUser() {
  const user = computed(() => {
    try {
      return JSON.parse(localStorage.getItem('user') || 'null') as { username?: string; role?: string } | null
    } catch {
      return null
    }
  })
  const isAdmin = computed(() => user.value?.role === 'admin')
  return { user, isAdmin }
}
