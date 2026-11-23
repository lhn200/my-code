import { computed, ref } from 'vue'

import { toApiError, type ApiError } from '../api/client'
import {
  finishInterviewSession,
  getInterviewSession,
  submitInterviewAnswer,
} from '../api/interviews'
import type {
  InterviewSession,
  InterviewSessionMessage,
  InterviewSessionPayload,
  InterviewReportSummary,
} from '../api/types'

/** 单个演练会话的状态机：加载、作答、生成报告，错误统一收敛为 ApiError。 */
export function useInterviewSession(sessionId: string) {
  const payload = ref<InterviewSessionPayload | null>(null)
  const isLoading = ref(false)
  const isSubmitting = ref(false)
  const isFinishing = ref(false)
  const error = ref<ApiError | null>(null)

  const session = computed<InterviewSession | null>(() => payload.value?.session ?? null)
  const messages = computed<InterviewSessionMessage[]>(() => payload.value?.messages ?? [])
  const report = computed<InterviewReportSummary | null>(() => payload.value?.report ?? null)

  const lastMessage = computed<InterviewSessionMessage | null>(
    () => messages.value[messages.value.length - 1] ?? null,
  )

  const canAnswer = computed(() => {
    const current = session.value
    const last = lastMessage.value
    return (
      current?.status === 'active' &&
      last?.role === 'interviewer' &&
      (last.kind === 'question' || last.kind === 'followup')
    )
  })

  const isCompleted = computed(() => session.value?.status === 'completed')

  const progress = computed(() => {
    const current = session.value
    return {
      asked: current?.asked_count ?? 0,
      planned: current?.planned_count ?? 0,
      current: current?.current_question_no ?? 0,
    }
  })

  function apply(next: InterviewSessionPayload): void {
    payload.value = next
    error.value = null
  }

  async function load(): Promise<boolean> {
    isLoading.value = true
    error.value = null
    try {
      apply(await getInterviewSession(sessionId))
      return true
    } catch (cause) {
      error.value = toApiError(cause)
      return false
    } finally {
      isLoading.value = false
    }
  }

  async function answer(text: string): Promise<boolean> {
    if (!canAnswer.value || isSubmitting.value) {
      return false
    }
    isSubmitting.value = true
    error.value = null
    try {
      apply(await submitInterviewAnswer(sessionId, text))
      return true
    } catch (cause) {
      error.value = toApiError(cause)
      return false
    } finally {
      isSubmitting.value = false
    }
  }

  async function finish(): Promise<boolean> {
    if (isFinishing.value) {
      return false
    }
    isFinishing.value = true
    error.value = null
    try {
      apply(await finishInterviewSession(sessionId))
      return true
    } catch (cause) {
      error.value = toApiError(cause)
      return false
    } finally {
      isFinishing.value = false
    }
  }

  return {
    payload,
    session,
    messages,
    report,
    isLoading,
    isSubmitting,
    isFinishing,
    error,
    canAnswer,
    isCompleted,
    progress,
    load,
    answer,
    finish,
  }
}
