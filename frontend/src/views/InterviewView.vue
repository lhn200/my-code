<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import ErrorNotice from '@/components/ErrorNotice.vue'
import LoadingState from '@/components/LoadingState.vue'
import { useInterviewSession } from '@/composables/useInterviewSession'
import type { InterviewSessionMessage } from '@/api/types'

const ANSWER_LIMIT = 2000

const route = useRoute()
const sessionId = computed(() => String(route.params.sessionId ?? ''))
const interview = useInterviewSession(sessionId.value)

const {
  session,
  messages,
  report,
  isLoading,
  isSubmitting,
  isFinishing,
  error,
  canAnswer,
  isCompleted,
  progress,
  load,
  answer,
  finish,
} = interview

const draft = ref('')
const confirmingFinish = ref(false)
const messagesRef = ref<HTMLElement | null>(null)
const bottomRef = ref<HTMLElement | null>(null)

const answerCount = computed(
  () => messages.value.filter((item) => item.role === 'candidate' && item.kind === 'answer').length,
)

const statusLabel = computed(() => {
  switch (session.value?.status) {
    case 'active':
      return '进行中'
    case 'ready_to_finish':
      return '待生成报告'
    case 'completed':
      return '已完成'
    default:
      return ''
  }
})

const statusTone = computed(() => {
  if (session.value?.status === 'completed') {
    return 'stamp--moss'
  }
  if (session.value?.status === 'ready_to_finish') {
    return 'stamp--amber'
  }
  return ''
})

const notFound = computed(() => error.value?.code === 'interview_not_found')

const dimensions = computed(() =>
  Object.entries(report.value?.dimension_averages ?? {}).map(([name, value]) => ({
    name,
    value: Number(value),
  })),
)

const canFinishEarly = computed(
  () => session.value?.status === 'active' && answerCount.value > 0 && !isSubmitting.value,
)

function messageLabel(message: InterviewSessionMessage): string {
  if (message.role === 'candidate') {
    return '候选人'
  }
  if (message.kind === 'followup') {
    return `面试官 · 第 ${message.question_no} 题追问`
  }
  if (message.kind === 'feedback') {
    return '面试官 · 即时反馈'
  }
  return `面试官 · 第 ${message.question_no} 题`
}

async function scrollToBottom(): Promise<void> {
  await nextTick()
  bottomRef.value?.scrollIntoView({ behavior: 'smooth', block: 'end' })
}

watch(messages, () => {
  void scrollToBottom()
})

onMounted(async () => {
  const ok = await load()
  if (ok) {
    void scrollToBottom()
  }
})

async function submitAnswer(): Promise<void> {
  const text = draft.value.trim()
  if (!text || isSubmitting.value) {
    return
  }
  const ok = await answer(text)
  if (ok) {
    draft.value = ''
    confirmingFinish.value = false
  }
}

function handleDraftKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
    event.preventDefault()
    void submitAnswer()
  }
}

async function submitFinish(): Promise<void> {
  if (!confirmingFinish.value) {
    confirmingFinish.value = true
    return
  }
  confirmingFinish.value = false
  await finish()
}

function cancelFinish(): void {
  confirmingFinish.value = false
}
</script>

<template>
  <section class="page">
    <header class="page-header">
      <div>
        <div class="crumb">演练 / <b>INTERVIEW</b></div>
        <h1>{{ session?.job_title || '模拟面试演练' }}</h1>
        <p v-if="session">
          第 {{ Math.min(progress.asked, progress.planned) }} / {{ progress.planned }} 题
          · 已回答 {{ answerCount }} 题
          · 每题最多 {{ session.max_followups }} 次追问
        </p>
        <p v-else>AI 面试官逐题提问，实时反馈与追问。</p>
      </div>
      <div class="row header-actions">
        <span v-if="session" class="stamp" :class="statusTone">{{ statusLabel }}</span>
        <RouterLink
          v-if="session"
          class="btn btn-ghost btn-sm"
          :to="`/runs/${session.thread_id}`"
        >
          返回分析结果
        </RouterLink>
        <RouterLink v-else class="btn btn-ghost btn-sm" to="/runs">返回查询</RouterLink>
      </div>
    </header>

    <LoadingState v-if="isLoading" label="正在载入演练会话…" />

    <div v-else-if="notFound" class="notice notice-error" role="alert">
      <p>演练会话不存在或已失效，请返回分析结果重新开始。</p>
      <RouterLink class="btn btn-sm" to="/runs">返回查询</RouterLink>
    </div>

    <template v-else-if="session">
      <ErrorNotice
        v-if="error"
        :message="error.message"
        :code="error.code"
        :thread-id="error.threadId"
        :retryable="false"
      />

      <div class="interview-shell">
        <div ref="messagesRef" class="thread" aria-live="polite">
          <article
            v-for="message in messages"
            :key="message.id"
            class="entry"
            :class="[
              message.role === 'candidate' ? 'entry--candidate' : 'entry--interviewer',
              message.kind === 'feedback' ? 'entry--feedback' : '',
            ]"
          >
            <div class="entry-meta">
              <span class="entry-who">{{ messageLabel(message) }}</span>
              <span
                v-if="message.kind === 'feedback' && message.score !== null"
                class="entry-score"
              >
                {{ message.score }} 分
              </span>
            </div>
            <p class="entry-content">{{ message.content }}</p>
          </article>

          <div v-if="isSubmitting" class="entry entry--interviewer entry--pending">
            <div class="entry-meta"><span class="entry-who">面试官</span></div>
            <p class="entry-content">正在评估你的回答并准备下一题…</p>
          </div>
          <div ref="bottomRef" class="thread-end"></div>
        </div>

        <section v-if="canAnswer" class="composer" aria-label="作答区">
          <label class="composer-label" for="interview-answer">
            你的回答
            <span class="composer-count">{{ draft.length }} / {{ ANSWER_LIMIT }}</span>
          </label>
          <textarea
            id="interview-answer"
            v-model="draft"
            class="composer-input"
            rows="5"
            :maxlength="ANSWER_LIMIT"
            placeholder="结合简历中的真实经历作答，尽量给出具体做法与结果。Ctrl / Cmd + Enter 提交。"
            :disabled="isSubmitting"
            @keydown="handleDraftKeydown"
          ></textarea>
          <div class="composer-actions">
            <button
              type="button"
              class="btn btn-primary"
              :disabled="isSubmitting || !draft.trim()"
              @click="submitAnswer"
            >
              {{ isSubmitting ? '评估中…' : '提交回答' }}
            </button>
            <button
              v-if="canFinishEarly"
              type="button"
              class="btn btn-ghost"
              :disabled="isFinishing"
              @click="submitFinish"
            >
              {{ confirmingFinish ? '确认结束并生成报告' : '提前结束' }}
            </button>
            <button
              v-if="confirmingFinish"
              type="button"
              class="btn btn-ghost btn-sm"
              @click="cancelFinish"
            >
              取消
            </button>
          </div>
        </section>

        <section v-else-if="session.status === 'ready_to_finish'" class="composer finish-panel">
          <p class="finish-copy">所有问题已作答完毕，生成评估报告后将回填到该岗位结果。</p>
          <div class="composer-actions">
            <button
              type="button"
              class="btn btn-primary"
              :disabled="isFinishing"
              @click="submitFinish"
            >
              {{ isFinishing ? '生成中…' : confirmingFinish ? '确认生成报告' : '生成评估报告' }}
            </button>
            <button
              v-if="confirmingFinish"
              type="button"
              class="btn btn-ghost btn-sm"
              @click="cancelFinish"
            >
              取消
            </button>
          </div>
        </section>

        <p v-else-if="isCompleted" class="notice notice-success" role="status">
          本场演练已完成，报告已回填到岗位结果。
        </p>
      </div>

      <section v-if="report" class="card report-card" aria-labelledby="report-heading">
        <div class="report-head">
          <div>
            <p class="eyebrow">INTERVIEW REPORT</p>
            <h2 id="report-heading">演练评估报告</h2>
          </div>
          <div class="report-score-block">
            <b>{{ report.overall_score ?? '—' }}</b>
            <span>/ 100</span>
          </div>
        </div>

        <p class="report-meta">
          真人演练 · 已回答 {{ report.answered_count }} / {{ report.planned_count }} 题 ·
          {{ report.status === 'completed' ? '完整完成' : '提前结束' }}
        </p>

        <div v-if="dimensions.length" class="dims" aria-label="维度平均分">
          <div v-for="item in dimensions" :key="item.name" class="dim">
            <span class="dim-name">{{ item.name }}</span>
            <span class="dim-track"><i :style="{ width: `${Math.min(100, item.value)}%` }"></i></span>
            <span class="dim-value">{{ Math.round(item.value) }}</span>
          </div>
        </div>

        <div class="report-grid">
          <section v-if="report.highlights.length" class="report-block">
            <h3>亮点</h3>
            <ul class="good">
              <li v-for="item in report.highlights" :key="`h-${item}`">{{ item }}</li>
            </ul>
          </section>
          <section v-if="report.red_flags.length" class="report-block">
            <h3>风险</h3>
            <ul class="bad">
              <li v-for="item in report.red_flags" :key="`r-${item}`">{{ item }}</li>
            </ul>
          </section>
          <section v-if="report.requirement_gaps.length" class="report-block">
            <h3>岗位缺口</h3>
            <ul class="warn">
              <li v-for="item in report.requirement_gaps" :key="`g-${item}`">{{ item }}</li>
            </ul>
          </section>
          <section v-if="report.improvements.length" class="report-block">
            <h3>改进建议</h3>
            <ul class="plain">
              <li v-for="item in report.improvements" :key="`i-${item}`">{{ item }}</li>
            </ul>
          </section>
        </div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.header-actions {
  align-self: flex-end;
}

.interview-shell {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.thread {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  max-height: 62vh;
  overflow-y: auto;
  padding: var(--space-4);
  border: 1px solid var(--color-border-strong);
  background: var(--color-bg);
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

.entry--interviewer {
  align-self: flex-start;
}

.entry--candidate {
  align-self: flex-end;
  border-color: var(--color-border-strong);
  background: var(--color-surface-muted);
}

.entry--feedback {
  align-self: flex-start;
  border-left: 2px solid var(--color-primary);
  background: var(--color-bg);
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

.entry-score {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--color-primary);
}

.entry-content {
  margin: 0;
  font-size: var(--text-sm);
  line-height: 1.75;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.entry--interviewer .entry-content {
  font-family: var(--font-serif);
  font-size: 15px;
  font-weight: 600;
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
  gap: var(--space-2);
  flex-wrap: wrap;
}

.finish-panel {
  align-items: flex-start;
}

.finish-copy {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-ink-2);
}

.report-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.report-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--color-border);
}

.report-head h2 {
  margin: 4px 0 0;
  font-size: var(--text-xl);
  font-weight: 700;
}

.report-score-block {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.report-score-block b {
  font-family: var(--font-serif);
  font-size: 34px;
  font-weight: 800;
  line-height: 1;
}

.report-score-block span {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--color-text-muted);
}

.report-meta {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 9.5px;
  letter-spacing: 0.06em;
  color: var(--color-text-muted);
}

.dims {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--space-3) var(--space-5);
}

.dim {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 11px;
}

.dim-name {
  min-width: 4.5em;
  color: var(--color-text-muted);
}

.dim-track {
  flex: 1;
  height: 3px;
  background: var(--color-surface-muted);
}

.dim-track i {
  display: block;
  height: 100%;
  background: var(--color-primary);
}

.dim-value {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--color-ink-2);
}

.report-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--space-4);
}

.report-block h3 {
  margin: 0 0 6px;
  font-family: var(--font-mono);
  font-size: 9px;
  font-weight: 500;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}

.report-block ul {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 0;
  padding-left: var(--space-3);
  font-size: 11.5px;
  line-height: 1.65;
  list-style: disc;
}

.report-block .good {
  color: var(--color-moss);
}

.report-block .bad {
  color: var(--color-primary-strong);
}

.report-block .warn {
  color: var(--color-amber);
}

.report-block .plain {
  color: var(--color-ink-2);
}

@media (max-width: 720px) {
  .entry {
    max-width: 100%;
  }

  .thread {
    max-height: none;
  }

  .report-head {
    flex-direction: column;
  }
}
</style>
