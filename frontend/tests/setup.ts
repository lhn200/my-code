import { afterEach, vi } from 'vitest'

import { clearToken } from '@/auth/token'
import { getLocalStorage } from '@/utils/storage'

// happy-dom 通过 GlobalWindow 注入全局时不会暴露 localStorage 的 getter，
// 这里补一个内存实现，供 token 持久化与刷新恢复测试使用。
if (typeof window !== 'undefined' && !window.localStorage) {
  const store = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: {
      get length() {
        return store.size
      },
      clear: () => store.clear(),
      getItem: (key: string) => store.get(key) ?? null,
      key: (index: number) => Array.from(store.keys())[index] ?? null,
      removeItem: (key: string) => {
        store.delete(key)
      },
      setItem: (key: string, value: string) => {
        store.set(key, String(value))
      },
    },
  })
}

afterEach(() => {
  clearToken()
  getLocalStorage()?.clear()
  vi.restoreAllMocks()
  vi.unstubAllEnvs()
})
