import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import type { CoachMessage, CoachSessionPayload } from '@/api/types'

const api = vi.hoisted(() => ({
  createCoachSession: vi.fn(),
  listCoachSessions: vi.fn(),
  getCoachSession: vi.fn(),
  updateCoachSession: vi.fn(),
  deleteCoachSession: vi.fn(),
  sendCoachMessage: vi.fn(),
}))

vi.mock('@/api/coach', () => ({
  createCoachSession: api.createCoachSession,
  listCoachSessions: api.listCoachSessions,
  getCoachSession: api.getCoachSession,
  updateCoachSession: api.updateCoachSession,
  deleteCoachSession: api.deleteCoachSession,
  sendCoachMessage: api.sendCoachMessage,
}))

import { useCoachChat } from '@/composables/useCoachChat'

function message(overrides: Partial<CoachMessage> = {}): CoachMessage {
  return {
    id: 'm1',
    role: 'user',
    content: '我最需要补强什么？',
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function payload(overrides: Partial<CoachSessionPayload> = {}): CoachSessionPayload {
  return {
    session: {
      id: 's1',
      thread_id: 't1',
      title: '新的教练会话',
      message_count: 0,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      ...overrides.session,
    },
    messages: overrides.messages ?? [],
  }
}

describe('useCoachChat', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('新建会话后成为当前会话', async () => {
    api.createCoachSession.mockResolvedValue(payload())
    const state = useCoachChat()

    const ok = await state.create('t1')

    expect(ok).toBe(true)
    expect(api.createCoachSession).toHaveBeenCalledWith({ thread_id: 't1' })
    expect(state.session.value?.id).toBe('s1')
    expect(state.sessions.value.map((item) => item.id)).toEqual(['s1'])
  })

  it('发送消息后追加回复并更新标题', async () => {
    const state = useCoachChat()
    api.createCoachSession.mockResolvedValue(payload())
    await state.create(null)

    api.sendCoachMessage.mockResolvedValue(
      payload({
        session: {
          ...payload().session,
          title: '我最需要补强什么？',
          message_count: 2,
          updated_at: '2026-01-02T00:00:00Z',
        },
        messages: [
          message(),
          message({ id: 'm2', role: 'coach', content: '建议先补强岗位缺口。' }),
        ],
      }),
    )

    const ok = await state.send('我最需要补强什么？')

    expect(ok).toBe(true)
    expect(api.sendCoachMessage).toHaveBeenCalledWith('s1', '我最需要补强什么？')
    expect(state.messages.value).toHaveLength(2)
    expect(state.session.value?.title).toBe('我最需要补强什么？')
  })

  it('发送失败时保留已有消息并暴露错误码', async () => {
    const state = useCoachChat()
    api.createCoachSession.mockResolvedValue(payload())
    await state.create(null)
    api.sendCoachMessage.mockRejectedValue(
      new ApiError({ status: 502, code: 'coach_reply_failed', message: '模型不可用' }),
    )

    const ok = await state.send('给我建议')

    expect(ok).toBe(false)
    expect(state.error.value?.code).toBe('coach_reply_failed')
    expect(state.messages.value).toHaveLength(0)
    expect(state.session.value?.id).toBe('s1')
  })

  it('加载会话列表并支持切换', async () => {
    api.listCoachSessions.mockResolvedValue({ items: [payload().session] })
    const state = useCoachChat()

    const ok = await state.loadSessions('t1')

    expect(ok).toBe(true)
    expect(api.listCoachSessions).toHaveBeenCalledWith('t1')
    expect(state.sessions.value).toHaveLength(1)
  })

  it('删除当前会话后清空选中', async () => {
    const state = useCoachChat()
    api.createCoachSession.mockResolvedValue(payload())
    await state.create(null)
    api.deleteCoachSession.mockResolvedValue(undefined)

    const ok = await state.remove('s1')

    expect(ok).toBe(true)
    expect(api.deleteCoachSession).toHaveBeenCalledWith('s1')
    expect(state.sessions.value).toHaveLength(0)
    expect(state.session.value).toBeNull()
  })

  it('重命名后同步列表与当前会话', async () => {
    const state = useCoachChat()
    api.createCoachSession.mockResolvedValue(payload())
    await state.create(null)
    api.updateCoachSession.mockResolvedValue(
      payload({ session: { ...payload().session, title: '面试冲刺' } }),
    )

    const ok = await state.rename('s1', '面试冲刺')

    expect(ok).toBe(true)
    expect(state.session.value?.title).toBe('面试冲刺')
    expect(state.sessions.value[0]?.title).toBe('面试冲刺')
  })
})
