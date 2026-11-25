import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import type { SessionSummaryResponse } from '@/api/memories'
import type { SessionItem } from '@/api/types'

const api = vi.hoisted(() => ({
  fetchSessionSummary: vi.fn(),
  regenerateSessionSummary: vi.fn(),
  listSessions: vi.fn(),
}))

vi.mock('@/api/memories', () => ({
  fetchSessionSummary: api.fetchSessionSummary,
  regenerateSessionSummary: api.regenerateSessionSummary,
}))

vi.mock('@/api/sessions', () => ({ listSessions: api.listSessions }))

import { useSessionSummary } from '@/composables/useSessionSummary'

const session: SessionItem = {
  thread_id: 't1',
  title: '会话 A',
  status: 'completed',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z',
  deleted_at: null,
}

function summary(overrides: Partial<SessionSummaryResponse> = {}): SessionSummaryResponse {
  return {
    thread_id: 't1',
    summarized: true,
    version: 1,
    updated_at: '2026-01-02T00:00:00Z',
    summarized_through_turn: 6,
    summary_status: 'ok',
    summary: {
      facts: ['用户有三年运营经验'],
      open_questions: [],
      preferences: [],
      constraints: [],
      decisions: [],
    },
    ...overrides,
  }
}

describe('useSessionSummary', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listSessions.mockResolvedValue({
      items: [session],
      total: 1,
      page: 1,
      page_size: 20,
    })
    api.fetchSessionSummary.mockResolvedValue(summary())
    api.regenerateSessionSummary.mockResolvedValue({ ...summary(), regenerated: true })
  })

  it('加载会话列表', async () => {
    const state = useSessionSummary()

    await state.loadSessions()

    expect(api.listSessions).toHaveBeenCalledWith(
      { page: 1, page_size: 20, q: '', trashed: false },
      expect.objectContaining({ signal: expect.anything() }),
    )
    expect(state.sessions.value).toHaveLength(1)
  })

  it('选中会话后加载摘要', async () => {
    const state = useSessionSummary()

    await state.select('t1')

    expect(api.fetchSessionSummary).toHaveBeenCalledWith(
      't1',
      expect.objectContaining({ signal: expect.anything() }),
    )
    expect(state.summary.value?.version).toBe(1)
    expect(state.selectedSession.value).toBeNull()
  })

  it('重新生成成功后更新版本', async () => {
    api.regenerateSessionSummary.mockResolvedValue({
      ...summary({ version: 2 }),
      regenerated: true,
    })
    const state = useSessionSummary()
    await state.select('t1')

    const outcome = await state.regenerate()

    expect(api.regenerateSessionSummary).toHaveBeenCalledWith('t1', 1)
    expect(outcome).toBe('success')
    expect(state.summary.value?.version).toBe(2)
    expect(state.outcomeMessage.value).toBe('摘要已更新')
  })

  it('没有新轮次时返回 no_turns', async () => {
    api.regenerateSessionSummary.mockResolvedValue({
      ...summary(),
      regenerated: false,
    })
    const state = useSessionSummary()
    await state.select('t1')

    const outcome = await state.regenerate()

    expect(outcome).toBe('no_turns')
    expect(state.outcomeMessage.value).toBe('暂无新的未总结轮次')
  })

  it('409 冲突时提示并重新加载摘要', async () => {
    api.regenerateSessionSummary.mockRejectedValue(
      new ApiError({ status: 409, code: 'summary_conflict', message: 'changed' }),
    )
    api.fetchSessionSummary
      .mockResolvedValueOnce(summary())
      .mockResolvedValueOnce(summary({ version: 3 }))
    const state = useSessionSummary()
    await state.select('t1')

    const outcome = await state.regenerate()

    expect(outcome).toBe('conflict')
    expect(state.summary.value?.version).toBe(3)
    expect(state.outcome.value).toBe('conflict')
    expect(api.fetchSessionSummary).toHaveBeenCalledTimes(2)
  })

  it('502 失败时保留原摘要', async () => {
    api.regenerateSessionSummary.mockRejectedValue(
      new ApiError({ status: 502, code: 'summary_failed', message: 'model down' }),
    )
    const state = useSessionSummary()
    await state.select('t1')

    const outcome = await state.regenerate()

    expect(outcome).toBe('failed')
    expect(state.summary.value?.version).toBe(1)
    expect(state.outcomeMessage.value).toBe('摘要生成失败，已保留原摘要，可稍后重试')
  })

  it('摘要正文不写入 localStorage', async () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem')
    const state = useSessionSummary()
    await state.select('t1')
    await state.regenerate()

    expect(spy).not.toHaveBeenCalled()
    spy.mockRestore()
  })
})
