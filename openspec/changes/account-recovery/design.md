## Context

`add-auth-sessions` 已交付邮箱 + 密码注册、登录、登出、`GET /api/auth/me`、统一鉴权依赖 `get_current_user`，并用 `users` 表存 argon2 密码哈希、签发含 `sub` / `iat` / `exp` 的 HS256 JWT，同时把邮箱验证、修改密码与找回密码显式列为 Non-Goals。`add-frontend-shell` 提供了 Vue 3 + Vite 骨架、路由、集中 HTTP 封装与 `useAuth`，`add-auth-sessions` 在其上补了 `/login`、`/register` 与 401 处理。

因此本 change 面对的是一个「有身份、无恢复」的账号系统：能登录，但忘记密码无法自助恢复，邮箱真实性未被证明，密码泄露后旧 token 仍可用满剩余 TTL。约束与既有 change 一致：Python 3.13 + FastAPI、单机 SQLite（WAL）、无 Redis / 无消息队列、前端纯 SPA、不引入 Pinia。本 change 只补账号恢复闭环，不改变登录与注册的核心契约，也不引入通用 token 吊销体系。

## Goals / Non-Goals

**Goals:**

- 让已登录用户能自助修改密码，并让改密前签发的 JWT 立即失效，且不影响其他用户。
- 建立「注册邮箱可达」的事实：一次性验证令牌 + `email_verified_at` + 可重发的验证邮件。
- 让忘记密码的用户能通过邮箱重置密码，同时不泄露邮箱是否注册。
- 提供可替换的邮件发送抽象，开发环境零依赖可跑通全流程，生产环境走 SMTP 且日志不含令牌。
- 新增一次性令牌表与两列用户字段，用与 `add-auth-sessions` 一致的幂等 DDL + `PRAGMA user_version` 迁移。
- 前端补齐 `/forgot-password`、`/reset-password`、`/verify-email` 与账号设置中的修改密码表单，复用现有路由、HTTP 封装与 `useAuth`。

**Non-Goals:**

- 通用强制吊销：不实现登出即吊销、按设备下线、封禁账号、JWT 黑名单或 `token_version`。这些留给后续 `add-token-revocation`；本 change 的失效机制只覆盖「改密/重置密码」这一事件。
- OAuth / 第三方登录、修改邮箱、MFA / TOTP、账号锁定与风控、密码强度字典校验。
- 邮件模板系统、发送队列 / 重试任务、送达回执、短信或推送渠道。
- refresh token 与多设备会话管理。
- 多 worker 共享限流状态；沿用 `add-auth-sessions` 的单进程固定窗口假设。
- 存量用户的批量邮箱验证回溯或强制下线。

## Architecture Assessment

### Existing Design Reuse

- 复用 `add-auth-sessions` 的 `users` 表、邮箱归一化规则（`strip().lower()`）与 argon2 哈希/校验函数；本 change 不新建第二套身份表或第二套密码算法。
- 复用 `get_current_user` 作为唯一身份入口：修改密码与重发验证邮件都通过它取 `User`，路由不解析 JWT。
- 复用既有的 SQLite 连接、事务上下文、WAL 与 busy timeout，以及 `db/migrations.py` 的 `PRAGMA user_version` 迁移模式。
- 复用 `auth/rate_limit.py` 的进程内固定窗口计数器，只增加新的 key 维度与阈值配置。
- 复用 `add-frontend-shell` 的 `api/client.ts`、`ApiError`、路由守卫与 `useAuth`；新增页面走同一请求封装与错误归一化，不新建请求层或状态库。
- 复用 `add-auth-sessions` 的 JWT 声明：本 change 不新增 `jti`、不改变 `sub` / `iat` / `exp` 语义，只在鉴权时多读一次 `users.password_changed_at`。
- 复用既有统一错误文案与「不区分账号是否存在」的响应原则；新增端点沿用同一错误信封。

### Boundaries and Ownership

```
浏览器
  ├─ /login /register            既有
  ├─ /forgot-password            提交邮箱 → 统一成功文案
  ├─ /reset-password?token=      令牌 + 新密码 → 204 → 清理本地 token → /login
  ├─ /verify-email?token=        页面加载后 POST 验证（GET 链接本身不消费令牌）
  ├─ /settings                   修改密码表单（meta.requiresAuth）
  └─ EmailVerificationBanner     未验证时展示，触发重发
        ↓ api/account.ts → api/client.ts（统一 ApiError{status, code, message}）
FastAPI
  ├─ /api/auth/password/change   ← get_current_user
  ├─ /api/auth/password/forgot   ← 匿名，恒 202
  ├─ /api/auth/password/reset    ← 匿名，令牌即凭证
  ├─ /api/auth/email/verify-request ← get_current_user
  ├─ /api/auth/email/verify      ← 匿名，令牌即凭证
  └─ /api/auth/me                追加 email_verified_at
        ↓
服务层
  ├─ auth/tokens.py   签发 / 校验 / 消费 / 替换 / 清理（唯一令牌语义所有者）
  ├─ auth/password.py 哈希校验 + 新密码策略
  └─ email/*.py       EmailSender 实现与工厂
        ↓
SQLite（与 add-auth-sessions 同一文件）
  ├─ users            新增 email_verified_at、password_changed_at
  └─ auth_tokens      一次性令牌哈希、kind、TTL、使用时间
```

- 令牌所有权：只有 `auth/tokens.py` 生成明文令牌、计算哈希、校验与标记使用；路由与前端永远不接触哈希格式。
- 失效判定所有权：只有 `get_current_user` 比较 `iat` 与 `password_changed_at`；业务路由不重复判断。
- 邮件所有权：只有邮件工厂按配置构造 `EmailSender`；业务代码只调用 `send(...)`，不感知 SMTP 细节。
- 事务边界：令牌「替换旧令牌 + 插入新令牌」在单个事务内完成；邮件发送在事务提交之后，发送失败不回滚令牌，也不影响注册/重置结果。
- 失败边界：所有令牌错误在进入密码写入前返回；弱密码不消费令牌；未验证邮箱在重置写入前返回 403。

### Options and Rationale

| 决策点 | 选择 | 替代方案 | 理由 |
| --- | --- | --- | --- |
| 改密后旧 JWT 失效 | `users.password_changed_at` 与 JWT `iat` 比较 | JWT 黑名单 / `token_version` 自增 / 服务端会话表 | 无新增存储与额外查询，只复用 `get_current_user` 已有的用户行；`password_changed_at` 天然只表达「改密」语义，不会被误当作通用吊销。代价是秒级精度与无法按设备失效 |
| 一次性令牌存放 | 只存 `sha256(token)`，唯一索引 | 明文入库 / 可逆加密 / HMAC | 数据库或备份泄露时哈希无法直接使用；令牌本身为 256 bit 随机值，SHA-256 不需要加盐；比 HMAC 少一个密钥管理面 |
| 令牌生成 | `secrets.token_urlsafe(32)` | `uuid4` / 自增 id + 签名 | 256 bit 熵可抵抗猜测；URL 安全，可直接放入邮件链接 |
| 令牌种类 | 单表 `auth_tokens` + `kind` 枚举 | 两张表（`email_verification_tokens` / `password_reset_tokens`） | 两种令牌结构、生命周期与操作完全一致，单表 + `kind` 减少重复 DDL 与重复查询代码 |
| 重发语义 | 同用户同 `kind` 只保留一个可用令牌，签发新令牌时删除旧的未使用记录 | 允许多条并行 / 用 `revoked_at` 标记 | 单活跃令牌让「重发后旧链接失效」可预测，且无需新增字段；多链接并行只会扩大泄漏面 |
| 令牌过期清理 | 签发与校验时顺带删除过期超过 7 天的记录，并提供 `cleanup_expired_tokens()` | 后台定时任务 / 每次全表清理 | 单机无调度器；过期判定在读取时完成，删除只为控制表大小，顺带清理即可 |
| 忘记密码响应 | 任何邮箱恒 `202` + 相同响应体 | 未注册返回 404 / 未验证返回 403 | 任何差异都可被用来枚举账号；未验证的拒绝必须在其他环节表达（重置端点与前端提示） |
| 未验证邮箱与找回密码 | 不为未验证邮箱签发重置令牌；重置端点仍校验 `email_verified_at`，不满足返回 `403 email_not_verified` | 允许重置后再要求验证 | 「找回密码前必须已验证邮箱」是明确策略；两层校验覆盖历史数据与状态被篡改的情况 |
| 改密时当前密码错误的状态码 | `400 invalid_credentials` | `401` | 前端全局 401 会清理 token 并跳登录页；这里用户已登录且会话仍有效，用 400 避免误登出 |
| 密码策略 | 长度 8–128，且新密码不得与旧密码相同（argon2 校验） | 只校验长度 / 引入 zxcvbn | 与既有注册的「至少 8 位」一致，额外阻止「改回原密码」；引入强度库属于新依赖与新体验，超出范围 |
| 邮件发送实现 | `EmailSender` 接口 + `console` / `smtp` 两种实现，工厂按 `EMAIL_BACKEND` 选择 | 直接调用 `smtplib` / 引入第三方邮件 SDK | 开发与测试零依赖；生产用标准库即可；接口隔离使测试可注入假发送器 |
| SMTP 调用方式 | `smtplib` 在 `asyncio.to_thread` 中执行，超时 10 秒 | 在事件循环内同步发送 | 同步 SMTP 会阻塞整个事件循环；放到线程池并设超时，避免一个慢邮件服务器拖垮所有请求 |
| 邮件链接消费时机 | 链接打开 `GET` 只渲染页面，由页面显式 `POST` 提交令牌 | 邮件链接直接 `GET /api/auth/email/verify?token=` | 邮件安全扫描器常预取链接，GET 直接消费会把令牌提前用掉；POST 由用户动作触发 |
| 生产环境保护 | `APP_ENV=production` 且 `EMAIL_BACKEND=console` 时启动失败 | 仅文档提醒 | 配置错误是最常见的令牌泄漏路径，启动期失败比运行期日志泄漏可控 |
| 前端状态 | 页面局部 `ref` + 既有 `useAuth` | Pinia / 新 composable 全局单例 | 四个页面状态互不共享，只有 `user` 需要跨页；引入 store 属于额外依赖与样板 |

### Quality Attributes

- 安全：令牌 256 bit 随机、只存哈希、单次使用、TTL 明确；`console` 后端仅在非生产启用；日志对 `password`、`token`、`Authorization` 与邮件链接脱敏；`forgot` 全分支等量工作降低时序差异；重置令牌只能作用于签发时绑定的用户，请求体不接受 `email` 覆盖。
- 可靠性：令牌替换与插入同事务；邮件失败不影响注册与重置结果，用户可重发；SMTP 有超时且不阻塞事件循环；过期令牌在读取时即刻拒绝，清理失败不影响正确性。
- 性能：每个恢复动作只增加一次带索引的 `auth_tokens` 查询与一次 `users` 主键更新；argon2 仍是唯一重计算路径；`auth_tokens` 按 `token_hash` 唯一索引命中，按 `(user_id, kind, created_at)` 支撑重发替换。
- 可观测性：记录 `request_id`、`user_id`、端点、状态码与错误码；邮件日志只记录 `kind`、掩码后的收件人与异常类型；不记录令牌、哈希、邮件正文与完整链接。
- 可测试性：令牌服务可注入时钟与随机源，直接构造过期/未过期/已使用记录；`EmailSender` 可替换为内存实现断言发送内容；`get_current_user` 的 `iat` 比较可用固定时间单测。
- 可维护性：TTL、限流阈值、链接基地址全部配置化；令牌语义只在 `auth/tokens.py` 实现一次；前端错误码映射集中在一处。

### Complexity and Exceptions

新增一张表、两列与若干索引，属于同一 SQLite 文件内的增量 DDL，不引入新存储服务或后台进程。新增的运行时能力全部依赖 Python 标准库，无新依赖；唯一新增的外部依赖是生产环境的 SMTP 服务器，属于部署配置而非代码依赖。复杂度集中在令牌状态机（未使用 / 已使用 / 已过期 / 被替换），因此实现时把所有状态迁移收敛在一个服务模块，并用测试锁定「弱密码不消费令牌」「重发使旧令牌失效」两条易错语义。

例外与刻意限制：`password_changed_at` 为秒级精度，同一秒内改密前签发的 token 存在理论上的存活窗口，接受该风险并以「改密后前端强制清理 token 并重新登录」补偿；生产环境不提供 `console` 后端的降级开关，宁可启动失败也不允许令牌进日志。

## Decisions

1. **令牌契约**：明文令牌为 `secrets.token_urlsafe(32)`，数据库仅存 `sha256(plain_token).hexdigest()`；查询按 `token_hash` 唯一索引命中。令牌不接受客户端自定义内容，也不携带用户信息，用户归属以数据库行的 `user_id` 为准。
2. **`auth_tokens` 结构**：`id INTEGER PRIMARY KEY AUTOINCREMENT`、`user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE`、`kind TEXT NOT NULL CHECK (kind IN ('email_verify','password_reset'))`、`token_hash TEXT NOT NULL UNIQUE`、`expires_at TEXT NOT NULL`、`used_at TEXT`、`created_at TEXT NOT NULL`。时间统一为 UTC ISO-8601 文本，与 `users.created_at` 一致。
3. **索引**：`token_hash` 唯一索引（内联 `UNIQUE`）、`(user_id, kind, created_at DESC)` 复合索引用于重发替换与历史排查、`expires_at` 索引用于过期清理。
4. **TTL 与时钟**：邮箱验证令牌默认 24 小时（`EMAIL_VERIFY_TOKEN_TTL_HOURS`），重置令牌默认 30 分钟（`PASSWORD_RESET_TOKEN_TTL_MINUTES`）。过期判定在服务层用 UTC 当前时间比较 `expires_at`；过期记录不自动置 `used_at`，但读取时一律拒绝并返回 `token_expired`。
5. **单次使用**：校验成功后在同一事务内写入 `used_at`；再次提交同一令牌返回 `400 invalid_token`。并发提交依靠「`UPDATE ... WHERE used_at IS NULL` 影响行数为 0 即视为已被使用」的条件更新保证只有一个请求成功。
6. **重发替换**：为某用户签发新令牌前，先删除该用户同 `kind` 且 `used_at IS NULL` 的记录，再插入新记录；两步同事务。用户拿到的最新邮件链接有效，旧链接立即失效。
7. **修改密码**：`POST /api/auth/password/change` 接收 `current_password`、`new_password`。先用 argon2 校验当前密码，失败返回 `400 invalid_credentials`；再校验新密码长度 8–128 且与当前密码不同，失败返回 `422 weak_password` 且不写库。成功后更新 `password_hash` 与 `password_changed_at`，并在同一事务内删除该用户所有未使用的 `password_reset` 令牌。接口返回 `204`，并按 `user_id` 受 `PASSWORD_CHANGE_PER_HOUR`（默认 10）限流，超限返回 `429 rate_limited` 且不校验密码。
8. **JWT 定向失效**：`get_current_user` 解析并校验 JWT 后，若 `users.password_changed_at` 非空且 `iat < password_changed_at`（按秒比较），返回 `401 token_revoked`，不执行业务。`password_changed_at` 为 `NULL` 表示从未改密，所有既有 token 继续有效。该比较只影响该用户，不写任何状态，也不作用于其他用户。
9. **邮箱验证签发**：注册成功后在响应返回前签发 `email_verify` 令牌并尝试发信；发信或签发失败只记录脱敏日志，不影响 `201`。验证链接为 `${FRONTEND_BASE_URL}/verify-email?token=<plain_token>`，其中 `FRONTEND_BASE_URL` 去掉尾部斜杠。
10. **邮箱验证消费**：`POST /api/auth/email/verify` 接受 `{token}`，无需登录（邮件可能在未登录设备打开）。该端点 MUST 只接受 `kind = email_verify` 的令牌，提交 `password_reset` 令牌按 `400 invalid_token` 处理。校验通过后写入 `users.email_verified_at`（若已存在则保持原值）与 `used_at`，返回 `200`；令牌不存在或已使用返回 `400 invalid_token`，过期返回 `400 token_expired`。持有他人令牌只会验证令牌所属用户，不影响当前登录用户。该端点与重置端点共享按来源 IP 的 `TOKEN_RATE_LIMIT_PER_HOUR`（默认 30）限流，超限返回 `429 rate_limited` 且不消费令牌。
11. **重发验证邮件**：`POST /api/auth/email/verify-request` 要求登录。已验证用户返回 `200 {"status": "already_verified"}` 且不发信；未验证用户按第 6 条替换令牌后发信，返回 `202 {"status": "sent"}`；超过 `EMAIL_VERIFY_RESEND_PER_HOUR`（默认 5，按 `user_id` 计）返回 `429 rate_limited` 且不发信。
12. **忘记密码**：`POST /api/auth/password/forgot` 接受 `{email}`，归一化后查询；无论邮箱是否存在、是否已验证，均返回 `202` 与相同响应体。仅当用户存在且 `email_verified_at` 非空时签发 `password_reset` 令牌并发信。未命中分支同样执行令牌生成与哈希的等价工作以降低时序差异；按来源 IP 的 `PASSWORD_FORGOT_PER_HOUR`（默认 5）在查库前生效，超限返回 `429 rate_limited` 且响应与账号存在性无关。
13. **重置密码**：`POST /api/auth/password/reset` 接受 `{token, new_password}`，不接受 `email`。该端点 MUST 只接受 `kind = password_reset` 的令牌，提交邮箱验证令牌按 `400 invalid_token` 处理。令牌不存在或已使用返回 `400 invalid_token`，过期返回 `400 token_expired`；新密码不合规返回 `422 weak_password` 且**不消费令牌**（用户可修正后重试）；用户 `email_verified_at` 为空返回 `403 email_not_verified` 且不写库。成功后更新 `password_hash` 与 `password_changed_at`、写入 `used_at`，并删除该用户其他未使用的 `password_reset` 令牌，返回 `204`。该端点按来源 IP 受 `TOKEN_RATE_LIMIT_PER_HOUR` 限流，超限返回 `429 rate_limited` 且不消费令牌。
14. **错误码命名空间**：JWT 相关错误沿用 `add-auth-sessions` 的 `not_authenticated` / `token_invalid` / `token_expired`，新增 `token_revoked`；一次性令牌相关错误使用 `invalid_token` / `token_expired`；业务策略错误使用 `invalid_credentials` / `weak_password` / `email_not_verified` / `rate_limited`。两套名称刻意区分：`token_invalid` 指 JWT，`invalid_token` 指邮件/重置令牌，前端按端点上下文处理。
15. **错误响应信封**：新增端点失败时返回 `{"detail": {"code": "<code>", "message": "<统一中文文案>"}}`；请求体字段缺失或类型错误仍由 FastAPI 默认 422 处理。前端按 `code` 分支，不解析 `message` 文案。
16. **`/api/auth/me` 扩展**：响应追加 `email_verified_at`（UTC ISO-8601 或 `null`），不修改既有字段；登录响应保持不变，前端登录成功后调用一次 `fetchMe` 刷新用户状态。
17. **邮件抽象**：`EmailSender` 暴露 `send(*, to: str, subject: str, text: str) -> None`。`console` 实现把完整邮件（含链接）打印到标准输出，仅在非生产可用；`smtp` 实现使用 `smtplib.SMTP`（端口 587 时 `starttls()`，465 时 `SMTP_SSL`），超时 10 秒，在 `asyncio.to_thread` 中执行。
18. **配置与启动校验**：读取并校验 `APP_ENV`、`EMAIL_BACKEND`、`SMTP_*`、`FRONTEND_BASE_URL`、两个 TTL 与四个限流阈值。`EMAIL_BACKEND` 非 `console` / `smtp`、TTL 或阈值非正整数、`EMAIL_BACKEND=smtp` 缺少 `SMTP_HOST` 或 `SMTP_FROM`、`SMTP_USER` 与 `SMTP_PASSWORD` 只提供其一、`APP_ENV=production` 且 `EMAIL_BACKEND=console`，均在启动阶段失败退出，不监听端口。
19. **日志脱敏**：任何日志与错误响应不得包含明文令牌、`token_hash`、密码、`Authorization` 头与完整邮件链接；邮件日志使用掩码邮箱（如 `a***@example.com`）与 `kind`。
20. **迁移**：`db/migrations.py` 在既有基线版本上递增 `PRAGMA user_version`；`CREATE TABLE IF NOT EXISTS auth_tokens`；通过 `PRAGMA table_info(users)` 判断后再 `ALTER TABLE users ADD COLUMN email_verified_at TEXT` 与 `ADD COLUMN password_changed_at TEXT`；索引用 `CREATE INDEX IF NOT EXISTS`。全过程幂等，重复启动不报错。
21. **前端路由与页面**：`/forgot-password`、`/reset-password`、`/verify-email` 为公开路由；`/settings` 受保护。`/reset-password` 与 `/verify-email` 从 query 读取 `token`，缺失时展示错误与「重新申请」入口。修改密码成功后清理本地 token 并跳 `/login`，因为当前 JWT 已因 `password_changed_at` 失效。

## Risks / Trade-offs

- [`password_changed_at` 秒级精度] → 同一秒内改密前签发的 token 可能仍通过比较；前端在改密成功后无条件清理本地 token 并重新登录，窗口仅存在于非正常客户端，接受。
- [定向失效容易被误解为通用吊销] → 在 proposal、design、spec 与 tasks 中显式声明边界；`add-token-revocation` 负责黑名单 / `token_version` / 按设备下线。当前不提供「登出所有设备」按钮。
- [SMTP 不可用导致验证与重置邮件发不出] → 注册与重置不受影响；重发有限流但可重试；日志记录异常类型便于告警。未验证用户暂时无法找回密码，需先成功收到验证邮件，这是策略的必然代价。
- [为防止枚举，未验证邮箱的找回请求也返回 202] → 用户在 UI 上得不到「未验证」提示；前端在登录后的提示条与设置页显式引导先完成验证，且重置端点会以 `403 email_not_verified` 兜底。
- [单活跃令牌使多设备重复申请时旧链接失效] → 属预期语义；提示文案说明「以最新邮件为准」；重发有每小时限额，避免被当作邮件轰炸工具。
- [邮件安全扫描器预取链接] → 验证链接只打开前端页面，令牌由页面显式 POST 提交，GET 不消费令牌；重置页面同理。
- [SMTP 同步调用阻塞事件循环] → 放入线程池并设 10 秒超时；失败转成可重试错误，不无限挂起。
- [`console` 后端把令牌写入日志] → 仅 `APP_ENV != production` 可用，生产环境启动即失败；测试断言生产配置不通过启动校验。
- [进程内限流在多 worker 下不共享] → 沿用 `add-auth-sessions` 的单进程假设；扩容时改网关或 Redis，接口契约不变。
- [存量用户全部未验证，上线后暂时无法自助重置] → 迁移不自动标记已验证（否则等于伪造事实）；存量用户可登录后点击重发完成验证；过渡策略列为 Open Question。
- [令牌表持续增长] → 签发与校验时清理过期超过 7 天的记录；`expires_at` 索引支撑清理；清理失败不影响正确性。

## Migration Plan

1. 前置：`add-auth-sessions` 与 `add-frontend-shell` 已 apply；后端 `users` 表与 `JWT_SECRET` 已就绪，前端骨架与 `useAuth` 已存在。
2. 配置：先补齐 `APP_ENV`、`EMAIL_BACKEND`、`SMTP_*`、`FRONTEND_BASE_URL` 与 TTL / 限流变量；生产环境必须使用 `smtp` 且 `SMTP_*` 完整，否则启动失败。
3. 数据库：启动时执行幂等迁移——创建 `auth_tokens` 与索引、为 `users` 添加 `email_verified_at` 与 `password_changed_at`、`PRAGMA user_version` 递增。以 `add-auth-sessions` 结束时写入的版本号为基线加一，不硬编码绝对版本。
4. 存量数据：既有用户两列均为 `NULL`，语义为「未验证、从未改密」；既有 JWT 因 `password_changed_at` 为 `NULL` 继续有效，不强制下线。系统不自动把存量用户标记为已验证，避免制造虚假的「可找回」承诺。
5. 发布顺序：后端迁移与接口先上线（新端点对旧前端无影响）→ 前端发布三个公开页、设置页与未验证提示条。`/api/auth/me` 只追加字段，旧前端忽略即可。
6. 回滚：移除 5 个新增路由与前端 3 条公开路由、`/settings` 与提示条；`get_current_user` 去掉 `iat` 比较；`auth_tokens` 表与 `users` 两列保留（旧代码不读取，不影响运行）。已发出的邮件链接在路由移除后自然失效；修改过密码的用户其旧 token 仍会因回滚后的鉴权逻辑而重新可用，回滚窗口内应同时接受该风险。

## Open Questions

- 存量未验证用户的过渡策略：是否需要一次性运维脚本按邮箱域或用户名单发送验证邮件，还是完全依赖用户登录后自助重发？
