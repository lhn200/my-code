## Why

`add-auth-sessions` 明确把邮箱验证、找回密码与修改密码列为 Non-Goals，交付的账号体系只有「注册 — 登录 — 登出」。这留下三个无法用产品手段弥补的缺口：

- 用户忘记密码即永久失去简历原文、岗位分析与优化历史，只能人工改库；
- 注册邮箱从未被证明可达，账号与「可找回的身份」之间没有绑定，后续任何以邮件为渠道的安全动作都不可信；
- 密码疑似泄露时用户没有自助轮换手段，也无法让泄露前签发的 token 停止生效。

`add-auth-sessions` 已经落地 `users` 表、argon2 密码哈希、含 `iat` 的 JWT 与唯一的鉴权入口 `get_current_user`；`add-frontend-shell` 已经提供 Vue 3 + Vite 骨架、路由与集中 HTTP 封装。这两处契约正好是本 change 所需的全部地基：JWT 已有 `iat`，可以在不改 token 结构的前提下做定向失效；`users` 可以幂等加列；邮件发送只需要一层抽象，不需要消息队列或新服务。此时补齐账号恢复能力的成本最低，再晚就要在有真实用户数据的前提下做表迁移与人工救火。

## What Changes

- 新增修改密码：`POST /api/auth/password/change` 要求登录，校验当前密码与新密码策略（长度 8–128、不得与旧密码相同）。当前密码错误返回统一 `400 invalid_credentials`；策略不满足返回 `422 weak_password`。成功后写入 `users.password_changed_at`，使该用户此前签发的 JWT 立即失效。
- JWT 定向失效：`get_current_user` 在既有解析流程后增加 `iat` 与 `password_changed_at` 比较，`iat` 早于改密时间即返回 `401 token_revoked`。这是「改密后旧 token 失效」的定向机制，**不是**通用吊销：登出、按设备下线、封禁账号、批量踢线都不在本 change 范围内，通用强制吊销留给后续 `add-token-revocation`。
- 新增邮箱验证：注册成功后自动签发一次性验证令牌并发信（开发环境 `console` 后端输出链接）；`users.email_verified_at` 记录验证时间；令牌单次使用、默认 TTL 24 小时、数据库只存哈希；支持重发并受每用户每小时限额约束。未验证用户仍可登录，但前端展示未验证提示；找回密码只对已验证邮箱生效。
- 新增找回密码：`POST /api/auth/password/forgot` 对任意邮箱统一返回 `202` 与相同响应体（防枚举），仅当邮箱已注册且已验证时才真正发信；`POST /api/auth/password/reset` 使用令牌 + 新密码重置，令牌单次使用、默认 TTL 30 分钟、只存哈希；重置成功后同样更新 `password_changed_at`，使旧 JWT 失效。
- 新增邮件发送抽象：`EmailSender` 接口 + `console`（开发）与 `smtp`（生产）两种实现，通过 `EMAIL_BACKEND` 与 `SMTP_*` 配置选择；生产环境禁止 `console` 后端，且禁止把令牌或含令牌链接写入日志。
- 新增数据表 `auth_tokens`（`id`、`user_id`、`kind`、`token_hash`、`expires_at`、`used_at`、`created_at`），`users` 增加 `email_verified_at` 与 `password_changed_at`；建立索引；迁移方式与 `add-auth-sessions` 一致（幂等 DDL + `PRAGMA user_version`）。
- 新增接口：`POST /api/auth/password/change`、`POST /api/auth/password/forgot`、`POST /api/auth/password/reset`、`POST /api/auth/email/verify-request`、`POST /api/auth/email/verify`；统一业务错误码 `invalid_credentials`、`weak_password`、`invalid_token`、`token_expired`、`email_not_verified`、`token_revoked`、`rate_limited`。
- `GET /api/auth/me` 追加 `email_verified_at` 字段（`null` 表示未验证），既有字段与注册、登录响应不变。
- 前端（依赖 `add-frontend-shell` 与 `add-auth-sessions`）：新增 `/forgot-password`、`/reset-password`、`/verify-email` 公开页面，以及在账号设置中新增修改密码表单；统一表单校验、提交态与错误提示；不引入 Pinia 或其他新状态库。
- 安全与测试：令牌只存哈希、单次使用、过期清理、接口限流、统一响应防枚举；测试覆盖正常、过期、复用、跨用户令牌、旧 JWT 失效、未验证邮箱被拒绝找回密码。
- 不做：通用 token 吊销 / 登出所有设备（`add-token-revocation`）、OAuth 与第三方登录、修改邮箱、MFA / TOTP、邮件模板系统与发送队列、短信或推送渠道、refresh token、防枚举以外的账号锁定策略、多 worker 共享限流。

## Capabilities

### New Capabilities
<!-- 本 change 不新增 capability：修改密码、邮箱验证、找回密码、一次性令牌与邮件发送抽象都属于既有 user-authentication 的增量能力。 -->

### Modified Capabilities
- `user-authentication`: 在 `add-auth-sessions` 已定义的注册、登录、登出、`GET /api/auth/me`、`get_current_user` 与前端登录注册基础上追加账号恢复能力。既有注册与登录契约不变；`/api/auth/me` 只追加 `email_verified_at`；`get_current_user` 增加 `iat` 与 `password_changed_at` 的定向失效校验。增量需求全部写在 `specs/user-authentication/spec.md`，不复制既有需求。

## Architecture Impact

依赖顺序是硬约束：`add-career-assistant-core` → `add-auth-sessions`（`users`、JWT、`get_current_user`、既有 SQLite 连接与迁移骨架）→ `add-frontend-shell`（Vue 骨架、路由、HTTP 封装、`useAuth` 与 401 处理）→ 本 change。本 change 不修改 LangGraph 图、`runs` / checkpoint 语义与部署拓扑。

- 分层与所有权：`/api/auth/*` 路由只做入参校验、状态码与用户可见文案；一次性令牌的签发、校验、消费、替换与清理全部收敛在新的令牌服务（`backend/app/auth/tokens.py`），路由不得自行生成或比较 token；`EmailSender` 只被服务层调用，路由不感知 `smtplib`。
- 令牌生命周期：`auth_tokens` 只存 `sha256(token)`，明文仅在签发瞬间存在于内存与邮件正文中。同一用户同一 `kind` 只保留一个可用令牌，重发即替换旧令牌，避免并行链接长期有效。
- 与既有鉴权的关系：JWT 结构不新增字段，只在 `get_current_user` 增加一次 `users` 已查询结果上的时间比较；因此该机制是定向的、无额外存储，也不会误伤其他用户或未改密用户。
- 邮件副作用与事务边界：先提交令牌记录再发送邮件；发送失败回滚不了「已提交的令牌」，因此不回滚业务，只记录脱敏日志并允许用户重发。注册流程不因发信失败而失败。
- 防枚举：`/password/forgot` 在「邮箱不存在」「存在但未验证」「存在且已验证」三条分支上返回完全相同的状态码与响应体，并执行等量的令牌生成/哈希工作；限流在查库前按来源 IP 生效，避免通过 429 差异推断账号存在。
- 存储与配置：复用 `CHECKPOINT_DB_PATH` 指向的同一 SQLite 文件与既有连接/事务封装，不新增数据库；新增配置全部走环境变量，无新增 Python 运行时依赖（`smtplib`、`hashlib`、`secrets` 均为标准库）。

## Impact

- 后端新增：`backend/app/auth/tokens.py`（一次性令牌签发/校验/消费/清理）、`backend/app/db/auth_tokens.py`（数据访问）、`backend/app/email/base.py`（`EmailSender` 接口）、`backend/app/email/console.py`、`backend/app/email/smtp.py`、`backend/app/email/factory.py`（按 `EMAIL_BACKEND` 构造发送器）。
- 后端修改：`backend/app/db/migrations.py`（`auth_tokens` 表、`users` 两列、索引、`PRAGMA user_version` 递增）、`backend/app/db/users.py`（读取/更新 `email_verified_at`、`password_changed_at`、密码哈希）、`backend/app/auth/password.py`（新密码策略校验）、`backend/app/auth/dependencies.py`（`iat` 定向失效）、`backend/app/auth/rate_limit.py`（复用固定窗口计数器，新增三个维度）、`backend/app/api/auth.py`（新增 5 个端点、注册触发验证邮件、`/me` 追加字段）、`backend/app/config.py`（新增配置与启动校验）、`backend/app/main.py`（启动时校验邮件后端与 TTL/限流配置并注册路由）。
- 前端新增（依赖 `add-frontend-shell` 与 `add-auth-sessions`）：`frontend/src/views/ForgotPasswordView.vue`、`ResetPasswordView.vue`、`VerifyEmailView.vue`、`SettingsView.vue`、`frontend/src/components/EmailVerificationBanner.vue`、`frontend/src/api/account.ts`。
- 前端修改：`frontend/src/router/`（三条公开路由 + 受保护的 `/settings`）、`frontend/src/api/client.ts`（`ApiError` 携带机器可读 `code`）、`frontend/src/api/types.ts`（`User.email_verified_at`）、`frontend/src/composables/useAuth.ts`（登录后刷新 `me`、提供验证状态）、`frontend/src/views/LoginView.vue`（忘记密码入口）、`frontend/src/views/RegisterView.vue`（注册成功提示查收验证邮件）、全局布局（挂载未验证提示条）。
- 配置新增：`APP_ENV`（`development` / `test` / `production`，默认 `development`）、`EMAIL_BACKEND`（`console` / `smtp`，默认 `console`）、`SMTP_HOST`、`SMTP_PORT`（默认 587）、`SMTP_USER`、`SMTP_PASSWORD`、`SMTP_FROM`、`FRONTEND_BASE_URL`（默认 `http://localhost:5173`，用于拼接验证/重置链接）、`EMAIL_VERIFY_TOKEN_TTL_HOURS`（默认 24）、`PASSWORD_RESET_TOKEN_TTL_MINUTES`（默认 30）、`EMAIL_VERIFY_RESEND_PER_HOUR`（默认 5）、`PASSWORD_FORGOT_PER_HOUR`（默认 5）、`TOKEN_RATE_LIMIT_PER_HOUR`（默认 30，作用于验证与重置端点）、`PASSWORD_CHANGE_PER_HOUR`（默认 10）。
- 依赖新增：无。邮件发送使用标准库 `smtplib` / `email.message`，令牌生成与哈希使用 `secrets` / `hashlib`；前端不新增运行时依赖。
- 测试：修改密码成功/当前密码错误/新密码不合规/未登录；改密前 JWT 失效、改密后新 JWT 可用、其他用户不受影响；验证邮件签发与发送、令牌单次使用/过期/伪造/跨用户、重发替换与限流；找回密码统一 202、未注册与未验证不发信、重置成功/过期/复用/弱密码/未验证邮箱拒绝；`auth_tokens` 无明文、日志无令牌；生产环境 `console` 后端启动失败。
- 迁移：首次启动幂等创建 `auth_tokens` 与索引，并为 `users` 加列，`PRAGMA user_version` 递增；存量用户 `email_verified_at` 与 `password_changed_at` 均为 `NULL`（未验证、从未改密，既有 JWT 继续有效）；回滚时移除新增路由与前端路由即可，表与列保留不影响旧代码。
