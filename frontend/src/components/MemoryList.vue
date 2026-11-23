<script setup lang="ts">
import type { MemoryItem, MemoryKind } from '@/api/memories'

defineProps<{
  items: MemoryItem[]
  pendingId?: string
}>()

const emit = defineEmits<{
  (event: 'remove', item: MemoryItem): void
  (event: 'confirm', item: MemoryItem): void
  (event: 'ignore', item: MemoryItem): void
}>()

const KIND_LABELS: Record<MemoryKind, string> = {
  preference: '偏好',
  goal: '目标',
  fact: '事实',
  constraint: '约束',
}

const KIND_TONES: Record<MemoryKind, string> = {
  preference: 'tag--blue',
  goal: 'tag--moss',
  fact: 'tag',
  constraint: 'tag--amber',
}

const STATUS_LABELS: Record<MemoryItem['status'], string> = {
  active: '生效中',
  pending_confirmation: '待确认',
  archived: '已归档',
}

const ARCHIVE_LABELS: Record<string, string> = {
  ttl: '过期自动归档',
  manual: '手动归档',
  conflict: '冲突归档',
  deleted: '来源会话已删除',
}

function formatTime(value: string | null): string {
  if (!value) {
    return '—'
  }
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function archiveLabel(reason: string | null): string {
  if (!reason) {
    return ''
  }
  return ARCHIVE_LABELS[reason] ?? reason
}

function onRemove(item: MemoryItem): void {
  const confirmed = window.confirm(`确定删除这条记忆吗？\n\n${item.content}`)
  if (confirmed) {
    emit('remove', item)
  }
}
</script>

<template>
  <ul class="memory-list">
    <li
      v-for="item in items"
      :key="item.id"
      class="memory-item"
      :class="{
        'memory-item-pending': item.status === 'pending_confirmation',
        'memory-item-archived': item.status === 'archived',
      }"
    >
      <div class="memory-meta">
        <span class="tag" :class="KIND_TONES[item.kind]">{{ KIND_LABELS[item.kind] }}</span>
        <span class="stamp" :class="item.status === 'archived' ? 'stamp--gray' : 'stamp--moss'">
          {{ STATUS_LABELS[item.status] }}
        </span>
        <span class="memory-confidence">CONF {{ Math.round(item.confidence * 100) }}%</span>
        <span v-if="item.status === 'archived'" class="memory-time">
          {{ archiveLabel(item.archived_reason) }}
        </span>
        <span v-else class="memory-time">更新于 {{ formatTime(item.updated_at) }}</span>
        <span v-if="item.expires_at" class="memory-time">有效期至 {{ formatTime(item.expires_at) }}</span>
      </div>

      <p class="memory-content">{{ item.content }}</p>

      <div class="row memory-actions">
        <button
          v-if="item.status === 'pending_confirmation'"
          type="button"
          class="btn btn-sm btn-primary"
          :disabled="pendingId === item.id"
          @click="emit('confirm', item)"
        >
          确认
        </button>
        <button
          v-if="item.status === 'pending_confirmation'"
          type="button"
          class="btn btn-sm"
          :disabled="pendingId === item.id"
          @click="emit('ignore', item)"
        >
          忽略
        </button>
        <button
          type="button"
          class="btn btn-sm btn-danger"
          :disabled="pendingId === item.id"
          @click="onRemove(item)"
        >
          删除
        </button>
      </div>
    </li>
  </ul>
</template>

<style scoped>
.memory-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.memory-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: 14px var(--space-4);
  border: 1px solid var(--color-border);
  border-left: 2px solid var(--color-border-strong);
  background: var(--color-bg);
}

.memory-item-pending {
  border-left-color: var(--color-amber);
  background: var(--color-surface);
}

.memory-item-archived {
  opacity: 0.72;
}

.memory-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

.memory-confidence,
.memory-time {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.05em;
  color: var(--color-text-muted);
}

.memory-content {
  margin: 0;
  font-family: var(--font-serif);
  font-size: 14.5px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
}

.memory-actions {
  gap: var(--space-2);
}
</style>
