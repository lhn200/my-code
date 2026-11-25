import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import type { SessionItem } from '@/api/types'

const api = vi.hoisted(() => ({
  listSessions: vi.fn(),
  restoreSession: vi.fn(),
  deleteSession: vi.fn(),
  purgeSession: vi.fn(),
  renameSession: vi.fn(),
}))

vi.mock('@/api/sessions', () => api)

import { useSessionList } from '@/composables/useSessionList'

const item: SessionItem = {
  thread_id: 't1',
  title: '会话 A',
  status: 'completed',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z',
  deleted_at: null,
}

function pageResponse(total = 1, items: SessionItem[] = [item]) {
  return { items, total, page: 1, page_size: 10 }
}

describe('useSessionList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listSessions.mockResolvedValue(pageResponse())
    api.restoreSession.mockResolvedValue(item)
    api.deleteSession.mockResolvedValue(undefined)
    api.purgeSession.mockResolvedValue(undefined)
  })

  it('按默认参数加载第一页', async () => {
    const list = useSessionList()
    await list.load()

    expect(api.listSessions).toHaveBeenCalledWith(
      { page: 1, page_size: 10, q: '', trashed: false },
      expect.objectContaining({ signal: expect.anything() }),
    )
    expect(list.items.value).toHaveLength(1)
    expect(list.total.value).toBe(1)
  })

  it('切换回收站与关键词时重置到第一页', async () => {
    api.listSessions.mockResolvedValue(pageResponse(25))
    const list = useSessionList()
    await list.load()
    await list.setPage(2)
    expect(list.params.page).toBe(2)

    await list.setQuery('后端')
    expect(list.params.page).toBe(1)
    expect(api.listSessions.mock.calls.at(-1)?.[0]).toMatchObject({ q: '后端', page: 1 })

    await list.setTrashed(true)
    expect(api.listSessions.mock.calls.at(-1)?.[0]).toMatchObject({ trashed: true, page: 1 })
  })

  it('页码越界时收敛到最后一页', async () => {
    api.listSessions.mockResolvedValue(pageResponse(5))
    const list = useSessionList()
    list.params.page = 3

    await list.load()

    expect(list.params.page).toBe(1)
    expect(api.listSessions).toHaveBeenCalledTimes(2)
  })

  it('恢复会话后刷新列表', async () => {
    const list = useSessionList()
    await list.load()

    const succeeded = await list.restore('t1')

    expect(succeeded).toBe(true)
    expect(api.restoreSession).toHaveBeenCalledWith('t1')
    expect(api.listSessions).toHaveBeenCalledTimes(2)
  })

  it('软删除调用 DELETE 接口', async () => {
    const list = useSessionList()
    await list.load()

    const succeeded = await list.removeToTrash('t1')

    expect(succeeded).toBe(true)
    expect(api.deleteSession).toHaveBeenCalledWith('t1')
  })

  it('409 not_trashed 展示可读提示', async () => {
    api.purgeSession.mockRejectedValue(
      new ApiError({
        status: 409,
        code: 'not_trashed',
        message: 'session is not in the trash',
      }),
    )
    const list = useSessionList()
    await list.load()

    const succeeded = await list.purge('t1')

    expect(succeeded).toBe(false)
    expect(list.actionError.value).toBe('该会话不在回收站中，请刷新后重试')
  })
})
