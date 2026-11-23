import { getLocalStorage } from '@/utils/storage'

const STORAGE_KEY = 'career_assistant_token'

function readStoredToken(): string {
  try {
    return getLocalStorage()?.getItem(STORAGE_KEY) ?? ''
  } catch {
    return ''
  }
}

let currentToken = readStoredToken()

export function getToken(): string {
  return currentToken
}

export function setToken(value: string): void {
  currentToken = value
  try {
    const storage = getLocalStorage()
    if (!storage) {
      return
    }
    if (value) {
      storage.setItem(STORAGE_KEY, value)
    } else {
      storage.removeItem(STORAGE_KEY)
    }
  } catch {
    // localStorage 不可用时仅保留内存态。
  }
}

export function clearToken(): void {
  setToken('')
}

/** 测试或跨标签页场景下，从 localStorage 重新读取 token。 */
export function restoreTokenFromStorage(): string {
  currentToken = readStoredToken()
  return currentToken
}

export { STORAGE_KEY }
