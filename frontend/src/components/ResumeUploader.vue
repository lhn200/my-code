<script setup lang="ts">
import { computed, ref } from 'vue'

import type { ResumeUploadResponse } from '@/api/types'
import type { UploadStatus } from '@/composables/useResumeIntake'
import { MAX_UPLOAD_BYTES, SUPPORTED_EXTENSIONS } from '@/composables/useResumeIntake'

const props = defineProps<{
  modelValue: string
  status: UploadStatus
  fileName?: string
  fileSize?: number
  errorMessage?: string
  result?: ResumeUploadResponse | null
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  select: [file: File]
  cancel: []
}>()

const inputRef = ref<HTMLInputElement | null>(null)
const dragging = ref(false)

const uploading = computed(() => props.status === 'uploading')
const displayName = computed(() => props.fileName || '')
const displaySize = computed(() => {
  if (!props.fileSize) {
    return ''
  }
  if (props.fileSize >= 1024 * 1024) {
    return `${(props.fileSize / (1024 * 1024)).toFixed(1)} MB`
  }
  return `${Math.max(1, Math.round(props.fileSize / 1024))} KB`
})
const pageCount = computed(() => props.result?.page_count ?? props.result?.pages ?? 0)

function pickFile(): void {
  if (uploading.value || props.disabled) {
    return
  }
  inputRef.value?.click()
}

function onFileChange(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) {
    emit('select', file)
  }
  input.value = ''
}

function onDrop(event: DragEvent): void {
  dragging.value = false
  if (uploading.value || props.disabled) {
    return
  }
  const file = event.dataTransfer?.files?.[0]
  if (file) {
    emit('select', file)
  }
}
</script>

<template>
  <div class="resume-uploader">
    <div
      class="drop-zone"
      :class="{ 'drop-zone-active': dragging, 'drop-zone-disabled': disabled || uploading }"
      role="button"
      tabindex="0"
      :aria-disabled="disabled || uploading"
      @click="pickFile"
      @keydown.enter.prevent="pickFile"
      @keydown.space.prevent="pickFile"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="onDrop"
    >
      <span class="drop-glyph" aria-hidden="true">档</span>
      <p class="drop-title">点击选择或拖拽简历文件到此处</p>
      <p class="drop-hint">
        支持 {{ SUPPORTED_EXTENSIONS.join(' / ') }}，单个文件不超过
        {{ Math.round(MAX_UPLOAD_BYTES / (1024 * 1024)) }}MB
      </p>
      <input
        ref="inputRef"
        class="visually-hidden"
        type="file"
        accept=".pdf,.docx,.png,.jpg,.jpeg,.webp"
        :disabled="disabled || uploading"
        @change="onFileChange"
      />
    </div>

    <div v-if="displayName" class="file-meta">
      <span class="tag">{{ displayName }}</span>
      <span v-if="displaySize" class="hint">{{ displaySize }}</span>
    </div>

    <p v-if="uploading" class="notice" role="status">
      正在上传并解析文件…
      <button type="button" class="link-button" @click="$emit('cancel')">取消上传</button>
    </p>

    <p v-if="status === 'error' && errorMessage" class="field-error" role="alert">
      {{ errorMessage }}
    </p>

    <template v-if="status === 'success' && result">
      <div class="parse-meta">
        <span class="tag tag--moss">页数：{{ pageCount }}</span>
        <span class="tag">来源：{{ result.used_ocr ? 'OCR 识别' : '文本提取' }}</span>
        <span class="tag">字符数：{{ result.char_count }}</span>
      </div>
      <p v-if="result.used_ocr" class="notice notice-warning" role="status">
        该文本由 OCR 识别生成，请先核对内容。
      </p>
      <p v-if="result.low_confidence" class="notice notice-warning" role="alert">
        识别置信度较低，请仔细核对解析文本后再提交分析。
      </p>
      <div class="field">
        <label :for="`resume-preview-${result.file_id}`">解析文本（可编辑）</label>
        <textarea
          :id="`resume-preview-${result.file_id}`"
          :value="modelValue"
          rows="10"
          @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
        ></textarea>
        <span class="hint">解析后的文本可继续手动编辑，修改会用于本次分析。</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.resume-uploader {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.drop-zone {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-6) var(--space-5);
  border: 1.5px dashed var(--color-border-strong);
  background: var(--color-bg);
  text-align: center;
  cursor: pointer;
  transition:
    border-color var(--dur-fast) var(--ease),
    background var(--dur-fast) var(--ease);
}

.drop-zone:hover,
.drop-zone-active {
  border-color: var(--color-primary);
  background: var(--color-surface);
}

.drop-zone-disabled {
  cursor: not-allowed;
  opacity: 0.65;
}

.drop-glyph {
  font-family: var(--font-serif);
  font-size: 30px;
  line-height: 1;
  color: var(--color-border-strong);
}

.drop-title {
  margin: 6px 0 0;
  font-weight: 600;
}

.drop-hint {
  margin: 0;
  font-size: 11px;
  color: var(--color-text-muted);
}

.file-meta {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.parse-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
</style>
