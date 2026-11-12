import { isAxiosError } from 'axios'
import { ElMessage } from 'element-plus/es/components/message/index'

export function extractErrorMessage(data: unknown, fallback = '请求失败'): string {
  if (!data || typeof data !== 'object') return fallback
  const rec = data as Record<string, unknown>
  if (typeof rec.detail === 'string' && rec.detail.trim()) return rec.detail
  if (rec.detail && typeof rec.detail === 'object' && !Array.isArray(rec.detail)) {
    const detail = rec.detail as Record<string, unknown>
    if (typeof detail.message === 'string' && detail.message.trim()) return detail.message
    if (typeof detail.error === 'string' && detail.error.trim()) return detail.error
  }
  if (Array.isArray(rec.detail) && rec.detail.length) {
    const first = rec.detail[0]
    if (typeof first === 'string' && first.trim()) return first
    if (first && typeof first === 'object') {
      const item = first as Record<string, unknown>
      if (typeof item.msg === 'string' && item.msg.trim()) return item.msg
      if (typeof item.message === 'string' && item.message.trim()) return item.message
    }
  }
  if (typeof rec.message === 'string' && rec.message.trim()) return rec.message
  // 知识库接口在降级时返回 { error: "..." }（见 knowledge/service.py）
  if (typeof rec.error === 'string' && rec.error.trim()) return rec.error
  return fallback
}

/** 取响应体里的可读错误文案；非 axios 错误回落到 Error.message。 */
export function errorResponseMessage(err: unknown, fallback = '请求失败'): string {
  if (isAxiosError(err)) return extractErrorMessage(err.response?.data, fallback)
  if (err instanceof Error && err.message.trim()) return err.message
  return fallback
}

/**
 * 将请求/网络错误归类为用户可读文案（F7 三类文案）：
 * - 无响应（网络/后端未启动） → "后端服务未启动"
 * - 空列表场景由各视图自行提示"暂无设备，请先导入拓扑基线"
 * - 设备侧连接失败 → "设备未接入或凭据为空"
 */
export function requestErrorMessage(err: unknown, fallback = '请求失败'): string {
  if (isAxiosError(err)) {
    if (!err.response) {
      return err.code === 'ECONNABORTED' ? '请求超时，请稍后重试' : '无法连接后端服务，请检查连接后重试'
    }
    const fromBody = extractErrorMessage(err.response.data, '')
    if (fromBody) return fromBody
    if (err.response.status === 401) return '登录已过期，请重新登录'
    if (err.response.status === 403) return '权限不足，请联系管理员'
    return fallback
  }
  return fallback
}

/** 拦截器已对 Axios 错误弹过 Toast 时，页面不要再弹一遍。 */
export function isInterceptedRequestError(err: unknown): boolean {
  // 拦截器只对"非 silent"的 axios 错误弹 Toast；silent 请求由调用方自己提示
  return isAxiosError(err) && !(err.config as { silent?: boolean } | undefined)?.silent
}

/**
 * 页面 catch 里统一用这个替代裸 `ElMessage.error(...)`。
 *
 * 背景（2026-09-09 审计 P1-45）：拦截器已经对非 silent 错误弹过一次 Toast，
 * 页面再弹一次会出现两条互相矛盾的提示（如"后端服务未启动" + "下发失败"）。
 */
export function notifyRequestError(err: unknown, fallback = '操作失败'): void {
  if (isInterceptedRequestError(err)) return
  ElMessage.error(requestErrorMessage(err, fallback))
}
