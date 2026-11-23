<script setup lang="ts">
defineProps<{
  message: string
  code?: string
  threadId?: string
  retryLabel?: string
  retryable?: boolean
}>()

defineEmits<{ retry: [] }>()
</script>

<template>
  <div class="notice notice-error error-notice" role="alert" aria-live="assertive">
    <p class="eyebrow">ERROR · 运行异常</p>
    <p class="error-message">{{ message }}</p>
    <div class="error-meta-row">
      <span v-if="code" class="tag tag--red">错误码 {{ code }}</span>
      <span v-if="threadId" class="error-meta">
        thread_id：<code>{{ threadId }}</code>
      </span>
    </div>
    <button v-if="retryable !== false" type="button" class="btn btn-sm" @click="$emit('retry')">
      {{ retryLabel ?? '重试' }}
    </button>
  </div>
</template>

<style scoped>
.error-notice {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
}

.error-notice .eyebrow {
  color: var(--color-primary-strong);
  margin: 0;
}

.error-message {
  margin: 0;
  font-weight: 600;
}

.error-meta-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.error-meta {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 10px;
  word-break: break-all;
}

code {
  font-family: var(--font-mono);
}
</style>
