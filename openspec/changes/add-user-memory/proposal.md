## Why

`add-career-assistant-core` 建立了 `AgentState`、`thread_id` 与 SQLite checkpoint，一次分析可以在同一 thread 内恢复；`add-auth-sessions` 补上了用户维度与 `runs` 会话目录；`add-mock-interview` 引入 interrupt/resume，使单个会话可持续几十轮。三者叠加后暴露两个互相独立、不能用同一机制解决的问题：

1. **会话窗口成本不可控**：主图与面试子图倾向把历史问答原样带入下一次模型调用，轮次越多 token 越大；长 JD、长简历贴进对话后更难裁剪。没有预算与摘要时，最终会撞上模型上下文上限，或在撞上限之前先把成本与延迟推高。
2. **记忆无法跨会话复用**：用户的目标（如"半年内转向数据方向"）、偏好（"不接受外包与长期出差"）与约束（"目前在职，只能线上面试"）每次都要重新说明；`thread_id` 级 checkpoint 只能服务单次会话，无法承载"跨会话仍然成立"的信息。

会话摘要属于"本会话内的上下文管理"，必须严格隔离在 `user_id + thread_id` 内；长期记忆属于"用户级资产"，需要跨 thread 检索、可查看、可删除、可关闭。把两者混在一起会导致跨会话泄漏或把用户偏好错误固化。本 change 拆成两个能力，并在预算分配、提示词注入边界与删除语义上显式对齐。

## What Changes

- 新增共享会话记忆模块：轮次记录、token 计数、上下文预算装配、裁剪与显式截断标记、滚动摘要。
- 会话轮次与摘要按 `user_id + thread_id` 命名空间隔离；恢复会话时只加载本会话摘要与最近轮次，不回放全量 transcript。
- 上下文预算默认 8000 tokens：长期记忆 800、会话摘要 1200、最近轮次 4800、当前输入 1200；超预算时按"先减记忆、再丢最旧轮次、再压缩摘要"的顺序裁剪，最近轮次保底 2 轮，当前输入不丢弃。
- 单条消息超过 4000 字符时按"头 70% + 尾 30%"截断并插入显式标记；岗位 JD 与简历不走普通截断，改用 `jd_digest` / `resume_digest` 结构化摘要或既有结构化字段，禁止静默丢弃。
- token 计数优先使用 tiktoken（`cl100k_base`），不可用时降级为轻量估算（CJK 约 1 token/字，其余约 3.5 字符/token），估算值放大 1.15 倍作为安全余量，并在启动日志记录降级原因。
- 滚动摘要：未总结轮次达到 12 轮触发，保留最近 6 轮原文，每次最多总结最早 6 轮；摘要结构化保留事实、未解决问题、用户偏好、约束与决策，并携带版本号与更新时间。
- 摘要写入 checkpoint 中的 `AgentState`；单轮运行结束后由 FastAPI `BackgroundTasks` 异步回写，interrupt 图在 `summarize` 节点内联执行；超时 20 秒、重试 2 次，失败降级为"旧摘要 + 最近 N 轮"且不阻塞主流程。
- 新增 SQLite 表 `user_memories`、`user_memory_settings`、`session_memory_meta`，并为 `user_memories` 建 FTS5（trigram）索引；SQLite 未启用 FTS5 时降级为 `LIKE` 关键词匹配。
- 长期记忆类型限定为 `preference` / `goal` / `fact` / `constraint`；只保存提炼后的稳定信息，不保存简历原文、JD 原文或对话原文。
- 长期记忆写入只在运行结束或用户显式确认后执行，每次最多 5 条；置信度 ≥0.7 直接生效，0.4–0.7 进入待确认，<0.4 丢弃；命中敏感信息整条拒绝写入。
- 新增记忆接口：`GET /api/memories`、`DELETE /api/memories/{id}`、`PATCH /api/memories/{id}`、`DELETE /api/memories`（一键清空）、`GET /api/memories/settings`、`PUT /api/memories/settings`、`GET /api/sessions/{thread_id}/summary`（返回结构化摘要正文）、`POST /api/sessions/{thread_id}/summary/regenerate`（增量重新生成摘要）。
- 长期记忆默认关闭（opt-in）；关闭后不写入也不检索，已有记忆仍可查看与删除；关闭长期记忆不影响会话摘要与预算裁剪。
- 记忆与摘要只能作为带分隔符的参考数据进入 human message，不得进入 system prompt；按节点白名单注入，岗位分析节点不注入任何用户记忆与简历细节。
- 长期记忆按类型 TTL 自动归档：`fact` 默认 180 天、`goal` 365 天，`preference` / `constraint` 默认永不过期；写入、编辑、确认与去重更新都会重算 `expires_at`，到期只归档不物理删除，默认列表与检索不再返回，可按 `status=archived` 查看与删除。归档在启动后执行一次，并按 1 小时节流惰性执行，另提供 `python -m app.memory.cli expire` 手动触发。
- 前端新增设置页记忆开关、记忆列表、待确认项、归档项与删除确认；设置页展示会话摘要正文（只读）并提供"重新生成摘要"按钮。
- 不做：向量检索、embedding 与语义重排（后续独立 change `add-memory-semantic-search` 承接）、记忆导出/导入与跨设备同步（后续独立 change `add-memory-portability` 承接，格式与脱敏规则由该 change 定义）、跨用户共享、摘要正文可视化编辑、记忆物理删除与定时守护任务、修改 core 主图路由与回流逻辑、流式输出。

## Capabilities

### New Capabilities

- `session-memory`: 会话记忆命名空间隔离、恢复语义、上下文 token 预算与裁剪优先级、长消息截断与关键输入保护、token 计数降级、滚动摘要的触发/内容/版本/持久化/失败降级、异步执行、摘要状态与正文查询、手动重新生成摘要及其并发与失败语义、摘要注入边界、`AgentState` 向后兼容。
- `long-term-memory`: `user_memories` 数据模型与索引、记忆类型与内容规范、去重与冲突更新、写入时机与提炼范围、敏感信息与置信度分级、按类型 TTL 自动归档、开关语义、跨会话检索与排序（含过期过滤）、检索上限、注入边界与节点白名单、记忆 CRUD 与设置接口、归档查询、会话删除后的保留语义、后台执行与失败处理。

### Modified Capabilities

<!-- openspec/specs/ 下尚无已归档 capability；core 的 session-checkpoint 与 mock-interview 的滚动摘要由本 change 以新增公共能力补充，不回写既有 spec。 -->

## Architecture Impact

依赖顺序：`add-career-assistant-core`（`AgentState`、thread、checkpoint、角色模型）→ `add-auth-sessions`（`user_id`、`runs`、归属校验）→ `add-mock-interview`（多轮会话形态）→ 本 change（会话窗口治理 + 用户级记忆）→ 前端设置页依赖 `add-frontend-shell` 与 `add-auth-sessions`。

架构层面：

- 新增 `backend/app/memory/` 作为唯一记忆域：`token_budget.py`（计数与装配）、`session_memory.py`（轮次、摘要与手动重新生成）、`long_term.py`（表访问、去重、检索、TTL 归档）、`extraction.py`（提炼与敏感过滤）、`rendering.py`（分隔符注入）、`cli.py`（手动归档命令）。
- 记忆服务是唯一读写 SQL 的地方；图节点只调用服务，不直接拼 SQL，也不直接做 `content[:200]` 之类的截断。
- 身份注入通过 `config["configurable"]` 传入 `user_id` 与 `memory_enabled`，不进入 `AgentState`、不写入 checkpoint；长期记忆检索与开关判断以 token 解析出的用户为准，绝不接受请求体传入的 `user_id`。
- checkpoint 仍是摘要与轮次的真相来源；`session_memory_meta` 只是给会话列表与"已总结"标记用的轻量投影，允许缺失与滞后，读取时以 checkpoint 为准并顺带修正投影。
- `AgentState` 只增不改：新增 `session_turns`、`session_summary`、`session_summary_version`、`session_summary_updated_at`、`summarized_through_turn`、`memory_context`、`memory_context_meta`、`context_budget_meta`，均带默认值；旧 checkpoint 缺失这些键时由 `load_context` 补齐，不改变既有字段语义与 reducer。
- 预算装配只影响"送入模型的消息副本"，不改写状态中的原始 `resume_text` / `jobs`；因此裁剪与摘要是可逆的上下文视图，而不是数据销毁。
- 后台执行复用 FastAPI `BackgroundTasks`，不引入 Celery/Redis；单机无队列，任务在进程重启后允许丢失，由下一次会话读取时懒触发补偿。
- 前端只消费接口，不缓存记忆正文或摘要正文到 `localStorage`；新增 `useMemory`、`useSessionSummary` composable 与 `/settings/memory` 页面，样式沿用既有 CSS 变量。

## Impact

- 后端新增：`backend/app/memory/`（预算、会话记忆、长期记忆、TTL 归档、提炼、渲染、CLI）、`backend/app/api/memories.py`、`backend/app/api/session_memory.py`、`backend/app/prompts/summarizer.md`、`backend/app/prompts/memory_extractor.md`。
- 后端修改：`backend/app/state.py`（新增可选字段与默认值填充）、`backend/app/graph/`（入口节点加载上下文、节点按白名单注入、运行结束触发后台任务）、`backend/app/graph/interview/`（`summarize` 节点复用共享模块并保留 3 轮配置）、`backend/app/config/models.yaml` 与 `model_router.py`（新增 `summarizer`、`memory_extractor` 轻模型角色）、`backend/app/db/`（新增表、TTL 列与索引的幂等 DDL、`PRAGMA user_version` 递增）、`backend/app/api/sessions.py`（删除会话时解除记忆来源关联）、`backend/app/main.py`（启动归档与注册新路由）。
- 前端新增：`frontend/src/views/MemorySettingsView.vue`（路由 `/settings/memory`，与 `account-recovery` 的 `/settings` 分离）、`frontend/src/components/MemoryList.vue`、`frontend/src/components/SessionSummaryPanel.vue`、`frontend/src/composables/useMemory.ts`、`frontend/src/composables/useSessionSummary.ts`、`frontend/src/api/memories.ts`；设置页提供摘要正文展示与"重新生成摘要"按钮，会话列表与结果页增加"已总结"标记。
- 数据表新增：`user_memories`（含 `expires_at`、`archived_reason`）、`user_memories_fts`（FTS5 虚表 + 同步触发器）、`user_memory_settings`、`session_memory_meta`，全部落在既有 `CHECKPOINT_DB_PATH` 指向的同一 SQLite 文件。
- 配置新增：`SESSION_CONTEXT_BUDGET`（8000）、`CONTEXT_MEMORY_TOKENS`（800）、`CONTEXT_SUMMARY_TOKENS`（1200）、`CONTEXT_RECENT_TURNS_TOKENS`（4800）、`CONTEXT_CURRENT_INPUT_TOKENS`（1200）、`RECENT_TURNS_KEEP`（6）、`MIN_RECENT_TURNS`（2）、`SUMMARY_TRIGGER_TURNS`（12）、`SUMMARY_MAX_CHARS`（1200）、`SUMMARY_TIMEOUT_SECONDS`（20）、`MAX_MESSAGE_CHARS`（4000）、`MEMORY_ENABLED_DEFAULT`（false）、`MEMORY_TOP_K`（5）、`MEMORY_MAX_TOP_K`（8）、`MEMORY_MAX_CONTENT_CHARS`（200）、`MEMORY_MIN_CONFIDENCE`（0.7）、`MEMORY_PENDING_CONFIDENCE`（0.4）、`MEMORY_TTL_DAYS_FACT`（180）、`MEMORY_TTL_DAYS_GOAL`（365）、`MEMORY_TTL_DAYS_PREFERENCE`（0）、`MEMORY_TTL_DAYS_CONSTRAINT`（0）。
- 依赖新增：`tiktoken`（可选，缺失时自动降级）；FTS5 依赖 Python 自带 SQLite 编译选项，不可用时自动降级为 `LIKE`，不新增存储引擎。
- 测试：预算分配与裁剪顺序、截断标记、关键输入不丢失、摘要触发/版本/恢复/失败降级、摘要正文查询与手动重新生成、跨用户与跨会话隔离、去重与冲突更新、敏感信息拒绝、开关语义、检索排序与 top-k 上限、TTL 归档与过期过滤、删除与一键清空、注入边界、后台任务不阻塞、旧 checkpoint 兼容、检索性能。
- 迁移：新增表、TTL 列与索引使用幂等 DDL；启动完成后执行一次过期归档，之后按 1 小时节流惰性执行。存量 checkpoint 不迁移，新字段在首次读取时补默认值；回滚只需下线路由与后台触发，表可保留且旧代码忽略新增字段。
