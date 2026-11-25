import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/client'
import { MAX_JOBS, createJobDraft, useAnalysisForm } from '@/composables/useAnalysisForm'

function fillValid(form: ReturnType<typeof useAnalysisForm>): void {
  form.goal.value = '找一份后端工作'
  form.jobs.value[0].title = '后端工程师'
  form.jobs.value[0].positionText = '负责服务端开发'
  form.resumeText.value = '五年后端经验'
}

describe('useAnalysisForm', () => {
  it('拦截空目标、空岗位内容与空简历', () => {
    const form = useAnalysisForm()
    expect(form.validate('paste', false)).toBe(false)
    expect(form.fieldErrors.goal).toBe('请填写求职目标')
    expect(form.fieldErrors.resume_text).toBe('请粘贴简历文本')
    expect(form.fieldErrors[`jobs.${form.jobs.value[0].uid}.title`]).toBe('请填写岗位标题')
    expect(form.fieldErrors[`jobs.${form.jobs.value[0].uid}.positionText`]).toBe('请填写岗位 JD')
  })

  it('修正后可重新通过校验', () => {
    const form = useAnalysisForm()
    form.validate('paste', false)
    fillValid(form)
    expect(form.validate('paste', false)).toBe(true)
    expect(form.errorCount.value).toBe(0)
  })

  it('拦截没有岗位的场景', () => {
    const form = useAnalysisForm()
    form.goal.value = '目标'
    form.resumeText.value = '简历'
    form.jobs.value = []
    expect(form.validate('paste', false)).toBe(false)
    expect(form.fieldErrors.jobs).toBe('请至少填写 1 个岗位')
  })

  it('限制岗位数量为 5 个', () => {
    const form = useAnalysisForm()
    for (let index = 1; index < MAX_JOBS; index += 1) {
      expect(form.addJob()).toBe(true)
    }
    expect(form.jobs.value).toHaveLength(MAX_JOBS)
    expect(form.addJob()).toBe(false)
    expect(form.jobs.value).toHaveLength(MAX_JOBS)
  })

  it('上传模式要求成功解析结果', () => {
    const form = useAnalysisForm()
    fillValid(form)
    expect(form.validate('upload', false)).toBe(false)
    expect(form.fieldErrors.resume_text).toBe('请上传并解析简历文件')
    expect(form.validate('upload', true)).toBe(true)
  })

  it('三个岗位提交三条记录且 job_id 唯一', () => {
    const form = useAnalysisForm()
    fillValid(form)
    form.addJob()
    form.addJob()
    form.jobs.value[1].title = '前端工程师'
    form.jobs.value[1].positionText = '负责前端开发'
    form.jobs.value[2].title = '数据工程师'
    form.jobs.value[2].positionText = '负责数据管道'

    const payload = form.buildRequest()
    expect(payload.jobs).toHaveLength(3)
    expect(new Set(payload.jobs.map((job) => job.job_id)).size).toBe(3)
    expect(payload.jobs[2]).toMatchObject({
      title: '数据工程师',
      original_position_text: '负责数据管道',
    })
    expect(payload).not.toHaveProperty('thread_id')
  })

  it('同标题不同 JD 不合并', () => {
    const form = useAnalysisForm()
    fillValid(form)
    form.addJob()
    form.jobs.value[1].title = form.jobs.value[0].title
    form.jobs.value[1].positionText = '另一个岗位的 JD'

    const payload = form.buildRequest()
    expect(payload.jobs).toHaveLength(2)
    expect(payload.jobs[0].original_position_text).not.toBe(
      payload.jobs[1].original_position_text,
    )
  })

  it('删除中间岗位后保持顺序', () => {
    const form = useAnalysisForm()
    fillValid(form)
    form.addJob()
    form.addJob()
    form.jobs.value[0].title = '岗位 A'
    form.jobs.value[1].title = '岗位 B'
    form.jobs.value[2].title = '岗位 C'

    form.removeJob(form.jobs.value[1].uid)

    expect(form.buildRequest().jobs.map((job) => job.title)).toEqual(['岗位 A', '岗位 C'])
  })

  it('至少保留一个岗位', () => {
    const form = useAnalysisForm()
    form.removeJob(form.jobs.value[0].uid)
    expect(form.jobs.value).toHaveLength(1)
  })

  it('把 422 字段映射到具体岗位并汇总未知字段', () => {
    const form = useAnalysisForm()
    form.addJob()
    const target = form.jobs.value[1]

    form.applyApiError(
      new ApiError({
        status: 422,
        code: 'validation_error',
        message: 'request validation failed',
        fields: [
          { field: 'goal', type: 'blank', message: 'goal must not be blank' },
          {
            field: 'jobs[1].original_position_text',
            type: 'string_type',
            message: 'must be a string',
          },
          { field: 'unexpected_field', type: 'unexpected_field', message: '未知字段' },
        ],
      }),
    )

    expect(form.fieldErrors.goal).toBe('请填写求职目标')
    expect(form.fieldErrors[`jobs.${target.uid}.positionText`]).toBe('must be a string')
    expect(form.generalErrors.value).toContain('未知字段')
  })

  it('too_many_jobs 在顶部汇总', () => {
    const form = useAnalysisForm()
    form.applyApiError(
      new ApiError({
        status: 422,
        code: 'too_many_jobs',
        message: 'too many jobs',
        fields: [{ field: 'jobs', type: 'too_many_jobs', message: 'at most 5 jobs per run' }],
      }),
    )
    expect(form.generalErrors.value).toContain(`单次最多分析 ${MAX_JOBS} 个岗位`)
  })

  it('createJobDraft 生成稳定且唯一的标识', () => {
    const first = createJobDraft()
    const second = createJobDraft()
    expect(first.uid).not.toBe(second.uid)
    expect(first.jobId).toBe(first.uid)
  })
})
