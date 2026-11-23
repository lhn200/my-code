## Context

`add-career-assistant-core` 已定义 `thread_id` 语义、SQLite checkpoint 与 `/api/runs` 五个接口，但接口无鉴权，且 `proposal.md` 已明确把"注册登录与分析空间"留给后续 change。`add-frontend-shell` 正在并行搭建 Vue 3 + Vite 骨架，路由与 HTTP 封装尚未固化。本 change 同时落在两端：后端补账号与用户维度隔离，前端补登录/注册页与守卫。

约束：Python 3.13 + FastAPI、单机 SQLite（已启用 WAL）、无 Redis、无消息队列、前后端分离部署（Nginx 静态托管前端）。本 change 不引入 refresh token、不做多设备会话管理、不做 RBAC。

## Goals / Non-Goals

**Goals:**
- 建立邮箱 + 密码账号体系，密码用 argon2 哈希，登录签发有 TTL 的 JWT。
- 以 `get_current_user` 为唯一鉴权入口，把所有 `/api/runs` 访问收敛到"当前用户自己的会话"。
- 用 `runs` 表承载会话目录（归属、标题、状态、排序），checkpoint 继续承载运行状态。
- 提供会话分页、标题搜索、重命名、回收站软删除、从回收站恢复与永久删除；永久删除同时清理 checkpoint。
- 明确 legacy（无主）checkpoint 的不可见语义，避免上线后历史数据被任意用户读到；提供 dry-run 优先的命令行运维清理工具。
- 前端在 `add-frontend-shell` 骨架内提供 `/login`、`/register`、路由守卫、token 持久化与 401 自动跳转，auth 状态用 composable 管理。

**Non-Goals:**
- 修改密码、邮箱验证、找回密码：统一由 `account-recovery` change 交付，本 change 不实现。
- OAuth / 第三方登录、RBAC / 管理员后台、审计日志系统。
- 多设备会话管理、强制吊销、refresh token；强制吊销由后续 `add-token-revocation` change 交付。
- checkpoint 内容加密与简历字段脱敏（本 change 只做访问隔离）。
- 多进程/多实例共享限流状态。

## Architecture Assessment

### Existing Design Reuse

- 复用 core 的 `thread_id` 生成与复用规则、checkpoint 读写封装（`backend/app/checkpoint/sqlite.py`）与 `data/checkpoints.sqlite` 文件；不新建第二套存储引擎。
- 复用 core 的错误语义骨架：422 入参错误、404 资源不存在、500 内部错误；本 change 只新增 401 / 409 / 429。
- 复用 core 的 WAL 与 busy timeout 配置；业务表与 checkpoint 表同库，共享同一连接池参数。
- 复用 `add-frontend-shell` 的目录约定（`views/`、`components/`、`composables/`、`api/`）、路由实例与 HTTP 封装；不另建第二套请求层，不引入 Pinia。
- 复用 `add-dark-mode` 的 token 体系与既有表单控件样式，登录/注册页不引入新的配色方案。

### Boundaries and Ownership

```
浏览器
  └─ useAuth (composable，唯一 auth 状态源)
       ├─ token 持久化 localStorage
       ├─ 路由守卫 meta.requiresAuth
       └─ HTTP 封装：注入 Authorization，401 → 清理 + 跳 /login
            ↓
FastAPI
  ├─ /api/auth/*     注册、登录、登出、me（无需业务数据）
  ├─ get_current_user 依赖：解析 token → 查 users → 注入 User
  ├─ /api/runs/*     先按 thread_id + user_id 定位，再执行业务
  └─ /api/sessions/* 列表、重命名、删除（owner 校验同上）
            ↓
SQLite（单文件）
  ├─ users / runs     业务表：归属、标题、状态、排序
  └─ checkpoints...    LangGraph saver 表：运行状态真相
```

- 身份所有权：只有 `get_current_user` 解析 token；路由函数只接收 `User`，不接触 JWT 字节。
- 归属判定所有权：集中在一个查询辅助函数 `get_owned_run(thread_id, user_id)`，所有会话读写必须经过它，保证"先判归属、后判存在"。
- 图与状态所有权不变：LangGraph 节点与 `AgentState` 完全不感知用户，`user_id` 只存在于 HTTP 层与 `runs` 表，不进入图状态，避免 checkpoint 结构变更。
- 删除所有权：删除由会话接口编排，checkpoint 清理委托给 `checkpoint/sqlite.py` 暴露的 `delete_thread(thread_id)`，事务边界在 API 层。
- 失败边界：鉴权失败立即 401，不执行业务；owner 校验失败 404，不暴露差异；删除失败整体回滚并 500。

### Options and Rationale

| 决策点 | 选择 | 替代方案 | 理由 |
| --- | --- | --- | --- |
| 认证机制 | 无状态 JWT（HS256，`sub`=user id，`exp`） | 服务端 session + Cookie | 单机、无 Redis，服务端 session 需要额外会话表与清理任务；JWT 与现有"无内存态会话"的设计一致。代价是无法即时吊销，接受 2 小时窗口 |
| 密码哈希 | argon2id（`argon2-cffi`） | bcrypt；PBKDF2 | argon2id 是当前密码哈希推荐算法，抗 GPU 与侧信道更强；bcrypt 有 72 字节截断问题。参数按单次 ~100–200ms 调优 |
| 跨用户访问 | 404 | 403 | 403 明确告诉攻击者"该 thread_id 存在"，可被用于枚举；统一 404 让"无权访问"与"不存在"不可区分 |
| token 存放 | localStorage + Bearer 头 | httpOnly Cookie | httpOnly 能抗 XSS 读取，但需要 CSRF 防护（SameSite + token 或双提交）与跨域 Cookie 配置，且与"无 refresh token"叠加后体验差；localStorage 方案无 CSRF 面，但暴露于 XSS，靠 CSP、禁用 `v-html`、短 TTL、401 即清退来收敛 |
| 业务表位置 | 与 checkpoint 同一个 SQLite 文件 | 独立 `auth.sqlite`；外部数据库 | 删除会话需要同时删 `runs` 行与 checkpoint 行；同库同连接才能用一个事务保证"要么都删、要么都留"。独立库只能靠补偿逻辑 |
| 删除语义 | 软删除到回收站（`deleted_at`），支持恢复；永久删除时才物理清理 checkpoint | 立即物理删除；仅标记不可见 | 回收站是用户明确要求；软删除保住 checkpoint 可恢复，误删成本低。代价是磁盘占用与过期清理需求，用 `TRASH_RETENTION_DAYS` 与运维命令兜底 |
| 会话列表 | offset 分页 + 标题 LIKE 搜索 | 全量返回；游标分页 | 单用户会话量有限，offset 足够且实现简单；搜索在 SQLite 内完成，索引覆盖 `(user_id, deleted_at, updated_at DESC)` |
| legacy 清理 | 命令行工具，默认 dry-run，只删无 `runs` 记录的 thread | 在 API 暴露清理接口；自动删除 | 清理是运维动作，不应让普通用户触发；dry-run + 批次 + 审计日志把误删风险降到最低 |
| 前端状态 | `useAuth` 单例 composable（模块级 `ref`） | Pinia | 需求只有 user + token 两项，Pinia 引入额外依赖与样板；composable 已能满足守卫、组件共享与测试 |
| 限流实现 | 进程内固定窗口计数（IP 维度） | Redis 令牌桶；SlowAPI | 单进程部署，内存计数零依赖；多 worker 时各进程独立计数，作为"简单限流"可接受，已在 Non-Goals 声明 |
| 邮箱唯一性 | 写入前 `strip().lower()` 归一化 + 唯一索引 | 依赖 DB collation | 归一化后唯一索引行为可预期，避免 `Alice@x.com` 与 `alice@x.com` 双账号 |

### Quality Attributes

- 安全：JWT 校验固定 `algorithms=["HS256"]` 防算法混淆；密码验证对"用户不存在"也执行一次 dummy argon2 校验，使耗时接近，配合统一文案降低枚举；`Authorization` 头与 `password` 字段在日志中脱敏；`JWT_SECRET` 缺失即启动失败，杜绝默认密钥上线。
- 可靠性：删除走单事务；checkpoint 删除接口幂等（不存在也视为成功）；限流窗口用单调时钟。
- 性能：登录是唯一重计算路径（argon2），其余请求只做 HMAC 校验 + 一次 `users` 主键查询；`runs` 上建 `(user_id, deleted_at, updated_at DESC)` 索引支撑列表、回收站过滤与分页。
- 可观测性：日志记录 `request_id`、`user_id`、路由与状态码；不记录 email 明文以外的凭证类字段，不记录 token；清理命令单独写审计日志。
- 可测试性：`create_access_token` / `decode_token` / `hash_password` / `verify_password` 为纯函数，可用固定密钥与固定时间来测过期；`get_current_user` 可用 dependency override 注入假用户；前端 `useAuth` 可在无网络情况下测守卫分支。

### Complexity and Exceptions

新增依赖 `argon2-cffi` 与 `pyjwt` 均为认证刚需，无法用标准库等价替代（`hashlib.scrypt` 可行但生态与参数管理不如 argon2 成熟）。新增 `users` / `runs` 两张表属于同一 SQLite 文件内的增量 DDL，不引入新存储服务。前端不新增运行时依赖。回滚方式：移除鉴权依赖与新路由注册，业务表保留（不影响 core 运行），前端移除两条路由与守卫即可；已签发 token 在密钥移除后自然失效。

## Decisions

1. **JWT 契约**：`sub` 为用户 id（字符串），`iat`、`exp` 为 UTC 时间戳，签名算法 HS256；校验时固定算法并校验 `exp`。`expires_in` 以秒返回，默认 7200。
2. **密码哈希参数集中在 `auth/password.py`**，使用 `PasswordHasher` 默认参数并显式记录版本；校验失败只返回布尔值，不在异常中带哈希前缀。
3. **统一鉴权依赖 `get_current_user`** 返回 `User` 模型；`WWW-Authenticate: Bearer` 随 401 返回，错误体含稳定 `code`（如 `not_authenticated` / `token_expired` / `token_invalid`）供前端统一处理，但文案不区分账号是否存在。
4. **归属校验唯一入口**：`get_owned_run(thread_id, user_id)` 查询 `runs`，查不到即 404；所有 `/api/runs`、`/api/sessions` 操作先调用它，杜绝"先读 checkpoint 再判归属"的顺序错误。
5. **`runs` 与 checkpoint 的关系**：`runs` 是会话目录与所有权来源，checkpoint 是状态来源。`runs` 中无记录的 checkpoint 即 legacy，API 的列表、查询、恢复、删除均不可见；不自动归属，也不由 API 删除，只允许运维命令清理。
6. **删除采用回收站语义**：`DELETE /api/sessions/{thread_id}` 只设置 `deleted_at`，保留 `runs` 行与 checkpoint；默认列表与 `/api/runs` 访问均按 `deleted_at IS NULL` 过滤。恢复接口清空 `deleted_at`；永久删除接口只接受已软删除的会话，在同一事务内删除 checkpoint 三张表的数据与 `runs` 行，失败回滚。
7. **回收站保留期**：`TRASH_RETENTION_DAYS`（默认 30）只约束运维清理，不在请求路径自动删除；过期会话由清理命令按批次物理删除，避免用户请求触发长事务。
8. **启动校验与建表**：`main.py` 启动时先校验 `JWT_SECRET`、`JWT_EXPIRES_MINUTES`、`LOGIN_RATE_LIMIT_PER_MINUTE`、`TRASH_RETENTION_DAYS`，再执行幂等 DDL（`CREATE TABLE IF NOT EXISTS` + `PRAGMA user_version`）后注册路由；校验失败不监听端口。
9. **登录限流**：`(client_ip)` 维度固定窗口计数，窗口 60 秒，默认阈值 10；超限直接 429，不进入密码校验；计数结构加锁以适配 async 并发。
10. **前端 token 生命周期**：登录成功写 `localStorage` 的单一键；冷启动时 `useAuth` 读取 token 并调用一次 `/api/auth/me` 校验（同一 Promise 去重）；任意 401 触发清理并带 `redirect` 参数跳 `/login`，`redirect` 仅接受站内相对路径，防止开放重定向。
11. **前端页面归属**：`/login`、`/register` 为公开路由，`meta.requiresAuth` 标记其余业务路由；已登录访问公开页时重定向首页。
12. **分页与搜索参数**：`page` 默认 1、`page_size` 默认 20 且上限 100；`q` 去空白后按标题 LIKE 匹配，转义 `%`、`_`、`\`；`trashed` 默认 false，true 时只返回 `deleted_at IS NOT NULL` 并按 `deleted_at DESC` 排序；响应统一为 `{items,total,page,page_size}`。
13. **legacy 清理命令**：`python -m backend.scripts.cleanup_legacy_checkpoints`，默认 dry-run，`--yes` 才删除；`--older-than-days` 默认 30、`--batch-size` 默认 500；只选择 `thread_id NOT IN (SELECT thread_id FROM runs)`，含回收站会话在内的一律保护；每批提交并写 `data/audit/legacy_cleanup.log`；`--purge-expired-trash` 按 `TRASH_RETENTION_DAYS` 删除过期回收站会话。

## Risks / Trade-offs

- [无 refresh token，2 小时后需重新登录] → TTL 可配置；前端 401 统一引导登录并保留回跳路径，降低中断感。
- [localStorage 中 token 可被 XSS 读取] → 不引入 `v-html` 渲染不可信内容；部署层加 CSP；token TTL 较短；登出与 401 立即清除。残留风险接受，并在 design 与 code review 中显式记录。
- [登出后 token 仍在有效期内可用（无吊销）] → 明确语义为"客户端丢弃 token"；通用强制吊销由后续 `add-token-revocation` 引入 `token_version` 或黑名单表，密码变更的定向失效由 `account-recovery` 承担。
- [进程内限流在多 worker 下不共享] → 单进程部署假设；扩容时改为网关层或 Redis 限流，接口契约不变。
- [软删除导致 checkpoint 占用磁盘] → `TRASH_RETENTION_DAYS` 默认 30，提供 `--purge-expired-trash` 批量清理；回收站列表明确展示删除时间，用户可自行永久删除。
- [标题搜索随会话数增长变慢] → `(user_id, deleted_at, updated_at DESC)` 索引 + `page_size` 上限 100；后续如需全文检索再引入 FTS5。
- [legacy 清理误删在用会话] → 默认 dry-run、必须 `--yes`、SQL 只选无 `runs` 记录的 thread、分批提交 + 审计日志；含回收站会话也受保护。
- [强制吊销未实现] → 本 change 明确为"客户端丢弃 token"；密码修改等定向失效由 `account-recovery` 的 `password_changed_at` 承担，通用吊销留给 `add-token-revocation`。
- [argon2 在低配机器上拖慢登录] → 参数按单次 100–200ms 调优并写入配置注释；限流进一步限制暴力尝试成本。

## Migration Plan

1. 部署顺序：`add-career-assistant-core` 已存在 → 本 change 后端（建表 + 鉴权）→ `add-frontend-shell` 骨架 → 本 change 前端页面与守卫。前端必须先有骨架才能挂载页面，故前端部分在 tasks 中排在其后。
2. 首次启动自动创建 `users`、`runs` 与索引，幂等；`runs` 增加 `deleted_at` 列（`ALTER TABLE ... ADD COLUMN` 前先查 `PRAGMA table_info`），`PRAGMA user_version` 记录已应用版本。
3. 存量 checkpoint 不迁移、不归属：没有 `runs` 记录即视为 legacy，接口层不可见。上线后按需运行 `cleanup_legacy_checkpoints`，先 dry-run 确认数量，再 `--yes` 清理；不强制在发布流程中执行。
4. 回滚：下线新增路由与前端路由；移除 `get_current_user` 依赖后 `/api/runs` 回到无鉴权状态（仅限回滚窗口内网使用）；`users` / `runs` 表与 `deleted_at` 保留不删，checkpoint 未受影响。

## Open Questions

- 已决策：legacy checkpoint 提供命令行清理（默认 dry-run）；强制吊销由后续 `add-token-revocation` 交付；修改密码 / 邮箱验证 / 找回密码合并为 `account-recovery`；会话列表分页 + 搜索；删除采用回收站语义。
- 暂无其他未决问题。
