import request from './request'

export const login = (data: { username: string; password: string }) =>
  request.post('/auth/login', data)

export const getMe = () => request.get('/auth/me')

export const changePassword = (data: { old_password: string; new_password: string }) =>
  request.put('/auth/password', data)

export interface Account {
  id: number
  username: string
  display_name?: string
  role: 'user' | 'admin'
  is_active: boolean
  last_login_at?: string | null
}

export const listAccounts = (params: { q: string; offset: number }) =>
  request.get<Account[], Account[]>('/auth/users', { params, silent: true })

export const createAccount = (data: { username: string; display_name: string; password: string; role: Account['role'] }) =>
  request.post<Account, Account>('/auth/users', data, { silent: true })

export const resetTraineePassword = (accountId: number, newPassword: string) =>
  request.put(`/auth/users/${accountId}/password`, { new_password: newPassword }, { silent: true })
