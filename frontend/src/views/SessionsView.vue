<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import type { SessionItem } from '@/api/types'
import EmptyState from '@/components/EmptyState.vue'
import ErrorNotice from '@/components/ErrorNotice.vue'
import LoadingState from '@/components/LoadingState.vue'
import { useSessionList } from '@/composables/useSessionList'

const {
  params,
  items,
  total,
  isLoading,
  error,
  actionError,
  actionPendingId,
  totalPages,
  load,
  setPage,
  setTrashed,
  setQuery,
  restore,
  removeToTrash,
  purge,
  cancel,
} = useSessionList()

const search = ref('')
let searchTimer: ReturnType<typeof setTimeout> | null = null

watch(search, (value) => {
  if (searchTimer) {
    clearTimeout(searchTimer)
  }
  searchTimer = setTimeout(() => {
    void setQuery(value)
  }, 300)
})

onMounted(() => {
  void load()
})

onUnmounted(() => {
  if (searchTimer) {
    clearTimeout(searchTimer)
  }
  cancel()
})

const STATUS_LABELS: Record<string, string> = {
  succeeded: '已完成',
  completed: '已完成',
  partial: '部分完成',
  failed: '失败',
  running: '进行中',
  pending: '等待中',
  interrupted: '已中断',
  canceled: '已取消',
}

function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status
}

function statusTone(status: string): string {
  if (status === 'succeeded' || status === 'completed') {
    return 'stamp--moss'
  }
  if (status === 'partial' || status === 'running' || status === 'pending') {
    return 'stamp--amber'
  }
  if (status === 'failed') {
    return ''
  }
  return 'stamp--gray'
}

function shortId(value: string): string {
  return value.length > 10 ? `${value.slice(0, 8)}…` : value
}

function switchTab(trashed: boolean): void {
  void setTrashed(trashed)
}

function formatTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

async function onRestore(item: SessionItem): Promise<void> {
  await restore(item.thread_id)
}

async function onRemove(item: SessionItem): Promise<void> {
  await removeToTrash(item.thread_id)
}

async function onPurge(item: SessionItem): Promise<void> {
  const confirmed = window.confirm(`确定永久删除「${item.title}」吗？该操作不可恢复。`)
  if (!confirmed) {
    return
  }
  await purge(item.thread_id)
}

function isBusy(item: SessionItem): boolean {
  return actionPendingId.value === item.thread_id
}
</script>

<template>
  <section class="page">
    <header class="page-header">
      <div>
        <div class="crumb">档案室 / <b>会话目录</b></div>
        <h1>会话列表</h1>
        <p>管理你的分析会话，支持搜索、分页与回收站恢复。</p>
      </div>
      <RouterLink class="btn btn-primary btn-sm" to="/">新建分析</RouterLink>
    </header>

    <div class="card session-card">
      <div class="toolbar">
        <div class="tabs" role="tablist" aria-label="会话状态">
          <button
            type="button"
            role="tab"
            class="tab"
            :class="{ 'tab-active': !params.trashed }"
            :aria-selected="!params.trashed"
            @click="switchTab(false)"
          >
            活跃会话
          </button>
          <button
            type="button"
            role="tab"
            class="tab"
            :class="{ 'tab-active': params.trashed }"
            :aria-selected="params.trashed"
            @click="switchTab(true)"
          >
            回收站
          </button>
        </div>

        <div class="search-field">
          <label class="visually-hidden" for="session-search">搜索标题</label>
          <input
            id="session-search"
            v-model="search"
            type="search"
            placeholder="搜索会话标题…"
          />
        </div>
      </div>

      <p v-if="actionError" class="field-error" role="alert">{{ actionError }}</p>

      <LoadingState v-if="isLoading" label="正在加载会话列表…" />
      <ErrorNotice
        v-else-if="error"
        :message="error.message"
        :code="error.code"
        @retry="load"
      />
      <EmptyState
        v-else-if="!items.length"
        :title="params.trashed ? '回收站为空' : '还没有会话'"
        :description="
          params.trashed ? '删除的会话会在这里保留一段时间。' : '创建一次分析后，会话会出现在这里。'
        "
      />

      <template v-else>
        <div class="table-head" aria-hidden="true">
          <span>会话</span>
          <span>状态</span>
          <span>更新时间</span>
          <span>操作</span>
        </div>

        <ul class="session-list">
          <li v-for="item in items" :key="item.thread_id" class="session-item">
            <div class="session-main">
              <RouterLink
                v-if="!params.trashed"
                class="session-title"
                :to="{ name: 'run-detail', params: { threadId: item.thread_id } }"
              >
                {{ item.title }}
              </RouterLink>
              <p v-else class="session-title">{{ item.title }}</p>
              <span class="session-id" :title="item.thread_id">
                THREAD {{ shortId(item.thread_id) }}
              </span>
              <span v-if="item.deleted_at" class="session-deleted">
                删除于 {{ formatTime(item.deleted_at) }}
              </span>
            </div>

            <div class="session-status">
              <span class="stamp" :class="statusTone(item.status)" :title="item.status">
                {{ statusLabel(item.status) }}
              </span>
            </div>

            <div class="session-time">{{ formatTime(item.updated_at) }}</div>

            <div class="session-actions">
              <RouterLink
                v-if="!params.trashed"
                class="btn btn-sm"
                :to="{ name: 'run-detail', params: { threadId: item.thread_id } }"
              >
                查看
              </RouterLink>
              <button
                v-if="!params.trashed"
                type="button"
                class="btn btn-sm btn-danger"
                :disabled="isBusy(item)"
                @click="onRemove(item)"
              >
                删除
              </button>
              <button
                v-if="params.trashed"
                type="button"
                class="btn btn-sm"
                :disabled="isBusy(item)"
                @click="onRestore(item)"
              >
                恢复
              </button>
              <button
                v-if="params.trashed"
                type="button"
                class="btn btn-sm btn-danger"
                :disabled="isBusy(item)"
                @click="onPurge(item)"
              >
                永久删除
              </button>
            </div>
          </li>
        </ul>

        <div class="pagination">
          <span class="pagination-info">
            第 {{ params.page }} / {{ totalPages() }} 页 · 共 {{ total }} 条
          </span>
          <div class="row">
            <button
              type="button"
              class="btn btn-sm"
              :disabled="params.page <= 1 || isLoading"
              @click="setPage(params.page - 1)"
            >
              上一页
            </button>
            <button
              type="button"
              class="btn btn-sm"
              :disabled="params.page >= totalPages() || isLoading"
              @click="setPage(params.page + 1)"
            >
              下一页
            </button>
          </div>
        </div>
      </template>
    </div>
  </section>
</template>

<style scoped>
.session-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  flex-wrap: wrap;
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--color-border);
}

.tabs {
  display: flex;
  gap: var(--space-5);
}

.tab {
  padding: 4px 0;
  border: none;
  border-bottom: 1.5px solid transparent;
  background: none;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.tab:hover {
  color: var(--color-text);
}

.tab-active {
  border-bottom-color: var(--color-primary);
  color: var(--color-primary);
  font-weight: 600;
}

.search-field {
  min-width: 240px;
}

.search-field input {
  padding: 8px 12px;
}

.table-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 130px 170px 200px;
  gap: var(--space-4);
  padding: 0 var(--space-3) 8px;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--color-text-muted);
  border-bottom: 1px solid var(--color-text);
}

.session-list {
  display: flex;
  flex-direction: column;
  border-top: 1px solid var(--color-border);
}

.session-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 130px 170px 200px;
  gap: var(--space-4);
  align-items: center;
  padding: 14px var(--space-3);
  border-bottom: 1px solid var(--color-border);
  transition: background var(--dur-fast) var(--ease);
}

.session-item:hover {
  background: var(--color-bg);
}

.session-main {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.session-title {
  margin: 0;
  overflow: hidden;
  color: var(--color-text);
  font-family: var(--font-serif);
  font-size: 15px;
  font-weight: 600;
  text-decoration: none;
  text-overflow: ellipsis;
  white-space: nowrap;
}

a.session-title:hover {
  color: var(--color-primary);
}

.session-id {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.08em;
  color: var(--color-ink-3);
}

.session-deleted {
  font-size: 10px;
  color: var(--color-primary);
}

.session-time {
  font-family: var(--font-mono);
  font-size: 10px;
  line-height: 1.6;
  color: var(--color-text-muted);
}

.session-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
  padding-top: var(--space-2);
}

.pagination-info {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--color-text-muted);
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

@media (max-width: 1024px) {
  .table-head {
    display: none;
  }

  .session-item {
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas:
      "main status"
      "time actions";
    row-gap: var(--space-2);
  }

  .session-main {
    grid-area: main;
  }

  .session-status {
    grid-area: status;
    justify-self: end;
  }

  .session-time {
    grid-area: time;
  }

  .session-actions {
    grid-area: actions;
  }
}

@media (max-width: 720px) {
  .session-item {
    grid-template-columns: 1fr;
    grid-template-areas:
      "main"
      "status"
      "time"
      "actions";
  }

  .session-status,
  .session-actions {
    justify-self: start;
    justify-content: flex-start;
  }

  .search-field {
    width: 100%;
    min-width: 0;
  }
}
</style>
