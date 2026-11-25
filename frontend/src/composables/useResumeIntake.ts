import { computed, ref } from 'vue'

import { isApiError, toApiError, type ApiError } from '@/api/client'
import { uploadResume } from '@/api/resumes'
import type { ResumeUploadResponse } from '@/api/types'

export type UploadStatus = 'idle' | 'uploading' | 'success' | 'error'

export const SUPPORTED_EXTENSIONS = ['pdf', 'docx', 'png', 'jpg', 'jpeg', 'webp'] as const
export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024

const ERROR_MESSAGES: Record<string, string> = {
  resume_no_text: '未能从文件中提取到可用文字，请改用粘贴文本',
  resume_encrypted: '该 PDF 已加密，请解除密码后重试或改为粘贴文本',
  resume_unreadable: '文件无法解析，请检查文件是否损坏或改为粘贴文本',
  resume_unsupported_type: '不支持的文件类型，请上传 PDF、DOCX 或图片',
  resume_type_mismatch: '文件内容与扩展名不匹配，请确认文件类型',
  resume_too_large: '文件超过 5MB 上限，请压缩后重试',
  resume_empty: '文件为空，请重新选择',
  resume_ocr_limit: 'OCR 页数超过上限，请拆分文件或改用粘贴文本',
}

function fileExtension(name: string): string {
  const index = name.lastIndexOf('.')
  return index >= 0 ? name.slice(index + 1).toLowerCase() : ''
}

export function validateResumeFile(file: File): string {
  const extension = fileExtension(file.name)
  if (!SUPPORTED_EXTENSIONS.includes(extension as (typeof SUPPORTED_EXTENSIONS)[number])) {
    return `不支持的文件类型，请上传 ${SUPPORTED_EXTENSIONS.join('、')} 格式`
  }
  if (file.size <= 0) {
    return '文件为空，请重新选择'
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return '文件超过 5MB 上限，请压缩后重试'
  }
  return ''
}

export function resumeErrorMessage(error: ApiError): string {
  if (error.kind === 'timeout') {
    return '上传超时，请稍后重试或改用粘贴文本'
  }
  if (error.kind === 'network') {
    return '网络连接失败，请检查网络后重试'
  }
  return ERROR_MESSAGES[error.code] ?? error.message ?? '上传失败，请稍后重试'
}

export function useResumeIntake(options: { onParsed?: (text: string) => void } = {}) {
  const status = ref<UploadStatus>('idle')
  const selectedFile = ref<File | null>(null)
  const result = ref<ResumeUploadResponse | null>(null)
  const errorMessage = ref('')
  const errorCode = ref('')
  let controller: AbortController | null = null

  const isUploading = computed(() => status.value === 'uploading')
  const hasParsedResult = computed(
    () => status.value === 'success' && Boolean(result.value),
  )

  async function selectFile(file: File): Promise<boolean> {
    if (status.value === 'uploading') {
      return false
    }
    selectedFile.value = file
    result.value = null
    errorMessage.value = ''
    errorCode.value = ''

    const invalid = validateResumeFile(file)
    if (invalid) {
      status.value = 'error'
      errorCode.value = 'client_validation'
      errorMessage.value = invalid
      return false
    }

    controller?.abort()
    controller = new AbortController()
    status.value = 'uploading'
    try {
      const parsed = await uploadResume(file, { signal: controller.signal })
      result.value = parsed
      status.value = 'success'
      options.onParsed?.(parsed.text)
      return true
    } catch (error) {
      if (isApiError(error) && error.code === 'request_canceled') {
        status.value = 'idle'
        return false
      }
      const apiError = toApiError(error)
      status.value = 'error'
      errorCode.value = apiError.code
      errorMessage.value = resumeErrorMessage(apiError)
      return false
    } finally {
      controller = null
    }
  }

  function cancel(): void {
    controller?.abort()
    controller = null
    if (status.value === 'uploading') {
      status.value = 'idle'
    }
  }

  function reset(): void {
    controller?.abort()
    controller = null
    status.value = 'idle'
    selectedFile.value = null
    result.value = null
    errorMessage.value = ''
    errorCode.value = ''
  }

  return {
    status,
    selectedFile,
    result,
    errorMessage,
    errorCode,
    isUploading,
    hasParsedResult,
    selectFile,
    cancel,
    reset,
  }
}
