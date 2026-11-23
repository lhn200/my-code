import { createApp } from 'vue'

import { installUnauthorizedHandler } from '@/auth/unauthorized'
import App from '@/App.vue'
import { useAuth } from '@/composables/useAuth'
import { createAppRouter } from '@/router'
import '@/styles/tokens.css'
import '@/styles/base.css'

const auth = useAuth()
auth.restore()

const router = createAppRouter()
installUnauthorizedHandler(router, auth)

createApp(App).use(router).mount('#app')
