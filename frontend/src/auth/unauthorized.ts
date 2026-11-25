import type { Router } from 'vue-router'

import { setUnauthorizedHandler } from '@/api/client'
import { sanitizeRedirect } from '@/utils/redirect'

export interface AuthController {
  clearSession: () => void
}

/**
 * 401 统一处理：清理本地会话并跳转登录页，携带站内相对 redirect。
 * 客户端内部有防重入标记，多个并发 401 只会触发一次。
 */
export function installUnauthorizedHandler(router: Router, auth: AuthController): void {
  setUnauthorizedHandler(() => {
    auth.clearSession()
    const current = router.currentRoute.value
    if (current.name !== 'login') {
      void router.replace({
        name: 'login',
        query: { redirect: sanitizeRedirect(current.fullPath) },
      })
    }
  })
}
