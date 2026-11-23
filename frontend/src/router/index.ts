import {
  createRouter,
  createWebHistory,
  type RouteRecordRaw,
  type RouterHistory,
} from 'vue-router'

import { authGuard } from '@/auth/guard'
import CreateView from '@/views/CreateView.vue'
import LoginView from '@/views/LoginView.vue'
import MemorySettingsView from '@/views/MemorySettingsView.vue'
import RegisterView from '@/views/RegisterView.vue'
import RunDetailView from '@/views/RunDetailView.vue'
import RunQueryView from '@/views/RunQueryView.vue'
import SessionsView from '@/views/SessionsView.vue'
import { sanitizeRedirect } from '@/utils/redirect'

export { authGuard, sanitizeRedirect }

export const routes: RouteRecordRaw[] = [
  { path: '/', name: 'create', component: CreateView, meta: { requiresAuth: true } },
  { path: '/runs', name: 'run-query', component: RunQueryView, meta: { requiresAuth: true } },
  {
    path: '/runs/:threadId',
    name: 'run-detail',
    component: RunDetailView,
    meta: { requiresAuth: true },
  },
  {
    path: '/sessions',
    name: 'sessions',
    component: SessionsView,
    meta: { requiresAuth: true },
  },
  {
    path: '/settings/memory',
    name: 'memory-settings',
    component: MemorySettingsView,
    meta: { requiresAuth: true },
  },
  { path: '/login', name: 'login', component: LoginView },
  { path: '/register', name: 'register', component: RegisterView },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export function createAppRouter(
  history: RouterHistory = createWebHistory(),
): ReturnType<typeof createRouter> {
  const router = createRouter({ history, routes })
  router.beforeEach((to) => authGuard(to))
  return router
}
