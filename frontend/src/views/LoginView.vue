<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import { toApiError } from '@/api/client'
import { useAuth } from '@/composables/useAuth'
import { sanitizeRedirect } from '@/router'
import { isValidEmail } from '@/utils/validation'

const route = useRoute()
const router = useRouter()
const { login } = useAuth()

const email = ref('')
const password = ref('')
const fieldErrors = reactive<Record<string, string>>({})
const submitError = ref('')
const submitting = ref(false)

const registered = computed(() => route.query.registered === '1')

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
    await login(email.value.trim(), password.value)
    await router.replace(sanitizeRedirect(route.query.redirect))
  } catch (caught) {
    const error = toApiError(caught)
    if (error.code === 'invalid_credentials') {
      submitError.value = '邮箱或密码不正确'
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
        <h2>把每一次投递，<br /><em>当作一场有准备的交锋</em>。</h2>
        <p class="auth-lede">
          读岗、审稿、改写、预演、建议。五个智能体在同一条工作流里协作，
          把模糊的「我感觉还行」变成可核对的分数、缺口与版本。
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

        <h1>登录工作台</h1>
        <p class="auth-sub">使用邮箱进入你的分析档案。</p>

        <p v-if="registered" class="notice notice-success" role="status">
          注册成功，请使用新账号登录。
        </p>

        <form class="stack" novalidate @submit.prevent="onSubmit">
          <div class="field">
            <label for="login-email">邮箱</label>
            <input
              id="login-email"
              v-model="email"
              type="email"
              autocomplete="email"
              :aria-invalid="Boolean(fieldErrors.email)"
            />
            <p v-if="fieldErrors.email" class="field-error">{{ fieldErrors.email }}</p>
          </div>

          <div class="field">
            <label for="login-password">密码</label>
            <input
              id="login-password"
              v-model="password"
              type="password"
              autocomplete="current-password"
              :aria-invalid="Boolean(fieldErrors.password)"
            />
            <p v-if="fieldErrors.password" class="field-error">{{ fieldErrors.password }}</p>
            <span class="hint">至少 8 位，区分大小写。</span>
          </div>

          <p v-if="submitError" class="field-error" role="alert">{{ submitError }}</p>

          <div class="auth-actions">
            <button type="submit" class="btn btn-primary" :disabled="submitting">
              {{ submitting ? '登录中…' : '进入工作台' }}
            </button>
            <p class="auth-switch">
              还没有账号？<RouterLink to="/register">注册</RouterLink>
            </p>
          </div>
        </form>

        <p class="auth-legal">BY CONTINUING · 你同意仅将简历用于本次分析</p>
      </div>
    </div>
  </section>
</template>
