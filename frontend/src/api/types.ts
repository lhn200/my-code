/** 与后端 AgentState / RunResult 契约对齐的手写类型。 */

export type RunStatus = 'succeeded' | 'partial' | 'failed'
export type JobStatus = 'ok' | 'failed'
export type ResumeSource = 'baseline' | 'variant'

export interface FieldError {
  field: string
  type: string
  message: string
}

export interface RunJobInput {
  job_id?: string
  title: string
  original_position_text: string
}

export interface RunRequest {
  goal: string
  resume_text: string
  jobs: RunJobInput[]
}

export interface JobProfile {
  job_id: string
  title: string
  company: string
  must_have: string[]
  nice_to_have: string[]
  responsibilities: string[]
  keywords: string[]
  status: JobStatus
  error: string | null
}

export interface ReviewResult {
  job_id: string
  variant_version: number
  score: number
  dimensions: Record<string, number>
  matched: string[]
  missing: string[]
  issues: string[]
  status: JobStatus
  error: string | null
}

export interface ResumeVariant {
  job_id: string
  variant_version: number
  text: string
  base_version: number
}

export interface OptimizationRound {
  job_id: string
  round: number
  variant_version: number
  score_before: number
  score_after: number | null
  summary: string
}

export interface InterviewReportSummary {
  job_id: string
  interview_thread_id: string
  status: 'completed' | 'abandoned'
  generated_at: string
  dimension_averages: Record<string, number>
  overall_score: number | null
  highlights: string[]
  red_flags: string[]
  improvements: string[]
  requirement_gaps: string[]
  answered_count: number
  planned_count: number
}

export interface JobResult {
  job_id: string
  title: string
  status: JobStatus
  error: string | null
  profile: JobProfile | null
  resume_source: ResumeSource
  current_variant_version: number
  resume_text: string
  review: ReviewResult | null
  variants: ResumeVariant[]
  optimization_history: OptimizationRound[]
}

export interface RunResult {
  run_status: RunStatus
  thread_id: string
  advice: string
  jobs: JobResult[]
  interview_reports: Record<string, InterviewReportSummary>
}

export interface RunErrorEntry {
  stage?: string
  job_id?: string
  message?: string
}

export interface RunState {
  goal?: string
  resume_text?: string
  jobs?: RunJobInput[]
  threshold?: number
  max_rounds?: number
  advice?: string
  errors?: RunErrorEntry[]
  [key: string]: unknown
}

/** GET /api/runs/{thread_id} 与快照读取的响应。 */
export interface RunStatePayload {
  thread_id: string
  next: string[]
  state: RunState
  result: RunResult
}

export interface SnapshotSummary {
  checkpoint_id: string
  created_at: string
  step: number
  next: string[]
}

export interface SnapshotListResponse {
  thread_id: string
  snapshots: SnapshotSummary[]
}

export interface ResumeUploadResponse {
  file_id: string
  file_url: string | null
  source_type: 'pdf' | 'docx' | 'image' | string
  page_count: number
  /** 兼容字段；后端当前返回 page_count。 */
  pages?: number
  used_ocr: boolean
  char_count: number
  low_confidence: boolean
  text: string
}

export interface User {
  id: string
  email: string
  created_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
}

export interface SessionItem {
  thread_id: string
  title: string
  status: string
  created_at: string
  updated_at: string
  deleted_at: string | null
}

export interface SessionListResponse {
  items: SessionItem[]
  total: number
  page: number
  page_size: number
}
