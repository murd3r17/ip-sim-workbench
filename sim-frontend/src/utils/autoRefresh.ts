/**
 * 页面数据自动刷新：定时轮询 + 页面回到可见时立即刷新。
 * 用于设备状态、总览、告警、任务等展示的"及时性"（如设备上线/下线、任务流转）。
 * 内部处理：in-flight 防请求堆叠、onUnmounted 自动清理。
 *
 * 注意：调用方经常在 onMounted 回调里调用本函数。此时 mounted 队列已在 flush，
 * 再注册 onMounted 不会执行，所以定时器必须立即启动，只把清理挂到 onUnmounted。
 */
import { getCurrentInstance, onUnmounted } from 'vue'

export function useAutoRefresh(fn: () => Promise<unknown> | void, intervalMs = 15000) {
  let timer = 0
  let inFlight = false
  let disposed = false

  const run = async () => {
    if (inFlight || disposed) return
    inFlight = true
    try {
      await fn()
    } catch {
      /* 轮询失败静默，等待下一轮 */
    } finally {
      inFlight = false
    }
  }

  const onVisible = () => {
    if (document.visibilityState === 'visible') run()
  }

  timer = window.setInterval(run, intervalMs)
  document.addEventListener('visibilitychange', onVisible)

  const stop = () => {
    if (disposed) return
    disposed = true
    window.clearInterval(timer)
    document.removeEventListener('visibilitychange', onVisible)
  }

  if (getCurrentInstance()) {
    onUnmounted(stop)
  }
  return stop
}
