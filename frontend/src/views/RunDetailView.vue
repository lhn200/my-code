<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import EmptyState from '@/components/EmptyState.vue'
import ErrorNotice from '@/components/ErrorNotice.vue'
import LoadingState from '@/components/LoadingState.vue'
import RunResults from '@/components/RunResults.vue'
import SnapshotPanel from '@/components/SnapshotPanel.vue'
import { useRunDetail } from '@/composables/useRunDetail'
import { useSnapshots } from '@/composables/useSnapshots'

const route = useRoute()
const threadId = computed(() => String(route.params.threadId ?? ''))

const detail = useRunDetail(() => threadId.value)
const snapshots = useSnapshots(() => threadId.value)

const {
  result,
  state,
  isLoading,
  error,
  notFound,
  isResumable,
  isRunning,
  isResuming,
  resumeError,
  load,
  resume,
  cancel,
} = detail

const {
  snapshots: snapshotItems,
  isLoading: snapshotsLoading,
  error: snapshotsError,
  selected,
  selectedCheckpoint,
  isSelecting,
  selectionError,
  load: loadSnapshots,
  select,
  closeSelection,
  cancel: cancelSnapshots,
} = snapshots

const pageTitle = computed(() => {
  if (isRunning.value) {
    return '分析进行中'
  }
  if (!result.value) {
    return '分析结果'
  }
  const titles = result.value.jobs
    .map((job) => job.title?.trim())
    .filter((title): title is string => Boolean(title))
  if (!titles.length) {
    return '分析结果'
  }
  return titles.slice(0, 2).join(' · ')
})

const jobCount = computed(() => result.value?.jobs.length ?? 0)

const POLL_INTERVAL_MS = 4000
let pollTimer: ReturnType<typeof setTimeout> | null = null
let disposed = false

function stopPolling(): void {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

function schedulePoll(): void {
  if (disposed) {
    return
  }
  stopPolling()
  pollTimer = setTimeout(() => {
    void poll()
  }, POLL_INTERVAL_MS)
}

async function poll(): Promise<void> {
  pollTimer = null
  await load({ silent: true })
  if (disposed) {
    return
  }
  if (isRunning.value) {
    schedulePoll()
    return
  }
  if (!error.value) {
    void loadSnapshots()
  }
}

async function afterLoad(): Promise<void> {
  if (error.value) {
    return
  }
  if (isRunning.value) {
    schedulePoll()
    return
  }
  void loadSnapshots()
}

onMounted(async () => {
  await load()
  await afterLoad()
})

onUnmounted(() => {
  disposed = true
  stopPolling()
  cancel()
  cancelSnapshots()
})

async function reload(): Promise<void> {
  stopPolling()
  await load()
  await afterLoad()
}

async function onResume(): Promise<void> {
  const succeeded = await resume()
  if (succeeded) {
    await loadSnapshots()
  }
}

function onSelectSnapshot(checkpointId: string): void {
  void select(checkpointId)
}
</script>

<template>
  <section class="page">
    <header class="page-header">
      <div>
        <div class="crumb">会话 / <b>THREAD</b></div>
        <h1>{{ pageTitle }}</h1>
        <p>
          <template v-if="result">共 {{ jobCount }} 个岗位 · </template>
          thread_id：<code>{{ threadId }}</code>
        </p>
      </div>
      <div class="row header-actions">
        <span class="tag">档案视图</span>
        <RouterLink class="btn btn-ghost btn-sm" to="/">新建分析</RouterLink>
      </div>
    </header>

    <LoadingState v-if="isLoading" label="正在加载会话状态…" />

    <div v-else-if="notFound" class="notice notice-error" role="alert">
      <p>会话不存在或已失效，请确认 thread_id 后重新查询。</p>
      <RouterLink class="btn btn-sm" to="/runs">返回查询</RouterLink>
    </div>

    <ErrorNotice
      v-else-if="error"
      :message="error.message"
      :code="error.code"
      :thread-id="error.threadId"
      @retry="reload"
    />

    <template v-else-if="result">
      <div v-if="isRunning" class="notice notice-warning" role="status">
        <p>
          分析正在后台执行，通常需要数分钟。本页会自动刷新，也可以先去做别的事，稍后回到会话列表查看结果。
        </p>
      </div>

      <RunResults :result="result" :state="state" />

      <section v-if="!isRunning" class="card session-ops" aria-labelledby="resume-heading">
        <div>
          <p class="eyebrow">SESSION CONTROL</p>
          <h2 id="resume-heading">会话操作</h2>
          <p v-if="isResumable">该会话仍有未完成步骤，可继续执行。</p>
          <p v-else class="muted">该会话已完成，无需恢复。</p>
        </div>
        <div class="row">
          <button
            v-if="isResumable"
            type="button"
            class="btn btn-primary"
            :disabled="isResuming"
            @click="onResume"
          >
            {{ isResuming ? '恢复中…' : '恢复会话' }}
          </button>
          <span v-else class="stamp stamp--moss">COMPLETED</span>
        </div>
        <p v-if="isResuming" class="notice" role="status">正在恢复会话，请稍候…</p>
        <ErrorNotice
          v-if="resumeError"
          :message="resumeError.message"
          :code="resumeError.code"
          :thread-id="resumeError.threadId"
          :retryable="false"
        />
      </section>

      <SnapshotPanel
        v-if="!isRunning"
        :snapshots="snapshotItems"
        :is-loading="snapshotsLoading"
        :error="snapshotsError"
        :selected="selected"
        :selected-checkpoint="selectedCheckpoint"
        :is-selecting="isSelecting"
        :selection-error="selectionError"
        @refresh="loadSnapshots"
        @select="onSelectSnapshot"
        @close="closeSelection"
      />
    </template>

    <EmptyState
      v-else
      title="没有可展示的结果"
      description="请稍后重试，或返回查询页重新输入 thread_id。"
    />
  </section>
</template>

<style scoped>
.header-actions {
  align-self: flex-end;
}

.session-ops {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  align-items: flex-start;
}

.session-ops h2 {
  margin: 4px 0 6px;
  font-size: var(--text-lg);
}

.session-ops p {
  margin: 0;
  font-size: var(--text-sm);
}

code {
  font-family: var(--font-mono);
  word-break: break-all;
}
</style>
