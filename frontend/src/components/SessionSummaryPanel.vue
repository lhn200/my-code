<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'

import type { SessionSummaryBody } from '@/api/memories'
import { useSessionSummary } from '@/composables/useSessionSummary'

const {
  sessions,
  sessionsLoading,
  sessionsError,
  selectedThreadId,
  summary,
  summaryLoading,
  summaryError,
  regenerating,
  outcome,
  outcomeMessage,
  loadSessions,
  select,
  regenerate,
  cancel,
} = useSessionSummary()

const SECTIONS: Array<{ key: keyof SessionSummaryBody; label: string }> = [
  { key: 'facts', label: '事实' },
  { key: 'open_questions', label: '待确认问题' },
  { key: 'preferences', label: '偏好' },
  { key: 'constraints', label: '约束' },
  { key: 'decisions', label: '决策' },
]

onMounted(() => {
  void loadSessions()
})

onUnmounted(() => {
  cancel()
})

function formatTime(value: string | null): string {
  if (!value) {
    return '—'
  }
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function statusLabel(status: string): string {
  if (status === 'completed') {
    return '已完成'
  }
  if (status === 'running') {
    return '进行中'
  }
  return status
}
</script>

<template>
  <section class="summary-panel" aria-labelledby="summary-heading">
    <p class="eyebrow">SESSION SUMMARY</p>
    <h2 id="summary-heading">会话摘要</h2>
    <p class="summary-sub">查看每个会话的滚动摘要，可手动重新生成。</p>

    <div class="summary-block">
      <p class="block-label">选择会话</p>
      <p v-if="sessionsLoading" class="summary-muted">正在加载会话…</p>
      <p v-else-if="sessionsError" class="notice notice-error">{{ sessionsError }}</p>
      <p v-else-if="!sessions.length" class="summary-muted">暂无会话。</p>

      <ul v-else class="session-list">
        <li v-for="item in sessions" :key="item.thread_id">
          <button
            type="button"
            class="session-button"
            :class="{ 'session-button-active': item.thread_id === selectedThreadId }"
            :aria-pressed="item.thread_id === selectedThreadId"
            @click="select(item.thread_id)"
          >
            <span class="session-title">{{ item.title }}</span>
            <span class="session-meta">
              {{ statusLabel(item.status) }} · {{ formatTime(item.updated_at) }}
            </span>
          </button>
        </li>
      </ul>
    </div>

    <div class="summary-block summary-stage">
      <p v-if="summaryLoading" class="summary-muted">正在加载摘要…</p>
      <p v-else-if="summaryError" class="notice notice-error">{{ summaryError }}</p>

      <template v-else-if="summary">
        <div class="meta-row">
          <span class="tag">版本 {{ summary.version }}</span>
          <span class="tag">摘要到第 {{ summary.summarized_through_turn }} 轮</span>
          <span class="tag">{{ summary.summary_status }}</span>
        </div>
        <p class="summary-updated">更新于 {{ formatTime(summary.updated_at) }}</p>

        <p v-if="!summary.summarized || !summary.summary" class="summary-muted">
          暂无摘要，可点击重新生成。
        </p>

        <template v-else>
          <div v-for="section in SECTIONS" :key="section.key" class="summary-section">
            <h3>{{ section.label }}</h3>
            <ul v-if="summary.summary[section.key].length">
              <li v-for="(entry, index) in summary.summary[section.key]" :key="index">
                {{ entry }}
              </li>
            </ul>
            <p v-else class="summary-muted">暂无</p>
          </div>
        </template>

        <div class="summary-actions">
          <button
            type="button"
            class="btn btn-primary"
            :disabled="regenerating || !selectedThreadId"
            @click="regenerate"
          >
            {{ regenerating ? '生成中…' : '重新生成摘要' }}
          </button>
          <span
            v-if="outcome !== 'idle'"
            class="notice"
            :class="{
              'notice-success': outcome === 'success',
              'notice-warning': outcome === 'no_turns' || outcome === 'conflict',
              'notice-error': outcome === 'failed',
            }"
          >
            {{ outcomeMessage }}
          </span>
        </div>
      </template>

      <p v-else class="summary-muted">选择左侧会话后查看摘要。</p>
    </div>
  </section>
</template>

<style scoped>
.summary-panel {
  position: sticky;
  top: 88px;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-5);
  border: 1px solid var(--color-text);
  background: var(--color-text);
  color: var(--color-on-ink);
}

.summary-panel .eyebrow {
  margin: 0;
  color: var(--color-on-ink-muted);
}

.summary-panel h2 {
  margin: 0;
  color: var(--color-on-ink);
  font-size: var(--text-xl);
  font-weight: 700;
}

.summary-sub {
  margin: -10px 0 0;
  color: var(--color-on-ink-soft);
  font-size: 11.5px;
  line-height: 1.7;
}

.summary-block {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-on-ink-line);
}

.block-label {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--color-on-ink-muted);
}

.summary-muted {
  margin: 0;
  color: var(--color-on-ink-muted);
  font-size: 11.5px;
}

.session-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 220px;
  overflow-y: auto;
}

.session-button {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  width: 100%;
  padding: 9px 12px;
  border: 1px solid var(--color-on-ink-line);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-on-ink-soft);
  text-align: left;
  transition:
    border-color var(--dur-fast) var(--ease),
    background var(--dur-fast) var(--ease);
}

.session-button:hover {
  border-color: var(--color-on-ink-muted);
  background: var(--color-on-ink-surface);
}

.session-button-active {
  border-color: var(--color-primary);
  background: var(--color-on-ink-surface);
}

.session-title {
  font-family: var(--font-serif);
  font-size: 13px;
  font-weight: 600;
  color: var(--color-on-ink);
}

.session-meta {
  font-family: var(--font-mono);
  font-size: 8.5px;
  color: var(--color-on-ink-dim);
}

.meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.summary-panel .tag {
  border-color: var(--color-on-ink-line);
  background: var(--color-on-ink-surface);
  color: var(--color-on-ink-soft);
}

.summary-updated {
  margin: -6px 0 0;
  font-family: var(--font-mono);
  font-size: 9px;
  color: var(--color-on-ink-dim);
}

.summary-section h3 {
  margin: 0 0 5px;
  color: var(--color-accent-soft);
  font-family: var(--font-mono);
  font-size: 9px;
  font-weight: 500;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.summary-section ul {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.summary-section li {
  display: flex;
  gap: 7px;
  color: var(--color-on-ink-soft);
  font-size: 12px;
  line-height: 1.7;
}

.summary-section li::before {
  content: "·";
  color: var(--color-on-ink-dim);
}

.summary-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-on-ink-line);
}

.summary-panel .btn {
  border-color: var(--color-on-ink-muted);
  color: var(--color-on-ink);
}

.summary-panel .btn-primary {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: var(--color-primary-contrast);
}

.summary-panel .notice {
  margin: 0;
  background: var(--color-on-ink-surface);
  border-color: var(--color-on-ink-line);
  color: var(--color-on-ink-soft);
}

.summary-panel .notice-success {
  border-color: var(--color-moss);
  color: var(--color-moss-soft);
}

.summary-panel .notice-warning {
  border-color: var(--color-amber);
  color: var(--color-amber-soft);
}

.summary-panel .notice-error {
  border-color: var(--color-primary);
  color: var(--color-accent-soft);
}

@media (max-width: 1024px) {
  .summary-panel {
    position: static;
  }
}
</style>
