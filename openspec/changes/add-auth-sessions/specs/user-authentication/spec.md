## ADDED Requirements

### Requirement: 邮箱密码注册

系统 SHALL 提供 `POST /api/auth/register`，接收 `email` 与 `password` 创建账号。邮箱 MUST 全局唯一且做格式校验，密码 MUST 至少 8 个字符。注册成功 MUST 返回 `201` 与用户标识（`id`、`email`），且响应中 MUST NOT 包含密码或密码哈希。

#### Scenario: 注册成功

- **WHEN** 用户提交未注册的合法邮箱与长度不少于 8 位的密码
- **THEN** 系统 MUST 创建用户记录并返回 `201`
- **AND** 响应体 MUST 包含 `id` 与 `email`
- **AND** 响应体 MUST NOT 包含 `password` 或 `password_hash` 字段

#### Scenario: 重复邮箱注册

- **WHEN** 用户提交一个已存在（忽略大小写差异）的邮箱
- **THEN** 系统 MUST 返回 `409`
- **AND** 响应 MUST NOT 回显该邮箱是否已绑定其他账号的额外细节

#### Scenario: 弱密码注册

- **WHEN** 用户提交少于 8 个字符的密码
- **THEN** 系统 MUST 返回 `422`
- **AND** MUST NOT 创建用户记录

#### Scenario: 邮箱格式非法

- **WHEN** 用户提交不符合邮箱格式的字符串
- **THEN** 系统 MUST 返回 `422`
- **AND** MUST NOT 创建用户记录

### Requirement: 密码以 argon2 哈希存储

系统 MUST 使用 argon2 对密码做哈希，数据库中 MUST NOT 出现明文密码或可逆加密后的密码。密码原文与哈希 MUST NOT 写入任何日志、错误响应或异常堆栈。

#### Scenario: 密码哈希落库

- **WHEN** 注册或修改密码成功
- **THEN** `users.password_hash` MUST 为 argon2 算法生成的哈希串
- **AND** 该值 MUST NOT 等于用户提交的原文

#### Scenario: 密码不进入日志

- **WHEN** 注册、登录或鉴权过程中发生异常并被记录
- **THEN** 日志内容 MUST NOT 包含密码原文
- **AND** 请求体中的 `password` 字段 MUST 在日志输出前被脱敏

### Requirement: 登录签发 JWT access token

系统 SHALL 提供 `POST /api/auth/login`，校验邮箱与密码后签发 JWT access token。token MUST 通过 `Authorization: Bearer <token>` 使用，默认有效期为 120 分钟，并 MUST 可通过环境变量 `JWT_EXPIRES_MINUTES` 调整。

#### Scenario: 登录成功

- **WHEN** 用户提交已注册邮箱与正确密码
- **THEN** 系统 MUST 返回 `200`
- **AND** 响应体 MUST 包含 `access_token`、`token_type`（值为 `bearer`）与 `expires_in`（秒）
- **AND** token MUST 包含用户标识与过期时间声明

#### Scenario: 登录失败统一文案

- **WHEN** 用户提交不存在的邮箱，或邮箱存在但密码错误
- **THEN** 系统 MUST 返回相同的 `401` 状态码与完全相同的错误文案
- **AND** 响应 MUST NOT 透露该邮箱是否已注册

#### Scenario: token 有效期可配置

- **WHEN** 环境变量 `JWT_EXPIRES_MINUTES` 设置为一个正整数
- **THEN** 新签发 token 的 `exp` MUST 与配置的分钟数一致
- **AND** `expires_in` MUST 等于配置分钟数乘以 60

### Requirement: 登出

系统 SHALL 提供 `POST /api/auth/logout`。登出 MUST 要求合法 token，并 MUST 使调用方丢弃本地 token；服务端 MUST 不依赖内存态会话表判断有效性。

#### Scenario: 已登录用户登出

- **WHEN** 携带合法 token 调用登出接口
- **THEN** 系统 MUST 返回 `200` 或 `204`
- **AND** 前端 MUST 清除本地存储的 token

#### Scenario: 未登录调用登出

- **WHEN** 未携带 token 或 token 无效时调用登出接口
- **THEN** 系统 MUST 返回 `401`

### Requirement: 当前用户信息

系统 SHALL 提供 `GET /api/auth/me`，返回当前 token 对应的用户信息（至少 `id`、`email`、`created_at`），且 MUST NOT 返回密码哈希。

#### Scenario: 查询当前用户

- **WHEN** 携带合法 token 调用 `GET /api/auth/me`
- **THEN** 系统 MUST 返回 `200` 与当前用户信息
- **AND** 返回内容 MUST NOT 包含 `password_hash`

#### Scenario: 未携带 token 访问

- **WHEN** 未携带 `Authorization` 头访问 `GET /api/auth/me`
- **THEN** 系统 MUST 返回 `401`
- **AND** 响应 MUST 包含可用于触发前端跳转登录的机器可读错误标识（如 `code`）

#### Scenario: token 已过期

- **WHEN** 携带的 token 的 `exp` 早于当前时间
- **THEN** 系统 MUST 返回 `401`
- **AND** MUST NOT 按匿名用户继续处理请求

#### Scenario: token 签名非法

- **WHEN** 携带的 token 被篡改或使用非当前密钥签名
- **THEN** 系统 MUST 返回 `401`
- **AND** 响应 MUST NOT 包含密钥、签名校验细节或堆栈

### Requirement: 鉴权依赖 get_current_user

系统 MUST 提供统一的 FastAPI 依赖 `get_current_user`，从 `Authorization: Bearer` 解析并校验 token，返回 `User` 对象。所有需要登录的接口 MUST 通过该依赖获取用户，MUST NOT 在业务代码中重复解析 token。

#### Scenario: 受保护接口未登录

- **WHEN** 未登录用户调用任一受保护接口（包括 `/api/runs` 系列与 `/api/sessions` 系列）
- **THEN** 系统 MUST 返回 `401`
- **AND** MUST NOT 执行业务逻辑或写入任何数据

#### Scenario: 鉴权通过后传递用户

- **WHEN** token 合法且对应用户存在
- **THEN** 依赖 MUST 返回包含 `id` 的 `User` 对象
- **AND** 路由函数 MUST 仅通过该对象获取用户身份

#### Scenario: token 对应用户已被删除

- **WHEN** token 合法但其 `sub` 指向的用户在数据库中不存在
- **THEN** 系统 MUST 返回 `401`

### Requirement: 认证配置与启动校验

系统 MUST 从环境变量读取 `JWT_SECRET` 与 `JWT_EXPIRES_MINUTES`。`JWT_SECRET` 缺失或为空时，服务 MUST 在启动阶段直接失败退出，MUST NOT 使用硬编码默认密钥启动。

#### Scenario: JWT_SECRET 缺失

- **WHEN** 进程启动时环境变量 `JWT_SECRET` 未设置或为空字符串
- **THEN** 启动 MUST 失败并以非零状态码退出
- **AND** 错误信息 MUST 明确指出缺少 `JWT_SECRET`
- **AND** MUST NOT 以任何默认密钥对外提供服务

#### Scenario: JWT_EXPIRES_MINUTES 非法

- **WHEN** `JWT_EXPIRES_MINUTES` 不是正整数
- **THEN** 启动 MUST 失败并退出

### Requirement: 登录接口限流

系统 MUST 对 `POST /api/auth/login` 实施进程内限流，默认每个来源每分钟最多 10 次尝试，阈值可通过 `LOGIN_RATE_LIMIT_PER_MINUTE` 配置。

#### Scenario: 超过限流阈值

- **WHEN** 同一来源在一分钟窗口内超过配置的登录尝试次数
- **THEN** 系统 MUST 返回 `429`
- **AND** MUST NOT 继续校验密码
- **AND** 限流响应 MUST NOT 暴露账号是否存在

#### Scenario: 窗口过后恢复

- **WHEN** 超过限流窗口后再次发起登录
- **THEN** 系统 MUST 恢复正常校验流程

### Requirement: 前端登录与注册页面

前端 SHALL 提供 `/login` 与 `/register` 两个页面，且 MUST 依赖 `add-frontend-shell` 提供的 Vue 3 + Vite 骨架、路由与 HTTP 封装。表单提交 MUST 调用对应后端接口，失败时 MUST 展示后端返回的统一错误文案。

#### Scenario: 登录成功进入应用

- **WHEN** 用户在 `/login` 提交正确邮箱与密码
- **THEN** 前端 MUST 将 `access_token` 持久化到 `localStorage`
- **AND** MUST 跳转到登录前希望访问的页面或首页
- **AND** 导航区域 MUST 展示当前用户邮箱

#### Scenario: 注册成功后登录

- **WHEN** 用户在 `/register` 提交合法邮箱与不少于 8 位的密码并注册成功
- **THEN** 前端 MUST 提示注册成功并跳转到 `/login`
- **AND** MUST NOT 在注册响应中缓存任何 token

#### Scenario: 表单校验失败

- **WHEN** 用户输入非法邮箱或少于 8 位的密码即提交
- **THEN** 前端 MUST 在提交前阻止请求并展示字段级错误
- **AND** MUST NOT 向后端发送格式非法的请求体

### Requirement: 前端路由守卫与 401 处理

前端 MUST 通过路由 `meta` 标记受保护页面，并用全局导航守卫拦截未登录访问。auth 状态 MUST 由 composable（如 `useAuth`）统一管理，MUST NOT 引入 Pinia。

#### Scenario: 未登录访问受保护页面

- **WHEN** 本地无 token 的用户直接访问受保护路由
- **THEN** 前端 MUST 重定向到 `/login`
- **AND** MUST 记录原目标路径以便登录后回跳

#### Scenario: 刷新后保持登录

- **WHEN** 已登录用户刷新页面
- **THEN** 前端 MUST 从 `localStorage` 恢复 token 并继续渲染受保护页面
- **AND** MUST 调用 `GET /api/auth/me` 校验 token 是否仍有效

#### Scenario: 任意请求返回 401

- **WHEN** 任一 API 请求返回 `401`
- **THEN** 前端 MUST 清除本地 token 与用户状态
- **AND** MUST 跳转到 `/login`
- **AND** MUST NOT 进入无限重定向循环

#### Scenario: 已登录访问登录页

- **WHEN** 已持有有效 token 的用户访问 `/login` 或 `/register`
- **THEN** 前端 MUST 重定向到首页
