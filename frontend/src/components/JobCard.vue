<script setup lang="ts">
import { computed } from 'vue'

import type { InterviewReportSummary, JobResult } from '@/api/types'
import ScoreBadge from './ScoreBadge.vue'

const props = defineProps<{
  job: JobResult
  interview?: InterviewReportSummary | null
  risky?: boolean
  threshold?: number
  practicing?: boolean
}>()

defineEmits<{ practice: [] }>()

const failed = computed(() => props.job.status !== 'ok' || !props.job.review)
const company = computed(() => props.job.profile?.company?.trim() || '公司未标注')
const matched = computed(() => props.job.review?.matched ?? [])
const missing = computed(() => props.job.review?.missing ?? [])
const issues = computed(() => props.job.review?.issues ?? [])
const dimensions = computed(() =>
  Object.entries(props.job.review?.dimensions ?? {}).map(([name, value]) => ({
    name,
    value: Number(value),
  })),
)
const score = computed(() => props.job.review?.score ?? 0)
const effectiveThreshold = computed(() => Number(props.threshold ?? 70))
const history = computed(() => props.job.optimization_history ?? [])

const stamp = computed(() => {
  if (failed.value) {
    return { label: '分析失败', tone: 'stamp--gray' }
  }
  if (props.risky) {
    return { label: '达到上限', tone: 'stamp--amber' }
  }
  if (score.value >= effectiveThreshold.value) {
    return { label: score.value >= 80 ? '建议投递' : '达到阈值', tone: 'stamp--moss' }
  }
  return { label: '待补强', tone: '' }
})

const versionLabel = computed(() => {
  if (props.job.resume_source === 'variant') {
    return `v${props.job.current_variant_version} 定制简历`
  }
  return '原始简历'
})

const note = computed(() => {
  if (failed.value) {
    return '该岗位未产出可用结果'
  }
  if (props.risky) {
    return `已完成 ${history.value.length} 轮优化，仍未达到阈值`
  }
  if (!history.value.length) {
    return '未触发优化'
  }
  return `完成 ${history.value.length} 轮优化`
})

const meterWidth = computed(() => `${Math.max(0, Math.min(100, score.value))}%`)

const interviewTone = computed(() => {
  if (!props.interview) {
    return 'stamp--gray'
  }
  return props.interview.status === 'completed' ? 'stamp--moss' : 'stamp--amber'
})

const interviewLabel = computed(() => {
  if (!props.interview) {
    return ''
  }
  return props.interview.status === 'completed' ? '面试已完成' : '面试已中止'
})

const interviewSource = computed(() =>
  props.interview?.source === 'practice' ? '真人演练' : '离线预评估',
)
</script>

<template>
  <article class="job-card" :class="{ 'job-card-failed': failed }">
    <aside class="dossier-score">
      <ScoreBadge v-if="!failed && job.review" :score="job.review.score" />
      <div v-else class="score-missing">
        <span class="score-dash">—</span>
        <span class="score-missing-label">NO SCORE</span>
      </div>

      <div class="meter" aria-hidden="true">
        <i :style="{ width: failed ? '0%' : meterWidth }"></i>
      </div>

      <span class="stamp" :class="stamp.tone">{{ stamp.label }}</span>
      <p class="score-note">{{ note }}</p>
    </aside>

    <div class="dossier-body">
      <header class="job-head">
        <div>
          <h3>{{ job.title || '未命名岗位' }}</h3>
          <p class="company">{{ company }}</p>
        </div>
        <div class="tag-list">
          <span v-if="!failed" class="tag">{{ versionLabel }}</span>
          <span v-if="risky" class="tag tag--amber">风险</span>
          <span v-if="failed" class="tag">未完成</span>
          <button
            v-if="!failed"
            type="button"
            class="btn btn-ghost btn-sm"
            :disabled="practicing"
            @click="$emit('practice')"
          >
            {{ practicing ? '准备中…' : '开始演练' }}
          </button>
        </div>
      </header>

      <div v-if="failed" class="fail" role="status">
        <p class="failure-title">该岗位分析失败</p>
        <p class="failure-reason">{{ job.error || '未返回可用的评审结果' }}</p>
      </div>

      <template v-else>
        <div v-if="dimensions.length" class="dims" aria-label="维度评分">
          <div v-for="item in dimensions" :key="item.name" class="dim">
            <span class="dim-name">{{ item.name }}</span>
            <span class="dim-track"><i :style="{ width: `${Math.min(100, item.value)}%` }"></i></span>
            <span class="dim-value">{{ item.value }}</span>
          </div>
        </div>

        <section v-if="matched.length" class="block">
          <h4>匹配亮点</h4>
          <div class="tag-list">
            <span v-for="item in matched" :key="item" class="tag tag--moss">{{ item }}</span>
          </div>
        </section>

        <section class="block">
          <h4>缺失项</h4>
          <div v-if="missing.length" class="tag-list">
            <span v-for="item in missing" :key="item" class="tag tag--amber">{{ item }}</span>
          </div>
          <p v-else class="muted">无缺失项</p>
        </section>

        <section class="block">
          <h4>问题清单</h4>
          <ul v-if="issues.length" class="issue-list">
            <li v-for="item in issues" :key="item">{{ item }}</li>
          </ul>
          <p v-else class="muted">无问题记录</p>
        </section>

        <section v-if="history.length" class="block">
          <h4>优化轨迹</h4>
          <div class="timeline">
            <span class="timeline-node">
              <i class="dot"></i>
              <b>{{ history[0]?.score_before ?? score }}</b>
              <small>起始</small>
            </span>
            <template v-for="round in history" :key="round.round">
              <span class="timeline-dash" aria-hidden="true"></span>
              <span class="timeline-node">
                <i class="dot dot-fill"></i>
                <b>{{ round.score_after ?? '—' }}</b>
                <small>第 {{ round.round }} 轮</small>
              </span>
            </template>
          </div>
        </section>

        <section v-if="interview" class="interview">
          <div class="interview-head">
            <div class="interview-score">
              <b>{{ interview.overall_score ?? '—' }}</b>
              <span>/ 100 · 模拟面试</span>
            </div>
            <span class="stamp" :class="interviewTone">{{ interviewLabel }}</span>
          </div>
          <p class="interview-meta">
            {{ interviewSource }} · 已回答 {{ interview.answered_count }} /
            {{ interview.planned_count }} 题
          </p>
          <ul class="interview-list">
            <li v-for="item in interview.highlights" :key="`h-${item}`" class="good">
              亮点 · {{ item }}
            </li>
            <li v-for="item in interview.red_flags" :key="`r-${item}`" class="bad">
              风险 · {{ item }}
            </li>
            <li v-for="item in interview.requirement_gaps" :key="`g-${item}`" class="warn">
              缺口 · {{ item }}
            </li>
            <li v-for="item in interview.improvements" :key="`i-${item}`" class="plain">
              改进 · {{ item }}
            </li>
          </ul>
        </section>
      </template>
    </div>
  </article>
</template>

<style scoped>
.job-card {
  display: grid;
  grid-template-columns: 178px minmax(0, 1fr);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
}

.job-card-failed {
  border-color: var(--color-primary);
}

.dossier-score {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-5);
  border-right: 1px solid var(--color-border);
  background: var(--color-bg);
}

.score-missing {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.score-dash {
  font-family: var(--font-serif);
  font-size: 48px;
  font-weight: 900;
  line-height: 1;
  color: var(--color-ink-3);
}

.score-missing-label {
  font-family: var(--font-mono);
  font-size: 8px;
  letter-spacing: 0.16em;
  color: var(--color-ink-3);
}

.meter {
  width: 100%;
  height: 3px;
  background: var(--color-surface-muted);
  overflow: hidden;
}

.meter i {
  display: block;
  height: 100%;
  background: var(--color-text);
}

.score-note {
  margin: 0;
  font-size: 10px;
  line-height: 1.5;
  color: var(--color-text-muted);
}

.dossier-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-5);
  min-width: 0;
}

.job-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--color-border);
}

.job-head h3 {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: 700;
}

.company {
  margin: 4px 0 0;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.06em;
  color: var(--color-text-muted);
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.dims {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
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

.block h4 {
  margin: 0 0 8px;
  font-family: var(--font-mono);
  font-size: 9px;
  font-weight: 500;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}

.block p {
  margin: 0;
  font-size: var(--text-sm);
}

.issue-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.issue-list li {
  display: flex;
  gap: 8px;
  font-size: var(--text-sm);
  color: var(--color-ink-2);
}

.issue-list li::before {
  content: "—";
  color: var(--color-primary);
}

.timeline {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 0;
}

.timeline-node {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.timeline-node b {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
}

.timeline-node small {
  font-family: var(--font-mono);
  font-size: 8px;
  color: var(--color-ink-3);
}

.dot {
  width: 6px;
  height: 6px;
  border: 1px solid var(--color-ink-3);
  border-radius: 50%;
}

.dot-fill {
  border-color: var(--color-primary);
  background: var(--color-primary);
}

.timeline-dash {
  width: 24px;
  height: 1px;
  margin: 0 6px;
  background: var(--color-border-strong);
}

.interview {
  padding: var(--space-4);
  border: 1px solid var(--color-border-strong);
  background: var(--color-bg);
}

.interview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.interview-score {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.interview-score b {
  font-family: var(--font-serif);
  font-size: 24px;
  font-weight: 700;
  line-height: 1;
}

.interview-score span {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.1em;
  color: var(--color-text-muted);
}

.interview-meta {
  margin: 6px 0 10px;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.06em;
  color: var(--color-text-muted);
}

.interview-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11.5px;
  line-height: 1.65;
}

.interview-list li {
  display: flex;
  gap: 7px;
}

.interview-list li::before {
  content: "·";
}

.interview-list .good {
  color: var(--color-moss);
}

.interview-list .bad {
  color: var(--color-primary-strong);
}

.interview-list .warn {
  color: var(--color-amber);
}

.fail {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.failure-title {
  margin: 0;
  font-weight: 600;
}

.failure-reason {
  margin: 0;
  font-size: var(--text-sm);
}

@media (max-width: 720px) {
  .job-card {
    grid-template-columns: 1fr;
  }

  .dossier-score {
    flex-direction: row;
    flex-wrap: wrap;
    align-items: center;
    border-right: none;
    border-bottom: 1px solid var(--color-border);
    padding: var(--space-4);
  }

  .dossier-score .meter {
    flex-basis: 100%;
  }

  .dossier-body {
    padding: var(--space-4);
  }
}
</style>
