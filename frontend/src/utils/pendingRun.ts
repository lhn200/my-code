import { getLocalStorage } from '@/utils/storage'

const STORAGE_KEY = 'career_assistant_pending_run'
const TTL_MS = 30 * 60 * 1000

export interface PendingRunMark {
  submittedAt: number
  goal: string
}

export function markPendingRun(goal: string): void {
  try {
    const mark: PendingRunMark = { submittedAt: Date.now(), goal }
    getLocalStorage()?.setItem(STORAGE_KEY, JSON.stringify(mark))
  } catch {
    // localStorage 不可用时忽略。
  }
}

export function readPendingRun(now: number = Date.now()): PendingRunMark | null {
  try {
    const raw = getLocalStorage()?.getItem(STORAGE_KEY)
    if (!raw) {
      return null
    }
    const parsed = JSON.parse(raw) as Partial<PendingRunMark>
    if (typeof parsed.submittedAt !== 'number' || !Number.isFinite(parsed.submittedAt)) {
      clearPendingRun()
      return null
    }
    if (now - parsed.submittedAt > TTL_MS || now < parsed.submittedAt) {
      clearPendingRun()
      return null
    }
    return {
      submittedAt: parsed.submittedAt,
      goal: typeof parsed.goal === 'string' ? parsed.goal : '',
    }
  } catch {
    clearPendingRun()
    return null
  }
}

export function clearPendingRun(): void {
  try {
    getLocalStorage()?.removeItem(STORAGE_KEY)
  } catch {
    // ignore
  }
}

export { STORAGE_KEY, TTL_MS }
