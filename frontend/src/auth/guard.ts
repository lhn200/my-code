import type { RouteLocationNormalized } from 'vue-router'

import { useAuth } from '@/composables/useAuth'
import { sanitizeRedirect } from '@/utils/redirect'

export function authGuard(to: RouteLocationNormalized) {
  const { isAuthenticated } = useAuth()
  if (to.meta.requiresAuth && !isAuthenticated.value) {
    return {
      name: 'login',
      query: { redirect: sanitizeRedirect(to.fullPath) },
    }
  }
  if ((to.name === 'login' || to.name === 'register') && isAuthenticated.value) {
    return { path: '/' }
  }
  return true
}
