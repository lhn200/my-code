<script setup lang="ts">
import { reactive, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import { toApiError } from '@/api/client'
import { useAuth } from '@/composables/useAuth'
import { isValidEmail } from '@/utils/validation'

const router = useRouter()
const { register } = useAuth()

const email = ref('')
const password = ref('')
const fieldErrors = reactive<Record<string, string>>({})
const submitError = ref('')
const submitting = ref(false)

function validate(): boolean {
  for (const key of Object.keys(fieldErrors)) {
    delete fieldErrors[key]
  }
  if (!isValidEmail(email.value)) {
    fieldErrors.email = '请输入有效的邮箱地址'
  }
  if (password.value.length < 8) {
    fieldErrors.password = '密码至少需要 8 位'
  }
  return Object.keys(fieldErrors).length === 0
}

async function onSubmit(): Promise<void> {
  if (submitting.value || !validate()) {
    return
  }
  submitting.value = true
  submitError.value = ''
  try {
    await register(email.value.trim(), password.value)
    await router.push({ name: 'login', query: { registered: '1' } })
  } catch (caught) {
    const error = toApiError(caught)
    if (error.code === 'email_taken') {
      fieldErrors.email = '该邮箱已被注册'
    } else if (error.fields.length) {
      for (const item of error.fields) {
        if (item.field === 'email' || item.field === 'password') {
          fieldErrors[item.field] = item.message
        } else {
          submitError.value = item.message
        }
      }
    } else {
      submitError.value = error.message
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="auth-layout">
    <aside class="auth-brand">
      <div>
        <p class="eyebrow">CAREER DOSSIER · MULTI-AGENT</p>
        <h2>为你的下一份工作，<br /><em>建立可追溯的档案</em>。</h2>
        <p class="auth-lede">
          每次分析都会留下岗位得分、简历版本与优化轨迹。
          注册后，你的会话与长期记忆只属于这个账号。
        </p>
      </div>
      <div>
        <div class="auth-stats">
          <div class="auth-stat"><b>5</b><span>AGENTS</span></div>
          <div class="auth-stat"><b>≤5</b><span>JOBS / RUN</span></div>
          <div class="auth-stat"><b>2</b><span>ROUNDS</span></div>
        </div>
        <p class="auth-privacy">会话与长期记忆按账号隔离 · 简历仅服务端解析</p>
      </div>
    </aside>

    <div class="auth-panel">
      <div class="auth-form">
        <RouterLink to="/login" class="auth-mark">
          <span class="seal" aria-hidden="true">职</span>
          <span>求职助手</span>
        </RouterLink>

        <h1>创建账号</h1>
        <p class="auth-sub">注册后即可保存并管理自己的分析会话。</p>

        <form class="stack" novalidate @submit.prevent="onSubmit">
          <div class="field">
            <label for="register-email">邮箱</label>
            <input
              id="register-email"
              v-model="email"
              type="email"
              autocomplete="email"
              :aria-invalid="Boolean(fieldErrors.email)"
            />
            <p v-if="fieldErrors.email" class="field-error">{{ fieldErrors.email }}</p>
          </div>

          <div class="field">
            <label for="register-password">密码</label>
            <input
              id="register-password"
              v-model="password"
              type="password"
              autocomplete="new-password"
              :aria-invalid="Boolean(fieldErrors.password)"
            />
            <p v-if="fieldErrors.password" class="field-error">{{ fieldErrors.password }}</p>
            <span class="hint">密码至少 8 位。</span>
          </div>

          <p v-if="submitError" class="field-error" role="alert">{{ submitError }}</p>

          <div class="auth-actions">
            <button type="submit" class="btn btn-primary" :disabled="submitting">
              {{ submitting ? '注册中…' : '创建账号' }}
            </button>
            <p class="auth-switch">
              已有账号？<RouterLink to="/login">登录</RouterLink>
            </p>
          </div>
        </form>

        <p class="auth-legal">BY CONTINUING · 你同意仅将简历用于本次分析</p>
      </div>
    </div>
  </section>
</template>
