## 1. 依赖与配置

- [ ] 1.1 在 `backend/pyproject.toml` 增加 `argon2-cffi` 与 `pyjwt`，并确认与 `fastapi`、`langgraph` 现有版本无冲突
- [ ] 1.2 在配置入口新增 `JWT_SECRET`、`JWT_EXPIRES_MINUTES`（默认 120）、`LOGIN_RATE_LIMIT_PER_MINUTE`（默认 10）、`TRASH_RETENTION_DAYS`（默认 30），并在 `.env.example` 补充说明
- [ ] 1.3 在 `backend/app/main.py` 启动流程中加入配置校验：`JWT_SECRET` 缺失或为空、`JWT_EXPIRES_MINUTES` / `LOGIN_RATE_LIMIT_PER_MINUTE` / `TRASH_RETENTION_DAYS` 非正整数时直接抛错退出，不监听端口

## 2. 数据层

- [ ] 2.1 实现 `backend/app/db/connection.py`：复用 `CHECKPOINT_DB_PATH` 指向的同一 SQLite 文件，启用 WAL 与 busy timeout，提供事务上下文
- [ ] 2.2 实现 `backend/app/db/migrations.py`：基于 `PRAGMA user_version` 的幂等迁移，首次启动创建 `users`、`runs`（含 `deleted_at`）表与 `(user_id, deleted_at, updated_at DESC)` 索引；对既有库先查 `PRAGMA table_info` 再补 `deleted_at`
- [ ] 2.3 实现 `backend/app/db/users.py`：创建用户、按邮箱（归一化小写）查询、按 id 查询，捕获唯一约束冲突并转为业务错误
- [ ] 2.4 实现 `backend/app/db/runs.py`：创建会话、按 `thread_id + user_id` 查询（默认要求 `deleted_at IS NULL`）、分页列表（`page` / `page_size` / `q` / `trashed`）、统计总数、更新标题、更新状态与 `updated_at`、软删除、恢复、按 `thread_id + user_id` 物理删除、查询过期回收站

## 3. 密码与 JWT 基础

- [ ] 3.1 实现 `backend/app/auth/password.py`：argon2id 哈希与校验，预生成一个 dummy 哈希用于"用户不存在"路径的等时校验
- [ ] 3.2 实现 `backend/app/auth/jwt.py`：`create_access_token(user_id)` 写入 `sub` / `iat` / `exp`，`decode_token` 固定 `algorithms=["HS256"]` 并校验 `exp`
- [ ] 3.3 补单元测试：同一密码两次哈希不同但均可校验、错误密码校验失败、过期 token 被拒、篡改签名被拒、算法声明被替换为 `none` 时被拒

## 4. 鉴权依赖与认证接口

- [ ] 4.1 实现 `backend/app/auth/dependencies.py` 的 `get_current_user`：解析 `Authorization: Bearer`、校验 token、按 `sub` 查用户，返回 `User`；失败返回 `401` 与稳定错误码（`not_authenticated` / `token_expired` / `token_invalid`）
- [ ] 4.2 实现 `POST /api/auth/register`：入参校验（邮箱格式、密码长度 ≥ 8）、邮箱归一化、重复邮箱返回 409、响应不含密码字段
- [ ] 4.3 实现 `POST /api/auth/login`：统一失败文案、装载 dummy 哈希校验、成功返回 `access_token` / `token_type=bearer` / `expires_in`
- [ ] 4.4 实现 `POST /api/auth/logout` 与 `GET /api/auth/me`：前者要求合法 token，后者不返回 `password_hash`
- [ ] 4.5 实现 `backend/app/auth/rate_limit.py`：按来源 IP 的 60 秒固定窗口计数，超限返回 429 且不校验密码，阈值读配置
- [ ] 4.6 补接口测试：注册成功、重复邮箱 409、弱密码 422、非法邮箱 422、登录成功、登录失败文案一致、缺失 token 401、过期 token 401、登出 204/200、`/me` 返回当前用户、限流触发 429

## 5. 运行接口的用户隔离

- [ ] 5.1 实现 `backend/app/api/ownership.py` 的 `get_owned_run(thread_id, user_id)`：查不到即抛 404，作为所有会话读写的前置校验
- [ ] 5.2 改造 `POST /api/runs`：接入 `get_current_user`，生成或校验 `thread_id` 后写入 `runs`（`user_id`、默认 `title`、`status=running`），完成后更新状态与 `updated_at`
- [ ] 5.3 改造 `POST /api/runs/{thread_id}/resume`、`GET /api/runs/{thread_id}`、`GET /api/runs/{thread_id}/snapshots`：先经 `get_owned_run` 校验归属，再读写 checkpoint，并更新 `updated_at`
- [ ] 5.4 补测试：未登录 401；本人可访问；访问他人 `thread_id` 返回 404 且响应与不存在完全一致；查询不存在的 `thread_id` 返回 404 且不写入 `runs`

## 6. 会话空间接口

- [ ] 6.1 实现 `GET /api/sessions`：只返回当前用户记录；支持 `page`（默认 1）、`page_size`（默认 20，上限 100）、`q`（标题 LIKE，转义 `%`/`_`）、`trashed`（默认 false），返回 `{items,total,page,page_size}`，按 `updated_at` 倒序、回收站按 `deleted_at` 倒序
- [ ] 6.2 实现 `PATCH /api/sessions/{thread_id}`：经归属校验后更新标题，空白或超过 100 字符返回 422；回收站会话返回 404
- [ ] 6.3 在 `backend/app/checkpoint/sqlite.py` 增加 `delete_thread(thread_id)`：按当前 saver 版本删除该 thread 的 checkpoint 相关表数据，幂等
- [ ] 6.4 实现 `DELETE /api/sessions/{thread_id}`：软删除，只设置 `deleted_at`，保留 checkpoint；由 `get_owned_run` 保证归属，重复删除幂等
- [ ] 6.5 实现 `POST /api/sessions/{thread_id}/restore`：仅回收站会话可恢复，清空 `deleted_at` 并更新 `updated_at`；活跃会话返回 409 `not_trashed`
- [ ] 6.6 实现 `DELETE /api/sessions/{thread_id}/purge`：仅回收站会话可永久删除，同一事务内先删 checkpoint 再删 `runs` 行，失败回滚 500；活跃会话返回 409 `not_trashed`
- [ ] 6.7 补测试：分页边界与越界、`page_size` 超 100 返回 422、标题搜索大小写不敏感、`q=%` 按字面匹配、搜索不跨用户、默认列表不含回收站、`trashed=true` 只含回收站、软删除后 `GET`/resume 404、恢复后列表可见且 checkpoint 可读、重复恢复 409、purge 后 404、purge 活跃会话 409、删除/恢复/purge 他人会话 404 且数据未变

## 7. legacy checkpoint 语义

- [ ] 7.1 确认列表、状态查询、resume、snapshots、删除与 purge 路径都只以 `runs` 判定可见性，不直接依据 checkpoint 是否存在
- [ ] 7.2 补测试：仅有 checkpoint 无 `runs` 记录的 `thread_id` 不出现在列表、查询返回 404、resume 返回 404、删除/purge 返回 404，且其 checkpoint 数据未被删除
- [ ] 7.3 实现 `backend/scripts/cleanup_legacy_checkpoints.py`：默认 dry-run；`--yes` 执行；`--older-than-days`（默认 30）、`--batch-size`（默认 500）、`--audit-log`（默认 `data/audit/legacy_cleanup.log`）、`--purge-expired-trash`；只选择 `thread_id NOT IN (SELECT thread_id FROM runs)`，分批提交
- [ ] 7.4 实现过期回收站清理：`--purge-expired-trash` 按 `TRASH_RETENTION_DAYS` 删除 `deleted_at` 超期的 `runs` 行与 checkpoint，未过期会话不动
- [ ] 7.5 补运维测试：默认 dry-run 不删除、`--yes` 只删无主 thread、回收站会话受保护、超过批量大小分批提交、审计日志含计数且不含简历内容、重复执行幂等、过期回收站被清理
- [ ] 7.6 在 README 或 `backend/scripts/README.md` 写明 dry-run 先行、备份建议、审计日志位置与回滚边界

## 8. 前端登录注册与守卫（依赖 `add-frontend-shell`）

- [ ] 8.1 实现 `frontend/src/api/auth.ts` 与 `frontend/src/api/sessions.ts`，复用骨架的 HTTP 封装，登录成功后不自动写入 store
- [ ] 8.2 实现 `frontend/src/composables/useAuth.ts`：模块级单例状态（`user`、`token`）、`login` / `register` / `logout` / `fetchMe`，token 读写 `localStorage`，`fetchMe` 用同一 Promise 去重
- [ ] 8.3 实现 `frontend/src/views/LoginView.vue` 与 `RegisterView.vue`：前端字段校验（邮箱格式、密码 ≥ 8）、展示后端统一错误、注册成功后跳 `/login`
- [ ] 8.4 在路由配置中为业务页面加 `meta.requiresAuth`，实现全局前置守卫：无 token 重定向 `/login` 并携带站内相对 `redirect`，已登录访问 `/login`、`/register` 重定向首页
- [ ] 8.5 在 HTTP 拦截器中处理 401：清除 token 与用户状态、跳转 `/login`，并加防重入标记避免循环跳转
- [ ] 8.6 在导航区接入当前用户邮箱与登出入口，登出后回到 `/login`
- [ ] 8.7 补充 `useAuth` 与路由守卫的单元测试：无 token 被拦截、刷新后从 `localStorage` 恢复、401 清理并跳转、非法 `redirect` 被降级为首页
- [ ] 8.8 改造会话列表：搜索框（防抖）、分页控件、活跃/回收站切换；回收站中提供恢复与永久删除，永久删除需二次确认
- [ ] 8.9 处理列表空态、加载态、分页越界与搜索无结果；恢复/删除失败时展示统一错误并保留当前页
- [ ] 8.10 补前端测试：切换分页与搜索参数正确、回收站只展示已删除会话、恢复后回到活跃列表、永久删除二次确认、`409 not_trashed` 提示

## 9. 安全与验证

- [ ] 9.1 补启动测试：`JWT_SECRET` 缺失时启动失败且错误信息指明该变量；`JWT_EXPIRES_MINUTES=0` 时启动失败
- [ ] 9.2 检查日志脱敏：构造登录与注册异常，断言日志与响应均不含 `password`、密码哈希、`Authorization` 头与 token
- [ ] 9.3 端到端验证：注册 → 登录 → 创建运行 → 列表可见 → 重命名 → 第二个用户登录后列表为空且访问首个用户 `thread_id` 得 404 → 首个用户软删除后默认列表不可见、回收站可见 → 恢复后重新可见 → 再删除并永久删除后查询 404
- [ ] 9.4 验证 token 过期路径：用 `JWT_EXPIRES_MINUTES=1` 或构造过期 token，确认接口返回 401 且前端跳转 `/login`
- [ ] 9.5 验证回滚：移除鉴权依赖与新增路由后，core 的 `/api/runs` 在回滚窗口内仍可运行，`users` / `runs` 表与 checkpoint 数据不受影响
- [ ] 9.6 验证运维清理：在含 legacy checkpoint 与正常会话的库上先 dry-run、再 `--yes`，确认只删无主 thread、审计日志生成、重复执行幂等
- [ ] 9.7 运行 `openspec validate add-auth-sessions --strict` 并通过，确认 `openspec status --change "add-auth-sessions" --json` 中 `tasks` 为 `done`
