import { computed, ref } from 'vue'

import { toApiError, type ApiError } from '../api/client'
import {
  createCoachSession,
  deleteCoachSession,
  getCoachSession,
  listCoachSessions,
  sendCoachMessage,
  updateCoachSession,
} from '../api/coach'
import type {
  CoachMessage,
  CoachSession,
  CoachSessionPayload,
} from '../api/types'

/** AI 教练会话状态：列表、当前会话、发送与错误统一收敛为 ApiError。 */
export function useCoachChat() {
  const sessions = ref<CoachSession[]>([])
  const active = ref<CoachSessionPayload | null>(null)
  const isLoading = ref(false)
  const isLoadingSession = ref(false)
  const isSending = ref(false)
  const error = ref<ApiError | null>(null)

  const session = computed<CoachSession | null>(() => active.value?.session ?? null)
  const messages = computed<CoachMessage[]>(() => active.value?.messages ?? [])

  function upsert(item: CoachSession): void {
    const rest = sessions.value.filter((entry) => entry.id !== item.id)
    sessions.value = [item, ...rest].sort((left, right) =>
      right.updated_at.localeCompare(left.updated_at),
    )
  }

  function apply(next: CoachSessionPayload): void {
    active.value = next
    upsert(next.session)
    error.value = null
  }

  async function loadSessions(threadId: string | null = null): Promise<boolean> {
    isLoading.value = true
    error.value = null
    try {
      const response = await listCoachSessions(threadId)
      sessions.value = response.items
      return true
    } catch (cause) {
      error.value = toApiError(cause)
      return false
    } finally {
      isLoading.value = false
    }
  }

  async function openSession(sessionId: string): Promise<boolean> {
    isLoadingSession.value = true
    error.value = null
    try {
      apply(await getCoachSession(sessionId))
      return true
    } catch (cause) {
      error.value = toApiError(cause)
      return false
    } finally {
      isLoadingSession.value = false
    }
  }

  async function create(threadId: string | null = null): Promise<boolean> {
    error.value = null
    try {
      apply(await createCoachSession({ thread_id: threadId }))
      return true
    } catch (cause) {
      error.value = toApiError(cause)
      return false
    }
  }

  async function rename(sessionId: string, title: string): Promise<boolean> {
    error.value = null
    try {
      const next = await updateCoachSession(sessionId, { title })
      if (active.value?.session.id === sessionId) {
        active.value = { ...active.value, session: next.session }
      }
      upsert(next.session)
      return true
    } catch (cause) {
      error.value = toApiError(cause)
      return false
    }
  }

  async function remove(sessionId: string): Promise<boolean> {
    error.value = null
    try {
      await deleteCoachSession(sessionId)
      sessions.value = sessions.value.filter((entry) => entry.id !== sessionId)
      if (active.value?.session.id === sessionId) {
        active.value = null
      }
      return true
    } catch (cause) {
      error.value = toApiError(cause)
      return false
    }
  }

  async function send(text: string): Promise<boolean> {
    const current = active.value?.session
    const content = text.trim()
    if (!current || !content || isSending.value) {
      return false
    }
    isSending.value = true
    error.value = null
    try {
      apply(await sendCoachMessage(current.id, content))
      return true
    } catch (cause) {
      error.value = toApiError(cause)
      return false
    } finally {
      isSending.value = false
    }
  }

  return {
    sessions,
    active,
    session,
    messages,
    isLoading,
    isLoadingSession,
    isSending,
    error,
    loadSessions,
    openSession,
    create,
    rename,
    remove,
    send,
  }
}
