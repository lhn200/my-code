## 1. 前置检查与配置

- [ ] 1.1 确认 `add-career-assistant-core` 已 apply：`AgentState`、`thread_id`、`AsyncSqliteSaver`、`model_routing` 可用，否则中止本 change
- [ ] 1.2 确认 `add-auth-sessions` 已 apply：`get_current_user`、`get_owned_run`、`runs` 表与同库 WAL 可用
- [ ] 1.3 确认 `add-mock-interview` 已 apply：面试子图与 `summarize` 节点可复用
- [ ] 1.4 在 `backend/app/config/models.yaml` 新增 `summarizer` 与 `memory_extractor` 角色（轻模型、`temperature=0.2`），未配置时回退全局默认模型
- [ ] 1.5 扩展角色白名单与启动校验，使两个新角色与非空 `model`、`temperature` 区间校验一致
- [ ] 1.6 新增并校验配置项：`SESSION_CONTEXT_BUDGET=8000`、`CONTEXT_MEMORY_TOKENS=800`、`CONTEXT_SUMMARY_TOKENS=1200`、`CONTEXT_RECENT_TURNS_TOKENS=4800`、`CONTEXT_CURRENT_INPUT_TOKENS=1200`、`RECENT_TURNS_KEEP=6`、`MIN_RECENT_TURNS=2`、`SUMMARY_TRIGGER_TURNS=12`、`SUMMARY_MAX_CHARS=1200`、`SUMMARY_TIMEOUT_SECONDS=20`、`MAX_MESSAGE_CHARS=4000`、`MEMORY_ENABLED_DEFAULT=false`、`MEMORY_TOP_K=5`、`MEMORY_MAX_TOP_K=8`、`MEMORY_MAX_CONTENT_CHARS=200`、`MEMORY_MIN_CONFIDENCE=0.7`、`MEMORY_PENDING_CONFIDENCE=0.4`、`MEMORY_TTL_DAYS_FACT=180`、`MEMORY_TTL_DAYS_GOAL=365`、`MEMORY_TTL_DAYS_PREFERENCE=0`、`MEMORY_TTL_DAYS_CONSTRAINT=0`；非正数、top-k 超上限、TTL 为负数或预算总和超限必须启动失败

## 2. 状态与预算

- [ ] 2.1 在 `backend/app/state.py` 新增可选字段：`session_turns`、`session_summary`、`session_summary_version`、`session_summary_updated_at`、`summarized_through_turn`、`memory_context`、`memory_context_meta`、`context_budget_meta`，保持既有字段与 reducer 不变
- [ ] 2.2 实现 `ensure_memory_defaults()`，在 `load_context` 入口补齐旧 checkpoint 缺失字段
- [ ] 2.3 实现 token 计数器：优先 `tiktoken.get_encoding("cl100k_base")`，导入或编码失败时降级为 `ceil(cjk_chars + other_chars / 3.5 + 4)` 并乘 1.15；空串返回 0，异常退化为字符长度，启动日志记录一次降级原因
- [ ] 2.4 实现 `context_assembler`：按 800/1200/4800/1200 分配预算，输出消息列表与 `context_budget_meta`
- [ ] 2.5 实现裁剪顺序：记忆条数与单条长度 → 最旧轮次（保底 2 轮）→ 摘要压缩到 600 tokens → 仍超限返回 `context_overflow`
- [ ] 2.6 实现普通消息截断：超过 4000 字符保留头 70% + 尾 30%，插入 `...[已截断 N 字]...`，只作用于消息副本
- [ ] 2.7 实现 JD/简历保护：`jd_digest`（≤800 字符）与 `resume_digest`（≤1500 字符）生成、失败降级为结构化字段 + 截断标记并记录 `digest_fallback`
- [ ] 2.8 为计数器、预算分配、裁剪顺序、截断标记、digest 降级编写单元测试，断言 `context_budget_meta` 字段完整且不含正文

## 3. 滚动摘要

- [ ] 3.1 在 `backend/app/prompts/summarizer.md` 编写摘要提示词：结构化输出 `facts`、`open_questions`、`preferences`、`constraints`、`decisions`，明确不得编造与长度上限
- [ ] 3.2 实现 `session_memory` 模块：轮次追加（一轮 = 一次用户输入 + 对应输出）、有界轮次（上限 18）、未总结轮次计数与 `summarized_through_turn`
- [ ] 3.3 实现摘要触发：未总结轮次 ≥12 时总结最早 6 轮，保留最近 6 轮，`version` 加 1，写入 `session_summary` 与 `updated_at`
- [ ] 3.4 实现恢复装配：只取本 thread 摘要与最近 6 轮，摘要与轮次按 `summarized_through_turn` 去重
- [ ] 3.5 实现单轮运行结束后的 `BackgroundTasks` 摘要与 `aupdate_state` 回写，携带 `expected_version` 乐观校验
- [ ] 3.6 实现面试子图内联摘要：复用共享模块，`recent_turns_keep=3` 保持既有行为，受 `SUMMARY_TIMEOUT_SECONDS=20` 约束
- [ ] 3.7 实现失败降级：保留旧摘要、标记 `summary_status=failed`、最多重试 2 次（1s / 3s 退避），不阻塞主流程
- [ ] 3.8 实现懒补偿：下一次读取发现未总结轮次 ≥12 时重新触发，不在启动时全表扫描
- [ ] 3.9 实现 `session_memory_meta` 投影 upsert，读取时以 checkpoint 版本为准修正投影
- [ ] 3.10 编写摘要测试：阈值 12 触发、单次最多 6 轮、版本递增、重启后恢复、超时降级、重试耗尽仍可继续、投影缺失与不一致
- [ ] 3.11 在 `backend/tests/memory/test_session_summary.py` 为手动重新生成补单元测试：有未总结轮次时基于"现有摘要 + 最早 ≤6 轮"重算且 `version+1`；无未总结轮次时不写 checkpoint、版本与 `summarized_through_turn` 不变；`expected_version` 不匹配时不覆盖并返回冲突；模型超时、非法 JSON、缺字段时保留旧摘要并置 `summary_status=failed`；同一 thread 并发调用被锁串行化；后完成的旧任务不覆盖更高版本
- [ ] 3.12 在 `backend/tests/memory/test_session_summary.py` 为摘要正文查询补单元测试：`facts`/`open_questions`/`preferences`/`constraints`/`decisions` 完整序列化，空摘要返回 `null` 或空结构，正文与元信息不包含任何轮次原文，跨用户读取在服务层即拒绝，重新生成返回的正文与最新 checkpoint 一致

## 4. 长期记忆表与检索

- [ ] 4.1 在 `backend/app/db/` 增加幂等 DDL：`user_memories`（含 `expires_at`、`archived_reason`）、`user_memory_settings`、`session_memory_meta`、唯一部分索引、`(user_id, status, updated_at DESC)` 索引与 `(status, expires_at)` 归档索引，并递增 `PRAGMA user_version`
- [ ] 4.2 创建 `user_memories_fts`（`tokenize='trigram'`）与同步触发器；FTS5 不可用时记录原因并标记 `LIKE` 降级
- [ ] 4.3 实现内容归一化与哈希：去空白、压连续空白、200 字符上限、`sha256(user_id + kind + content)[:32]`
- [ ] 4.4 实现去重写入：相同哈希更新 `updated_at`、`confidence` 与按 `kind` 重算的 `expires_at`，不新增行；墓碑行不参与唯一约束
- [ ] 4.5 实现冲突操作：接收提炼结果的 `add` / `update(target_id)` / `skip`，新置信度不低于旧值 +0.1 才覆盖，否则跳过并计数
- [ ] 4.6 实现检索词提取（最多 8 个、长度 ≥2）与 FTS5 / `LIKE` 双路径查询，关键词少于 3 字符时走 `LIKE`
- [ ] 4.7 实现打分与排序：`0.6 * relevance + 0.25 * recency + 0.15 * confidence`，`recency = 0.5 ** (days / 30)`，无关键词时权重改为 0.625 / 0.375
- [ ] 4.8 实现 top-k 与 token 双上限：默认 5、上限 8、总 800 tokens、单条注入 150 字符，超出按分数降条数
- [ ] 4.9 实现开关读取：默认关闭，每次写入与检索前读取 `user_memory_settings`，缺失行按默认值解释
- [ ] 4.10 编写检索测试：相关度排序、时间衰减、纯置信度降级、top-k 上限、token 裁剪、跨用户不可见、待确认 / 已归档 / 已过期不参与
- [ ] 4.11 实现 TTL 计算：写入与更新时按 `kind` 设置 `expires_at`（0 表示永不过期），确认、编辑、去重与冲突更新均重算
- [ ] 4.12 实现 `archive_expired_memories()`：单条 UPDATE 把到期且 `status in ('active','pending_confirmation')` 的行改为 `archived` / `archived_reason='ttl'`；启动后执行一次，检索与列表前按进程内 1 小时节流惰性执行
- [ ] 4.13 实现 `python -m app.memory.cli expire` 手动归档命令，并在列表与检索 SQL 中固定过滤 `expires_at IS NULL OR expires_at > now`
- [ ] 4.14 编写 TTL 测试：默认 fact/goal 过期时间、preference/constraint 不过期、到期归档、归档后默认列表与检索不可见、`status=archived` 可查可删、更新刷新 `expires_at`、负数配置启动失败

## 5. 写入管线

- [ ] 5.1 在 `backend/app/prompts/memory_extractor.md` 编写提炼提示词：只输出稳定、可复用、与求职相关的短句，最多 5 条，禁止原文与逐字引用
- [ ] 5.2 实现提炼输入构造：使用运行结果与摘要，不把简历原文、JD 原文或完整对话直接塞入提炼提示词
- [ ] 5.3 实现提炼上下文：携带同 `kind` 最近 5 条记忆，要求模型返回 `add` / `update(target_id)` / `skip`
- [ ] 5.4 实现敏感信息过滤：身份证、手机号、邮箱、住址、银行卡、健康、婚育、民族、宗教、政治面貌、凭证类规则，命中整条拒绝且只记计数
- [ ] 5.5 实现置信度分层：≥0.7 为 `active`，0.4–0.7 为 `pending_confirmation`，<0.4 丢弃
- [ ] 5.6 实现写入时机：仅在 `completed` / `partial` 运行结束或用户显式确认后写入，运行中与进行中不写
- [ ] 5.7 接入 `BackgroundTasks`，按 `user_id` 加进程内 `asyncio.Lock` 保证同一用户串行，失败重试 2 次且不影响主结果
- [ ] 5.8 关闭记忆时禁止创建提炼任务与调用提炼模型
- [ ] 5.9 编写管线测试：运行结束才写、最多 5 条、低置信度丢弃、待确认不参与检索、敏感内容拒绝、关闭记忆不写、提炼失败不影响主结果

## 6. 接口

- [ ] 6.1 实现 `GET /api/memories`：按 `user_id` 过滤、支持 `kind` / `status` / `q` / `limit`，`limit` 有上限，非法枚举返回 422
- [ ] 6.2 实现 `DELETE /api/memories/{id}`：墓碑清空 `content` 与 `content_hash`，写 `deleted_at`，重复删除幂等，非本人返回 404
- [ ] 6.3 实现 `DELETE /api/memories`：一键清空当前用户全部记忆并返回删除条数
- [ ] 6.4 实现 `PATCH /api/memories/{id}`：编辑 `content` / `kind`、确认待确认、忽略归档；复用内容规范与敏感过滤，非法入参 422
- [ ] 6.5 实现 `GET/PUT /api/memories/settings`：默认 `enabled=false`，`PUT` 只接受布尔值，按用户 upsert
- [ ] 6.6 实现 `GET /api/sessions/{thread_id}/summary`：返回 `summarized`、`version`、`updated_at`、`summarized_through_turn`、`summary_status` 与结构化 `summary` 正文，不返回轮次原文，先 `get_owned_run` 后读取
- [ ] 6.7 在 `backend/app/api/sessions.py` 删除会话流程中确认 `source_thread_id` 由 `ON DELETE SET NULL` 置空，记忆行保留
- [ ] 6.8 在 `main.py` 注册新路由，确保启动顺序为：配置校验 → DDL → 启动归档 → 路由注册
- [ ] 6.9 编写接口测试：401、404、422、空列表、过滤、幂等删除、一键清空、跨用户隔离、设置持久化
- [ ] 6.10 实现 `POST /api/sessions/{thread_id}/summary/regenerate`：同 thread 锁内增量重算（现有摘要 + 最早 ≤6 个未总结轮次），`expected_version` 乐观校验，成功 `version+1`；无未总结轮次返回 `regenerated=false`；冲突 409 `summary_conflict`；失败 502 `summary_failed` 且保留旧摘要
- [ ] 6.11 在 `backend/tests/api/test_session_summary.py` 编写摘要接口测试：正文含结构化字段且不含轮次原文；空摘要 `summarized=false`；跨用户 404；未登录 401；重新生成 `version+1` 且正文与 `GET` 一致；无未总结轮次返回 `regenerated=false` 且版本不变；并发冲突返回 409 且不覆盖较新摘要；模型失败返回 502 且 `GET` 仍返回旧摘要

## 7. 前端

- [ ] 7.1 新增 `frontend/src/api/memories.ts` 与 TypeScript 类型（含记忆项 `expires_at` 与摘要响应 `summary` 正文），复用既有 HTTP 封装与 401 处理
- [ ] 7.2 新增 `frontend/src/composables/useMemory.ts`：加载列表、加载与更新设置、删除单条、清空、确认与忽略、切换 `status=archived` 查看归档
- [ ] 7.3 新增 `/settings/memory` 页面（`MemorySettingsView.vue`，`meta.requiresAuth`）：记忆开关、类型筛选、记忆列表、待确认区、归档区；作为独立页面，避免与 `account-recovery` 的 `/settings` 冲突
- [ ] 7.4 新增 `MemoryList.vue` 与删除确认交互；删除与清空成功后本地同步更新，失败时回滚并提示；展示 `expires_at` 与 `archived_reason`
- [ ] 7.5 实现开关切换的乐观更新与失败回滚，并在关闭状态提示"已停止写入与使用记忆，已有记忆仍可删除"
- [ ] 7.6 实现空态（无记忆）、关闭态（开关关闭）与失败态（接口错误可重试），样式只引用既有 CSS 变量
- [ ] 7.7 在 `/settings/memory` 新增"会话摘要"区域：列出当前用户会话与摘要状态，可展开只读查看结构化摘要正文，包含 `facts`、`open_questions`、`preferences`、`constraints`、`decisions`
- [ ] 7.8 实现"重新生成摘要"按钮：调用 `POST /api/sessions/{thread_id}/summary/regenerate`，请求中禁用并展示加载态；`regenerated=false` 提示暂无新轮次；409 展示当前摘要；502 提示失败并保留原摘要
- [ ] 7.9 新增 `frontend/src/composables/useSessionSummary.ts` 与 `SessionSummaryPanel.vue`，摘要正文不写入 `localStorage`
- [ ] 7.10 编写 `frontend/tests/useSessionSummary.spec.ts` 与 `SessionSummaryPanel.spec.ts`：正文按五类字段渲染、空摘要与空数组降级、加载与卸载中止请求、重新生成成功后刷新版本与正文、`regenerated=false` 提示暂无新轮次、409 展示当前摘要且保留正文、502 保留旧正文并提示可重试、请求中按钮禁用且不重复提交、摘要正文不写入 `localStorage`
- [ ] 7.11 编写前端手工验证清单：开关切换、删除确认、待确认确认、归档筛选、空态、错误态、摘要正文展示、重新生成四种结果（成功 / 无新轮次 / 冲突 / 失败）

## 8. 测试与验证

- [ ] 8.1 隔离测试：同一用户两个 thread 的摘要与轮次不混入；用户 A 无法读取用户 B 的摘要状态与记忆
- [ ] 8.2 预算测试：默认 8000 分配、自定义配置、非法配置启动失败、裁剪顺序、仍超限返回 `context_overflow`
- [ ] 8.3 关键输入测试：超长 JD / 简历走 digest、原文不变、digest 失败降级、岗位分析不注入简历与记忆
- [ ] 8.4 摘要测试：12 轮触发、保留 6 轮、每次最多 6 轮、版本递增、重启恢复、失败降级与懒补偿
- [ ] 8.5 记忆测试：去重、冲突更新、待确认、敏感拒绝、开关关闭不写不检索、删除墓碑、一键清空、会话删除后 `source_thread_id` 为空
- [ ] 8.6 注入边界测试：system prompt 不含摘要与记忆；记忆中的指令不改变评分与路由；白名单外类型被过滤
- [ ] 8.7 兼容测试：用不含新增字段的旧 checkpoint 恢复，断言默认值补齐且运行正常；断言既有字段与 reducer 行为不变
- [ ] 8.8 性能验证：构造单用户 1000 条记忆，断言检索 P95 < 50ms 且使用索引；确认无全表扫描
- [ ] 8.9 手工验证：开启记忆跑一次分析 → 运行结束后出现记忆；关闭记忆再跑一次 → 不新增；删除单条与一键清空生效；设置页展示摘要正文并可重新生成
- [ ] 8.10 摘要接口验证：正文含结构化字段且不含轮次原文；跨用户 404；重新生成版本递增；无未总结轮次 `regenerated=false`；模型失败保留旧摘要
- [ ] 8.11 TTL 验证：构造已过期 `fact`，断言默认列表与检索不可见、`status=archived` 可见、`archived_reason=ttl`、更新后 `expires_at` 刷新、CLI 可手动触发
- [ ] 8.12 运行 `openspec validate add-user-memory --strict` 并确认通过
