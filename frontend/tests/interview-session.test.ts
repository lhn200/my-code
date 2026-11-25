import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import type {
  InterviewSessionMessage,
  InterviewSessionPayload,
} from '@/api/types'

const api = vi.hoisted(() => ({
  getInterviewSession: vi.fn(),
  submitInterviewAnswer: vi.fn(),
  finishInterviewSession: vi.fn(),
}))

vi.mock('@/api/interviews', () => ({
  getInterviewSession: api.getInterviewSession,
  submitInterviewAnswer: api.submitInterviewAnswer,
  finishInterviewSession: api.finishInterviewSession,
}))

import { useInterviewSession } from '@/composables/useInterviewSession'

function message(overrides: Partial<InterviewSessionMessage> = {}): InterviewSessionMessage {
  return {
    id: 'm1',
    role: 'interviewer',
    kind: 'question',
    question_no: 1,
    content: '请介绍一下你最近的项目。',
    score: null,
    strengths: [],
    improvements: [],
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function payload(overrides: Partial<InterviewSessionPayload> = {}): InterviewSessionPayload {
  return {
    session: {
      id: 's1',
      thread_id: 't1',
      job_id: 'job-1',
      job_title: '后端工程师',
      status: 'active',
      planned_count: 5,
      asked_count: 1,
      current_question_no: 1,
      followups_used: 0,
      max_followups: 1,
      variant_version: 0,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      completed_at: null,
      ...overrides.session,
    },
    messages: overrides.messages ?? [message()],
    report: overrides.report ?? null,
  }
}

describe('useInterviewSession', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('加载会话后可作答', async () => {
    api.getInterviewSession.mockResolvedValue(payload())
    const state = useInterviewSession('s1')

    const ok = await state.load()

    expect(ok).toBe(true)
    expect(api.getInterviewSession).toHaveBeenCalledWith('s1')
    expect(state.messages.value).toHaveLength(1)
    expect(state.progress.value).toEqual({ asked: 1, planned: 5, current: 1 })
    expect(state.canAnswer.value).toBe(true)
  })

  it('提交回答后追加反馈与下一题', async () => {
    api.getInterviewSession.mockResolvedValue(payload())
    api.submitInterviewAnswer.mockResolvedValue(
      payload({
        session: { ...payload().session, asked_count: 2, current_question_no: 2 } as never,
        messages: [
          message(),
          message({ id: 'm2', role: 'candidate', kind: 'answer', content: '我负责了数据平台。' }),
          message({ id: 'm3', role: 'interviewer', kind: 'feedback', content: '结构清晰。', score: 78 }),
          message({ id: 'm4', question_no: 2, content: '请说明量化结果。' }),
        ],
      }),
    )
    const state = useInterviewSession('s1')
    await state.load()

    const ok = await state.answer('我负责了数据平台。')

    expect(ok).toBe(true)
    expect(api.submitInterviewAnswer).toHaveBeenCalledWith('s1', '我负责了数据平台。')
    expect(state.messages.value).toHaveLength(4)
    expect(state.canAnswer.value).toBe(true)
    expect(state.session.value?.asked_count).toBe(2)
  })

  it('待生成报告时不可继续作答', async () => {
    const last = message({ id: 'm2', kind: 'feedback', role: 'interviewer', score: 80 })
    api.getInterviewSession.mockResolvedValue(
      payload({
        session: { ...payload().session, status: 'ready_to_finish' } as never,
        messages: [message(), last],
      }),
    )
    const state = useInterviewSession('s1')
    await state.load()

    expect(state.canAnswer.value).toBe(false)
    await state.answer('再补一句')
    expect(api.submitInterviewAnswer).not.toHaveBeenCalled()
  })

  it('生成报告后状态为已完成', async () => {
    api.getInterviewSession.mockResolvedValue(
      payload({
        session: { ...payload().session, status: 'ready_to_finish' } as never,
        messages: [message(), message({ id: 'm2', kind: 'feedback' })],
      }),
    )
    api.finishInterviewSession.mockResolvedValue(
      payload({
        session: {
          ...payload().session,
          status: 'completed',
          completed_at: '2026-01-02T00:00:00Z',
        } as never,
        messages: [message(), message({ id: 'm2', kind: 'feedback' })],
        report: {
          job_id: 'job-1',
          interview_thread_id: 'practice-s1',
          status: 'completed',
          generated_at: '2026-01-02T00:00:00Z',
          source: 'practice',
          session_id: 's1',
          dimension_averages: { skills: 80 },
          overall_score: 80,
          highlights: ['表达清晰'],
          red_flags: [],
          improvements: ['补充数据'],
          requirement_gaps: ['Kubernetes'],
          answered_count: 5,
          planned_count: 5,
        },
      }),
    )
    const state = useInterviewSession('s1')
    await state.load()

    const ok = await state.finish()

    expect(ok).toBe(true)
    expect(api.finishInterviewSession).toHaveBeenCalledWith('s1')
    expect(state.isCompleted.value).toBe(true)
    expect(state.report.value?.source).toBe('practice')
  })

  it('作答失败时保留会话并暴露错误码', async () => {
    api.getInterviewSession.mockResolvedValue(payload())
    api.submitInterviewAnswer.mockRejectedValue(
      new ApiError({ status: 502, code: 'interview_generation_failed', message: '模型不可用' }),
    )
    const state = useInterviewSession('s1')
    await state.load()

    const ok = await state.answer('我的回答')

    expect(ok).toBe(false)
    expect(state.error.value?.code).toBe('interview_generation_failed')
    expect(state.messages.value).toHaveLength(1)
    expect(state.canAnswer.value).toBe(true)
  })

  it('加载 404 会话时暴露 interview_not_found', async () => {
    api.getInterviewSession.mockRejectedValue(
      new ApiError({ status: 404, code: 'interview_not_found', message: '不存在' }),
    )
    const state = useInterviewSession('missing')

    const ok = await state.load()

    expect(ok).toBe(false)
    expect(state.error.value?.code).toBe('interview_not_found')
    expect(state.session.value).toBeNull()
  })
})
