## 0. 前置检查

- [ ] 0.1 确认 `add-auth-sessions` 已 apply：`users` 表、argon2 哈希、含 `iat` 的 JWT、`get_current_user`、`auth/rate_limit.py` 与 `api/auth.py` 均存在
- [ ] 0.2 确认 `add-frontend-shell` 与 `add-auth-sessions` 的前端部分已 apply：路由、`api/client.ts`、`ApiError`、`useAuth`、401 拦截与 `/login`、`/register` 均存在
- [ ] 0.3 阅读 `db/migrations.py` 当前 `PRAGMA user_version` 基线，记录本 change 迁移目标版本号为基线 +1（不硬编码绝对数字）

## 1. 数据表结构与一次性令牌

- [ ] 1.1 在 `backend/app/db/migrations.py` 增加幂等 DDL：`CREATE TABLE IF NOT EXISTS auth_tokens`（`id`、`user_id`、`kind CHECK IN ('email_verify','password_reset')`、`token_hash UNIQUE`、`expires_at`、`used_at`、`created_at`）
- [ ] 1.2 在迁移中通过 `PRAGMA table_info(users)` 判断列是否存在，再执行 `ALTER TABLE users ADD COLUMN email_verified_at TEXT` 与 `ADD COLUMN password_changed_at TEXT`
- [ ] 1.3 增加索引：`(user_id, kind, created_at DESC)` 复合索引与 `expires_at` 索引，全部使用 `IF NOT EXISTS`；`token_hash` 的唯一约束由列内 `UNIQUE` 提供，不重复建同名索引
- [ ] 1.4 迁移末尾递增 `PRAGMA user_version`，确认连续启动两次不报错、不重复加列
- [ ] 1.5 实现 `backend/app/db/auth_tokens.py`：插入、按 `token_hash` 查询、条件更新 `used_at`（`WHERE used_at IS NULL`）、按用户与 `kind` 删除未使用记录、删除过期超过 7 天记录、按用户读取
- [ ] 1.6 实现 `backend/app/auth/tokens.py`：`secrets.token_urlsafe(32)` 生成明文、`sha256` 哈希、签发（先删除同用户同 `kind` 未使用记录再插入，单事务）、校验（不存在/过期/已使用分别返回原因）、消费（条件更新）、`cleanup_expired_tokens()`
- [ ] 1.7 补单元测试：哈希为 64 位十六进制且不等于明文；并发消费同一令牌只有一次成功；过期令牌校验返回过期；替换后旧令牌不再可用；清理只删除过期超过 7 天的记录

## 2. 邮件发送抽象与配置

- [ ] 2.1 在 `backend/app/email/base.py` 定义 `EmailSender` 接口：`send(*, to: str, subject: str, text: str) -> None`
- [ ] 2.2 实现 `backend/app/email/console.py`：把收件人、主题、正文与完整链接输出到标准输出，前缀标注 `[email:console]`，不得使用 `ERROR` 级别
- [ ] 2.3 实现 `backend/app/email/smtp.py`：使用 `smtplib`，端口 587 走 `starttls()`、465 走 `SMTP_SSL`，超时 10 秒，构造纯文本 `EmailMessage` 并设置 `From` / `To` / `Subject`
- [ ] 2.4 实现 `backend/app/email/factory.py`：按 `EMAIL_BACKEND` 返回单例发送器，未知取值直接抛配置错误
- [ ] 2.5 在 `backend/app/config.py` 增加 `APP_ENV`、`EMAIL_BACKEND`、`SMTP_HOST`、`SMTP_PORT`、`SMTP_USER`、`SMTP_PASSWORD`、`SMTP_FROM`、`FRONTEND_BASE_URL`、`EMAIL_VERIFY_TOKEN_TTL_HOURS`、`PASSWORD_RESET_TOKEN_TTL_MINUTES`、`EMAIL_VERIFY_RESEND_PER_HOUR`、`PASSWORD_FORGOT_PER_HOUR`、`TOKEN_RATE_LIMIT_PER_HOUR`、`PASSWORD_CHANGE_PER_HOUR` 及默认值
- [ ] 2.6 在 `backend/app/main.py` 启动校验中补齐：TTL / 限流为正整数、`smtp` 必填 `SMTP_HOST` 与 `SMTP_FROM`、`SMTP_USER` 与 `SMTP_PASSWORD` 同时提供或同时为空、`APP_ENV=production` 时禁止 `console`；失败直接退出
- [ ] 2.7 发信统一经 `asyncio.to_thread` 调用 `EmailSender.send`，捕获异常并记录掩码邮箱、`kind` 与异常类型，不记录令牌、哈希或完整链接
- [ ] 2.8 补测试：`console` 输出包含链接、`smtp` 配置缺失时启动失败、`production` + `console` 启动失败、非法 TTL 启动失败、发送异常不会向上冒泡为 500

## 3. 修改密码

- [ ] 3.1 在 `backend/app/auth/password.py` 增加新密码策略校验：长度 8–128、`argon2` 校验不得与当前密码相同
- [ ] 3.2 在 `backend/app/db/users.py` 增加更新密码哈希与 `password_changed_at` 的方法，并在同一事务内删除该用户未使用的 `password_reset` 令牌
- [ ] 3.3 实现 `POST /api/auth/password/change`：依赖 `get_current_user`，当前密码错误返回 `400 invalid_credentials`，策略失败返回 `422 weak_password`，成功返回 `204`
- [ ] 3.4 扩展 `backend/app/auth/rate_limit.py` 以支持 `user_id` 维度，并接入 `PASSWORD_CHANGE_PER_HOUR`（默认 10，按 `user_id`）限流，超限返回 `429 rate_limited` 且不校验密码
- [ ] 3.5 补接口测试：改密成功、当前密码错误 400、新密码过短/超长/与旧相同 422、未登录 401、改密后未使用的 `password_reset` 令牌失效

## 4. 邮箱验证

- [ ] 4.1 在 `POST /api/auth/register` 成功创建用户后签发 `email_verify` 令牌并尝试发信；任何发送或签发异常只记录日志，不影响 `201`
- [ ] 4.2 拼接验证链接 `${FRONTEND_BASE_URL}/verify-email?token=<明文令牌>`，去掉 `FRONTEND_BASE_URL` 尾部斜杠
- [ ] 4.3 实现 `POST /api/auth/email/verify-request`：要求登录；已验证返回 `200 already_verified` 且不发信；未验证替换旧令牌后发信并返回 `202`；超 `EMAIL_VERIFY_RESEND_PER_HOUR` 返回 `429`
- [ ] 4.4 实现 `POST /api/auth/email/verify`：匿名可用，只接受 `kind=email_verify` 令牌；令牌不存在/已使用或类型不符返回 `400 invalid_token`，过期返回 `400 token_expired`；成功写入 `email_verified_at` 与 `used_at` 并返回 `200`
- [ ] 4.5 保证验证端点只更新令牌所属用户，请求体不接受 `email` 或 `user_id`
- [ ] 4.6 在 `GET /api/auth/me` 响应中追加 `email_verified_at`，既有字段与顺序不破坏
- [ ] 4.7 补接口测试：注册后生成验证令牌、发信失败仍 201、有效令牌验证成功、重复使用 400、过期 400、伪造 400、跨用户只验证所属用户、给已验证用户重发 200 且不发信、重发超限 429、重发后旧令牌失效、`password_reset` 令牌提交到验证端点返回 400

## 5. 找回密码

- [ ] 5.1 实现 `POST /api/auth/password/forgot`：邮箱归一化后查询，三条分支均返回 `202` 与相同响应体；未命中分支执行等量令牌生成与哈希工作
- [ ] 5.2 仅当用户存在且 `email_verified_at` 非空时签发 `password_reset` 令牌并发送 `${FRONTEND_BASE_URL}/reset-password?token=<明文令牌>`
- [ ] 5.3 接入 `PASSWORD_FORGOT_PER_HOUR`（默认 5，按来源 IP）限流，限流在查库前生效，超限返回 `429 rate_limited`
- [ ] 5.4 实现 `POST /api/auth/password/reset`：只接受 `kind=password_reset` 令牌 → 校验令牌状态 → 校验新密码策略（失败不消费令牌）→ 校验 `email_verified_at`（为空返回 `403 email_not_verified`）→ 更新密码哈希与 `password_changed_at`、写入 `used_at`、删除其他未使用重置令牌 → 返回 `204`
- [ ] 5.5 接入 `TOKEN_RATE_LIMIT_PER_HOUR`（默认 30，按来源 IP）保护 verify 与 reset 端点，超限返回 `429 rate_limited`
- [ ] 5.6 补接口测试：已验证邮箱 202 并发信、未注册邮箱 202 且不发信、未验证邮箱 202 且不发信、响应体三者完全一致、重置成功 204、过期 400、复用 400、伪造 400、弱密码 422 且令牌未被消费、未验证邮箱 403、跨用户令牌只影响所属用户、重置后其他重置令牌失效、`email_verify` 令牌提交到重置端点返回 400、超过 `TOKEN_RATE_LIMIT_PER_HOUR` 返回 429 且令牌未被消费

## 6. JWT 定向失效校验

- [ ] 6.1 在 `backend/app/auth/dependencies.py` 的 `get_current_user` 中增加 `password_changed_at` 读取与 `iat` 比较：`password_changed_at` 非空且 `iat` 早于该时间返回 `401 token_revoked`
- [ ] 6.2 统一时间基准：将 `password_changed_at` 的 ISO-8601 UTC 文本解析为秒级时间戳后与 `iat` 比较，避免时区偏移
- [ ] 6.3 确认比较逻辑不写入任何状态、不修改其他用户字段，且 `password_changed_at` 为 `NULL` 时直接通过
- [ ] 6.4 补测试：改密前 token 401 `token_revoked`、改密后新登录 token 可用、同秒边界行为符合设计、其他用户 token 不受影响、`password_changed_at` 为 `NULL` 时既有 token 正常
- [ ] 6.5 补测试：重置密码成功后旧 JWT 同样返回 `401 token_revoked`

## 7. API 契约与错误码

- [ ] 7.1 在 `backend/app/api/auth.py` 注册五个新端点，路径固定为 `/api/auth/password/change`、`/api/auth/password/forgot`、`/api/auth/password/reset`、`/api/auth/email/verify-request`、`/api/auth/email/verify`
- [ ] 7.2 统一错误信封为 `{"detail": {"code": "...", "message": "..."}}`，新增端点只使用 `invalid_credentials`、`weak_password`、`invalid_token`、`token_expired`、`email_not_verified`、`token_revoked`、`rate_limited`，JWT 沿用 `not_authenticated` / `token_invalid`
- [ ] 7.3 为 `429` 响应补充 `Retry-After`，并确认限流响应不随邮箱或账号存在性变化
- [ ] 7.4 在 `backend/app/main.py` 注册路由并确认启动顺序为：配置校验 → 迁移 → 路由注册，校验失败不监听端口
- [ ] 7.5 补契约测试：五个端点各有成功与至少一种失败用例，断言状态码、`code` 与响应体结构

## 8. 前端

- [ ] 8.1 在 `frontend/src/api/client.ts` 的 `ApiError` 中增加可选 `code`，从统一错误信封解析；无 `code` 时回退既有文案
- [ ] 8.2 在 `frontend/src/api/types.ts` 的 `User` 中增加 `email_verified_at: string | null`
- [ ] 8.3 新增 `frontend/src/api/account.ts`：`changePassword`、`requestPasswordReset`、`resetPassword`、`requestEmailVerification`、`verifyEmail`
- [ ] 8.4 新增 `frontend/src/views/ForgotPasswordView.vue`：邮箱校验、提交态禁用、统一成功文案（不区分邮箱是否存在）、失败按 `code` 映射提示
- [ ] 8.5 新增 `frontend/src/views/ResetPasswordView.vue`：从 query 读取 `token`，缺失即提示并提供重新申请入口；新密码与确认密码校验；成功后清除 token 与用户状态并跳 `/login`
- [ ] 8.6 新增 `frontend/src/views/VerifyEmailView.vue`：读取 `token`，由用户点击后调用验证接口；成功/过期/已使用分别提示；已登录时刷新 `me`
- [ ] 8.7 新增 `frontend/src/views/SettingsView.vue`：修改密码三段表单（当前、新、确认），前端校验长度 8–128、两次一致、新旧不同；`invalid_credentials` 只展示字段错误、不触发 401 登出；成功后清 token 并跳 `/login`
- [ ] 8.8 新增 `frontend/src/components/EmailVerificationBanner.vue`：`email_verified_at` 为 `null` 时展示，提供重发按钮，重发成功提示查收邮件，已验证后隐藏；挂载到全局布局
- [ ] 8.9 修改路由：新增 `/forgot-password`、`/reset-password`、`/verify-email` 公开路由与 `/settings` 受保护路由；`/login` 增加「忘记密码」入口
- [ ] 8.10 修改 `frontend/src/composables/useAuth.ts`：登录成功后调用一次 `fetchMe` 刷新 `email_verified_at`；提供供提示条刷新用户状态的方法
- [ ] 8.11 修改 `RegisterView.vue` 成功提示，说明已发送验证邮件并引导查收；不缓存任何 token
- [ ] 8.12 补前端单测：`code` 到文案的映射、`/reset-password` 缺 token 不发请求、表单校验阻止提交、`invalid_credentials` 不清理 token、重置成功后清理 token

## 9. 测试与验证

- [ ] 9.1 跑后端全量测试，确认新增用例与 `add-auth-sessions` 既有用例均通过
- [ ] 9.2 数据库断言：任取一条已签发令牌，确认 `auth_tokens` 中只有 64 位十六进制哈希、无明文字段，且 `users` 两列存在
- [ ] 9.3 日志断言：构造发信失败、令牌校验失败与改密异常，确认日志与响应不含密码、明文令牌、`token_hash`、`Authorization` 头与完整链接
- [ ] 9.4 手工验证（开发环境，`EMAIL_BACKEND=console`）：注册 → 控制台取验证链接 → `/verify-email` 完成验证 → `/me` 的 `email_verified_at` 非空
- [ ] 9.5 手工验证修改密码：登录 → `/settings` 修改密码 → 用旧 token 调用任一受保护接口得到 `401 token_revoked` → 新密码登录成功
- [ ] 9.6 手工验证找回密码：退出登录 → `/forgot-password` 提交已验证邮箱 → 控制台取重置链接 → 重置成功 → 旧密码登录失败、新密码登录成功、旧 token 返回 `401 token_revoked`
- [ ] 9.7 手工验证防枚举：分别提交已注册已验证、已注册未验证、未注册三种邮箱，确认状态码与响应体完全一致，且只有第一种收到邮件
- [ ] 9.8 手工验证令牌单次使用与过期：重复打开同一重置链接得到 `invalid_token`；把 `expires_at` 改为过去时间后得到 `token_expired`
- [ ] 9.9 手工验证前端守卫：未登录访问 `/settings` 被重定向 `/login`；未验证用户登录后看到提示条，验证后提示消失
- [ ] 9.10 手工验证回滚路径：移除新增路由与 `iat` 校验后，既有登录与 `/api/runs` 可用，`auth_tokens` 与 `users` 新列不影响旧代码
- [ ] 9.11 运行 `openspec validate account-recovery --strict` 并通过
