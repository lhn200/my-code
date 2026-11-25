// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>()
  return { ...actual, useRouter: () => ({ push: vi.fn() }) }
})

import type { JobResult, RunResult } from '@/api/types'
import JobCard from '@/components/JobCard.vue'
import RunResults from '@/components/RunResults.vue'
import SnapshotPanel from '@/components/SnapshotPanel.vue'

function makeJob(overrides: Partial<JobResult> = {}): JobResult {
  const jobId = overrides.job_id ?? 'job-1'
  const base: JobResult = {
    job_id: jobId,
    title: '后端工程师',
    status: 'ok',
    error: null,
    profile: {
      job_id: jobId,
      title: '后端工程师',
      company: '示例公司',
      must_have: [],
      nice_to_have: [],
      responsibilities: [],
      keywords: [],
      status: 'ok',
      error: null,
    },
    resume_source: 'baseline',
    current_variant_version: 0,
    resume_text: '简历',
    review: {
      job_id: jobId,
      variant_version: 0,
      score: 80,
      dimensions: {},
      matched: [],
      missing: [],
      issues: [],
      status: 'ok',
      error: null,
    },
    variants: [],
    optimization_history: [],
    ...overrides,
  }
  return base
}

function makeResult(jobs: JobResult[], runStatus: RunResult['run_status'] = 'succeeded'): RunResult {
  return {
    run_status: runStatus,
    thread_id: 'thread-1',
    advice: '## 建议\n\n- 补充项目经历',
    jobs,
    interview_reports: {},
  }
}

describe('JobCard', () => {
  it('评分 0 与 100 都正确显示', () => {
    const zero = mount(JobCard, {
      props: { job: makeJob({ review: { ...makeJob().review!, score: 0 } }) },
    })
    expect(zero.find('.score-value').text()).toBe('0')

    const hundred = mount(JobCard, {
      props: { job: makeJob({ review: { ...makeJob().review!, score: 100 } }) },
    })
    expect(hundred.find('.score-value').text()).toBe('100')
  })

  it('缺失项为空时展示无缺失项', () => {
    const wrapper = mount(JobCard, { props: { job: makeJob() } })
    expect(wrapper.text()).toContain('无缺失项')
  })

  it('失败岗位展示失败原因且不展示评分', () => {
    const wrapper = mount(JobCard, {
      props: {
        job: makeJob({ status: 'failed', review: null, error: '模型调用失败' }),
      },
    })

    expect(wrapper.text()).toContain('该岗位分析失败')
    expect(wrapper.text()).toContain('模型调用失败')
    expect(wrapper.find('.score-badge').exists()).toBe(false)
  })

  it('有简历文本时展示下载按钮并派发事件', async () => {
    const wrapper = mount(JobCard, { props: { job: makeJob() } })
    const button = wrapper.findAll('button').find((item) => item.text().includes('下载 PDF'))

    expect(button).toBeTruthy()
    await button!.trigger('click')
    expect(wrapper.emitted('download')).toHaveLength(1)
  })

  it('没有简历文本时不展示下载按钮', () => {
    const wrapper = mount(JobCard, { props: { job: makeJob({ resume_text: '' }) } })

    expect(wrapper.findAll('button').some((item) => item.text().includes('下载 PDF'))).toBe(false)
  })
})

describe('RunResults', () => {
  it('正常三岗位展示三张卡片与成功提示', () => {
    const jobs = [
      makeJob({ job_id: 'job-1', title: '岗位 A' }),
      makeJob({ job_id: 'job-2', title: '岗位 B' }),
      makeJob({ job_id: 'job-3', title: '岗位 C' }),
    ]
    const wrapper = mount(RunResults, { props: { result: makeResult(jobs) } })

    expect(wrapper.findAll('.job-card')).toHaveLength(3)
    expect(wrapper.find('.notice-success').text()).toContain('全部岗位分析成功')
    expect(wrapper.text()).toContain('补充项目经历')
  })

  it('部分失败时同时展示成功岗位与失败卡片', () => {
    const jobs = [
      makeJob({ job_id: 'job-1', title: '岗位 A' }),
      makeJob({
        job_id: 'job-2',
        title: '岗位 B',
        status: 'failed',
        review: null,
        error: '岗位 B 分析失败',
      }),
    ]
    const wrapper = mount(RunResults, { props: { result: makeResult(jobs, 'partial') } })

    expect(wrapper.find('.notice-warning').text()).toContain('部分岗位分析成功')
    expect(wrapper.findAll('.job-card')).toHaveLength(2)
    expect(wrapper.find('.job-card-failed').text()).toContain('岗位 B 分析失败')
  })

  it('优化历史为空展示空状态', () => {
    const wrapper = mount(RunResults, { props: { result: makeResult([makeJob()]) } })
    expect(wrapper.text()).toContain('未触发简历优化')
  })

  it('达到轮数上限仍未达标时给出风险提示', () => {
    const job = makeJob({
      current_variant_version: 3,
      review: { ...makeJob().review!, score: 60, variant_version: 3 },
      optimization_history: [
        {
          job_id: 'job-1',
          round: 1,
          variant_version: 1,
          score_before: 50,
          score_after: 60,
          summary: '补充技能关键词',
        },
      ],
    })

    const wrapper = mount(RunResults, {
      props: {
        result: makeResult([job]),
        state: { max_rounds: 3, threshold: 80 },
      },
    })

    expect(wrapper.text()).toContain('达到轮数上限仍未达标')
  })
})

describe('SnapshotPanel', () => {
  it('快照列表为空展示空状态', () => {
    const wrapper = mount(SnapshotPanel, {
      props: {
        snapshots: [],
        isLoading: false,
        error: null,
        selected: null,
        selectedCheckpoint: '',
        isSelecting: false,
        selectionError: null,
      },
    })

    expect(wrapper.text()).toContain('暂无历史快照')
  })
})
