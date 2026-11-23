import { reactive, ref } from 'vue'

import { toApiError, type ApiError } from '@/api/client'
import {
  deleteSession,
  listSessions,
  purgeSession,
  restoreSession,
} from '@/api/sessions'
import type { SessionItem } from '@/api/types'

export function useSessionList() {
  const params = reactive({
    page: 1,
    pageSize: 10,
    q: '',
    trashed: false,
  })
  const items = ref<SessionItem[]>([])
  const total = ref(0)
  const isLoading = ref(false)
  const error = ref<ApiError | null>(null)
  const actionError = ref('')
  const actionPendingId = ref('')
  let controller: AbortController | null = null

  const totalPages = () => Math.max(1, Math.ceil(total.value / params.pageSize))

  async function load(): Promise<void> {
    controller?.abort()
    controller = new AbortController()
    isLoading.value = true
    error.value = null
    try {
      const response = await listSessions(
        {
          page: params.page,
          page_size: params.pageSize,
          q: params.q,
          trashed: params.trashed,
        },
        { signal: controller.signal },
      )
      const maxPage = Math.max(1, Math.ceil(response.total / params.pageSize))
      if (params.page > maxPage) {
        params.page = maxPage
        controller = null
        await load()
        return
      }
      items.value = response.items
      total.value = response.total
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

  function setPage(page: number): Promise<void> {
    params.page = Math.max(1, Math.min(page, totalPages()))
    return load()
  }

  function setTrashed(trashed: boolean): Promise<void> {
    if (params.trashed === trashed) {
      return Promise.resolve()
    }
    params.trashed = trashed
    params.page = 1
    return load()
  }

  function setQuery(query: string): Promise<void> {
    params.q = query
    params.page = 1
    return load()
  }

  async function restore(threadId: string): Promise<boolean> {
    return runAction(threadId, () => restoreSession(threadId))
  }

  async function removeToTrash(threadId: string): Promise<boolean> {
    return runAction(threadId, () => deleteSession(threadId))
  }

  async function purge(threadId: string): Promise<boolean> {
    return runAction(threadId, () => purgeSession(threadId))
  }

  async function runAction(threadId: string, action: () => Promise<unknown>): Promise<boolean> {
    if (actionPendingId.value) {
      return false
    }
    actionPendingId.value = threadId
    actionError.value = ''
    try {
      await action()
      await load()
      return true
    } catch (caught) {
      const apiError = toApiError(caught)
      actionError.value =
        apiError.code === 'not_trashed'
          ? '该会话不在回收站中，请刷新后重试'
          : apiError.message || '操作失败，请稍后重试'
      return false
    } finally {
      actionPendingId.value = ''
    }
  }

  function cancel(): void {
    controller?.abort()
    controller = null
  }

  return {
    params,
    items,
    total,
    isLoading,
    error,
    actionError,
    actionPendingId,
    totalPages,
    load,
    setPage,
    setTrashed,
    setQuery,
    restore,
    removeToTrash,
    purge,
    cancel,
  }
}
