// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
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

import SessionSummaryPanel from '@/components/SessionSummaryPanel.vue'

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

async function mountPanel() {
  const wrapper = mount(SessionSummaryPanel)
  await flushPromises()
  return wrapper
}

async function openSummary(wrapper: Awaited<ReturnType<typeof mountPanel>>) {
  const button = wrapper
    .findAll('button')
    .find((item) => item.text().includes('会话 A'))
  expect(button).toBeTruthy()
  await button!.trigger('click')
  await flushPromises()
}

function regenerateButton(wrapper: Awaited<ReturnType<typeof mountPanel>>) {
  return wrapper.findAll('button').find((item) => item.text().includes('重新生成摘要'))
}

describe('SessionSummaryPanel', () => {
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

  it('展示会话与结构化摘要正文', async () => {
    const wrapper = await mountPanel()
    await openSummary(wrapper)

    expect(wrapper.text()).toContain('用户有三年运营经验')
    expect(wrapper.text()).toContain('版本 1')
    expect(wrapper.text()).toContain('摘要到第 6 轮')
  })

  it('重新生成成功展示成功提示', async () => {
    api.regenerateSessionSummary.mockResolvedValue({
      ...summary({ version: 2 }),
      regenerated: true,
    })
    const wrapper = await mountPanel()
    await openSummary(wrapper)

    await regenerateButton(wrapper)!.trigger('click')
    await flushPromises()

    expect(wrapper.find('.notice-success').text()).toContain('摘要已更新')
    expect(wrapper.text()).toContain('版本 2')
  })

  it('无新轮次展示提示', async () => {
    api.regenerateSessionSummary.mockResolvedValue({ ...summary(), regenerated: false })
    const wrapper = await mountPanel()
    await openSummary(wrapper)

    await regenerateButton(wrapper)!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('暂无新的未总结轮次')
  })

  it('冲突时展示冲突提示并加载最新摘要', async () => {
    api.regenerateSessionSummary.mockRejectedValue(
      new ApiError({ status: 409, code: 'summary_conflict', message: 'changed' }),
    )
    api.fetchSessionSummary
      .mockResolvedValueOnce(summary())
      .mockResolvedValueOnce(summary({ version: 4 }))
    const wrapper = await mountPanel()
    await openSummary(wrapper)

    await regenerateButton(wrapper)!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('摘要在其他操作中已更新')
    expect(wrapper.text()).toContain('版本 4')
  })

  it('生成失败时展示失败提示并保留原摘要', async () => {
    api.regenerateSessionSummary.mockRejectedValue(
      new ApiError({ status: 502, code: 'summary_failed', message: 'model down' }),
    )
    const wrapper = await mountPanel()
    await openSummary(wrapper)

    await regenerateButton(wrapper)!.trigger('click')
    await flushPromises()

    expect(wrapper.find('.notice-error').text()).toContain('摘要生成失败')
    expect(wrapper.text()).toContain('版本 1')
    expect(wrapper.text()).toContain('用户有三年运营经验')
  })
})
