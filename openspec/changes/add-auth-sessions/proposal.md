## Why

`add-career-assistant-core` 交付了 LangGraph 工作流与 `POST /api/runs` 系列接口，但接口完全无鉴权，任何人拿到 `thread_id` 就能读取他人的简历与岗位分析结果；`add-dark-mode` 也只能在无身份的前端骨架上运行。真实求职数据（简历原文、投递意向、匹配分数）属于高敏感信息，一旦有第二个用户，缺少账号体系就不是功能缺口而是数据泄露。

现在补这一层，是因为核心接口契约已经稳定：`runs` 路由与 checkpoint 语义不会再大改，可以在其上叠加"当前用户"维度而不需要重写图结构；同时前端骨架正在并行搭建，路由与请求封装尚未固化，此时定义登录页、路由守卫和 401 处理成本最低。再晚，前端会先按"无鉴权"写完所有调用点，返工面更大。

## What Changes

- 新增邮箱 + 密码的注册与登录：密码使用 argon2 哈希，登录签发 JWT access token（`Authorization: Bearer`），默认 TTL 2 小时且可配置。
- 新增登出与当前用户信息接口；新增 `get_current_user` 鉴权依赖，未登录或 token 无效统一返回 401。
- 新增 SQLite 业务表 `users` 与 `runs`（`thread_id` 为主键，含 `user_id`、`title`、`status`、时间戳）。
- **BREAKING**：`POST /api/runs`、`POST /api/runs/{thread_id}/resume`、`GET /api/runs/{thread_id}`、`GET /api/runs/{thread_id}/snapshots` 全部要求登录，并只允许访问属于当前用户的会话；跨用户访问返回 404。已有的匿名调用方式不再可用。
- 新增会话空间接口：按用户分页列出会话、按标题搜索、重命名、软删除到回收站、从回收站恢复、永久删除；永久删除时同步清理对应 LangGraph checkpoint。
- 历史遗留的无主 checkpoint 标记为 legacy，不出现在任何用户的空间中，也不可通过 API 恢复或删除；提供命令行运维工具做 dry-run 优先的批量清理。
- 前端（依赖 `add-frontend-shell`）：新增 `/login`、`/register` 页面，路由守卫、token 持久化到 `localStorage`、401 自动跳转登录页；会话列表支持分页、搜索与回收站视图；auth 状态用 composable 管理，不引入 Pinia。
- 登出语义仍是客户端丢弃 token；强制吊销（`token_version` / 黑名单）留给后续 `add-token-revocation` change，本 change 不实现。
- 安全基线：登录失败使用统一错误文案且不区分邮箱是否存在；密码与 token 不写日志；`JWT_SECRET` 缺失时服务启动失败；登录接口做进程内简单限流。
- 不做：修改密码、邮箱验证、找回密码（统一由 `account-recovery` change 交付）、OAuth / 第三方登录、RBAC 与管理员后台、多设备会话管理、refresh token。

## Capabilities

### New Capabilities
- `user-authentication`: 邮箱密码注册、登录签发 JWT、登出、当前用户查询、`get_current_user` 鉴权依赖、最小前端登录/注册页与路由守卫、token 持久化与 401 处理、安全与限流约束。
- `analysis-session-space`: `users` / `runs` 表结构，`/api/runs` 系列接口按用户隔离，会话分页 / 搜索 / 重命名 / 回收站软删除 / 恢复 / 永久删除，checkpoint 清理，legacy checkpoint 的不可见语义与运维清理工具。

### Modified Capabilities
<!-- openspec/specs/ 下尚无既有 capability；core 的 session-checkpoint 与 runs 接口隔离语义在本 change 中以新增 capability 形式补充，不回写 core 的 spec。 -->

## Architecture Impact

依赖顺序是硬约束：`add-career-assistant-core` 提供 `thread_id`、checkpoint 与 `runs` 路由契约 → 本 change 在其上增加用户维度与业务元数据表 → `add-frontend-shell` 提供 Vue 3 + Vite 骨架与请求封装 → 本 change 在骨架内挂载 `/login`、`/register`、路由守卫与 401 拦截。

架构层面：

- 鉴权放在 FastAPI 依赖层（`get_current_user`），路由函数只消费 `User` 对象，不在业务代码里解析 token；图与节点完全不感知用户，避免 LangGraph 状态与账号体系耦合。
- `runs` 表是"用户可见的会话目录"，SQLite checkpoint 仍是"运行状态真相来源"。两者通过 `thread_id` 一对一关联：`runs` 负责归属、标题、列表排序与软删除，checkpoint 负责恢复与快照。
- 用户隔离在查询层强制生效：所有会话读写先按 `thread_id + user_id` 定位，先判归属再判存在，从根上避免通过 403/404 差异探测他人会话。
- 不引入 Pinia、不引入服务端 session 存储、不新增 Redis：单机 SQLite + 无状态 JWT 与现有部署约束一致。
- 复用 core 的 SQLite 连接与 WAL 配置，在同一数据库文件或同目录下新增业务表，不新增第二套存储引擎。

## Impact

- 后端新增：`backend/app/auth/`（密码哈希、JWT 签发校验、`get_current_user`、登录限流）、`backend/app/db/`（连接、迁移、`users` / `runs` 数据访问）、`backend/app/api/auth.py`、`backend/app/api/sessions.py`、`backend/scripts/cleanup_legacy_checkpoints.py`（legacy 与过期回收站清理）。
- 后端修改：`backend/app/api/runs.py` 全部路由接入鉴权与用户隔离；`backend/app/checkpoint/sqlite.py` 增加按 `thread_id` 删除 checkpoint 的能力；`backend/app/main.py` 启动时校验 `JWT_SECRET` 并注册新路由。
- 前端新增（依赖 `add-frontend-shell`）：`frontend/src/views/LoginView.vue`、`RegisterView.vue`、`frontend/src/composables/useAuth.ts`、`frontend/src/api/auth.ts`、`frontend/src/api/sessions.ts`、路由 meta 与全局守卫、HTTP 拦截器中的 401 处理。
- 配置新增：`JWT_SECRET`（必填，缺失启动失败）、`JWT_EXPIRES_MINUTES`（默认 120）、`LOGIN_RATE_LIMIT_PER_MINUTE`（默认 10）、`TRASH_RETENTION_DAYS`（默认 30）；业务表复用 `CHECKPOINT_DB_PATH` 指向的同一 SQLite 文件，不新增数据库路径配置。
- 依赖新增：`argon2-cffi`、`pyjwt`；前端无新增运行时依赖。
- 测试：注册/登录/登出/过期 token/跨用户访问/会话分页/标题搜索/回收站过滤/软删除与恢复/永久删除/legacy checkpoint 不可见/运维清理 dry-run 与幂等/`JWT_SECRET` 缺失启动失败。
- 迁移：为 `runs` 增加 `deleted_at` 列（幂等 ALTER）；为既有 checkpoint 建立无主记录的 legacy 语义，不自动删除；回滚时移除鉴权依赖与新增路由即可，`runs` 表可保留。
