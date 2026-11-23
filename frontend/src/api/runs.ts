import { request } from './client'
import type {
  RunStatePayload,
  RunRequest,
  RunResult,
  SnapshotListResponse,
} from './types'

export interface RunOptions {
  signal?: AbortSignal
  timeoutMs?: number
}

export function createRun(payload: RunRequest, options: RunOptions = {}): Promise<RunResult> {
  return request<RunResult>('/runs', {
    method: 'POST',
    body: payload,
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  })
}

export function resumeRun(threadId: string, options: RunOptions = {}): Promise<RunResult> {
  return request<RunResult>(`/runs/${encodeURIComponent(threadId)}/resume`, {
    method: 'POST',
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  })
}

export function getRun(threadId: string, options: RunOptions = {}): Promise<RunStatePayload> {
  return request<RunStatePayload>(`/runs/${encodeURIComponent(threadId)}`, {
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  })
}

export function listSnapshots(
  threadId: string,
  options: RunOptions = {},
): Promise<SnapshotListResponse> {
  return request<SnapshotListResponse>(`/runs/${encodeURIComponent(threadId)}/snapshots`, {
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  })
}

export function getSnapshot(
  threadId: string,
  checkpointId: string,
  options: RunOptions = {},
): Promise<RunStatePayload> {
  const base = `/runs/${encodeURIComponent(threadId)}/snapshots/${encodeURIComponent(checkpointId)}`
  return request<RunStatePayload>(base, {
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  })
}
