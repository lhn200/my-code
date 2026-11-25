import { request } from './client'
import type { SessionItem, SessionListResponse } from './types'

export interface SessionListParams {
  page?: number
  page_size?: number
  q?: string
  trashed?: boolean
}

export function listSessions(
  params: SessionListParams = {},
  options: { signal?: AbortSignal } = {},
): Promise<SessionListResponse> {
  const query = new URLSearchParams()
  query.set('page', String(params.page ?? 1))
  query.set('page_size', String(params.page_size ?? 20))
  if (params.q && params.q.trim()) {
    query.set('q', params.q.trim())
  }
  query.set('trashed', String(params.trashed ?? false))
  return request<SessionListResponse>(`/sessions?${query.toString()}`, {
    signal: options.signal,
  })
}

export function renameSession(threadId: string, title: string): Promise<SessionItem> {
  return request<SessionItem>(`/sessions/${encodeURIComponent(threadId)}`, {
    method: 'PATCH',
    body: { title },
  })
}

export function deleteSession(threadId: string): Promise<void> {
  return request<void>(`/sessions/${encodeURIComponent(threadId)}`, { method: 'DELETE' })
}

export function restoreSession(threadId: string): Promise<SessionItem> {
  return request<SessionItem>(`/sessions/${encodeURIComponent(threadId)}/restore`, {
    method: 'POST',
  })
}

export function purgeSession(threadId: string): Promise<void> {
  return request<void>(`/sessions/${encodeURIComponent(threadId)}/purge`, {
    method: 'DELETE',
  })
}
