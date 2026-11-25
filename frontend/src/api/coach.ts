import { request } from './client'
import type { CoachSessionListResponse, CoachSessionPayload } from './types'

export function createCoachSession(input: {
  thread_id?: string | null
  title?: string
}): Promise<CoachSessionPayload> {
  return request<CoachSessionPayload>('/coach/sessions', {
    method: 'POST',
    body: input,
  })
}

export function listCoachSessions(threadId?: string | null): Promise<CoachSessionListResponse> {
  const query = threadId ? `?thread_id=${encodeURIComponent(threadId)}` : ''
  return request<CoachSessionListResponse>(`/coach/sessions${query}`)
}

export function getCoachSession(sessionId: string): Promise<CoachSessionPayload> {
  return request<CoachSessionPayload>(`/coach/sessions/${encodeURIComponent(sessionId)}`)
}

export function updateCoachSession(
  sessionId: string,
  patch: { title?: string; thread_id?: string | null },
): Promise<CoachSessionPayload> {
  return request<CoachSessionPayload>(`/coach/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'PATCH',
    body: patch,
  })
}

export function deleteCoachSession(sessionId: string): Promise<void> {
  return request<void>(`/coach/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  })
}

export function sendCoachMessage(
  sessionId: string,
  content: string,
): Promise<CoachSessionPayload> {
  return request<CoachSessionPayload>(
    `/coach/sessions/${encodeURIComponent(sessionId)}/messages`,
    { method: 'POST', body: { content } },
  )
}
