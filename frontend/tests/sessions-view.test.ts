import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({
  params: { page: 1, pageSize: 10, q: '', trashed: true },
  items: [
    {
      thread_id: 't1',
      title: '回收站会话',
      status: 'completed',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-02T00:00:00Z',
      deleted_at: '2026-01-03T00:00:00Z',
    },
  ],
  total: 1,
  isLoading: false,
  error: null,
  actionError: '',
  actionPendingId: { value: '' },
  totalPages: () => 1,
  load: vi.fn().mockResolvedValue(undefined),
  setPage: vi.fn().mockResolvedValue(undefined),
  setTrashed: vi.fn().mockResolvedValue(undefined),
  setQuery: vi.fn().mockResolvedValue(undefined),
  restore: vi.fn().mockResolvedValue(true),
  removeToTrash: vi.fn().mockResolvedValue(true),
  purge: vi.fn().mockResolvedValue(true),
  cancel: vi.fn(),
}))

vi.mock('@/composables/useSessionList', () => ({
  useSessionList: () => state,
}))

import SessionsView from '@/views/SessionsView.vue'

describe('SessionsView 回收站操作', () => {
  it('永久删除需要二次确认', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const wrapper = mount(SessionsView, {
      global: {
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })
    await flushPromises()

    const purgeButton = wrapper
      .findAll('button')
      .find((button) => button.text() === '永久删除')
    expect(purgeButton).toBeTruthy()

    await purgeButton!.trigger('click')
    expect(state.purge).not.toHaveBeenCalled()

    confirmSpy.mockReturnValue(true)
    await purgeButton!.trigger('click')
    expect(state.purge).toHaveBeenCalledWith('t1')
  })
})
