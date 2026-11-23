<script setup lang="ts">
import { computed } from 'vue'

import type { JobResult, OptimizationRound, RunResult, RunState } from '@/api/types'
import EmptyState from './EmptyState.vue'
import JobCard from './JobCard.vue'
import MarkdownView from './MarkdownView.vue'

const props = defineProps<{
  result: RunResult
  state?: RunState | null
}>()

const statusInfo = computed(() => {
  switch (props.result.run_status) {
    case 'succeeded':
      return { label: '全部岗位分析成功', tone: 'notice-success', short: '全部成功' }
    case 'partial':
      return { label: '部分岗位分析成功', tone: 'notice-warning', short: '部分成功' }
    default:
      return { label: '分析失败', tone: 'notice-error', short: '分析失败' }
  }
})

const rounds = computed<Array<OptimizationRound & { title: string }>>(() => {
  const items: Array<OptimizationRound & { title: string }> = []
  for (const job of props.result.jobs) {
    for (const round of job.optimization_history) {
      items.push({ ...round, title: job.title || job.job_id })
    }
  }
  return items.sort(
    (left, right) => left.round - right.round || left.job_id.localeCompare(right.job_id),
  )
})

const maxRounds = computed(() => Number(props.state?.max_rounds ?? 0))
const threshold = computed(() => Number(props.state?.threshold ?? 0))

const riskyJobs = computed<JobResult[]>(() => {
  if (maxRounds.value <= 0 || threshold.value <= 0) {
    return []
  }
  return props.result.jobs.filter(
    (job) =>
      job.status === 'ok' &&
      job.current_variant_version >= maxRounds.value &&
      (job.review?.score ?? 0) < threshold.value,
  )
})

const scoredJobs = computed(() =>
  props.result.jobs.filter(
    (job): job is JobResult & { review: NonNullable<JobResult['review']> } =>
      job.status === 'ok' && Boolean(job.review),
  ),
)

const highestScore = computed(() => {
  if (!scoredJobs.value.length) {
    return null
  }
  return Math.max(...scoredJobs.value.map((job) => job.review.score))
})

const bestJobTitle = computed(() => {
  if (highestScore.value === null) {
    return '暂无评分'
  }
  const best = scoredJobs.value.find((job) => job.review.score === highestScore.value)
  return best?.title || best?.job_id || '—'
})

const interviewCount = computed(() => Object.keys(props.result.interview_reports ?? {}).length)

const failedCount = computed(() => props.result.jobs.filter((job) => job.status !== 'ok').length)

function isRiskyRound(round: OptimizationRound): boolean {
  return riskyJobs.value.some((job) => job.job_id === round.job_id)
}

function interviewFor(job: JobResult) {
  return props.result.interview_reports?.[job.job_id] ?? null
}
</script>

<template>
  <div class="run-results">
    <p class="notice" :class="statusInfo.tone" role="status">{{ statusInfo.label }}</p>

    <section class="run-summary" aria-label="运行摘要">
      <div class="summary-cell">
        <span class="summary-label">RUN STATUS</span>
        <span class="summary-status" :class="statusInfo.tone">
          <i aria-hidden="true"></i>
          <b>{{ statusInfo.short }}</b>
        </span>
        <p>{{ result.jobs.length }} 个岗位 · 失败 {{ failedCount }} 个</p>
      </div>
      <div class="summary-cell">
        <span class="summary-label">最高匹配分</span>
        <b class="summary-number">{{ highestScore ?? '—' }}</b>
        <p>{{ bestJobTitle }}</p>
      </div>
      <div class="summary-cell">
        <span class="summary-label">优化轮次</span>
        <b class="summary-number">{{ rounds.length }}</b>
        <p>简历改写记录</p>
      </div>
      <div class="summary-cell">
        <span class="summary-label">模拟面试</span>
        <b class="summary-number">{{ interviewCount }}</b>
        <p>已归档场次</p>
      </div>
    </section>

    <p v-if="!result.jobs.length" class="notice notice-error" role="alert">
      本次运行没有可展示的岗位结果，请保留 thread_id 以便排查。
    </p>

    <section class="dossier-list" aria-label="岗位分析结果">
      <JobCard
        v-for="job in result.jobs"
        :key="job.job_id"
        :job="job"
        :interview="interviewFor(job)"
        :risky="riskyJobs.some((item) => item.job_id === job.job_id)"
        :threshold="threshold || 70"
      />
    </section>

    <section class="card record-card" aria-labelledby="optimization-heading">
      <div class="card-head">
        <div>
          <p class="eyebrow">OPTIMIZATION LOG</p>
          <h2 id="optimization-heading">简历优化历史</h2>
        </div>
        <span class="tag">{{ rounds.length }} 轮</span>
      </div>

      <EmptyState
        v-if="!rounds.length"
        title="未触发简历优化"
        description="所有岗位均达到阈值，或没有产生优化轮次。"
      />
      <ol v-else class="round-list">
        <li v-for="round in rounds" :key="`${round.job_id}-${round.round}`" class="round-item">
          <span class="round-index">第 {{ round.round }} 轮</span>
          <span class="round-job">{{ round.title }}</span>
          <span class="round-score">{{ round.score_before }} → {{ round.score_after ?? '—' }}</span>
          <span v-if="isRiskyRound(round)" class="tag tag--amber">达到轮数上限仍未达标</span>
          <p v-if="round.summary" class="round-summary">{{ round.summary }}</p>
        </li>
      </ol>
      <p v-if="riskyJobs.length" class="notice notice-warning" role="status">
        以下岗位达到优化轮数上限仍未达到阈值：
        {{ riskyJobs.map((job) => job.title || job.job_id).join('、') }}
      </p>
    </section>

    <section class="card advice" aria-labelledby="advice-heading">
      <p class="eyebrow">ADVISOR MEMO</p>
      <h2 id="advice-heading">求职建议</h2>
      <MarkdownView :source="result.advice" />
    </section>
  </div>
</template>

<style scoped>
.run-results {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.run-summary {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  border: 1px solid var(--color-border-strong);
  background: var(--color-surface);
}

.summary-cell {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: var(--space-4) var(--space-5);
  border-right: 1px solid var(--color-border);
}

.summary-cell:last-child {
  border-right: 0;
}

.summary-label {
  font-family: var(--font-mono);
  font-size: 8.5px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}

.summary-number {
  font-family: var(--font-serif);
  font-size: 28px;
  font-weight: 700;
  line-height: 1.1;
}

.summary-cell p {
  margin: 0;
  font-size: 10.5px;
  color: var(--color-text-muted);
}

.summary-status {
  display: flex;
  align-items: center;
  gap: 7px;
  font-family: var(--font-serif);
  font-size: 18px;
  font-weight: 700;
  line-height: 1.2;
}

.summary-status i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.summary-status.notice-success {
  color: var(--color-moss);
  background: none;
  border: none;
}

.summary-status.notice-warning {
  color: var(--color-amber);
  background: none;
  border: none;
}

.summary-status.notice-error {
  color: var(--color-primary);
  background: none;
  border: none;
}

.dossier-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.card {
  padding: var(--space-5);
}

.card-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--color-border);
}

.card-head h2,
.advice h2 {
  margin: 4px 0 0;
  font-size: var(--text-xl);
  font-weight: 700;
}

.round-list {
  display: flex;
  flex-direction: column;
  gap: 0;
  border-top: 1px solid var(--color-border);
}

.round-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
  padding: 12px 0;
  border-bottom: 1px solid var(--color-border);
}

.round-index {
  min-width: 4.5em;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.06em;
  color: var(--color-primary);
}

.round-job {
  font-family: var(--font-serif);
  font-size: 14px;
  font-weight: 600;
}

.round-score {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--color-ink-2);
}

.round-summary {
  flex-basis: 100%;
  margin: 0;
  font-size: 11.5px;
  color: var(--color-text-muted);
}

.advice :deep(h2),
.advice :deep(h3),
.advice :deep(h4) {
  font-family: var(--font-serif);
  color: var(--color-text);
}

.advice :deep(h2) {
  margin: 22px 0 8px;
  font-size: 19px;
}

.advice :deep(h3) {
  margin: 18px 0 6px;
  font-size: 16px;
}

.advice :deep(h4) {
  margin: 16px 0 6px;
  font-size: 14px;
  color: var(--color-primary);
}

.advice :deep(p),
.advice :deep(li) {
  font-size: 13.5px;
  line-height: 1.85;
  color: var(--color-ink-2);
}

.advice :deep(ul),
.advice :deep(ol) {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 8px 0 14px;
  padding-left: var(--space-4);
  list-style: disc;
}

.advice :deep(strong) {
  color: var(--color-text);
}

.advice :deep(blockquote) {
  margin: 12px 0;
  padding: 10px 14px;
  border-left: 2px solid var(--color-primary);
  background: var(--color-bg);
  color: var(--color-text-muted);
}

.advice :deep(code) {
  padding: 1px 5px;
  background: var(--color-surface-muted);
  font-family: var(--font-mono);
  font-size: 0.9em;
}

@media (max-width: 1024px) {
  .run-summary {
    grid-template-columns: repeat(2, 1fr);
  }

  .summary-cell:nth-child(2) {
    border-right: 0;
  }

  .summary-cell:nth-child(-n + 2) {
    border-bottom: 1px solid var(--color-border);
  }
}

@media (max-width: 720px) {
  .run-summary {
    grid-template-columns: 1fr;
  }

  .summary-cell {
    border-right: 0;
    border-bottom: 1px solid var(--color-border);
  }

  .summary-cell:last-child {
    border-bottom: 0;
  }
}
</style>
