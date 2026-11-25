import { request } from './client'
import type { ResumeUploadResponse } from './types'

export function uploadResume(
  file: File,
  options: { signal?: AbortSignal; timeoutMs?: number } = {},
): Promise<ResumeUploadResponse> {
  const form = new FormData()
  form.append('file', file)
  return request<ResumeUploadResponse>('/resumes', {
    method: 'POST',
    body: form,
    signal: options.signal,
    timeoutMs: options.timeoutMs ?? 120_000,
  })
}
