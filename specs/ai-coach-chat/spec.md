# 规格：AI 模拟教练（多轮对话）

## 1. 背景与目标

现有「模拟面试」是逐题演练并生成报告，分析结果页只提供一次性的「求职建议」。用户希望有一个可持续追问的教练：围绕已完成的分析（目标、简历、岗位匹配、面试报告）进行多轮对话，获得具体、可执行的求职建议。

本规格新增独立「AI 教练」页面与后端会话服务：

1. 教练多轮对话：用户提问 → 教练结合上下文回答，可连续追问。
2. 默认引用最近一次完成的分析，页面顶部可切换到其他分析会话；也可选择不绑定分析。
3. 多个教练会话，支持历史列表、重命名、删除。
4. 回复一次性返回（非流式），发送后显示「思考中」。

## 2. 范围

### 做

- SQLite 新增 `coach_sessions`、`coach_messages` 两张表，`SCHEMA_VERSION` 升到 4。
- 新增 prompt 角色 `coach_chat` 与提示词文件。
- 新增后端数据访问层、服务层、REST 接口，并挂载路由。
- 新增前端独立页面、API 封装、composable、路由与导航入口。
- 绑定分析时组装上下文：目标、简历摘要、岗位画像/评分/缺口、面试报告摘要、长期记忆。

### 不做

- 不做训练计划生成、复盘讲评、深化面试追问（本次只做教练对话）。
- 不做流式输出、语音、多教练人格、消息编辑与重新生成。
- 不修改主分析图与既有面试演练逻辑。
- 不引入新 UI 库、状态管理库；沿用档案室视觉与原生 CSS 变量。

## 3. 数据模型（Schema v4）

### 3.1 `coach_sessions`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | TEXT PK | 会话 ID（`uuid4().hex`） |
| `user_id` | TEXT NOT NULL | 归属用户，外键 users(id) |
| `thread_id` | TEXT NULL | 绑定的分析会话；NULL 表示不绑定 |
| `title` | TEXT NOT NULL DEFAULT '' | 会话标题，空时展示「新的教练会话」 |
| `created_at` | TEXT NOT NULL | ISO 时间 |
| `updated_at` | TEXT NOT NULL | ISO 时间 |

索引：`(user_id, updated_at DESC)`。

### 3.2 `coach_messages`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | TEXT PK | 消息 ID |
| `session_id` | TEXT NOT NULL | 外键 coach_sessions(id) ON DELETE CASCADE |
| `seq` | INTEGER NOT NULL | 会话内递增序号 |
| `role` | TEXT CHECK IN ('user','coach') | 说话方 |
| `content` | TEXT NOT NULL | 文本 |
| `created_at` | TEXT NOT NULL | ISO 时间 |

索引/约束：唯一 `(session_id, seq)`。

### 3.3 迁移

- `backend/app/db/migrations.py`：`SCHEMA_VERSION = 4`；两张表与索引追加进 `_CORE_DDL`（`CREATE TABLE IF NOT EXISTS`，天然幂等）。
- 旧库升级无需回填，新表为空即用。

## 4. 后端接口契约

统一前缀 `/api`，全部 `Depends(get_current_user)`。返回体：

- 单会话：`{"session": {...}, "messages": [...]}`
- 列表：`{"items": [session, ...]}`，`session` 含 `message_count`。

| 方法 | 路径 | 请求体 | 说明 |
| --- | --- | --- | --- |
| POST | `/coach/sessions` | `{thread_id?: string\|null, title?: string}` | 新建会话，返回空消息列表 |
| GET | `/coach/sessions` | query `thread_id?` | 列出当前用户会话；传 `thread_id` 时仅列该分析下的会话 |
| GET | `/coach/sessions/{id}` | — | 读取会话与全部消息 |
| PATCH | `/coach/sessions/{id}` | `{title?: string, thread_id?: string\|null}` | 重命名或改绑分析；`thread_id: null` 解绑 |
| DELETE | `/coach/sessions/{id}` | — | 删除会话及其消息，返回 204 |
| POST | `/coach/sessions/{id}/messages` | `{content}` | 发送消息，返回最新完整会话 |

字段约束：

- `content` 去空后不得为空（否则 422 `coach_message_blank`），长度上限 `settings.max_message_chars`（默认 4000，超限 422 `coach_message_too_long`）。
- `title` 若提供，去空后不得为空，长度上限 `settings.max_session_title_chars`；schema 层校验，失败为 422 `validation_error`。
- `thread_id` 若提供且非 null，必须为当前用户未删除的 run，否则 404 `coach_analysis_not_found`。
- 会话归属不符统一 404 `coach_session_not_found`，不泄露存在性。

## 5. 会话流程与上下文

### 5.1 新建

1. 校验 `thread_id` 归属（`runs` 表，`deleted_at IS NULL`）。
2. `title` 为空时存空串；前端展示「新的教练会话」。
3. 返回空消息的会话载荷，不调用模型。

### 5.2 发送消息

1. 校验归属；`content` 去空、截断到 `max_message_chars` 后入库前校验。
2. 组装上下文：
   - 绑定分析时读取 `graph.aget_state(thread_config(thread_id)).values`；若快照为空或 run 已失效，降级为「无分析上下文」，不阻断对话。
   - `goal`、`resume_text`（超过 `max_message_chars` 用 `build_resume_digest` 压缩）。
   - 每个岗位：`title`、画像 `must_have/keywords`（各最多 6 条）、当前版本评审 `score/dimensions/missing/issues`（`current_review`）、对应 `interview_reports[job_id]` 的 `overall_score/improvements/requirement_gaps`。
   - 长期记忆：`retrieve_memories(connection, user_id=..., query=最新用户消息, settings=settings)`，仅保留 `kind/content`，最多 `memory_top_k` 条。
3. 读取最近 `settings.recent_turns_keep * 2` 条消息作为真实历史（`user → human`，`coach → ai`）。
4. 消息组装：`build_messages("coach_chat", prompts, {coach_context_json, user_message})` 得到 system + human；在 system 之后、human 之前插入历史轮次。
5. 调用 `call_text(context.model("coach_chat"), messages, attempts=2)`，受 `context.semaphore` 限并发。
6. 模型成功后单事务写入：用户消息、教练回复；更新 `updated_at`；若标题为空，用首条用户消息去空白后截 40 字作为标题。
7. 模型失败 → 502 `coach_reply_failed`，不写库，用户可重试。
8. 回复内容入库前截断到 `max_message_chars`。

## 6. Prompt 契约

### 6.1 `backend/app/prompts/coach_chat.md`

- 系统段：资深求职教练，中文多轮对话；只依据提供的分析上下文、简历与记忆作答，不编造经历/公司/数字；建议必须具体、可执行；上下文不足时明确说明并追问；不对年龄、性别、婚育、健康、民族、宗教、政治面貌等作评价；输出自然中文 Markdown，不输出 JSON。
- `--- HUMAN TEMPLATE ---` 之后的 human 段占位符：`[[coach_context_json]]`、`[[user_message]]`。
- 历史轮次以真实 `human/ai` 消息注入，避免与 `coach_context_json` 重复。
- 决策：不注册 `conversation_json` 占位符，历史由消息序列承载。

### 6.2 角色与模型注册

- `backend/app/prompts/loader.py`：`ROLES` 追加 `coach_chat`；`UNTRUSTED_PLACEHOLDERS` 追加 `coach_context_json`、`user_message`。
- `backend/app/config/model_router.py`：`ROLES` 同步追加 `coach_chat`。
- `backend/app/config/models.yaml`：`roles.coach_chat` = `{provider: openai, model: qwen-plus, temperature: 0.5}`。

## 7. 前端交互

### 7.1 页面 `/coach`

- 顶部：标题「AI 教练」、分析选择器（`GET /sessions?page_size=100` 读取未删除分析；额外提供「不绑定分析」）、新建会话按钮。
- 左栏：当前用户教练会话历史（按 `updated_at DESC`），展示标题、更新时间、消息数；支持重命名、删除（删除需二次确认）。
- 右栏：消息区；用户消息右对齐、教练消息左对齐（衬线正文）；发送中显示「教练思考中…」占位气泡；空会话显示引导文案与示例问题。
- 输入区：多行文本、字数提示、发送按钮；`Ctrl/Cmd + Enter` 发送；发送中禁用。
- 切换分析选择器时，重建/加载该分析下的会话列表；若列表为空自动新建一个绑定该分析的会话。
- 错误：复用 `ErrorNotice`；404 显示「教练会话不存在或已失效」。

### 7.2 文件

- 新增 `frontend/src/api/coach.ts`、`frontend/src/composables/useCoachChat.ts`、`frontend/src/views/CoachView.vue`。
- `frontend/src/api/types.ts`：新增 `CoachMessageRole`、`CoachSession`、`CoachMessage`、`CoachSessionPayload`、`CoachSessionListResponse`。
- `frontend/src/api/client.ts`：`KNOWN_CODES` 增补教练错误码中文文案。
- `frontend/src/router/index.ts`：新增 `/coach`（name `coach`，`requiresAuth: true`）。
- `frontend/src/App.vue`：导航增加「AI 教练」。

## 8. 错误码

| 码 | 状态 | 场景 |
| --- | --- | --- |
| `coach_session_not_found` | 404 | 会话不存在或不属于当前用户 |
| `coach_analysis_not_found` | 404 | 绑定/创建时的分析会话不存在或已删除 |
| `coach_message_blank` | 422 | 消息为空 |
| `coach_message_too_long` | 422 | 消息超长 |
| `coach_reply_failed` | 502 | 教练模型调用失败 |

## 9. 测试与验收

### 后端

新增 `backend/tests/test_coach_chat.py`（复用 `tests/fakes.py`，为 `coach_chat` 增加可配置文本 handler，并记录收到的消息）：

1. 新建未绑定会话 → 发送消息 → 回复追加、标题自动取首条消息。
2. 绑定已完成 run → 发送消息 → 断言模型收到的 human 消息包含岗位标题与评审分数。
3. 空消息 422、超长消息 422。
4. 跨用户访问 404；绑定不存在/已删除 run 404。
5. 重命名、改绑、解绑、删除；删除后读取 404。
6. 模型失败 502 且不写库（消息数不变）。
7. `test_prompts.py` 角色集合与数量更新为 11；`test_db_migration.py` 版本断言更新为 4。
- 命令：`python -m pytest backend/tests -q`。

### 前端

- 新增 `frontend/tests/coach-chat.test.ts`：composable 新建/发送/失败/删除分支。
- 命令：`npm run typecheck`、`npm run test`、`npm run build`。

### 浏览器 E2E

- 登录测试账号 → 导航进入「AI 教练」→ 选择已完成分析 → 自动/手动新建会话 → 发送 2 条消息（含一次追问）→ 重命名 → 刷新确认消息与选择状态保留 → 删除会话。

## 10. 兼容与回滚

- 新表为增量，旧数据不受影响；`SCHEMA_VERSION = 4` 幂等升级。
- 回滚只需下线路由与导航，存量表可保留。

## 11. 决策记录

- D1：教练会话独立于主图与面试演练，单轮一次模型调用，逻辑可预测。
- D2：绑定分析通过 `thread_id` 软关联；分析被删除时对话降级为无上下文，不阻断历史会话。
- D3：历史以真实 `human/ai` 消息注入，不额外注册 `conversation_json`，避免上下文重复。
- D4：回复一次性返回，前端用「思考中」占位，规避流式改造。
- D5：发送失败不落库，保持消息序列与模型实际看到的历史一致。
