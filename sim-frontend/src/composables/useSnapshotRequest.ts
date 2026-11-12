import { getCurrentScope, onScopeDispose, ref } from 'vue'

/** Keep the last successful snapshot; only the newest live request may apply. */
export function useSnapshotRequest(label: string) {
  const loading = ref(false)
  const error = ref('')
  let epoch = 0
  let disposed = false
  if (getCurrentScope()) onScopeDispose(() => { disposed = true; epoch++ })
  async function run<T>(load: () => Promise<T>, apply: (value: T) => void): Promise<boolean> {
    const request = ++epoch
    if (disposed) return false
    loading.value = true
    try {
      const value = await load()
      if (disposed || request !== epoch) return false
      apply(value)
      error.value = ''
      return true
    } catch {
      if (!disposed && request === epoch) error.value = `${label}读取失败，暂时无法确认最新数据；已显示内容可能陈旧，请重试。`
      return false
    } finally {
      if (!disposed && request === epoch) loading.value = false
    }
  }
  return { loading, error, run }
}
