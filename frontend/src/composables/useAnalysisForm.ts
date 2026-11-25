import { computed, reactive, ref } from 'vue'

import type { ApiError } from '@/api/client'
import type { RunRequest } from '@/api/types'

export const MAX_JOBS = 5

export interface JobDraft {
  uid: string
  jobId: string
  title: string
  positionText: string
}

export type ResumeMode = 'paste' | 'upload'

let jobSeq = 0

export function createJobDraft(): JobDraft {
  jobSeq += 1
  return {
    uid: `job-${jobSeq}`,
    jobId: `job-${jobSeq}`,
    title: '',
    positionText: '',
  }
}

function translationFor(field: string, type: string, fallback: string): string {
  const required = type === 'blank' || type === 'missing'
  if (field === 'goal') {
    return required ? '请填写求职目标' : fallback
  }
  if (field === 'resume_text') {
    return required ? '请提供简历内容' : fallback
  }
  if (field === 'jobs') {
    return type === 'too_many_jobs'
      ? `单次最多分析 ${MAX_JOBS} 个岗位`
      : required
        ? '请至少填写 1 个岗位'
        : fallback
  }
  if (field.endsWith('.title')) {
    return required ? '请填写岗位标题' : fallback
  }
  if (field.endsWith('.original_position_text')) {
    return required ? '请填写岗位 JD' : fallback
  }
  return fallback
}

export function useAnalysisForm() {
  const goal = ref('')
  const jobs = ref<JobDraft[]>([createJobDraft()])
  const resumeText = ref('')
  const fieldErrors = reactive<Record<string, string>>({})
  const generalErrors = ref<string[]>([])

  const errorCount = computed(
    () => Object.keys(fieldErrors).length + generalErrors.value.length,
  )

  function resetErrors(): void {
    for (const key of Object.keys(fieldErrors)) {
      delete fieldErrors[key]
    }
    generalErrors.value = []
  }

  function setFieldError(key: string, message: string): void {
    fieldErrors[key] = message
  }

  function mapFieldPath(path: string): string | null {
    if (path === 'goal' || path === 'resume_text') {
      return path
    }
    if (path === 'jobs') {
      return 'jobs'
    }
    const match = /^jobs\[(\d+)\]\.(title|original_position_text|job_id)$/.exec(path)
    if (!match) {
      return null
    }
    const index = Number(match[1])
    const draft = jobs.value[index]
    if (!draft) {
      return null
    }
    if (match[2] === 'title') {
      return `jobs.${draft.uid}.title`
    }
    if (match[2] === 'original_position_text') {
      return `jobs.${draft.uid}.positionText`
    }
    return null
  }

  function applyApiError(error: ApiError): void {
    resetErrors()
    const unmapped: string[] = []
    for (const item of error.fields) {
      const key = mapFieldPath(item.field)
      if (!key) {
        unmapped.push(item.message)
        continue
      }
      if (key === 'jobs') {
        generalErrors.value.push(translationFor(item.field, item.type, item.message))
        continue
      }
      setFieldError(key, translationFor(item.field, item.type, item.message))
    }
    if (error.code === 'too_many_jobs') {
      const message = `单次最多分析 ${MAX_JOBS} 个岗位`
      if (!generalErrors.value.includes(message)) {
        generalErrors.value.push(message)
      }
    }
    if (unmapped.length) {
      generalErrors.value.push(...unmapped)
    }
    if (!error.fields.length && !generalErrors.value.length) {
      generalErrors.value.push(error.message || '提交失败，请稍后重试')
    }
  }

  function validate(mode: ResumeMode, hasUploadedText: boolean): boolean {
    resetErrors()
    if (!goal.value.trim()) {
      setFieldError('goal', '请填写求职目标')
    }
    if (jobs.value.length === 0) {
      setFieldError('jobs', '请至少填写 1 个岗位')
    } else if (jobs.value.length > MAX_JOBS) {
      generalErrors.value.push(`单次最多分析 ${MAX_JOBS} 个岗位`)
    }
    for (const job of jobs.value) {
      if (!job.title.trim()) {
        setFieldError(`jobs.${job.uid}.title`, '请填写岗位标题')
      }
      if (!job.positionText.trim()) {
        setFieldError(`jobs.${job.uid}.positionText`, '请填写岗位 JD')
      }
    }
    const resumeReady =
      Boolean(resumeText.value.trim()) && (mode === 'paste' || hasUploadedText)
    if (!resumeReady) {
      setFieldError(
        'resume_text',
        mode === 'paste' ? '请粘贴简历文本' : '请上传并解析简历文件',
      )
    }
    return errorCount.value === 0
  }

  function buildRequest(): RunRequest {
    return {
      goal: goal.value.trim(),
      resume_text: resumeText.value.trim(),
      jobs: jobs.value.map((job) => ({
        job_id: job.jobId,
        title: job.title.trim(),
        original_position_text: job.positionText,
      })),
    }
  }

  function addJob(): boolean {
    if (jobs.value.length >= MAX_JOBS) {
      return false
    }
    jobs.value.push(createJobDraft())
    return true
  }

  function removeJob(uid: string): void {
    if (jobs.value.length <= 1) {
      return
    }
    jobs.value = jobs.value.filter((job) => job.uid !== uid)
  }

  function setResumeText(text: string): void {
    resumeText.value = text
  }

  function reset(): void {
    goal.value = ''
    jobs.value = [createJobDraft()]
    resumeText.value = ''
    resetErrors()
  }

  return {
    goal,
    jobs,
    resumeText,
    fieldErrors,
    generalErrors,
    errorCount,
    validate,
    buildRequest,
    applyApiError,
    addJob,
    removeJob,
    setResumeText,
    resetErrors,
    reset,
    mapFieldPath,
  }
}
