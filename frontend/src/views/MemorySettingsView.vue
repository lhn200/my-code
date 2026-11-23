<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import type { MemoryItem, MemoryKind } from '@/api/memories'
import EmptyState from '@/components/EmptyState.vue'
import MemoryList from '@/components/MemoryList.vue'
import SessionSummaryPanel from '@/components/SessionSummaryPanel.vue'
import { useMemory } from '@/composables/useMemory'

const {
  enabled,
  settingsSaving,
  settingsError,
  isLoading,
  error,
  actionError,
  actionPendingId,
  kind,
  showArchived,
  pending,
  active,
  archived,
  loadSettings,
  load,
  toggleEnabled,
  remove,
  clearAll,
  confirmItem,
  ignoreItem,
  setKind,
  setQuery,
  setShowArchived,
  cancel,
} = useMemory()

const search = ref('')
let searchTimer: ReturnType<typeof setTimeout> | null = null

const mainItems = computed(() => (showArchived.value ? archived.value : active.value))

watch(search, (value) => {
  if (searchTimer) {
    clearTimeout(searchTimer)
  }
  searchTimer = setTimeout(() => {
    void setQuery(value)
  }, 300)
})

onMounted(() => {
  void loadSettings()
  void load()
})

onUnmounted(() => {
  if (searchTimer) {
    clearTimeout(searchTimer)
  }
  cancel()
})

const KIND_OPTIONS: Array<{ value: MemoryKind | ''; label: string }> = [
  { value: '', label: '全部类型' },
  { value: 'preference', label: '偏好' },
  { value: 'goal', label: '目标' },
  { value: 'fact', label: '事实' },
  { value: 'constraint', label: '约束' },
]

async function onToggle(event: Event): Promise<void> {
  const target = event.target as HTMLInputElement
  const next = target.checked
  target.checked = enabled.value
  await toggleEnabled()
  target.checked = enabled.value
}

async function onKindChange(event: Event): Promise<void> {
  await setKind((event.target as HTMLSelectElement).value as MemoryKind | '')
}

async function onArchiveTab(next: boolean): Promise<void> {
  if (next === showArchived.value) {
    return
  }
  await setShowArchived(next)
}

async function onClearAll(): Promise<void> {
  const confirmed = window.confirm('确定清空全部记忆吗？该操作不可恢复。')
  if (confirmed) {
    await clearAll()
  }
}

async function onConfirm(item: MemoryItem): Promise<void> {
  await confirmItem(item)
}

async function onIgnore(item: MemoryItem): Promise<void> {
  await ignoreItem(item)
}

async function onRemove(item: MemoryItem): Promise<void> {
  await remove(item.id)
}
</script>

<template>
  <section class="page">
    <header class="page-header">
      <div>
        <div class="crumb">档案室 / <b>长期记忆</b></div>
        <h1>记忆设置</h1>
        <p>管理长期记忆与会话摘要。关闭后不再写入或检索长期记忆。</p>
      </div>
      <span class="stamp" :class="enabled ? 'stamp--moss' : 'stamp--gray'">
        {{ enabled ? 'MEMORY ON' : 'MEMORY OFF' }}
      </span>
    </header>

    <div class="mem-layout">
      <div class="stack">
        <section class="card switch-card">
          <label class="switch-row">
            <span class="switch-copy">
              <b>启用长期记忆</b>
              <span class="switch-desc">
                开启后，分析会写入并检索跨会话的偏好、目标与约束。
              </span>
            </span>
            <span class="switch-control">
              <input
                type="checkbox"
                :checked="enabled"
                :disabled="settingsSaving"
                @change="onToggle"
              />
              <span class="switch-track" aria-hidden="true"><i></i></span>
            </span>
          </label>
          <p v-if="settingsError" class="notice notice-error">{{ settingsError }}</p>
          <p v-else-if="!enabled" class="notice notice-warning">
            记忆已关闭：不会写入新的长期记忆，检索也不会注入记忆内容。
          </p>
        </section>

        <section class="card memory-card">
          <div class="mem-toolbar">
            <div class="tabs" role="tablist" aria-label="记忆归档状态">
              <button
                type="button"
                role="tab"
                class="tab"
                :class="{ 'tab-active': !showArchived }"
                :aria-selected="!showArchived"
                @click="onArchiveTab(false)"
              >
                生效中
              </button>
              <button
                type="button"
                role="tab"
                class="tab"
                :class="{ 'tab-active': showArchived }"
                :aria-selected="showArchived"
                @click="onArchiveTab(true)"
              >
                已归档
              </button>
            </div>
            <button type="button" class="btn btn-sm btn-danger" :disabled="!!actionPendingId" @click="onClearAll">
              清空全部
            </button>
          </div>

          <div class="mem-filters">
            <div class="field">
              <label for="memory-kind">类型</label>
              <select id="memory-kind" :value="kind" @change="onKindChange">
                <option v-for="option in KIND_OPTIONS" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </div>
            <div class="field search-field">
              <label for="memory-search">搜索内容</label>
              <input id="memory-search" v-model="search" type="search" placeholder="输入关键词" />
            </div>
          </div>

          <p v-if="error" class="notice notice-error">{{ error }}</p>
          <p v-if="actionError" class="notice notice-error">{{ actionError }}</p>

          <template v-if="!showArchived && pending.length">
            <div class="section-head">
              <h2>待确认记忆</h2>
              <span class="tag tag--amber">{{ pending.length }} 条待确认</span>
            </div>
            <MemoryList
              :items="pending"
              :pending-id="actionPendingId"
              @confirm="onConfirm"
              @ignore="onIgnore"
              @remove="onRemove"
            />
          </template>

          <div class="section-head">
            <h2>{{ showArchived ? '已归档记忆' : '生效中的记忆' }}</h2>
            <span class="tag">{{ mainItems.length }} 条</span>
          </div>

          <p v-if="isLoading" class="muted">正在加载记忆…</p>
          <EmptyState
            v-else-if="!mainItems.length"
            :title="showArchived ? '暂无归档记忆' : '暂无记忆'"
            :description="showArchived ? '归档后的记忆会保留在这里。' : '完成一次分析后会生成。'"
          />
          <MemoryList
            v-else
            :items="mainItems"
            :pending-id="actionPendingId"
            @confirm="onConfirm"
            @ignore="onIgnore"
            @remove="onRemove"
          />
        </section>
      </div>

      <SessionSummaryPanel />
    </div>
  </section>
</template>

<style scoped>
.mem-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 0.9fr);
  gap: var(--space-5);
  align-items: start;
}

.switch-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  cursor: pointer;
}

.switch-copy {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.switch-copy b {
  font-family: var(--font-serif);
  font-size: 16px;
  font-weight: 700;
}

.switch-desc {
  font-size: 11.5px;
  color: var(--color-text-muted);
}

.switch-control {
  position: relative;
  flex-shrink: 0;
}

.switch-control input {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}

.switch-track {
  display: block;
  width: 46px;
  height: 24px;
  padding: 3px;
  border: 1px solid var(--color-border-strong);
  border-radius: 999px;
  background: var(--color-surface-muted);
  transition: background var(--dur-fast) var(--ease);
}

.switch-track i {
  display: block;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--color-text-muted);
  transition: transform var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease);
}

.switch-control input:checked + .switch-track {
  background: var(--color-moss);
  border-color: var(--color-moss);
}

.switch-control input:checked + .switch-track i {
  transform: translateX(22px);
  background: var(--color-on-ink);
}

.switch-control input:focus-visible + .switch-track {
  outline: 2px solid var(--color-focus);
  outline-offset: 2px;
}

.memory-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.mem-toolbar {
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

.tab-active {
  border-bottom-color: var(--color-primary);
  color: var(--color-primary);
  font-weight: 600;
}

.mem-filters {
  display: flex;
  align-items: flex-end;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.mem-filters .field:first-child {
  width: 150px;
}

.search-field {
  flex: 1;
  min-width: 200px;
}

.section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-3);
  margin-top: var(--space-1);
}

.section-head h2 {
  margin: 0;
  font-size: var(--text-lg);
}

@media (max-width: 1024px) {
  .mem-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .switch-row {
    align-items: flex-start;
  }

  .mem-filters .field:first-child {
    width: 100%;
  }
}
</style>
