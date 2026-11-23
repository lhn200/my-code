<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import ErrorNotice from '@/components/ErrorNotice.vue'
import LoadingState from '@/components/LoadingState.vue'
import { listSessions } from '@/api/sessions'
import type { CoachSession, SessionItem } from '@/api/types'
import { useCoachChat } from '@/composables/useCoachChat'

const MESSAGE_LIMIT = 4000

const {
  sessions,
  active,
  messages,
  isLoading,
  isLoadingSession,
  isSending,
  error,
  loadSessions,
  openSession,
  create,
  rename,
  remove,
  send,
} = useCoachChat()

const analyses = ref<SessionItem[]>([])
const analysisError = ref('')
const selectedThread = ref('')
const draft = ref('')
const renamingId = ref('')
const renameDraft = ref('')
const confirmingDeleteId = ref('')
const bottomRef = ref<HTMLElement | null>(null)

const currentSession = computed<CoachSession | null>(() => active.value?.session ?? null)
const showIntro = computed(() => !!active.value && messages.value.length === 0)

const examples = [
  '我最需要补强的岗位缺口是什么？',
  '帮我改写简历里最有价值的一段项目描述。',
  '下一次面试的自我介绍该怎么讲？',
]

function displayTitle(session: CoachSession): string {
  return session.title?.trim() || '新的教练会话'
}

function formatTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return ''
  }
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

async function scrollToBottom(): Promise<void> {
  await nextTick()
  bottomRef.value?.scrollIntoView({ behavior: 'smooth', block: 'end' })
}

watch(messages, () => {
  void scrollToBottom()
})

watch(isSending, () => {
  void scrollToBottom()
})

async function bootstrap(): Promise<void> {
  try {
    const response = await listSessions({ page_size: 100 })
    analyses.value = response.items
    const finished =
      response.items.find((item) => item.status === 'completed') ??
      response.items.find((item) => item.status === 'partial') ??
      response.items[0]
    if (finished) {
      selectedThread.value = finished.thread_id
    }
  } catch {
    analysisError.value = '分析列表载入失败，可先在不绑定分析的情况下与教练对话。'
  }

  const ok = await loadSessions(selectedThread.value || null)
  if (!ok) {
    return
  }
  if (sessions.value.length) {
    await openSession(sessions.value[0].id)
  } else {
    await create(selectedThread.value || null)
  }
}

onMounted(() => {
  void bootstrap()
})

async function selectSession(sessionId: string): Promise<void> {
  renamingId.value = ''
  confirmingDeleteId.value = ''
  await openSession(sessionId)
}

async function switchAnalysis(): Promise<void> {
  const thread = selectedThread.value || null
  const ok = await loadSessions(thread)
  if (!ok) {
    return
  }
  if (sessions.value.length) {
    await openSession(sessions.value[0].id)
  } else {
    await create(thread)
  }
}

async function startNewSession(): Promise<void> {
  draft.value = ''
  renamingId.value = ''
  await create(selectedThread.value || null)
}

function startRename(item: CoachSession): void {
  renamingId.value = item.id
  renameDraft.value = item.title ?? ''
  confirmingDeleteId.value = ''
}

function cancelRename(): void {
  renamingId.value = ''
  renameDraft.value = ''
}

async function commitRename(): Promise<void> {
  const title = renameDraft.value.trim()
  if (!renamingId.value || !title) {
    return
  }
  const ok = await rename(renamingId.value, title)
  if (ok) {
    cancelRename()
  }
}

async function confirmDelete(sessionId: string): Promise<void> {
  if (confirmingDeleteId.value !== sessionId) {
    confirmingDeleteId.value = sessionId
    return
  }
  const ok = await remove(sessionId)
  if (ok) {
    confirmingDeleteId.value = ''
    if (!active.value && sessions.value.length) {
      await openSession(sessions.value[0].id)
    }
  }
}

async function submit(): Promise<void> {
  const text = draft.value.trim()
  if (!text || isSending.value) {
    return
  }
  const ok = await send(text)
  if (ok) {
    draft.value = ''
  }
}

function handleDraftKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
    event.preventDefault()
    void submit()
  }
}

function useExample(text: string): void {
  draft.value = text
}
</script>

<template>
  <section class="page">
    <header class="page-header">
      <div>
        <div class="crumb">教练 / <b>AI COACH</b></div>
        <h1>AI 模拟教练</h1>
        <p>围绕已完成的分析、简历与面试报告，持续追问并拿到可执行的改进建议。</p>
      </div>
      <div class="row header-actions">
        <label class="analysis-picker">
          <span>分析上下文</span>
          <select v-model="selectedThread" @change="switchAnalysis">
            <option value="">不绑定分析</option>
            <option v-for="item in analyses" :key="item.thread_id" :value="item.thread_id">
              {{ item.title }}
            </option>
          </select>
        </label>
        <button type="button" class="btn btn-primary btn-sm" :disabled="isLoading" @click="startNewSession">
          新建会话
        </button>
      </div>
    </header>

    <p v-if="analysisError" class="notice notice-warning" role="status">{{ analysisError }}</p>

    <ErrorNotice
      v-if="error"
      :message="error.message"
      :code="error.code"
      :thread-id="error.threadId"
      :retryable="false"
    />

    <div class="coach-layout">
      <aside class="coach-sidebar" aria-label="教练会话历史">
        <div class="sidebar-head">
          <span>历史会话</span>
          <b>{{ sessions.length }}</b>
        </div>

        <LoadingState v-if="isLoading" label="正在载入会话…" />

        <p v-else-if="!sessions.length" class="sidebar-empty">还没有会话，点击右上角「新建会话」开始。</p>

        <ul v-else class="session-list">
          <li
            v-for="item in sessions"
            :key="item.id"
            class="session-item"
            :class="{ 'session-item--active': currentSession?.id === item.id }"
          >
            <template v-if="renamingId === item.id">
              <input
                v-model="renameDraft"
                class="rename-input"
                type="text"
                maxlength="100"
                aria-label="会话名称"
                @keydown.enter="commitRename"
                @keydown.esc="cancelRename"
              />
              <div class="session-actions">
                <button type="button" class="link-button" @click="commitRename">保存</button>
                <button type="button" class="link-button" @click="cancelRename">取消</button>
              </div>
            </template>

            <template v-else>
              <button type="button" class="session-open" @click="selectSession(item.id)">
                <span class="session-title">{{ displayTitle(item) }}</span>
                <span class="session-meta">
                  {{ formatTime(item.updated_at) }} · {{ item.message_count }} 条
                </span>
              </button>
              <div class="session-actions">
                <button type="button" class="link-button" @click="startRename(item)">重命名</button>
                <button
                  type="button"
                  class="link-button"
                  :class="{ 'link-button--danger': confirmingDeleteId === item.id }"
                  @click="confirmDelete(item.id)"
                >
                  {{ confirmingDeleteId === item.id ? '确认删除' : '删除' }}
                </button>
              </div>
            </template>
          </li>
        </ul>
      </aside>

      <section class="coach-main">
        <LoadingState v-if="isLoadingSession" label="正在载入对话…" />

        <div v-else-if="!active" class="empty-panel">
          <p>从左侧选择一个会话，或新建一个会话开始与教练对话。</p>
          <button type="button" class="btn btn-primary btn-sm" @click="startNewSession">
            新建会话
          </button>
        </div>

        <template v-else>
          <div class="thread" aria-live="polite">
            <div v-if="showIntro" class="coach-intro">
              <p class="intro-title">今天想聊哪一部分？</p>
              <p class="intro-copy">
                你可以围绕岗位匹配、简历表达或面试表现提问；教练会结合当前分析上下文回答。
              </p>
              <div class="intro-examples">
                <button
                  v-for="item in examples"
                  :key="item"
                  type="button"
                  class="example-chip"
                  @click="useExample(item)"
                >
                  {{ item }}
                </button>
              </div>
            </div>

            <article
              v-for="message in messages"
              :key="message.id"
              class="entry"
              :class="message.role === 'user' ? 'entry--user' : 'entry--coach'"
            >
              <div class="entry-meta">
                <span class="entry-who">{{ message.role === 'user' ? '你' : 'AI 教练' }}</span>
                <span class="entry-time">{{ formatTime(message.created_at) }}</span>
              </div>
              <p class="entry-content">{{ message.content }}</p>
            </article>

            <div v-if="isSending" class="entry entry--coach entry--pending">
              <div class="entry-meta"><span class="entry-who">AI 教练</span></div>
              <p class="entry-content">教练思考中…</p>
            </div>
            <div ref="bottomRef" class="thread-end"></div>
          </div>

          <section class="composer" aria-label="发送消息">
            <label class="composer-label" for="coach-message">
              你的问题
              <span class="composer-count">{{ draft.length }} / {{ MESSAGE_LIMIT }}</span>
            </label>
            <textarea
              id="coach-message"
              v-model="draft"
              class="composer-input"
              rows="4"
              :maxlength="MESSAGE_LIMIT"
              placeholder="例如：这个岗位还差什么？我该怎么补？Ctrl / Cmd + Enter 发送。"
              :disabled="isSending"
              @keydown="handleDraftKeydown"
            ></textarea>
            <div class="composer-actions">
              <button
                type="button"
                class="btn btn-primary"
                :disabled="isSending || !draft.trim()"
                @click="submit"
              >
                {{ isSending ? '思考中…' : '发送' }}
              </button>
              <span class="composer-hint">
                当前：{{ currentSession ? displayTitle(currentSession) : '未选择会话' }}
              </span>
            </div>
          </section>
        </template>
      </section>
    </div>
  </section>
</template>

<style scoped>
.header-actions {
  align-self: flex-end;
}

.analysis-picker {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}

.analysis-picker select {
  min-width: 220px;
  padding: 7px 10px;
  border: 1px solid var(--color-border-strong);
  border-radius: 2px;
  background: var(--color-surface);
  font-family: inherit;
  font-size: 11px;
  letter-spacing: 0;
  text-transform: none;
  color: var(--color-text);
}

.coach-layout {
  display: grid;
  grid-template-columns: 264px minmax(0, 1fr);
  gap: var(--space-4);
  align-items: start;
}

.coach-sidebar {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-height: 72vh;
  overflow-y: auto;
  padding: var(--space-3);
  border: 1px solid var(--color-border-strong);
  background: var(--color-surface);
}

.sidebar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--color-border);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}

.sidebar-head b {
  font-size: 10px;
  color: var(--color-primary);
}

.sidebar-empty {
  margin: var(--space-3) 0;
  font-size: 11px;
  line-height: 1.7;
  color: var(--color-text-muted);
}

.session-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.session-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
  border: 1px solid var(--color-border);
  background: var(--color-bg);
}

.session-item--active {
  border-color: var(--color-primary);
  box-shadow: inset 2px 0 0 var(--color-primary);
}

.session-open {
  display: flex;
  flex-direction: column;
  gap: 3px;
  width: 100%;
  padding: 0;
  border: none;
  background: none;
  text-align: left;
  cursor: pointer;
}

.session-title {
  overflow: hidden;
  font-family: var(--font-serif);
  font-size: 13px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text);
}

.session-meta {
  font-family: var(--font-mono);
  font-size: 8.5px;
  letter-spacing: 0.04em;
  color: var(--color-text-muted);
}

.session-actions {
  display: flex;
  gap: var(--space-3);
}

.rename-input {
  width: 100%;
  padding: 5px 8px;
  border: 1px solid var(--color-border);
  background: var(--color-bg);
  font-family: inherit;
  font-size: 11px;
}

.link-button--danger {
  color: var(--color-danger);
}

.coach-main {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  min-width: 0;
}

.empty-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  align-items: flex-start;
  padding: var(--space-5);
  border: 1px dashed var(--color-border-strong);
  background: var(--color-surface);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.thread {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-height: 320px;
  max-height: 56vh;
  overflow-y: auto;
  padding: var(--space-4);
  border: 1px solid var(--color-border-strong);
  background: var(--color-bg);
}

.coach-intro {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-4);
  border-left: 2px solid var(--color-primary);
  background: var(--color-surface-muted);
}

.intro-title {
  margin: 0;
  font-family: var(--font-serif);
  font-size: 16px;
  font-weight: 700;
}

.intro-copy {
  margin: 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--color-ink-2);
}

.intro-examples {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.example-chip {
  padding: 5px 10px;
  border: 1px solid var(--color-border-strong);
  background: var(--color-bg);
  font-size: 11px;
  color: var(--color-ink-2);
  cursor: pointer;
}

.example-chip:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.entry {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-width: 86%;
  padding: 12px 14px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
}

.entry--coach {
  align-self: flex-start;
  border-left: 2px solid var(--color-primary);
}

.entry--user {
  align-self: flex-end;
  border-color: var(--color-border-strong);
  background: var(--color-surface-muted);
}

.entry--pending {
  opacity: 0.7;
  font-style: italic;
}

.entry-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.entry-who {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}

.entry-time {
  font-family: var(--font-mono);
  font-size: 8.5px;
  color: var(--color-ink-3);
}

.entry-content {
  margin: 0;
  font-size: var(--text-sm);
  line-height: 1.75;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.entry--coach .entry-content {
  font-family: var(--font-serif);
  font-size: 14.5px;
  line-height: 1.8;
}

.thread-end {
  height: 1px;
}

.composer {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-4);
  border: 1px solid var(--color-border-strong);
  background: var(--color-surface);
}

.composer-label {
  display: flex;
  justify-content: space-between;
  font-family: var(--font-mono);
  font-size: 9.5px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}

.composer-count {
  color: var(--color-ink-3);
}

.composer-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--color-border);
  border-radius: 2px;
  background: var(--color-bg);
  font-family: inherit;
  font-size: var(--text-sm);
  line-height: 1.7;
  resize: vertical;
}

.composer-input:focus {
  outline: 2px solid var(--color-primary);
  outline-offset: -1px;
}

.composer-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.composer-hint {
  overflow: hidden;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.04em;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-ink-3);
}

@media (max-width: 900px) {
  .coach-layout {
    grid-template-columns: 1fr;
  }

  .coach-sidebar {
    max-height: 240px;
  }

  .thread {
    max-height: none;
  }

  .entry {
    max-width: 100%;
  }

  .analysis-picker select {
    min-width: 0;
    width: 100%;
  }
}
</style>
