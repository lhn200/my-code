import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  buildUrl,
  request,
  resetUnauthorizedState,
  setUnauthorizedHandler,
} from '@/api/client'
import { setToken } from '@/auth/token'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('api client', () => {
  beforeEach(() => {
    setUnauthorizedHandler(null)
    resetUnauthorizedState()
  })

  it('归一化 422 字段错误', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(422, {
          error: {
            code: 'validation_error',
            message: 'request validation failed',
            fields: [
              {
                field: 'jobs[0].original_position_text',
                type: 'string_type',
                message: 'must be a string',
              },
            ],
          },
        }),
      ),
    )

    await expect(request('/runs', { method: 'POST', body: {} })).rejects.toMatchObject({
      status: 422,
      code: 'validation_error',
      fields: [
        {
          field: 'jobs[0].original_position_text',
          type: 'string_type',
          message: 'must be a string',
        },
      ],
    })
  })

  it('422 结构异常时回退为顶部 message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(422, {
          error: {
            code: 'validation_error',
            message: 'request validation failed',
            fields: 'not-an-array',
          },
        }),
      ),
    )

    try {
      await request('/runs', { method: 'POST', body: {} })
      throw new Error('should fail')
    } catch (caught) {
      const error = caught as ApiError
      expect(error.status).toBe(422)
      expect(error.fields).toEqual([])
      expect(error.message).toBe('request validation failed')
    }
  })

  it('404 映射为会话不存在', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(404, {
          error: { code: 'thread_not_found', message: 'run abc was not found' },
        }),
      ),
    )

    await expect(request('/runs/abc')).rejects.toMatchObject({
      status: 404,
      code: 'thread_not_found',
      message: '会话不存在或已失效',
    })
  })

  it('500 保留 thread_id 供排查', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(500, {
          error: { code: 'internal_error', message: 'internal error' },
          thread_id: 'thread-1',
        }),
      ),
    )

    await expect(request('/runs', { method: 'POST', body: {} })).rejects.toMatchObject({
      status: 500,
      threadId: 'thread-1',
    })
  })

  it('网络失败标记为 network', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('fetch failed')))

    await expect(request('/runs/abc')).rejects.toMatchObject({
      kind: 'network',
      status: 0,
    })
  })

  it('超时标记为 timeout', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener('abort', () => {
              reject(new DOMException('Aborted', 'AbortError'))
            })
          }),
      ),
    )

    await expect(request('/runs/abc', { timeoutMs: 10 })).rejects.toMatchObject({
      kind: 'timeout',
      code: 'request_timeout',
    })
  })

  it('基地址覆盖与同源回退', () => {
    vi.stubEnv('VITE_API_BASE_URL', '')
    expect(buildUrl('/runs')).toBe('/api/runs')

    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com/')
    expect(buildUrl('/runs')).toBe('https://api.example.com/api/runs')

    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com/api')
    expect(buildUrl('/runs')).toBe('https://api.example.com/api/runs')
  })

  it('请求携带 Bearer token', async () => {
    setToken('token-1')
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await request('/auth/me')

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer token-1')
  })

  it('401 只触发一次统一处理，登录接口除外', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockImplementation(() =>
          Promise.resolve(jsonResponse(401, { error: { code: 'token_expired' } })),
        ),
    )

    await Promise.allSettled([request('/runs/a'), request('/runs/b')])
    expect(handler).toHaveBeenCalledTimes(1)

    setUnauthorizedHandler(handler)
    await expect(
      request('/auth/login', { method: 'POST', body: { email: 'a@b.com', password: 'x' } }),
    ).rejects.toBeInstanceOf(ApiError)
    expect(handler).toHaveBeenCalledTimes(1)
  })
})
