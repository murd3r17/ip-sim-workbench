import request from './request'

export const login = (data: { username: string; password: string }) =>
  request.post('/auth/login', data)

export const getMe = () => request.get('/auth/me')

export const changePassword = (data: { old_password: string; new_password: string }) =>
  request.put('/auth/password', data)
