<script setup lang="ts">
import { onUnmounted } from 'vue'
import { useRouter } from 'vue-router'

import ErrorNotice from '@/components/ErrorNotice.vue'
import LoadingState from '@/components/LoadingState.vue'
import { useRunQuery } from '@/composables/useRunQuery'

const router = useRouter()
const { threadId, isLoading, error, fieldError, query, cancel } = useRunQuery()

async function onSubmit(): Promise<void> {
  const found = await query()
  if (found) {
    await router.push({ name: 'run-detail', params: { threadId: found } })
  }
}

onUnmounted(cancel)
</script>

<template>
  <section class="page">
    <header class="page-header">
      <div>
        <div class="crumb">档案室 / <b>检索</b></div>
        <h1>查询会话</h1>
        <p>输入已有的 thread_id，查看分析结果或继续恢复会话。</p>
      </div>
      <span class="stamp stamp--gray">RETRIEVE</span>
    </header>

    <form class="card query-card" novalidate @submit.prevent="onSubmit">
      <div class="field">
        <label for="thread-id">thread_id</label>
        <input
          id="thread-id"
          v-model="threadId"
          class="thread-input"
          type="text"
          autocomplete="off"
          spellcheck="false"
          placeholder="例如：8f14e45fceea167a"
          :aria-invalid="Boolean(fieldError)"
          aria-describedby="thread-error"
        />
        <p v-if="fieldError" id="thread-error" class="field-error">{{ fieldError }}</p>
        <span class="hint">thread_id 可在分析结果页或会话列表中找到。</span>
      </div>

      <div class="query-actions">
        <button type="submit" class="btn btn-primary" :disabled="isLoading">
          {{ isLoading ? '查询中…' : '查询档案 →' }}
        </button>
        <span class="hint">仅能查询属于当前账号的会话。</span>
      </div>

      <LoadingState v-if="isLoading" label="正在查询会话…" />
      <ErrorNotice
        v-else-if="error"
        :message="error.message"
        :code="error.code"
        :thread-id="error.threadId"
        @retry="onSubmit"
      />
    </form>
  </section>
</template>

<style scoped>
.query-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  max-width: 760px;
  padding: var(--space-6);
}

.thread-input {
  padding: 14px 16px;
  font-family: var(--font-mono);
  font-size: 16px;
  letter-spacing: 0.04em;
}

.query-actions {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex-wrap: wrap;
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}

@media (max-width: 720px) {
  .query-card {
    padding: var(--space-4);
  }

  .thread-input {
    font-size: 14px;
  }
}
</style>
