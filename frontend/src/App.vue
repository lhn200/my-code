<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, RouterView, useRouter } from 'vue-router'

import { useAuth } from '@/composables/useAuth'

const { isAuthenticated, user, logout } = useAuth()
const router = useRouter()

const avatarInitial = computed(() => {
  const source = user.value?.email ?? ''
  return source ? source.slice(0, 1).toUpperCase() : '职'
})

async function onLogout(): Promise<void> {
  await logout()
  await router.push({ name: 'login' })
}
</script>

<template>
  <div class="app-shell" :class="{ 'app-shell--guest': !isAuthenticated }">
    <header v-if="isAuthenticated" class="app-header">
      <div class="app-header-inner">
        <RouterLink to="/" class="brand">
          <span class="brand-seal" aria-hidden="true">职</span>
          <span class="brand-text">
            求职助手
            <small>CAREER DOSSIER</small>
          </span>
        </RouterLink>

        <nav class="app-nav" aria-label="主导航">
          <RouterLink to="/">创建分析</RouterLink>
          <RouterLink to="/runs">查询会话</RouterLink>
          <RouterLink to="/sessions">会话列表</RouterLink>
          <RouterLink to="/settings/memory">记忆设置</RouterLink>
        </nav>

        <div class="app-account">
          <span class="app-email">{{ user?.email }}</span>
          <button type="button" class="link-button" @click="onLogout">退出登录</button>
          <span class="app-avatar" aria-hidden="true">{{ avatarInitial }}</span>
        </div>
      </div>
    </header>

    <main class="app-main" :class="{ 'app-main--guest': !isAuthenticated }">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.app-header {
  position: sticky;
  top: 0;
  z-index: 60;
  background: var(--color-header-bg);
  border-bottom: 1px solid var(--color-border);
  backdrop-filter: blur(12px);
}

.app-header-inner {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  width: 100%;
  max-width: var(--content-max);
  margin: 0 auto;
  padding: 12px 36px;
  flex-wrap: wrap;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--color-text);
  text-decoration: none;
}

.brand-seal {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border: 1.5px solid var(--color-primary);
  color: var(--color-primary);
  font-family: var(--font-serif);
  font-size: 17px;
  font-weight: 900;
  line-height: 1;
  box-shadow: 2px 2px 0 var(--color-danger-wash);
}

.brand-text {
  display: flex;
  flex-direction: column;
  font-family: var(--font-serif);
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.04em;
  line-height: 1.2;
}

.brand-text small {
  margin-top: 3px;
  font-family: var(--font-mono);
  font-size: 8.5px;
  font-weight: 400;
  letter-spacing: 0.16em;
  color: var(--color-ink-3);
}

.app-nav {
  display: flex;
  align-items: center;
  gap: 24px;
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.06em;
}

.app-nav a {
  padding: 4px 0;
  border-bottom: 1.5px solid transparent;
  color: var(--color-text-muted);
  text-decoration: none;
  transition: color var(--dur-fast) var(--ease);
}

.app-nav a:hover {
  color: var(--color-primary);
}

.app-nav a.router-link-exact-active {
  color: var(--color-primary);
  border-bottom-color: var(--color-primary);
}

.app-account {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: 11px;
}

.app-email {
  color: var(--color-text-muted);
  font-family: var(--font-mono);
  font-size: 10px;
}

.app-avatar {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--color-text);
  color: var(--color-bg);
  font-family: var(--font-serif);
  font-size: 12px;
}

.app-main {
  width: 100%;
  max-width: var(--content-max);
  margin: 0 auto;
  padding: 48px 36px 96px;
}

.app-main--guest {
  max-width: none;
  padding: 0;
}

.app-shell--guest {
  background: var(--color-bg);
}

@media (max-width: 1024px) {
  .app-header-inner {
    gap: var(--space-4);
    padding: 12px 20px;
  }

  .app-nav {
    gap: 16px;
    order: 3;
    width: 100%;
    margin-left: 0;
    padding-bottom: 4px;
  }

  .app-main {
    padding: 32px 20px 80px;
  }
}

@media (max-width: 720px) {
  .app-email {
    display: none;
  }

  .app-nav {
    overflow-x: auto;
    flex-wrap: nowrap;
    white-space: nowrap;
  }
}
</style>
