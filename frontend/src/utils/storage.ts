export function getLocalStorage(): Storage | null {
  try {
    if (typeof window !== 'undefined' && window.localStorage) {
      return window.localStorage
    }
  } catch {
    // ignore
  }
  try {
    if (typeof localStorage !== 'undefined') {
      return localStorage
    }
  } catch {
    // ignore
  }
  return null
}
