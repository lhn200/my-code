## ADDED Requirements

### Requirement: 修改密码

系统 SHALL 提供 `POST /api/auth/password/change`，要求通过既有 `get_current_user` 鉴权，接收 `current_password` 与 `new_password`。当前密码 MUST 使用 argon2 校验；不匹配时 MUST 返回统一的 `400 invalid_credentials`，且 MUST NOT 修改任何数据。新密码 MUST 为 8–128 个字符，且 MUST NOT 与当前密码相同，否则 MUST 返回 `422 weak_password`。修改成功 MUST 返回 `204`，MUST 更新 `users.password_hash` 与 `users.password_changed_at`。该端点 MUST 按 `user_id` 受 `PASSWORD_CHANGE_PER_HOUR`（默认 10）限流，超限返回 `429 rate_limited`。本需求不改变 `add-auth-sessions` 的登录接口契约。

#### Scenario: 成功修改密码

- **WHEN** 已登录用户提交正确的 `current_password` 与符合策略的 `new_password`
- **THEN** 系统 MUST 返回 `204`
- **AND** `users.password_hash` MUST 变为新密码的 argon2 哈希
- **AND** `users.password_changed_at` MUST 被更新为当前 UTC 时间
- **AND** 使用新密码 MUST 能通过既有 `POST /api/auth/login` 登录

#### Scenario: 当前密码错误

- **WHEN** 已登录用户提交错误的 `current_password`
- **THEN** 系统 MUST 返回 `400`
- **AND** 响应体的 `code` MUST 为 `invalid_credentials`
- **AND** `password_hash` 与 `password_changed_at` MUST NOT 发生变化
- **AND** 错误文案 MUST NOT 区分「密码错误」与任何账号存在性信息

#### Scenario: 新密码不满足策略

- **WHEN** 用户提交少于 8 个字符、超过 128 个字符或与当前密码相同的 `new_password`
- **THEN** 系统 MUST 返回 `422`
- **AND** 响应体的 `code` MUST 为 `weak_password`
- **AND** MUST NOT 修改 `password_hash` 或 `password_changed_at`

#### Scenario: 未登录调用修改密码

- **WHEN** 未携带合法 JWT 调用 `POST /api/auth/password/change`
- **THEN** 系统 MUST 返回 `401`
- **AND** MUST NOT 校验或修改任何密码

#### Scenario: 修改密码超过限流阈值

- **WHEN** 同一用户在一小时窗口内超过 `PASSWORD_CHANGE_PER_HOUR` 次调用修改密码接口
- **THEN** 系统 MUST 返回 `429`
- **AND** 响应体的 `code` MUST 为 `rate_limited`
- **AND** MUST NOT 校验当前密码或修改任何数据

#### Scenario: 修改密码同时清理重置令牌

- **WHEN** 用户成功修改密码且此前存在未使用的 `password_reset` 令牌
- **THEN** 系统 MUST 在同一事务内使该用户所有未使用的 `password_reset` 令牌失效
- **AND** 这些令牌此后再用于重置 MUST 返回 `400 invalid_token`

### Requirement: 修改密码后定向失效既有 JWT

系统 MUST 在 `get_current_user` 中比较 JWT 的 `iat` 与 `users.password_changed_at`。当 `password_changed_at` 非空且 `iat` 早于该时间时，系统 MUST 返回 `401 token_revoked` 且 MUST NOT 执行业务逻辑。该机制 MUST 仅作用于发生改密或重置密码的用户，MUST NOT 影响其他用户或未改密用户的既有 token。本机制 MUST NOT 被描述或实现为通用 token 吊销：登出、按设备下线、封禁账号与批量踢线均不在本需求范围内，由后续 `add-token-revocation` 负责。

#### Scenario: 改密前签发的 JWT 立即失效

- **WHEN** 用户 A 在改密前获得 token，随后完成 `POST /api/auth/password/change`
- **THEN** 用该 token 调用任一受保护接口 MUST 返回 `401`
- **AND** 响应体的 `code` MUST 为 `token_revoked`
- **AND** MUST NOT 执行该接口的业务逻辑或写入数据

#### Scenario: 改密后重新登录可用

- **WHEN** 用户 A 改密成功并通过 `POST /api/auth/login` 重新登录
- **THEN** 新签发的 JWT MUST 能正常访问受保护接口
- **AND** 新 token 的 `iat` MUST 不早于 `password_changed_at`

#### Scenario: 定向失效不波及其他用户

- **WHEN** 用户 A 修改密码，而用户 B 的 token 在 A 改密前签发
- **THEN** 用户 B 的 token MUST 继续有效
- **AND** 用户 A 改密 MUST NOT 修改用户 B 的 `password_changed_at`

#### Scenario: 从未改密的用户不受影响

- **WHEN** 用户的 `password_changed_at` 为 `NULL`
- **THEN** 该用户任意有效期内签发的 JWT MUST 继续通过鉴权
- **AND** 系统 MUST NOT 因该字段为空而拒绝请求

#### Scenario: 重置密码同样触发失效

- **WHEN** 用户通过 `POST /api/auth/password/reset` 重置密码成功
- **THEN** 用户在重置前签发的 JWT MUST 在后续请求中返回 `401 token_revoked`

### Requirement: 注册后签发邮箱验证令牌

系统 MUST 在 `add-auth-sessions` 的 `POST /api/auth/register` 成功创建用户后，签发一条 `kind = email_verify` 的一次性令牌并尝试发送验证邮件。令牌 MUST 默认 24 小时过期，并 MUST 可通过 `EMAIL_VERIFY_TOKEN_TTL_HOURS` 调整。验证链接 MUST 为 `${FRONTEND_BASE_URL}/verify-email?token=<明文令牌>`。签发或发送失败 MUST NOT 改变注册结果，注册仍 MUST 返回 `201`，且 MUST NOT 回滚用户记录。注册接口的既有请求字段与响应字段不变。

#### Scenario: 注册成功触发验证邮件

- **WHEN** 用户提交未注册的合法邮箱与合规密码并注册成功
- **THEN** 系统 MUST 创建用户并 MAY 在注册响应返回前完成令牌签发与发信尝试
- **AND** `auth_tokens` MUST 新增一条 `kind = email_verify`、`used_at` 为 `NULL` 的记录
- **AND** 该记录的 `expires_at` MUST 约为创建时间加 `EMAIL_VERIFY_TOKEN_TTL_HOURS` 小时
- **AND** 注册响应 MUST 仍为 `201` 且包含 `id` 与 `email`

#### Scenario: 发信失败不影响注册

- **WHEN** 注册过程中邮件后端抛错或 SMTP 超时
- **THEN** 注册 MUST 仍返回 `201` 并保留用户记录
- **AND** 系统 MUST 记录不含令牌与链接的错误日志
- **AND** 用户 MUST 能通过 `POST /api/auth/email/verify-request` 重新获取验证邮件

#### Scenario: 重复邮箱不发送验证邮件

- **WHEN** 用户使用已存在邮箱注册并收到 `409`
- **THEN** MUST NOT 签发新的 `email_verify` 令牌
- **AND** MUST NOT 发送验证邮件

### Requirement: 邮箱验证令牌的消费

系统 SHALL 提供 `POST /api/auth/email/verify`，接受 `{token}`，不要求登录。校验通过 MUST 将 `users.email_verified_at` 设为当前 UTC 时间，并将对应 `auth_tokens` 记录的 `used_at` 设为当前时间；接口 MUST 返回 `200`。令牌不存在或已被使用 MUST 返回 `400 invalid_token`；令牌已过期 MUST 返回 `400 token_expired`。同一令牌 MUST 只能成功使用一次。令牌 MUST 只作用于其记录中的 `user_id`，请求体 MUST NOT 接受邮箱或用户标识覆盖。

#### Scenario: 使用有效令牌验证邮箱

- **WHEN** 用户在有效期内提交未被使用过的验证令牌
- **THEN** 系统 MUST 返回 `200`
- **AND** 对应用户的 `email_verified_at` MUST 被设置为当前 UTC 时间
- **AND** 该 `auth_tokens` 记录的 `used_at` MUST 被设置
- **AND** `GET /api/auth/me` MUST 返回非空的 `email_verified_at`

#### Scenario: 重复使用同一令牌

- **WHEN** 用户再次提交已经成功使用过的验证令牌
- **THEN** 系统 MUST 返回 `400`
- **AND** 响应体的 `code` MUST 为 `invalid_token`
- **AND** `email_verified_at` MUST 保持原值

#### Scenario: 验证令牌过期

- **WHEN** 用户提交 `expires_at` 早于当前时间的验证令牌
- **THEN** 系统 MUST 返回 `400`
- **AND** 响应体的 `code` MUST 为 `token_expired`
- **AND** MUST NOT 修改 `email_verified_at`

#### Scenario: 伪造或不存在的令牌

- **WHEN** 用户提交随机字符串或已被替换的旧验证令牌
- **THEN** 系统 MUST 返回 `400`
- **AND** 响应体的 `code` MUST 为 `invalid_token`
- **AND** 响应 MUST NOT 透露该令牌是否曾存在

#### Scenario: 跨用户提交验证令牌

- **WHEN** 已登录用户 B 提交属于用户 A 的验证令牌
- **THEN** 系统 MUST 只更新用户 A 的 `email_verified_at`
- **AND** 用户 B 的 `email_verified_at` MUST 保持不变

#### Scenario: 已验证用户重复验证

- **WHEN** 提交有效令牌且对应用户的 `email_verified_at` 已非空
- **THEN** 系统 MUST 返回 `200`
- **AND** MUST 将本次令牌标记为已使用
- **AND** MUST NOT 修改既有的 `email_verified_at`

#### Scenario: 使用重置令牌验证邮箱

- **WHEN** 用户把 `kind = password_reset` 的令牌提交到 `POST /api/auth/email/verify`
- **THEN** 系统 MUST 返回 `400`
- **AND** 响应体的 `code` MUST 为 `invalid_token`
- **AND** MUST NOT 设置 `email_verified_at`

#### Scenario: 验证端点超过限流

- **WHEN** 同一来源 IP 在一小时窗口内超过 `TOKEN_RATE_LIMIT_PER_HOUR` 次调用验证接口
- **THEN** 系统 MUST 返回 `429`
- **AND** 响应体的 `code` MUST 为 `rate_limited`
- **AND** MUST NOT 消费令牌或修改 `email_verified_at`

### Requirement: 重发邮箱验证邮件与限流

系统 SHALL 提供 `POST /api/auth/email/verify-request`，要求登录。未验证用户请求重发时，系统 MUST 为该用户签发新的 `email_verify` 令牌，并在同一事务内删除该用户此前同 `kind` 且未使用的令牌，随后发送邮件并返回 `202`。已验证用户请求时 MUST 返回 `200` 且 `status` 为 `already_verified`，MUST NOT 发送邮件。每个用户每小时最多发起 `EMAIL_VERIFY_RESEND_PER_HOUR`（默认 5）次请求，超限 MUST 返回 `429 rate_limited` 且 MUST NOT 签发令牌或发送邮件。

#### Scenario: 未验证用户重发成功

- **WHEN** 未验证用户调用 `POST /api/auth/email/verify-request`
- **THEN** 系统 MUST 返回 `202`
- **AND** MUST 插入一条新的 `email_verify` 令牌
- **AND** 该用户此前未使用的 `email_verify` 令牌 MUST 失效
- **AND** 邮件 MUST 只包含本次新令牌对应的链接

#### Scenario: 已验证用户请求重发

- **WHEN** `email_verified_at` 非空的用户调用 `POST /api/auth/email/verify-request`
- **THEN** 系统 MUST 返回 `200` 且 `status` 为 `already_verified`
- **AND** MUST NOT 签发新令牌或发送邮件
- **AND** MUST NOT 清除既有的 `email_verified_at`

#### Scenario: 重发超过限流阈值

- **WHEN** 同一用户在一小时窗口内发起第 6 次重发请求
- **THEN** 系统 MUST 返回 `429`
- **AND** 响应体的 `code` MUST 为 `rate_limited`
- **AND** MUST NOT 签发令牌或发送邮件

#### Scenario: 未登录请求重发

- **WHEN** 未携带合法 JWT 调用 `POST /api/auth/email/verify-request`
- **THEN** 系统 MUST 返回 `401`
- **AND** MUST NOT 发送任何邮件

### Requirement: 找回密码请求与防枚举

系统 SHALL 提供 `POST /api/auth/password/forgot`，接受 `{email}`。无论邮箱是否存在、是否已验证，系统 MUST 返回相同的 `202` 状态码与完全相同的响应体。仅当邮箱已注册且 `email_verified_at` 非空时，系统 MUST 签发 `kind = password_reset` 的令牌并发送重置邮件；其他情况 MUST NOT 发送邮件。重置令牌 MUST 默认 30 分钟过期，并 MUST 可通过 `PASSWORD_RESET_TOKEN_TTL_MINUTES` 调整。请求 MUST 按来源 IP 受 `PASSWORD_FORGOT_PER_HOUR`（默认 5）限流，超限返回 `429 rate_limited`，且该响应 MUST NOT 随邮箱是否存在而变化。

#### Scenario: 已验证邮箱请求重置

- **WHEN** 用户提交一个已注册且 `email_verified_at` 非空的邮箱
- **THEN** 系统 MUST 返回 `202`
- **AND** MUST 签发一条 `kind = password_reset` 的令牌
- **AND** 邮件 MUST 包含 `${FRONTEND_BASE_URL}/reset-password?token=<明文令牌>`
- **AND** 该令牌的 `expires_at` MUST 约为创建时间加 `PASSWORD_RESET_TOKEN_TTL_MINUTES` 分钟

#### Scenario: 未注册邮箱请求重置

- **WHEN** 用户提交一个从未注册的邮箱
- **THEN** 系统 MUST 返回与已验证邮箱完全相同的 `202` 状态码与响应体
- **AND** MUST NOT 签发令牌或发送邮件
- **AND** 响应 MUST NOT 包含该邮箱不存在、未注册或类似的提示

#### Scenario: 未验证邮箱请求重置

- **WHEN** 用户提交一个已注册但 `email_verified_at` 为 `NULL` 的邮箱
- **THEN** 系统 MUST 返回与已验证邮箱完全相同的 `202` 状态码与响应体
- **AND** MUST NOT 签发 `password_reset` 令牌或发送重置邮件
- **AND** 响应 MUST NOT 暴露该邮箱未验证

#### Scenario: 重复请求替换旧令牌

- **WHEN** 同一已验证用户在短时间内多次请求重置
- **THEN** 每次成功签发的请求 MUST 使该用户此前未使用的 `password_reset` 令牌失效
- **AND** 邮件中最新链接 MUST 可用，旧链接 MUST 返回 `400 invalid_token`

#### Scenario: 找回密码请求超过限流

- **WHEN** 同一来源 IP 在一小时窗口内超过 `PASSWORD_FORGOT_PER_HOUR` 次请求
- **THEN** 系统 MUST 返回 `429`
- **AND** 响应体的 `code` MUST 为 `rate_limited`
- **AND** MUST NOT 签发令牌或发送邮件

#### Scenario: 邮箱大小写与空白归一化

- **WHEN** 用户提交带首尾空白或大小写不同的已注册邮箱
- **THEN** 系统 MUST 按与 `add-auth-sessions` 一致的 `strip().lower()` 归一化后查询
- **AND** 不同大小写形式 MUST 命中同一用户记录
- **AND** MUST NOT 因大小写差异而创建第二个账号或重复签发令牌

### Requirement: 使用令牌重置密码

系统 SHALL 提供 `POST /api/auth/password/reset`，接受 `{token, new_password}`，不要求登录，MUST NOT 接受 `email` 或 `user_id` 覆盖令牌所属用户。该端点 MUST 只接受 `kind = password_reset` 的令牌，提交 `email_verify` 令牌 MUST 返回 `400 invalid_token`。令牌不存在或已使用 MUST 返回 `400 invalid_token`，过期 MUST 返回 `400 token_expired`。新密码 MUST 满足 8–128 个字符且 MUST NOT 与重置前密码相同，否则 MUST 返回 `422 weak_password` 且 MUST NOT 消费令牌。对应用户 `email_verified_at` 为空时 MUST 返回 `403 email_not_verified` 且 MUST NOT 修改密码。成功时 MUST 更新 `password_hash` 与 `password_changed_at`、写入 `used_at`，并使该用户其他未使用的 `password_reset` 令牌失效，返回 `204`。该端点 MUST 按来源 IP 受 `TOKEN_RATE_LIMIT_PER_HOUR`（默认 30）限流，超限返回 `429 rate_limited` 且 MUST NOT 消费令牌。

#### Scenario: 重置密码成功

- **WHEN** 用户在有效期内提交未被使用的重置令牌与符合策略的新密码
- **THEN** 系统 MUST 返回 `204`
- **AND** 对应用户的 `password_hash` MUST 更新为新密码的 argon2 哈希
- **AND** `password_changed_at` MUST 被更新
- **AND** 该令牌的 `used_at` MUST 被设置
- **AND** 新密码 MUST 能通过既有 `POST /api/auth/login` 登录

#### Scenario: 重置令牌过期

- **WHEN** 用户提交 `expires_at` 早于当前时间的重置令牌
- **THEN** 系统 MUST 返回 `400`
- **AND** 响应体的 `code` MUST 为 `token_expired`
- **AND** MUST NOT 修改密码

#### Scenario: 使用验证令牌重置密码

- **WHEN** 用户把 `kind = email_verify` 的令牌提交到 `POST /api/auth/password/reset`
- **THEN** 系统 MUST 返回 `400`
- **AND** 响应体的 `code` MUST 为 `invalid_token`
- **AND** MUST NOT 修改密码或消费该验证令牌

#### Scenario: 重置端点超过限流

- **WHEN** 同一来源 IP 在一小时窗口内超过 `TOKEN_RATE_LIMIT_PER_HOUR` 次调用重置或验证端点
- **THEN** 系统 MUST 返回 `429`
- **AND** 响应体的 `code` MUST 为 `rate_limited`
- **AND** MUST NOT 消费任何令牌

#### Scenario: 重置令牌重复使用

- **WHEN** 用户使用已经成功重置过密码的令牌再次提交
- **THEN** 系统 MUST 返回 `400`
- **AND** 响应体的 `code` MUST 为 `invalid_token`
- **AND** MUST NOT 修改密码

#### Scenario: 新密码不合规不消费令牌

- **WHEN** 用户提交有效令牌但新密码少于 8 个字符、超过 128 个字符或与旧密码相同
- **THEN** 系统 MUST 返回 `422`
- **AND** 响应体的 `code` MUST 为 `weak_password`
- **AND** 该令牌的 `used_at` MUST 保持 `NULL`，允许用户修正后重试

#### Scenario: 未验证邮箱的重置令牌被拒绝

- **WHEN** 令牌对应记录的用户的 `email_verified_at` 为 `NULL`
- **THEN** 系统 MUST 返回 `403`
- **AND** 响应体的 `code` MUST 为 `email_not_verified`
- **AND** `password_hash` 与 `password_changed_at` MUST NOT 发生变化

#### Scenario: 令牌只作用于所属用户

- **WHEN** 用户 B 提交属于用户 A 的重置令牌
- **THEN** 系统 MUST 只尝试重置用户 A 的密码
- **AND** 请求体 MUST NOT 能通过 `email` 或 `user_id` 指定其他用户
- **AND** 用户 B 的密码 MUST 保持不变

#### Scenario: 重置成功后其他重置链接失效

- **WHEN** 用户通过一个重置令牌成功修改密码，且此前存在其他未使用的 `password_reset` 令牌
- **THEN** 这些其他令牌 MUST 失效
- **AND** 其后再使用 MUST 返回 `400 invalid_token`

### Requirement: 一次性令牌的存储与生命周期

系统 MUST 将邮箱验证与密码重置令牌存放在 `auth_tokens` 表，表 MUST 包含 `id`、`user_id`、`kind`、`token_hash`、`expires_at`、`used_at`、`created_at`。数据库 MUST NOT 存储明文令牌，MUST 只存储 `sha256(明文令牌)` 的十六进制字符串。`kind` MUST 限于 `email_verify` 与 `password_reset`。`token_hash` MUST 唯一，系统 MUST 建立 `(user_id, kind, created_at DESC)` 与 `expires_at` 索引。令牌 MUST 单次使用；过期令牌 MUST 在读取时被拒绝，并 MUST 被定期清理。明文令牌、`token_hash` 与含令牌的链接 MUST NOT 出现在日志、错误响应或异常堆栈中。

#### Scenario: 数据库只存令牌哈希

- **WHEN** 任意验证或重置令牌被签发
- **THEN** `auth_tokens.token_hash` MUST 为 64 位十六进制 SHA-256 摘要
- **AND** 该值 MUST NOT 等于邮件中出现的明文令牌
- **AND** 数据库中 MUST NOT 存在任何明文令牌列

#### Scenario: 令牌类型受约束

- **WHEN** 写入 `auth_tokens.kind`
- **THEN** 取值 MUST 限于 `email_verify` 或 `password_reset`
- **AND** 其他取值 MUST 被拒绝

#### Scenario: 过期令牌被清理

- **WHEN** 系统签发或校验令牌，或调用令牌清理函数
- **THEN** `expires_at` 早于当前时间超过 7 天的记录 MAY 被删除
- **AND** 清理 MUST NOT 影响未过期令牌或已使用记录的正确判定

#### Scenario: 令牌不进入日志

- **WHEN** 发送验证或重置邮件、校验令牌或处理相关异常
- **THEN** 日志 MUST NOT 包含明文令牌、`token_hash` 或完整邮件链接
- **AND** 邮件日志 MAY 包含掩码后的收件邮箱与 `kind`

### Requirement: 用户表扩展与幂等迁移

系统 MUST 在既有 `users` 表上增加 `email_verified_at` 与 `password_changed_at` 两列，类型为可空的 UTC ISO-8601 文本。迁移 MUST 使用与 `add-auth-sessions` 一致的幂等 DDL（`CREATE TABLE IF NOT EXISTS`、`CREATE INDEX IF NOT EXISTS`，并通过 `PRAGMA table_info(users)` 判断后再 `ALTER TABLE`），且 MUST 递增 `PRAGMA user_version`。重复启动 MUST NOT 重复加列或报错。存量用户的 `email_verified_at` 与 `password_changed_at` MUST 为 `NULL`，分别表示「未验证」与「从未改密」；迁移 MUST NOT 自动把存量用户标记为已验证。

#### Scenario: 首次迁移完成建表与加列

- **WHEN** 服务在尚未应用本 change 的数据库上启动
- **THEN** 系统 MUST 创建 `auth_tokens` 表与三个索引
- **AND** `users` MUST 新增 `email_verified_at`、`password_changed_at` 两列
- **AND** `PRAGMA user_version` MUST 递增一个版本

#### Scenario: 重复启动保持幂等

- **WHEN** 已完成迁移的服务再次启动
- **THEN** 迁移 MUST NOT 重复加列、重复建表或抛出错误
- **AND** 既有用户数据与令牌数据 MUST 保持不变

#### Scenario: 存量用户默认状态

- **WHEN** 迁移前已存在的用户记录在迁移后读取
- **THEN** `email_verified_at` MUST 为 `NULL`
- **AND** `password_changed_at` MUST 为 `NULL`
- **AND** 其此前签发的 JWT MUST 继续有效

### Requirement: 邮件发送抽象与配置

系统 MUST 定义 `EmailSender` 接口并提供 `console` 与 `smtp` 两种实现，由 `EMAIL_BACKEND` 选择。`console` 实现 MUST 仅在非生产环境可用，并将邮件内容（含链接）输出到标准输出；`smtp` 实现 MUST 使用 `SMTP_HOST`、`SMTP_PORT`、`SMTP_USER`、`SMTP_PASSWORD`、`SMTP_FROM` 发送邮件。系统 MUST 在启动阶段校验配置：`EMAIL_BACKEND` 不属于 `console` / `smtp`、TTL 或限流阈值不是正整数、`smtp` 缺少 `SMTP_HOST` 或 `SMTP_FROM`、`SMTP_USER` 与 `SMTP_PASSWORD` 只提供其一、或 `APP_ENV=production` 且 `EMAIL_BACKEND=console` 时，MUST 启动失败并以非零状态码退出。SMTP 发送 MUST 设置超时，且 MUST NOT 阻塞事件循环。

#### Scenario: 开发环境使用 console 后端

- **WHEN** `APP_ENV=development` 且 `EMAIL_BACKEND=console`
- **THEN** 系统 MUST 正常启动
- **AND** 验证与重置邮件 MUST 输出到标准输出，包含可点击链接
- **AND** 该输出 MUST NOT 被当作 `ERROR` 级错误日志

#### Scenario: 生产环境使用 smtp 后端

- **WHEN** `APP_ENV=production` 且 `EMAIL_BACKEND=smtp`，`SMTP_HOST` 与 `SMTP_FROM` 均非空
- **THEN** 系统 MUST 正常启动并通过 SMTP 发送邮件
- **AND** 单次发送 MUST 在配置的超时时间内结束或失败
- **AND** 发送失败 MUST 只记录掩码邮箱、`kind` 与异常类型

#### Scenario: 生产环境误配 console 后端

- **WHEN** `APP_ENV=production` 且 `EMAIL_BACKEND=console`
- **THEN** 启动 MUST 失败并以非零状态码退出
- **AND** 错误信息 MUST 明确指出生产环境不允许 `console` 邮件后端

#### Scenario: SMTP 配置不完整

- **WHEN** `EMAIL_BACKEND=smtp` 且 `SMTP_HOST` 或 `SMTP_FROM` 为空
- **THEN** 启动 MUST 失败并以非零状态码退出
- **AND** MUST NOT 以任何降级后端对外提供服务

#### Scenario: TTL 或限流配置非法

- **WHEN** `EMAIL_VERIFY_TOKEN_TTL_HOURS`、`PASSWORD_RESET_TOKEN_TTL_MINUTES`、`EMAIL_VERIFY_RESEND_PER_HOUR`、`PASSWORD_FORGOT_PER_HOUR`、`TOKEN_RATE_LIMIT_PER_HOUR` 或 `PASSWORD_CHANGE_PER_HOUR` 不是正整数
- **THEN** 启动 MUST 失败并以非零状态码退出

### Requirement: 未验证用户的登录与前端提示

未验证邮箱的用户 MUST 仍能通过 `add-auth-sessions` 的 `POST /api/auth/login` 登录，本 change MUST NOT 为其增加登录拦截。`GET /api/auth/me` MUST 追加 `email_verified_at` 字段（UTC ISO-8601 或 `null`），既有字段 MUST 保持不变。前端 MUST 在用户 `email_verified_at` 为 `null` 时展示未验证提示，并提供重发验证邮件的入口。

#### Scenario: 未验证用户登录成功

- **WHEN** 用户邮箱未验证但密码正确
- **THEN** 系统 MUST 返回 `200` 与可用 JWT
- **AND** MUST NOT 以邮箱未验证为由拒绝登录
- **AND** `GET /api/auth/me` MUST 返回 `email_verified_at: null`

#### Scenario: 前端展示未验证提示

- **WHEN** 已登录用户的 `email_verified_at` 为 `null`
- **THEN** 前端 MUST 在全局布局展示未验证提示
- **AND** 提示 MUST 提供触发 `POST /api/auth/email/verify-request` 的入口
- **AND** 提示 MUST NOT 阻塞用户使用分析与会话功能

#### Scenario: 验证后提示消失

- **WHEN** 用户完成邮箱验证并刷新 `GET /api/auth/me`
- **THEN** `email_verified_at` MUST 非空
- **AND** 前端 MUST 隐藏未验证提示与重发入口

### Requirement: 统一业务错误码

本 change 新增的五个端点 MUST 在失败时返回稳定、机器可读的 `code`，并 MUST 使用 `{"detail": {"code": "...", "message": "..."}}` 的统一错误信封。`code` 取值 MUST 限于本 change 定义的集合：`invalid_credentials`、`weak_password`、`invalid_token`、`token_expired`、`email_not_verified`、`token_revoked`、`rate_limited`，以及既有鉴权的 `not_authenticated`、`token_invalid`、`token_expired`。其中 `token_invalid` 专指 JWT，`invalid_token` 专指邮件验证与密码重置令牌，`token_expired` 在两类令牌上语义相同。前端 MUST 按 `code` 分支处理，MUST NOT 依赖 `message` 文案。

#### Scenario: 当前密码错误返回统一错误码

- **WHEN** 修改密码时当前密码错误
- **THEN** 状态码 MUST 为 `400` 且 `code` MUST 为 `invalid_credentials`
- **AND** 响应 MUST NOT 区分「密码错误」与「账号异常」

#### Scenario: 令牌错误码区分失效原因

- **WHEN** 提交不存在或已使用的令牌
- **THEN** `code` MUST 为 `invalid_token`
- **AND** 当提交过期令牌时 `code` MUST 为 `token_expired`
- **AND** 两者 MUST 使用 `400` 状态码

#### Scenario: 未验证邮箱的错误码

- **WHEN** 重置密码时对应用户邮箱未验证
- **THEN** 状态码 MUST 为 `403` 且 `code` MUST 为 `email_not_verified`

#### Scenario: 旧 JWT 的错误码

- **WHEN** 携带 `iat` 早于 `password_changed_at` 的 JWT 访问受保护接口
- **THEN** 状态码 MUST 为 `401` 且 `code` MUST 为 `token_revoked`
- **AND** 前端 MUST 按 401 流程清理 token 并跳转 `/login`

### Requirement: 前端忘记密码与重置密码页面

前端 SHALL 在 `add-frontend-shell` 的路由与 `add-auth-sessions` 的 `useAuth`、HTTP 封装基础上新增 `/forgot-password` 与 `/reset-password` 两个公开路由。`/forgot-password` 提交邮箱后 MUST 展示与邮箱存在性无关的统一成功文案；`/reset-password` MUST 从 query 读取 `token`，缺失时展示错误与重新申请入口。重置成功后前端 MUST 清理本地 token 与用户状态、跳转 `/login` 并提示使用新密码登录。两个页面 MUST 复用既有 `ApiError` 与错误映射，MUST NOT 引入新状态库。

#### Scenario: 提交忘记密码

- **WHEN** 用户在 `/forgot-password` 提交任意合法格式邮箱
- **THEN** 前端 MUST 调用 `POST /api/auth/password/forgot`
- **AND** 无论后端命中与否 MUST 展示同一句「如果该邮箱已注册并完成验证，我们已发送重置链接」
- **AND** 提交期间 MUST 禁用重复提交

#### Scenario: 缺少重置令牌

- **WHEN** 用户访问 `/reset-password` 且 query 中没有 `token`
- **THEN** 前端 MUST NOT 调用重置接口
- **AND** MUST 展示「链接无效」并提供返回 `/forgot-password` 的入口

#### Scenario: 重置密码成功

- **WHEN** 用户在 `/reset-password` 提交合规新密码且后端返回 `204`
- **THEN** 前端 MUST 清除 `localStorage` 中的 token 与 `useAuth` 的用户状态
- **AND** MUST 跳转 `/login` 并提示「密码已更新，请使用新密码登录」
- **AND** MUST NOT 自动用旧凭据重新登录

#### Scenario: 前端表单校验

- **WHEN** 用户输入少于 8 个字符或两次输入不一致的新密码即提交
- **THEN** 前端 MUST 阻止请求并展示字段级错误
- **AND** MUST NOT 向 `/api/auth/password/reset` 发送请求体

#### Scenario: 重置链接过期或已使用

- **WHEN** 后端返回 `400 token_expired` 或 `400 invalid_token`
- **THEN** 前端 MUST 展示对应提示
- **AND** MUST 提供返回 `/forgot-password` 重新申请的入口

### Requirement: 前端邮箱验证页面

前端 SHALL 新增公开路由 `/verify-email`，从 query 读取 `token`。页面 MUST 在用户确认后调用 `POST /api/auth/email/verify`，且 MUST NOT 仅凭打开链接消费令牌。验证成功 MUST 展示成功状态；若用户已登录，MUST 刷新 `GET /api/auth/me` 以更新 `email_verified_at` 并隐藏未验证提示。令牌过期、已使用或缺失时 MUST 展示可区分原因并提供重新发送入口。

#### Scenario: 打开验证链接

- **WHEN** 用户访问 `/verify-email?token=<有效令牌>`
- **THEN** 页面 MUST 展示令牌已就绪并提供「完成验证」动作
- **AND** MUST NOT 在未发生用户动作前调用验证接口

#### Scenario: 完成邮箱验证

- **WHEN** 用户点击「完成验证」且后端返回 `200`
- **THEN** 前端 MUST 展示验证成功
- **AND** 若用户已登录 MUST 刷新 `me` 并隐藏未验证提示

#### Scenario: 验证令牌过期

- **WHEN** 后端返回 `400 token_expired`
- **THEN** 前端 MUST 展示「链接已过期」
- **AND** MUST 提供重新发送验证邮件的入口
- **AND** 重新发送 MUST 通过 `POST /api/auth/email/verify-request` 完成

#### Scenario: 验证令牌已使用

- **WHEN** 后端返回 `400 invalid_token`
- **THEN** 前端 MUST 展示「链接无效或已使用」
- **AND** MUST NOT 反复自动重试

### Requirement: 前端账号设置中的修改密码表单

前端 SHALL 新增受保护的 `/settings` 页面，其中 MUST 提供修改密码表单，包含当前密码、新密码与确认新密码三个字段。表单 MUST 在提交前校验新密码长度 8–128、确认密码一致且新密码与当前密码不同；失败时 MUST 展示字段级错误且不发送请求。提交成功后 MUST 清理本地 token 与用户状态并跳转 `/login`，因为既有 JWT 已失效。页面 MUST 复用既有表单样式与错误映射，MUST NOT 引入 Pinia 或其他状态库。

#### Scenario: 设置页修改密码成功

- **WHEN** 已登录用户在 `/settings` 提交正确当前密码与合规新密码
- **THEN** 前端 MUST 调用 `POST /api/auth/password/change` 并展示提交态
- **AND** 收到 `204` 后 MUST 清除本地 token 与用户状态
- **AND** MUST 跳转 `/login` 并提示使用新密码重新登录

#### Scenario: 当前密码错误提示

- **WHEN** 后端返回 `400 invalid_credentials`
- **THEN** 前端 MUST 在当前密码字段附近展示「当前密码不正确」
- **AND** MUST NOT 清理 token 或跳转登录页
- **AND** MUST 保留用户已填写的新密码字段（确认密码除外）

#### Scenario: 新密码不合规

- **WHEN** 后端返回 `422 weak_password` 或前端预校验失败
- **THEN** 前端 MUST 展示密码策略说明（8–128 位、不得与当前密码相同）
- **AND** MUST NOT 发送或重复发送请求

#### Scenario: 未登录访问设置页

- **WHEN** 无 token 用户访问 `/settings`
- **THEN** 既有路由守卫 MUST 重定向到 `/login`
- **AND** MUST 记录原目标路径以便登录后回跳
