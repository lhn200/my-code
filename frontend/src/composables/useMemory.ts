import { computed, ref } from 'vue'

import {
  clearMemories,
  deleteMemory,
  fetchMemorySettings,
  listMemories,
  updateMemory,
  updateMemorySettings,
  type MemoryItem,
  type MemoryKind,
} from '@/api/memories'
import { isApiError, toApiError } from '@/api/client'

const ACTION_MESSAGES: Record<string, string> = {
  sensitive_content: '内容包含敏感信息，未保存',
  memory_conflict: '已存在相同内容的记忆',
  memory_not_found: '该记忆已不存在，请刷新后重试',
  invalid_content: '内容不合法，请调整后重试',
}

function actionMessage(error: unknown): string {
  if (isApiError(error) && ACTION_MESSAGES[error.code]) {
    return ACTION_MESSAGES[error.code]
  }
  return toApiError(error).message
}

export function useMemory() {
  const enabled = ref(false)
  const settingsUpdatedAt = ref<string | null>(null)
  const settingsLoading = ref(false)
  const settingsSaving = ref(false)
  const settingsError = ref('')

  const items = ref<MemoryItem[]>([])
  const isLoading = ref(false)
  const error = ref('')
  const actionError = ref('')
  const actionPendingId = ref('')

  const kind = ref<MemoryKind | ''>('')
  const query = ref('')
  const showArchived = ref(false)

  const pending = computed(() =>
    items.value.filter((item) => item.status === 'pending_confirmation'),
  )
  const active = computed(() => items.value.filter((item) => item.status === 'active'))
  const archived = computed(() => items.value.filter((item) => item.status === 'archived'))

  let listController: AbortController | null = null
  let settingsController: AbortController | null = null

  async function loadSettings(): Promise<void> {
    settingsController?.abort()
    settingsController = new AbortController()
    settingsLoading.value = true
    settingsError.value = ''
    try {
      const result = await fetchMemorySettings({ signal: settingsController.signal })
      enabled.value = result.enabled
      settingsUpdatedAt.value = result.updated_at
    } catch (caught) {
      const failure = toApiError(caught)
      if (failure.kind !== 'canceled') {
        settingsError.value = `读取记忆设置失败：${failure.message}`
      }
    } finally {
      settingsLoading.value = false
    }
  }

  async function load(): Promise<void> {
    listController?.abort()
    listController = new AbortController()
    isLoading.value = true
    error.value = ''
    try {
      const response = await listMemories(
        {
          kind: kind.value || undefined,
          status: showArchived.value ? 'archived' : undefined,
          q: query.value,
          limit: 100,
        },
        { signal: listController.signal },
      )
      items.value = response.items
    } catch (caught) {
      const failure = toApiError(caught)
      if (failure.kind !== 'canceled') {
        error.value = `读取记忆失败：${failure.message}`
      }
    } finally {
      isLoading.value = false
    }
  }

  async function setEnabled(next: boolean): Promise<boolean> {
    if (settingsSaving.value) {
      return false
    }
    const previous = enabled.value
    enabled.value = next
    settingsSaving.value = true
    settingsError.value = ''
    try {
      const result = await updateMemorySettings(next)
      enabled.value = result.enabled
      settingsUpdatedAt.value = result.updated_at
      return true
    } catch (caught) {
      enabled.value = previous
      settingsError.value = `保存记忆设置失败：${toApiError(caught).message}`
      return false
    } finally {
      settingsSaving.value = false
    }
  }

  async function toggleEnabled(): Promise<boolean> {
    return setEnabled(!enabled.value)
  }

  async function runAction(
    id: string,
    action: () => Promise<void>,
    fallback: string,
  ): Promise<boolean> {
    if (actionPendingId.value) {
      return false
    }
    actionPendingId.value = id
    actionError.value = ''
    try {
      await action()
      return true
    } catch (caught) {
      actionError.value = `${fallback}：${actionMessage(caught)}`
      return false
    } finally {
      actionPendingId.value = ''
    }
  }

  async function remove(id: string): Promise<boolean> {
    const snapshot = items.value
    items.value = items.value.filter((item) => item.id !== id)
    const succeeded = await runAction(id, () => deleteMemory(id), '删除记忆失败')
    if (!succeeded) {
      items.value = snapshot
    }
    return succeeded
  }

  async function clearAll(): Promise<boolean> {
    const snapshot = items.value
    items.value = []
    const succeeded = await runAction('all', async () => {
      await clearMemories()
    }, '清空记忆失败')
    if (!succeeded) {
      items.value = snapshot
    }
    return succeeded
  }

  async function confirmItem(item: MemoryItem): Promise<boolean> {
    return runAction(
      item.id,
      async () => {
        const updated = await updateMemory(item.id, { status: 'active' })
        items.value = items.value.map((current) =>
          current.id === updated.id ? updated : current,
        )
      },
      '确认记忆失败',
    )
  }

  async function ignoreItem(item: MemoryItem): Promise<boolean> {
    const snapshot = items.value
    items.value = items.value.filter((current) => current.id !== item.id)
    const succeeded = await runAction(
      item.id,
      async () => {
        await updateMemory(item.id, { status: 'archived' })
      },
      '忽略记忆失败',
    )
    if (!succeeded) {
      items.value = snapshot
    }
    return succeeded
  }

  async function setKind(next: MemoryKind | ''): Promise<void> {
    kind.value = next
    await load()
  }

  async function setQuery(next: string): Promise<void> {
    query.value = next
    await load()
  }

  async function setShowArchived(next: boolean): Promise<void> {
    showArchived.value = next
    await load()
  }

  function cancel(): void {
    listController?.abort()
    settingsController?.abort()
  }

  return {
    enabled,
    settingsUpdatedAt,
    settingsLoading,
    settingsSaving,
    settingsError,
    items,
    isLoading,
    error,
    actionError,
    actionPendingId,
    kind,
    query,
    showArchived,
    pending,
    active,
    archived,
    loadSettings,
    load,
    setEnabled,
    toggleEnabled,
    remove,
    clearAll,
    confirmItem,
    ignoreItem,
    setKind,
    setQuery,
    setShowArchived,
    cancel,
  }
}
