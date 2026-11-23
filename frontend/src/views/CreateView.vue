<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import { isApiError } from '@/api/client'
import { createRun } from '@/api/runs'
import ResumeUploader from '@/components/ResumeUploader.vue'
import { MAX_JOBS, useAnalysisForm, type ResumeMode } from '@/composables/useAnalysisForm'
import { useResumeIntake } from '@/composables/useResumeIntake'
import { clearPendingRun, markPendingRun, readPendingRun } from '@/utils/pendingRun'

const router = useRouter()
const {
  goal,
  jobs,
  resumeText,
  fieldErrors,
  generalErrors,
  errorCount,
  validate,
  buildRequest,
  applyApiError,
  addJob,
  removeJob,
} = useAnalysisForm()

const intake = useResumeIntake({
  onParsed: (text) => {
    resumeText.value = text
  },
})
const {
  status: uploadStatus,
  selectedFile,
  result: parseResult,
  errorMessage: uploadErrorMessage,
  isUploading,
  hasParsedResult,
  selectFile,
  cancel: cancelUpload,
} = intake

const mode = ref<ResumeMode>('paste')
const submitting = ref(false)
const submitError = ref('')
const submitThreadId = ref('')
const pendingNotice = ref(false)

const canAddJob = computed(() => jobs.value.length < MAX_JOBS)
const submitDisabled = computed(() => submitting.value || isUploading.value)
const remainingJobs = computed(() => MAX_JOBS - jobs.value.length)
const errorMessages = computed(() =>
  Array.from(new Set([...generalErrors.value, ...Object.values(fieldErrors)])),
)

onMounted(() => {
  pendingNotice.value = Boolean(readPendingRun())
})

function dismissPendingNotice(): void {
  clearPendingRun()
  pendingNotice.value = false
}

function setMode(next: ResumeMode): void {
  mode.value = next
}

function onSelectFile(file: File): void {
  void selectFile(file)
}

function beforeUnload(event: BeforeUnloadEvent): void {
  event.preventDefault()
  event.returnValue = ''
}

watch(submitting, (value) => {
  if (typeof window === 'undefined') {
    return
  }
  if (value) {
    window.addEventListener('beforeunload', beforeUnload)
  } else {
    window.removeEventListener('beforeunload', beforeUnload)
  }
})

async function onSubmit(): Promise<void> {
  if (submitDisabled.value) {
    return
  }
  submitError.value = ''
  submitThreadId.value = ''
  if (!validate(mode.value, hasParsedResult.value)) {
    await nextTick()
    document.querySelector('.field-error')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    return
  }

  submitting.value = true
  markPendingRun(goal.value)

  try {
    const result = await createRun(buildRequest(), { timeoutMs: 60_000 })
    clearPendingRun()
    await router.push({ name: 'run-detail', params: { threadId: result.thread_id } })
  } catch (caught) {
    const apiError = isApiError(caught) ? caught : null
    if (apiError && apiError.code === 'request_canceled') {
      return
    }
    if (apiError?.kind === 'timeout') {
      submitError.value = '提交超时：请先到会话列表确认是否已创建，避免重复提交。'
      return
    }
    if (apiError) {
      applyApiError(apiError)
      submitError.value = apiError.message
      submitThreadId.value = apiError.threadId ?? ''
    } else {
      submitError.value = '提交失败，请稍后重试'
    }
    clearPendingRun()
  } finally {
    submitting.value = false
  }
}

onUnmounted(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('beforeunload', beforeUnload)
  }
  intake.cancel()
})
</script>

<template>
  <section class="page">
    <header class="page-header">
      <div>
        <div class="crumb">工作台 / <b>新建分析</b></div>
        <h1>创建分析</h1>
        <p>填写求职目标、目标岗位与简历，一次获取多岗位匹配评分与优化建议。</p>
      </div>
      <span class="tag">单次最多 {{ MAX_JOBS }} 个岗位</span>
    </header>

    <div v-if="pendingNotice" class="banner" role="status">
      <span>
        上次分析可能仍在进行。可前往
        <RouterLink to="/sessions">会话列表</RouterLink>
        查看最新结果。
      </span>
      <button type="button" class="btn btn-sm" @click="dismissPendingNotice">关闭提示</button>
    </div>

    <div class="grid">
      <form class="col-8 stack create-form" novalidate @submit.prevent="onSubmit">
        <div class="field">
          <label for="goal">01 · 求职目标</label>
          <textarea
            id="goal"
            v-model="goal"
            rows="3"
            placeholder="例如：寻找一份后端开发工程师工作，偏好远程或上海"
            :aria-invalid="Boolean(fieldErrors.goal)"
            aria-describedby="goal-error"
          ></textarea>
          <p v-if="fieldErrors.goal" id="goal-error" class="field-error">{{ fieldErrors.goal }}</p>
        </div>

        <section class="section" aria-labelledby="jobs-label">
          <div class="section-head">
            <span id="jobs-label" class="eyebrow">02 · 目标岗位</span>
            <span class="counter">
              {{ jobs.length }} / {{ MAX_JOBS }} · 还可新增 {{ remainingJobs }} 个
            </span>
          </div>

          <div class="job-list">
            <div v-for="(job, index) in jobs" :key="job.uid" class="job-edit">
              <div class="job-edit-head">
                <span class="job-no">
                  <b>{{ String(index + 1).padStart(2, '0') }}</b> 岗位
                </span>
                <button
                  v-if="jobs.length > 1"
                  type="button"
                  class="del-btn"
                  @click="removeJob(job.uid)"
                >
                  删除岗位
                </button>
              </div>

              <div class="field">
                <label :for="`title-${job.uid}`">岗位标题</label>
                <input
                  :id="`title-${job.uid}`"
                  v-model="job.title"
                  type="text"
                  placeholder="例如：高级后端工程师"
                  :aria-invalid="Boolean(fieldErrors[`jobs.${job.uid}.title`])"
                />
                <p v-if="fieldErrors[`jobs.${job.uid}.title`]" class="field-error">
                  {{ fieldErrors[`jobs.${job.uid}.title`] }}
                </p>
              </div>

              <div class="field">
                <label :for="`jd-${job.uid}`">岗位 JD · 原始职位描述</label>
                <textarea
                  :id="`jd-${job.uid}`"
                  v-model="job.positionText"
                  rows="6"
                  placeholder="粘贴完整的职位描述文本"
                  :aria-invalid="Boolean(fieldErrors[`jobs.${job.uid}.positionText`])"
                ></textarea>
                <p v-if="fieldErrors[`jobs.${job.uid}.positionText`]" class="field-error">
                  {{ fieldErrors[`jobs.${job.uid}.positionText`] }}
                </p>
                <span class="hint">粘贴完整 JD，系统会自动抽取硬性要求与关键词。</span>
              </div>
            </div>
          </div>

          <div class="row job-actions">
            <button type="button" class="btn btn-ghost btn-sm" :disabled="!canAddJob" @click="addJob">
              ＋ 新增岗位
            </button>
            <span v-if="!canAddJob" class="muted">单次最多分析 {{ MAX_JOBS }} 个岗位</span>
          </div>
          <p v-if="fieldErrors.jobs" class="field-error">{{ fieldErrors.jobs }}</p>
        </section>

        <section class="section" aria-labelledby="resume-label">
          <div class="section-head">
            <span id="resume-label" class="eyebrow">03 · 简历</span>
            <div class="seg" role="group" aria-label="简历输入方式">
              <button
                type="button"
                :class="{ on: mode === 'paste' }"
                :aria-pressed="mode === 'paste'"
                @click="setMode('paste')"
              >
                粘贴文本
              </button>
              <button
                type="button"
                :class="{ on: mode === 'upload' }"
                :aria-pressed="mode === 'upload'"
                @click="setMode('upload')"
              >
                上传文件
              </button>
            </div>
          </div>

          <ResumeUploader
            v-if="mode === 'upload'"
            v-model="resumeText"
            :status="uploadStatus"
            :file-name="selectedFile?.name"
            :file-size="selectedFile?.size"
            :error-message="uploadErrorMessage"
            :result="parseResult"
            :disabled="submitting"
            @select="onSelectFile"
            @cancel="cancelUpload"
          />

          <div v-if="mode === 'paste'" class="field">
            <label for="resume-text">简历内容</label>
            <textarea
              id="resume-text"
              v-model="resumeText"
              rows="10"
              placeholder="粘贴简历完整文本"
              :aria-invalid="Boolean(fieldErrors.resume_text)"
              aria-describedby="resume-error"
            ></textarea>
          </div>

          <p v-if="fieldErrors.resume_text" id="resume-error" class="field-error">
            {{ fieldErrors.resume_text }}
          </p>

          <div v-if="mode === 'paste'" class="row resume-tags">
            <span class="tag">支持 PDF / DOCX / 图片</span>
            <span class="tag tag--moss">服务端解析 · OCR 兜底</span>
            <span class="hint">解析后的文本可继续手动编辑。</span>
          </div>
        </section>

        <div v-if="errorCount" class="notice notice-error" role="alert" aria-live="polite">
          <p>有 {{ errorCount }} 处需要修正。</p>
          <ul v-if="errorMessages.length" class="summary-list">
            <li v-for="message in errorMessages" :key="message">{{ message }}</li>
          </ul>
        </div>

        <div class="submit-bar">
          <div class="submit-main">
            <button
              type="submit"
              class="btn btn-primary"
              :disabled="submitDisabled"
              :aria-busy="submitting"
            >
              {{ submitting ? '分析中…' : '开始分析 →' }}
            </button>
            <p class="hint">
              提交后立即进入结果页，分析在后台执行；可随时关闭页面，稍后到会话列表查看结果。
            </p>
            <p v-if="submitError" class="field-error" role="alert">{{ submitError }}</p>
            <p v-if="submitThreadId" class="muted">thread_id：<code>{{ submitThreadId }}</code></p>
          </div>
          <span class="counter">{{ jobs.length }} 个岗位 · 1 份简历</span>
        </div>
      </form>

      <aside class="col-4">
        <div class="aside">
          <h3>分析将如何运行</h3>
          <p class="aside-sub">提交后，五个智能体按顺序协作；岗位之间并行，互不阻塞。</p>

          <div class="agent">
            <div class="agent-top"><i>01</i><b>职位分析师</b></div>
            <p>读取 JD，抽取硬性要求、加分项与关键词，判断文本是否为有效岗位。</p>
          </div>
          <div class="agent">
            <div class="agent-top"><i>02</i><b>简历评审</b></div>
            <p>按技能、经验、项目、教育四维打分，列出匹配项、缺失项与问题。</p>
          </div>
          <div class="agent">
            <div class="agent-top"><i>03</i><b>简历优化</b></div>
            <p>低于阈值时按岗位独立改写，生成互不覆盖的定制版本并重新评审。</p>
          </div>
          <div class="agent">
            <div class="agent-top"><i>04</i><b>模拟面试</b></div>
            <p>基于岗位与当前简历版本评估，给出分数、亮点与需补强的缺口。</p>
          </div>
          <div class="agent">
            <div class="agent-top"><i>05</i><b>职业顾问</b></div>
            <p>汇总所有岗位结果，输出投递优先级、逐岗建议与下一步行动。</p>
          </div>

          <ul class="rule-list">
            <li>单次最多 {{ MAX_JOBS }} 个岗位，超限不会启动工作流</li>
            <li>匹配分低于 70 触发该岗位的优化回路</li>
            <li>优化与面试各最多 2 轮，避免无限循环</li>
          </ul>

          <p class="privacy">
            简历只在服务端解析，运行时状态仅保存文件引用与解析后的纯文本，不保存二进制内容。
          </p>
        </div>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.create-form {
  min-width: 0;
}

.section {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.counter {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.06em;
  color: var(--color-text-muted);
}

.seg {
  display: inline-flex;
  gap: 3px;
  padding: 3px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-sm);
  background: var(--color-bg);
}

.seg button {
  padding: 6px 14px;
  border: none;
  border-radius: 1px;
  background: transparent;
  color: var(--color-text-muted);
  font-size: 11px;
  transition:
    background var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.seg button.on {
  background: var(--color-text);
  color: var(--color-bg);
}

.job-list {
  display: flex;
  flex-direction: column;
}

.job-edit {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-5);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
}

.job-edit + .job-edit {
  margin-top: -1px;
}

.job-edit:focus-within {
  border-color: var(--color-text);
  box-shadow: 3px 3px 0 var(--color-surface-muted);
}

.job-edit-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
}

.job-no {
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.14em;
  color: var(--color-text-muted);
}

.job-no b {
  font-family: var(--font-serif);
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0;
  color: var(--color-text);
}

.del-btn {
  padding: 0;
  border: none;
  border-bottom: 1px solid var(--color-border-strong);
  background: none;
  color: var(--color-text-muted);
  font-size: 11px;
}

.del-btn:hover {
  color: var(--color-primary);
  border-bottom-color: var(--color-primary);
}

.job-actions {
  margin-top: var(--space-1);
}

.resume-tags {
  margin-top: var(--space-1);
}

.summary-list {
  margin: var(--space-2) 0 0;
  padding-left: var(--space-5);
  list-style: disc;
}

.submit-bar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  margin-top: var(--space-1);
  padding: 18px 0 16px;
  border-top: 1px solid var(--color-text);
  background: var(--color-bg);
}

.submit-main {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
}

.submit-main .notice {
  margin: 0;
}

.aside {
  position: sticky;
  top: 88px;
  display: flex;
  flex-direction: column;
  padding: var(--space-5);
  border: 1px solid var(--color-text);
  background: var(--color-bg);
}

.aside h3 {
  margin: 0;
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--color-border);
  font-size: 17px;
  font-weight: 700;
}

.aside-sub {
  margin: 10px 0 6px;
  font-size: 11px;
  line-height: 1.7;
  color: var(--color-text-muted);
}

.agent {
  padding: 12px 0;
  border-bottom: 1px dotted var(--color-border-strong);
}

.agent:last-of-type {
  border-bottom: 0;
  padding-bottom: 0;
}

.agent-top {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.agent-top i {
  font-family: var(--font-mono);
  font-style: normal;
  font-size: 9px;
  color: var(--color-primary);
}

.agent-top b {
  font-size: 13px;
  font-weight: 600;
}

.agent p {
  margin: 3px 0 0;
  font-size: 11px;
  line-height: 1.6;
  color: var(--color-text-muted);
}

.rule-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--color-border);
}

.rule-list li {
  display: flex;
  gap: 8px;
  font-size: 11px;
  color: var(--color-ink-2);
}

.rule-list li::before {
  content: "—";
  color: var(--color-primary);
}

.privacy {
  margin: 14px 0 0;
  padding: 10px 12px;
  border: 1px dashed var(--color-border-strong);
  font-size: 10px;
  line-height: 1.65;
  color: var(--color-text-muted);
}

code {
  font-family: var(--font-mono);
}

@media (max-width: 1024px) {
  .aside {
    position: static;
  }
}

@media (max-width: 720px) {
  .job-edit {
    padding: var(--space-4);
  }

  .submit-bar {
    position: sticky;
    bottom: 0;
    z-index: 5;
    flex-direction: column;
    box-shadow: 0 -10px 20px -16px var(--color-text);
  }

  .submit-bar .counter {
    align-self: flex-end;
  }
}
</style>
