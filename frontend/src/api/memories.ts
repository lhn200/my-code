import { request } from './client'

export type MemoryKind = 'preference' | 'goal' | 'fact' | 'constraint'
export type MemoryStatus = 'active' | 'pending_confirmation' | 'archived'

export interface MemoryItem {
  id: string
  kind: MemoryKind
  content: string
  confidence: number
  status: MemoryStatus
  source_thread_id: string | null
  source_type: string | null
  created_at: string
  updated_at: string
  expires_at: string | null
  archived_reason: string | null
}

export interface MemorySettings {
  enabled: boolean
  updated_at: string | null
}

export interface MemoryListParams {
  kind?: MemoryKind
  status?: MemoryStatus
  q?: string
  limit?: number
}

export interface MemoryListResponse {
  items: MemoryItem[]
  total: number
}

export interface MemoryUpdate {
  content?: string
  kind?: MemoryKind
  status?: 'active' | 'archived'
}

export interface SessionSummaryBody {
  facts: string[]
  open_questions: string[]
  preferences: string[]
  constraints: string[]
  decisions: string[]
}

export interface SessionSummaryResponse {
  thread_id: string
  summarized: boolean
  version: number
  updated_at: string | null
  summarized_through_turn: number
  summary_status: 'idle' | 'ok' | 'failed' | string
  summary: SessionSummaryBody | null
}

export interface SessionSummaryRegenerateResponse extends SessionSummaryResponse {
  regenerated: boolean
}

export function listMemories(
  params: MemoryListParams = {},
  options: { signal?: AbortSignal } = {},
): Promise<MemoryListResponse> {
  const query = new URLSearchParams()
  if (params.kind) {
    query.set('kind', params.kind)
  }
  if (params.status) {
    query.set('status', params.status)
  }
  if (params.q && params.q.trim()) {
    query.set('q', params.q.trim())
  }
  query.set('limit', String(params.limit ?? 50))
  return request<MemoryListResponse>(`/memories?${query.toString()}`, {
    signal: options.signal,
  })
}

export function fetchMemorySettings(
  options: { signal?: AbortSignal } = {},
): Promise<MemorySettings> {
  return request<MemorySettings>('/memories/settings', { signal: options.signal })
}

export function updateMemorySettings(enabled: boolean): Promise<MemorySettings> {
  return request<MemorySettings>('/memories/settings', {
    method: 'PUT',
    body: { enabled },
  })
}

export function updateMemory(id: string, patch: MemoryUpdate): Promise<MemoryItem> {
  return request<MemoryItem>(`/memories/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: patch,
  })
}

export function deleteMemory(id: string): Promise<void> {
  return request<void>(`/memories/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export function clearMemories(): Promise<{ deleted: number }> {
  return request<{ deleted: number }>('/memories', { method: 'DELETE' })
}

export function fetchSessionSummary(
  threadId: string,
  options: { signal?: AbortSignal } = {},
): Promise<SessionSummaryResponse> {
  return request<SessionSummaryResponse>(
    `/sessions/${encodeURIComponent(threadId)}/summary`,
    { signal: options.signal },
  )
}

export function regenerateSessionSummary(
  threadId: string,
  expectedVersion: number | null,
  options: { signal?: AbortSignal } = {},
): Promise<SessionSummaryRegenerateResponse> {
  return request<SessionSummaryRegenerateResponse>(
    `/sessions/${encodeURIComponent(threadId)}/summary/regenerate`,
    {
      method: 'POST',
      body: { expected_version: expectedVersion },
      signal: options.signal,
    },
  )
}
