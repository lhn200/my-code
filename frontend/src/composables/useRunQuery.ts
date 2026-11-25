import { ref } from 'vue'

import { toApiError, type ApiError } from '@/api/client'
import { getRun } from '@/api/runs'
import type { RunStatePayload } from '@/api/types'

export function useRunQuery() {
  const threadId = ref('')
  const isLoading = ref(false)
  const error = ref<ApiError | null>(null)
  const fieldError = ref('')
  const data = ref<RunStatePayload | null>(null)
  let controller: AbortController | null = null

  async function query(): Promise<string | null> {
    const value = threadId.value.trim()
    fieldError.value = ''
    error.value = null
    if (!value) {
      fieldError.value = '请输入 thread_id'
      return null
    }
    controller?.abort()
    controller = new AbortController()
    isLoading.value = true
    try {
      data.value = await getRun(value, { signal: controller.signal })
      return value
    } catch (caught) {
      const apiError = toApiError(caught)
      if (apiError.code !== 'request_canceled') {
        error.value = apiError
      }
      return null
    } finally {
      isLoading.value = false
      controller = null
    }
  }

  function cancel(): void {
    controller?.abort()
    controller = null
  }

  return { threadId, isLoading, error, fieldError, data, query, cancel }
}
