import { computed, ref } from 'vue'

import { isApiError, toApiError, type ApiError } from '@/api/client'
import { getRun, resumeRun } from '@/api/runs'
import type { RunStatePayload } from '@/api/types'

export function useRunDetail(getThreadId: () => string) {
  const data = ref<RunStatePayload | null>(null)
  const isLoading = ref(false)
  const error = ref<ApiError | null>(null)
  const isResuming = ref(false)
  const resumeError = ref<ApiError | null>(null)
  let controller: AbortController | null = null

  const notFound = computed(() => error.value?.status === 404)
  const isResumable = computed(() => Boolean(data.value && data.value.next.length > 0))
  const result = computed(() => data.value?.result ?? null)
  const state = computed(() => data.value?.state ?? null)

  async function load(): Promise<void> {
    const threadId = getThreadId().trim()
    if (!threadId) {
      error.value = null
      data.value = null
      return
    }
    controller?.abort()
    controller = new AbortController()
    isLoading.value = true
    error.value = null
    try {
      data.value = await getRun(threadId, { signal: controller.signal })
    } catch (caught) {
      const apiError = toApiError(caught)
      if (apiError.code !== 'request_canceled') {
        error.value = apiError
      }
    } finally {
      isLoading.value = false
      controller = null
    }
  }

  async function resume(): Promise<boolean> {
    const threadId = getThreadId().trim()
    if (!threadId || isResuming.value) {
      return false
    }
    isResuming.value = true
    resumeError.value = null
    try {
      await resumeRun(threadId)
      await load()
      return true
    } catch (caught) {
      const apiError = toApiError(caught)
      if (apiError.code !== 'request_canceled') {
        resumeError.value = apiError
      }
      return false
    } finally {
      isResuming.value = false
    }
  }

  function cancel(): void {
    controller?.abort()
    controller = null
  }

  return {
    data,
    result,
    state,
    isLoading,
    error,
    notFound,
    isResumable,
    isResuming,
    resumeError,
    load,
    resume,
    cancel,
  }
}

export function isCanceledError(value: unknown): boolean {
  return isApiError(value) && value.code === 'request_canceled'
}
