import { getToken } from '../auth/token'
import type { FieldError } from './types'

export type ApiErrorKind = 'http' | 'network' | 'timeout' | 'invalid_response' | 'canceled'

export interface ApiErrorOptions {
  status?: number
  code: string
  message: string
  fields?: FieldError[]
  threadId?: string
  kind?: ApiErrorKind
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly fields: FieldError[]
  readonly threadId?: string
  readonly kind: ApiErrorKind

  constructor(options: ApiErrorOptions) {
    super(options.message)
    this.name = 'ApiError'
    this.status = options.status ?? 0
    this.code = options.code
    this.fields = options.fields ?? []
    this.threadId = options.threadId
    this.kind = options.kind ?? 'http'
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError
}

export function toApiError(value: unknown): ApiError {
  if (isApiError(value)) {
    return value
  }
  return new ApiError({
    code: 'unknown_error',
    message: value instanceof Error ? value.message : '请求失败，请稍后重试',
    kind: 'network',
  })
}

export interface RequestOptions {
  method?: string
  body?: unknown
  signal?: AbortSignal
  timeoutMs?: number
  headers?: Record<string, string>
}

const DEFAULT_TIMEOUT_MS = 180_000

export function resolveApiBase(raw?: string): string {
  const value = (raw ?? import.meta.env.VITE_API_BASE_URL ?? '').trim()
  return value.replace(/\/+$/, '')
}

export function buildUrl(path: string, base: string = resolveApiBase()): string {
  const normalized = path.startsWith('/') ? path : `/${path}`
  if (!base) {
    return `/api${normalized}`
  }
  if (base.endsWith('/api')) {
    return `${base}${normalized}`
  }
  return `${base}/api${normalized}`
}

let unauthorizedHandler: (() => void) | null = null
let handlingUnauthorized = false

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler
  handlingUnauthorized = false
}

/** 登录成功后重新允许 401 处理。 */
export function resetUnauthorizedState(): void {
  handlingUnauthorized = false
}

function notifyUnauthorized(): void {
  if (handlingUnauthorized) {
    return
  }
  handlingUnauthorized = true
  unauthorizedHandler?.()
}

const DEFAULT_MESSAGES: Record<number, string> = {
  401: '登录已失效，请重新登录',
  404: '会话不存在或已失效',
  409: '当前状态不允许该操作',
  422: '提交内容不符合要求',
  429: '操作过于频繁，请稍后再试',
  500: '服务端处理失败，请稍后重试',
}

const KNOWN_CODES: Record<string, string> = {
  not_authenticated: '请先登录',
  token_expired: '登录已过期，请重新登录',
  token_invalid: '登录凭证无效，请重新登录',
  invalid_credentials: '邮箱或密码不正确',
  email_taken: '该邮箱已被注册',
  rate_limited: '登录尝试过于频繁，请稍后再试',
  thread_not_found: '会话不存在或已失效',
  snapshot_not_found: '该快照不存在或已失效',
  not_trashed: '该会话不在回收站中，请刷新后重试',
  too_many_jobs: '单次最多分析 5 个岗位',
  interview_not_found: '演练会话不存在或已失效',
  interview_job_not_ready: '该岗位尚未完成分析，暂时无法开始演练',
  interview_closed: '该演练已结束，无法继续作答',
  interview_waiting_question: '请等待面试官提问后再作答',
  interview_answer_blank: '回答内容不能为空',
  interview_answer_too_long: '回答过长，请精简后再提交',
  interview_generation_failed: '面试官暂时无法响应，请稍后重试',
  interview_no_answers: '请至少回答一道题后再生成报告',
  interview_report_failed: '评估报告生成失败，请稍后重试',
  coach_session_not_found: '教练会话不存在或已失效',
  coach_analysis_not_found: '所选分析会话不存在或已删除',
  coach_message_blank: '消息内容不能为空',
  coach_message_too_long: '消息过长，请精简后再发送',
  coach_reply_failed: '教练暂时无法回复，请稍后重试',
  request_timeout: '请求超时',
  network_error: '网络连接失败',
}

function parseFields(raw: unknown): FieldError[] {
  if (!Array.isArray(raw)) {
    return []
  }
  const fields: FieldError[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') {
      continue
    }
    const record = item as Record<string, unknown>
    if (typeof record.field !== 'string' || typeof record.message !== 'string') {
      continue
    }
    fields.push({
      field: record.field,
      type: typeof record.type === 'string' ? record.type : 'invalid',
      message: record.message,
    })
  }
  return fields
}

function normalizeHttpError(status: number, body: unknown): ApiError {
  const container = body && typeof body === 'object' ? (body as Record<string, unknown>) : {}
  const nested =
    container.error && typeof container.error === 'object'
      ? (container.error as Record<string, unknown>)
      : {}
  const code =
    typeof nested.code === 'string' && nested.code
      ? nested.code
      : typeof container.code === 'string' && container.code
        ? container.code
        : `http_${status}`
  const message =
    KNOWN_CODES[code] ??
    (typeof nested.message === 'string' && nested.message
      ? nested.message
      : (DEFAULT_MESSAGES[status] ?? '请求失败，请稍后重试'))
  const threadId =
    typeof container.thread_id === 'string' && container.thread_id
      ? container.thread_id
      : undefined
  return new ApiError({
    status,
    code,
    message,
    fields: parseFields(nested.fields),
    threadId,
    kind: 'http',
  })
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError'
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const controller = new AbortController()
  const external = options.signal
  let timedOut = false
  const onExternalAbort = () => controller.abort()
  external?.addEventListener('abort', onExternalAbort)

  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, options.timeoutMs ?? DEFAULT_TIMEOUT_MS)

  try {
    const isFormData =
      typeof FormData !== 'undefined' && options.body instanceof FormData
    const headers: Record<string, string> = {
      Accept: 'application/json',
      ...(options.headers ?? {}),
    }
    if (options.body !== undefined && !isFormData) {
      headers['Content-Type'] = 'application/json'
    }
    const token = getToken()
    if (token) {
      headers.Authorization = `Bearer ${token}`
    }

    let response: Response
    try {
      response = await fetch(buildUrl(path), {
        method: options.method ?? 'GET',
        headers,
        body:
          options.body === undefined
            ? undefined
            : isFormData
              ? (options.body as FormData)
              : JSON.stringify(options.body),
        signal: controller.signal,
      })
    } catch (error) {
      if (timedOut) {
        throw new ApiError({
          code: 'request_timeout',
          message: '请求超时，后端可能仍在执行',
          kind: 'timeout',
        })
      }
      if (isAbortError(error)) {
        throw new ApiError({
          code: 'request_canceled',
          message: '请求已取消',
          kind: 'canceled',
        })
      }
      throw new ApiError({
        code: 'network_error',
        message: '网络连接失败，请检查网络后重试',
        kind: 'network',
      })
    }

    if (response.status === 204) {
      return undefined as T
    }

    const text = await response.text()
    let parsed: unknown
    if (text) {
      try {
        parsed = JSON.parse(text)
      } catch {
        parsed = undefined
      }
    }

    if (!response.ok) {
      if (response.status === 401 && !path.startsWith('/auth/login') && !path.startsWith('/auth/register')) {
        notifyUnauthorized()
      }
      throw normalizeHttpError(response.status, parsed)
    }

    if (parsed === undefined) {
      throw new ApiError({
        status: response.status,
        code: 'invalid_response',
        message: '服务端返回了无法解析的数据',
        kind: 'invalid_response',
      })
    }

    return parsed as T
  } finally {
    clearTimeout(timer)
    external?.removeEventListener('abort', onExternalAbort)
  }
}
