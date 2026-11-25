import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { uploadResume } from '@/api/resumes'
import type { ResumeUploadResponse } from '@/api/types'
import ResumeUploader from '@/components/ResumeUploader.vue'
import {
  MAX_UPLOAD_BYTES,
  useResumeIntake,
  validateResumeFile,
} from '@/composables/useResumeIntake'

vi.mock('@/api/resumes', () => ({ uploadResume: vi.fn() }))

const uploadMock = vi.mocked(uploadResume)

function makeFile(name: string, size?: number): File {
  const file = new File(['content'], name, { type: 'application/octet-stream' })
  if (size !== undefined) {
    Object.defineProperty(file, 'size', { value: size })
  }
  return file
}

const parsed: ResumeUploadResponse = {
  file_id: 'file-1',
  file_url: null,
  source_type: 'pdf',
  page_count: 2,
  used_ocr: false,
  char_count: 42,
  low_confidence: true,
  text: '解析出来的简历文本',
}

describe('useResumeIntake', () => {
  it('拦截不支持的文件类型', async () => {
    const intake = useResumeIntake()
    const accepted = await intake.selectFile(makeFile('resume.txt'))

    expect(accepted).toBe(false)
    expect(uploadMock).not.toHaveBeenCalled()
    expect(intake.status.value).toBe('error')
    expect(intake.errorCode.value).toBe('client_validation')
    expect(intake.errorMessage.value).toContain('不支持的文件类型')
  })

  it('拦截超过 5MB 的文件', () => {
    const message = validateResumeFile(makeFile('resume.pdf', MAX_UPLOAD_BYTES + 1))
    expect(message).toContain('5MB')
  })

  it('上传成功回填解析文本', async () => {
    uploadMock.mockResolvedValue(parsed)
    const onParsed = vi.fn()
    const intake = useResumeIntake({ onParsed })

    const accepted = await intake.selectFile(makeFile('resume.pdf'))

    expect(accepted).toBe(true)
    expect(intake.status.value).toBe('success')
    expect(intake.hasParsedResult.value).toBe(true)
    expect(intake.result.value?.page_count).toBe(2)
    expect(onParsed).toHaveBeenCalledWith('解析出来的简历文本')
  })

  it('上传失败时映射错误码文案', async () => {
    uploadMock.mockRejectedValue(
      new ApiError({
        status: 422,
        code: 'resume_encrypted',
        message: 'pdf is encrypted',
        kind: 'http',
      }),
    )
    const intake = useResumeIntake()

    const accepted = await intake.selectFile(makeFile('resume.pdf'))

    expect(accepted).toBe(false)
    expect(intake.status.value).toBe('error')
    expect(intake.errorCode.value).toBe('resume_encrypted')
    expect(intake.errorMessage.value).toContain('加密')
  })

  it('上传中禁止重复选择', async () => {
    let resolveUpload: ((value: ResumeUploadResponse) => void) | undefined
    uploadMock.mockImplementation(
      () =>
        new Promise<ResumeUploadResponse>((resolve) => {
          resolveUpload = resolve
        }),
    )
    const intake = useResumeIntake()

    const first = intake.selectFile(makeFile('resume.pdf'))
    const second = await intake.selectFile(makeFile('resume.pdf'))

    expect(second).toBe(false)
    expect(uploadMock).toHaveBeenCalledTimes(1)

    resolveUpload?.(parsed)
    await first
    expect(intake.status.value).toBe('success')
  })

  it('取消上传后回到空闲态', async () => {
    uploadMock.mockImplementation(
      (_file, options) =>
        new Promise<ResumeUploadResponse>((_resolve, reject) => {
          options?.signal?.addEventListener('abort', () => {
            reject(
              new ApiError({
                code: 'request_canceled',
                message: '请求已取消',
                kind: 'canceled',
              }),
            )
          })
        }),
    )
    const intake = useResumeIntake()

    const pending = intake.selectFile(makeFile('resume.pdf'))
    intake.cancel()

    await pending
    expect(intake.status.value).toBe('idle')
  })
})

describe('ResumeUploader', () => {
  it('展示 OCR、页数与低置信度提示，并支持编辑解析文本', async () => {
    const wrapper = mount(ResumeUploader, {
      props: {
        modelValue: '原始文本',
        status: 'success',
        fileName: 'resume.png',
        fileSize: 2048,
        result: { ...parsed, used_ocr: true, low_confidence: true },
      },
    })

    const text = wrapper.text()
    expect(text).toContain('页数：2')
    expect(text).toContain('OCR')
    expect(text).toContain('识别置信度较低')

    await wrapper.find('textarea').setValue('修改后的文本')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['修改后的文本'])
  })

  it('上传失败展示错误信息', () => {
    const wrapper = mount(ResumeUploader, {
      props: {
        modelValue: '',
        status: 'error',
        errorMessage: '文件超过 5MB 上限，请压缩后重试',
        result: null,
      },
    })

    expect(wrapper.text()).toContain('文件超过 5MB 上限')
  })
})
