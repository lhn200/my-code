import { request } from './client'
import type { TokenResponse, User } from './types'

export interface Credentials {
  email: string
  password: string
}

export function register(payload: Credentials): Promise<User> {
  return request<User>('/auth/register', { method: 'POST', body: payload })
}

export function login(payload: Credentials): Promise<TokenResponse> {
  return request<TokenResponse>('/auth/login', { method: 'POST', body: payload })
}

export function logout(): Promise<void> {
  return request<void>('/auth/logout', { method: 'POST' })
}

export function me(options: { signal?: AbortSignal } = {}): Promise<User> {
  return request<User>('/auth/me', { signal: options.signal })
}
