import { describe, expect, it, vi } from 'vitest'

import { sanitizeRedirect } from '@/utils/redirect'
import { getLocalStorage } from '@/utils/storage'

function protectedRoute(fullPath = '/runs/abc') {
  return {
    meta: { requiresAuth: true },
    fullPath,
    name: 'run-detail',
    params: { threadId: 'abc' },
  } as never
}

describe('sanitizeRedirect', () => {
  it('只放行站内相对路径', () => {
    expect(sanitizeRedirect('/runs/abc')).toBe('/runs/abc')
    expect(sanitizeRedirect('https://evil.example.com')).toBe('/')
    expect(sanitizeRedirect('//evil.example.com')).toBe('/')
    expect(sanitizeRedirect('/login?redirect=x')).toBe('/')
    expect(sanitizeRedirect('/register')).toBe('/')
    expect(sanitizeRedirect(undefined)).toBe('/')
  })
})

describe('authGuard', () => {
  it('无 token 时跳转登录并带上 redirect', async () => {
    getLocalStorage()?.clear()
    vi.resetModules()

    const { authGuard } = await import('@/auth/guard')
    const result = authGuard(protectedRoute('/runs/abc'))

    expect(result).toEqual({ name: 'login', query: { redirect: '/runs/abc' } })
  })

  it('刷新后从 localStorage 恢复登录态', async () => {
    getLocalStorage()?.setItem('career_assistant_token', 'token-1')
    vi.resetModules()

    const { useAuth } = await import('@/composables/useAuth')
    const auth = useAuth()

    expect(auth.isAuthenticated.value).toBe(true)
    expect(auth.token.value).toBe('token-1')
  })

  it('已登录时访问受保护页面放行，访问登录页回到首页', async () => {
    getLocalStorage()?.setItem('career_assistant_token', 'token-1')
    vi.resetModules()

    const { authGuard } = await import('@/auth/guard')

    expect(authGuard(protectedRoute())).toBe(true)
    expect(
      authGuard({
        meta: {},
        fullPath: '/login',
        name: 'login',
        params: {},
      } as never),
    ).toEqual({ path: '/' })
  })
})

describe('installUnauthorizedHandler', () => {
  it('401 清理 token 并跳转登录页', async () => {
    vi.resetModules()
    const { setToken, getToken } = await import('@/auth/token')
    const { installUnauthorizedHandler } = await import('@/auth/unauthorized')
    const { request } = await import('@/api/client')

    setToken('token-1')
    const replace = vi.fn().mockResolvedValue(undefined)
    const router = {
      currentRoute: { value: { name: 'run-detail', fullPath: '/runs/abc' } },
      replace,
    } as never

    installUnauthorizedHandler(router, { clearSession: () => setToken('') })

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: { code: 'token_expired' } }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    await expect(request('/runs/abc')).rejects.toMatchObject({ status: 401 })

    expect(getToken()).toBe('')
    expect(replace).toHaveBeenCalledWith({
      name: 'login',
      query: { redirect: '/runs/abc' },
    })
  })
})
