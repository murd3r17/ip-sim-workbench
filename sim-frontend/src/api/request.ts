import axios from 'axios'
import { ElMessage } from 'element-plus/es/components/message/index'
import { extractErrorMessage } from '../utils/requestError'
import { clearClientSession } from '../utils/session'

declare module 'axios' {
  export interface AxiosRequestConfig {
    silent?: boolean
  }
}

const request = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
})

// 请求拦截器
request.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

function currentRedirectPath() {
  const path = `${window.location.pathname}${window.location.search}`
  if (!path || path.startsWith('/login')) return ''
  return path
}

// 响应拦截器：通用错误由这里弹 Toast；页面只在需要定制文案时再提示。
request.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const status = error.response?.status
    const silent = Boolean(error.config?.silent)
    const message = extractErrorMessage(error.response?.data, '请求失败')

    if (status === 401) {
      const onLogin = window.location.pathname.startsWith('/login')
      clearClientSession()
      if (onLogin) {
        if (!silent) ElMessage.error(message === '请求失败' ? '用户名或密码错误' : message)
      } else {
        const redirect = currentRedirectPath()
        // 带上 expired=1：登录页会提示"登录已过期"，否则用户只看到被整页刷回登录页
        const query = new URLSearchParams({ expired: '1' })
        if (redirect) query.set('redirect', redirect)
        window.location.href = `/login?${query.toString()}`
      }
    } else if (!silent) {
      // grouping：后端不可用时多个并发请求会各弹一条相同文案，合并成一条 + 计数
      if (status === 403) {
        ElMessage.error({ message: '权限不足，请联系管理员', grouping: true })
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
