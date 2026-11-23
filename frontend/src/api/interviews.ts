import { request } from './client'
import type {
  InterviewSessionListResponse,
  InterviewSessionPayload,
} from './types'

export function createInterviewSession(input: {
  thread_id: string
  job_id: string
}): Promise<InterviewSessionPayload> {
  return request<InterviewSessionPayload>('/interviews', {
    method: 'POST',
    body: input,
  })
}

export function getInterviewSession(sessionId: string): Promise<InterviewSessionPayload> {
  return request<InterviewSessionPayload>(`/interviews/${encodeURIComponent(sessionId)}`)
}

export function listInterviewSessions(
  threadId: string,
): Promise<InterviewSessionListResponse> {
  return request<InterviewSessionListResponse>(
    `/interviews?thread_id=${encodeURIComponent(threadId)}`,
  )
}

export function submitInterviewAnswer(
  sessionId: string,
  answer: string,
): Promise<InterviewSessionPayload> {
  return request<InterviewSessionPayload>(
    `/interviews/${encodeURIComponent(sessionId)}/answers`,
    { method: 'POST', body: { answer } },
  )
}

export function finishInterviewSession(
  sessionId: string,
): Promise<InterviewSessionPayload> {
  return request<InterviewSessionPayload>(
    `/interviews/${encodeURIComponent(sessionId)}/finish`,
    { method: 'POST' },
  )
}
