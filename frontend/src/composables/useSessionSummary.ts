import { computed, ref } from 'vue'

import {
  fetchSessionSummary,
  regenerateSessionSummary,
  type SessionSummaryResponse,
} from '@/api/memories'
import { isApiError, toApiError } from '@/api/client'
import { listSessions } from '@/api/sessions'
import type { SessionItem } from '@/api/types'

export type RegenerateOutcome = 'success' | 'no_turns' | 'conflict' | 'failed' | 'idle'

const OUTCOME_MESSAGES: Record<Exclude<RegenerateOutcome, 'idle'>, string> = {
  success: '摘要已更新',
  no_turns: '暂无新的未总结轮次',
  conflict: '摘要在其他操作中已更新，已为你加载最新内容',
  failed: '摘要生成失败，已保留原摘要，可稍后重试',
}

export function useSessionSummary(pageSize = 20) {
  const sessions = ref<SessionItem[]>([])
  const sessionsLoading = ref(false)
  const sessionsError = ref('')

  const selectedThreadId = ref('')
  const summary = ref<SessionSummaryResponse | null>(null)
  const summaryLoading = ref(false)
  const summaryError = ref('')
  const regenerating = ref(false)
  const outcome = ref<RegenerateOutcome>('idle')
  const outcomeMessage = ref('')

  const selectedSession = computed(
    () => sessions.value.find((item) => item.thread_id === selectedThreadId.value) ?? null,
  )

  let sessionsController: AbortController | null = null
  let summaryController: AbortController | null = null

  function setOutcome(next: RegenerateOutcome): void {
    outcome.value = next
    outcomeMessage.value = next === 'idle' ? '' : OUTCOME_MESSAGES[next]
  }

  async function loadSessions(): Promise<void> {
    sessionsController?.abort()
    sessionsController = new AbortController()
    sessionsLoading.value = true
    sessionsError.value = ''
    try {
      const response = await listSessions(
        { page: 1, page_size: pageSize, q: '', trashed: false },
        { signal: sessionsController.signal },
      )
      sessions.value = response.items
    } catch (caught) {
      const failure = toApiError(caught)
      if (failure.kind !== 'canceled') {
        sessionsError.value = `读取会话失败：${failure.message}`
      }
    } finally {
      sessionsLoading.value = false
    }
  }

  async function loadSummary(threadId: string): Promise<void> {
    summaryController?.abort()
    summaryController = new AbortController()
    summaryLoading.value = true
    summaryError.value = ''
    try {
      summary.value = await fetchSessionSummary(threadId, {
        signal: summaryController.signal,
      })
      setOutcome('idle')
    } catch (caught) {
      const failure = toApiError(caught)
      if (failure.kind !== 'canceled') {
        summaryError.value = `读取摘要失败：${failure.message}`
      }
    } finally {
      summaryLoading.value = false
    }
  }

  async function select(threadId: string): Promise<void> {
    selectedThreadId.value = threadId
    summary.value = null
    await loadSummary(threadId)
  }

  async function reloadSummary(): Promise<void> {
    if (!selectedThreadId.value) {
      return
    }
    await loadSummary(selectedThreadId.value)
  }

  async function regenerate(): Promise<RegenerateOutcome> {
    if (!selectedThreadId.value || regenerating.value) {
      return 'idle'
    }
    regenerating.value = true
    setOutcome('idle')
    try {
      const response = await regenerateSessionSummary(
        selectedThreadId.value,
        summary.value?.version ?? null,
      )
      summary.value = response
      if (response.regenerated) {
        setOutcome('success')
        return 'success'
      }
      setOutcome('no_turns')
      return 'no_turns'
    } catch (caught) {
      if (isApiError(caught) && caught.status === 409) {
        await reloadSummary()
        setOutcome('conflict')
        return 'conflict'
      }
      setOutcome('failed')
      return 'failed'
    } finally {
      regenerating.value = false
    }
  }

  function cancel(): void {
    sessionsController?.abort()
    summaryController?.abort()
  }

  return {
    sessions,
    sessionsLoading,
    sessionsError,
    selectedThreadId,
    selectedSession,
    summary,
    summaryLoading,
    summaryError,
    regenerating,
    outcome,
    outcomeMessage,
    loadSessions,
    select,
    reloadSummary,
    regenerate,
    cancel,
  }
}
