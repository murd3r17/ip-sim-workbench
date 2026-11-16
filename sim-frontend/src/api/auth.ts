import request from './request'
import type { BrowserSession } from '../stores/browserSession'

export const login = (data: { username: string; password: string }) =>
  request.post<BrowserSession, BrowserSession>('/auth/session', data, { headers: { 'X-Workbench-Login': '1' } })
export const logout = () => request.delete('/auth/session')

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

export interface TerminalGrant {
  grant_id: string
  device_id: number
  management_address: string
  ssh_port: number
  expires_at: string
  revoked_at: string | null
  note: string
}

export const listTerminalGrants = (userId: number) =>
  request.get<TerminalGrant[], TerminalGrant[]>(`/auth/users/${userId}/terminal-grants`, { silent: true })
export const issueTerminalGrant = (userId: number, deviceId: number, minutes: number, note: string) =>
  request.put(`/auth/users/${userId}/terminal-grants/${deviceId}`, { minutes, note }, { silent: true })
export const revokeTerminalGrant = (userId: number, grant: TerminalGrant) =>
  request.delete(`/auth/users/${userId}/terminal-grants/${grant.device_id}`, {
    params: { grant_id: grant.grant_id }, silent: true,
  })

export interface TerminalAccess { allowed: boolean; mode: 'sim' | 'ssh'; reason?: string }
export const getTerminalAccess = (deviceId: number) =>
  request.get<TerminalAccess, TerminalAccess>(`/webssh/access/${deviceId}`, { silent: true })
