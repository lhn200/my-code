import { computed, reactive } from 'vue'

import { login as apiLogin, logout as apiLogout, me as apiMe, register as apiRegister } from '@/api/auth'
import { isApiError, resetUnauthorizedState } from '@/api/client'
import type { User } from '@/api/types'
import {
  clearToken,
  getToken,
  restoreTokenFromStorage,
  setToken,
} from '@/auth/token'

const state = reactive<{ user: User | null; token: string }>({
  user: null,
  token: getToken(),
})

let mePromise: Promise<User | null> | null = null

function clearSession(): void {
  clearToken()
  state.token = ''
  state.user = null
}

function fetchMe(): Promise<User | null> {
  if (!state.token) {
    state.user = null
    return Promise.resolve(null)
  }
  if (mePromise) {
    return mePromise
  }
  mePromise = apiMe()
    .then((user) => {
      state.user = user
      return user
    })
    .catch((error) => {
      if (isApiError(error) && error.status === 401) {
        clearSession()
      }
      throw error
    })
    .finally(() => {
      mePromise = null
    })
  return mePromise
}

function restore(): void {
  state.token = restoreTokenFromStorage()
  if (!state.token) {
    state.user = null
    return
  }
  fetchMe().catch(() => {
    // 启动阶段静默处理；401 会由 clearSession 清理。
  })
}

async function login(email: string, password: string): Promise<User | null> {
  const response = await apiLogin({ email, password })
  setToken(response.access_token)
  state.token = response.access_token
  resetUnauthorizedState()
  return fetchMe()
}

function register(email: string, password: string): Promise<User> {
  return apiRegister({ email, password })
}

async function logout(): Promise<void> {
  try {
    if (state.token) {
      await apiLogout()
    }
  } catch {
    // 本地登出优先，服务端失败不阻塞。
  } finally {
    clearSession()
  }
}

const isAuthenticated = computed(() => Boolean(state.token))
const user = computed(() => state.user)
const token = computed(() => state.token)

export function useAuth() {
  return {
    user,
    token,
    isAuthenticated,
    login,
    register,
    logout,
    fetchMe,
    restore,
    clearSession,
  }
}
