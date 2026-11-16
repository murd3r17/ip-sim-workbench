import axios from 'axios'
import { ElMessage } from 'element-plus/es/components/message/index'
import { extractErrorMessage } from '../utils/requestError'
import {
  browserSessionHeaders, browserSessionRevision, expireBrowserSession, hydrateBrowserSession,
} from '../stores/browserSession'

declare module 'axios' {
  export interface AxiosRequestConfig {
    silent?: boolean
    sessionRevision?: number
  }
}

const request = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
})

// 请求拦截器
request.interceptors.request.use(
  (config) => {
    config.sessionRevision = browserSessionRevision()
    const mutating = !['get', 'head', 'options'].includes(config.method || 'get')
    for (const [key, value] of Object.entries(browserSessionHeaders(mutating))) {
      config.headers.set(key, value)
    }
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截器：通用错误由这里弹 Toast；页面只在需要定制文案时再提示。
request.interceptors.response.use(
  (response) => {
    if (response.config.sessionRevision !== browserSessionRevision()) {
      return Promise.reject(new Error('登录状态已变化，请重新打开当前操作。'))
    }
    return response.data
  },
  (error) => {
    const status = error.response?.status
    const silent = Boolean(error.config?.silent)
    const message = extractErrorMessage(error.response?.data, '请求失败')
    const observedRevision = error.config?.sessionRevision
    if (observedRevision !== browserSessionRevision()) return Promise.reject(error)

    if (status === 401) {
      const onLogin = window.location.pathname.startsWith('/login')
      if (onLogin) {
        if (!silent) ElMessage.error(message === '请求失败' ? '用户名或密码错误' : message)
      } else {
        expireBrowserSession(observedRevision)
      }
    } else {
      if (status === 403 && window.location.pathname !== '/login') void hydrateBrowserSession(true).catch(() => {})
      if (silent) return Promise.reject(error)
      // grouping：后端不可用时多个并发请求会各弹一条相同文案，合并成一条 + 计数
      if (status === 403) {
        ElMessage.error({ message: message || '权限不足，请联系管理员', grouping: true })
      } else if (!error.response) {
        ElMessage.error({
          message: error.code === 'ECONNABORTED' ? '请求超时，请稍后重试' : '无法连接后端服务，请检查连接后重试',
          grouping: true,
        })
      } else {
        ElMessage.error({ message, grouping: true })
      }
    }

    return Promise.reject(error)
  }
)

export default request
