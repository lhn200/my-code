import { ref } from 'vue'

import { toApiError, type ApiError } from '@/api/client'
import { getSnapshot, listSnapshots } from '@/api/runs'
import type { RunStatePayload, SnapshotSummary } from '@/api/types'

export function useSnapshots(getThreadId: () => string) {
  const snapshots = ref<SnapshotSummary[]>([])
  const isLoading = ref(false)
  const error = ref<ApiError | null>(null)
  const selectedCheckpoint = ref('')
  const selected = ref<RunStatePayload | null>(null)
  const isSelecting = ref(false)
  const selectionError = ref<ApiError | null>(null)
  let listController: AbortController | null = null
  let selectController: AbortController | null = null

  async function load(): Promise<void> {
    const threadId = getThreadId().trim()
    if (!threadId) {
      return
    }
    listController?.abort()
    listController = new AbortController()
    isLoading.value = true
    error.value = null
    try {
      const response = await listSnapshots(threadId, { signal: listController.signal })
      snapshots.value = response.snapshots
    } catch (caught) {
      const apiError = toApiError(caught)
      if (apiError.code !== 'request_canceled') {
        error.value = apiError
      }
    } finally {
      isLoading.value = false
      listController = null
    }
  }

  async function select(checkpointId: string): Promise<void> {
    const threadId = getThreadId().trim()
    if (!threadId || !checkpointId || isSelecting.value) {
      return
    }
    selectController?.abort()
    selectController = new AbortController()
    isSelecting.value = true
    selectionError.value = null
    try {
      selected.value = await getSnapshot(threadId, checkpointId, {
        signal: selectController.signal,
      })
      selectedCheckpoint.value = checkpointId
    } catch (caught) {
      const apiError = toApiError(caught)
      if (apiError.code !== 'request_canceled') {
        selectionError.value = apiError
      }
    } finally {
      isSelecting.value = false
      selectController = null
    }
  }

  function closeSelection(): void {
    selected.value = null
    selectedCheckpoint.value = ''
    selectionError.value = null
  }

  function cancel(): void {
    listController?.abort()
    selectController?.abort()
    listController = null
    selectController = null
  }

  return {
    snapshots,
    isLoading,
    error,
    selectedCheckpoint,
    selected,
    isSelecting,
    selectionError,
    load,
    select,
    closeSelection,
    cancel,
  }
}
