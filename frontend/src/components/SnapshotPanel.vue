<script setup lang="ts">
import type { ApiError } from '@/api/client'
import type { RunStatePayload, SnapshotSummary } from '@/api/types'
import EmptyState from './EmptyState.vue'
import ErrorNotice from './ErrorNotice.vue'
import LoadingState from './LoadingState.vue'
import RunResults from './RunResults.vue'

defineProps<{
  snapshots: SnapshotSummary[]
  isLoading: boolean
  error: ApiError | null
  selected: RunStatePayload | null
  selectedCheckpoint: string
  isSelecting: boolean
  selectionError: ApiError | null
}>()

defineEmits<{
  refresh: []
  select: [checkpointId: string]
  close: []
}>()

function formatTime(value: string): string {
  if (!value) {
    return '时间未知'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString()
}
</script>

<template>
  <section class="card snapshot-panel" aria-labelledby="snapshots-heading">
    <div class="snapshot-header">
      <div>
        <p class="eyebrow">CHECKPOINTS</p>
        <h2 id="snapshots-heading">历史快照</h2>
      </div>
      <button type="button" class="btn btn-ghost btn-sm" @click="$emit('refresh')">刷新快照</button>
    </div>

    <LoadingState v-if="isLoading" label="正在加载快照…" />
    <ErrorNotice
      v-else-if="error"
      :message="error.message"
      :code="error.code"
      @retry="$emit('refresh')"
    />
    <EmptyState
      v-else-if="!snapshots.length"
      title="暂无历史快照"
      description="运行产生检查点后，这里会按时间顺序展示。"
    />
    <ol v-else class="snapshot-list">
      <li v-for="snapshot in snapshots" :key="snapshot.checkpoint_id">
        <button
          type="button"
          class="snapshot-button"
          :class="{ 'snapshot-active': snapshot.checkpoint_id === selectedCheckpoint }"
          :disabled="isSelecting"
          @click="$emit('select', snapshot.checkpoint_id)"
        >
          <span class="snapshot-step">第 {{ snapshot.step }} 步</span>
          <span class="snapshot-time">{{ formatTime(snapshot.created_at) }}</span>
        </button>
      </li>
    </ol>

    <LoadingState v-if="isSelecting" label="正在读取历史快照…" />
    <ErrorNotice
      v-if="selectionError"
      :message="selectionError.message"
      :code="selectionError.code"
      :retryable="false"
    />

    <div v-if="selected && !isSelecting" class="snapshot-view">
      <div class="snapshot-view-header">
        <p class="notice notice-warning" role="status">历史快照，非当前状态</p>
        <button type="button" class="btn btn-sm" @click="$emit('close')">关闭快照</button>
      </div>
      <RunResults :result="selected.result" :state="selected.state" />
    </div>
  </section>
</template>

<style scoped>
.snapshot-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--color-border);
}

.snapshot-header h2 {
  margin: 4px 0 0;
  font-size: var(--text-lg);
}

.snapshot-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--space-2);
}

.snapshot-button {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  width: 100%;
  padding: 10px 13px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg);
  text-align: left;
  transition:
    border-color var(--dur-fast) var(--ease),
    background var(--dur-fast) var(--ease);
}

.snapshot-button:hover:not(:disabled) {
  border-color: var(--color-text);
  background: var(--color-surface);
}

.snapshot-step {
  font-family: var(--font-serif);
  font-size: 13px;
  font-weight: 600;
}

.snapshot-time {
  font-family: var(--font-mono);
  font-size: 9px;
  color: var(--color-text-muted);
}

.snapshot-active {
  border-color: var(--color-primary);
  background: var(--color-surface);
  box-shadow: 2px 2px 0 var(--color-danger-wash);
}

.snapshot-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  margin-top: var(--space-4);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}

.snapshot-view-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.snapshot-view-header .notice {
  margin: 0;
}
</style>
