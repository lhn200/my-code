# 规格：AI 面试官实时演练会话（方案 A）

## 1. 背景与目标

现有“模拟面试”是主分析图中的离线自答自评：模型根据岗位画像和简历自己出 5 题、自己推演答案并打分，`interview_thread_id` 为 `auto-*` 假 ID，用户没有真实作答过程。

本规格新增一个**独立的演练会话**：用户进入某个已完成分析的岗位，由 AI 面试官逐题提问，用户真实作答，系统即时给出反馈与追问，完成 5 题后生成评估报告并回填到该岗位结果中。

目标：

1. 真实的「提问 → 回答 → 反馈 → 追问 → 下一题」多轮闭环。
2. 会话与消息持久化，刷新页面可继续。
3. 演练结束后报告写回原 run 的 `interview_reports`，并在岗位卡展示，且与离线预评估可区分。
4. 严格遵守现有安全约束：简历/JD 是不可信数据、不涉及敏感话题、不编造事实。

## 2. 范围

### 做

- 新增 SQLite 表 `interview_sessions`、`interview_messages` 与迁移。
- 新增两个 prompt 角色：`interview_questioner`（提问/反馈/追问）与 `interview_evaluator`（终局评估）。
- 新增后端服务与 REST 接口：创建会话、提交回答、结束并生成报告、查询会话、按 run 列出会话。
- 报告新增来源字段，区分 `offline`（离线预评估）与 `practice`（真人演练）。
- 前端：岗位卡「开始演练」入口、独立对话页、报告展示与来源标签。

### 不做

- 不把交互式面试塞进主分析图，不引入长时间挂起的 `interrupt`。
- 不做语音、实时流式、多人面试、题库管理、评分标准配置后台。
- 不引入新 UI 库、Tailwind、Pinia，沿用现有档案室视觉与原生 CSS 变量。
- 不修改现有离线自评逻辑的行为，仅补充来源标记。

## 3. 数据模型

### 3.1 `interview_sessions`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | TEXT PK | 会话 ID，`new_thread_id()` 同风格生成 |
| `user_id` | TEXT NOT NULL | 归属用户，外键 users(id) |
| `thread_id` | TEXT NOT NULL | 来源 run 的 thread_id |
| `job_id` | TEXT NOT NULL | 来源岗位 |
| `job_title` | TEXT NOT NULL DEFAULT '' | 展示用岗位名快照 |
| `goal` | TEXT NOT NULL DEFAULT '' | 求职目标快照 |
| `job_profile_json` | TEXT NOT NULL DEFAULT '{}' | 岗位画像快照 |
| `resume_text` | TEXT NOT NULL DEFAULT '' | 简历快照（过长已用 digest 压缩） |
| `variant_version` | INTEGER NOT NULL DEFAULT 0 | 简历版本快照 |
| `status` | TEXT CHECK IN ('active','ready_to_finish','completed') | 会话状态 |
| `planned_count` | INTEGER NOT NULL DEFAULT 5 | 计划主问题数 |
| `asked_count` | INTEGER NOT NULL DEFAULT 0 | 已提问主问题数（含当前题） |
| `current_question_no` | INTEGER NOT NULL DEFAULT 0 | 当前主问题序号 |
| `followups_used` | INTEGER NOT NULL DEFAULT 0 | 当前主问题的追问次数 |
| `max_followups` | INTEGER NOT NULL DEFAULT 1 | 每题最多追问次数 |
| `report_json` | TEXT | 完成后的报告 JSON，用于幂等 |
| `created_at` | TEXT NOT NULL | ISO 时间 |
| `updated_at` | TEXT NOT NULL | ISO 时间 |
| `completed_at` | TEXT | 完成时间 |

索引：`(user_id, thread_id, updated_at DESC)`。

### 3.2 `interview_messages`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | TEXT PK | 消息 ID |
| `session_id` | TEXT NOT NULL | 外键 interview_sessions(id) ON DELETE CASCADE |
| `seq` | INTEGER NOT NULL | 会话内递增序号 |
| `role` | TEXT CHECK IN ('interviewer','candidate') | 说话方 |
| `kind` | TEXT CHECK IN ('question','followup','feedback','answer') | 消息类型 |
| `question_no` | INTEGER NOT NULL DEFAULT 0 | 关联主问题序号 |
| `content` | TEXT NOT NULL | 文本 |
| `score` | INTEGER | 反馈针对的回答分数（0-100） |
| `strengths_json` | TEXT NOT NULL DEFAULT '[]' | 反馈亮点 |
| `improvements_json` | TEXT NOT NULL DEFAULT '[]' | 反馈改进点 |
| `created_at` | TEXT NOT NULL | ISO 时间 |

索引：`(session_id, seq)`；唯一约束 `(session_id, seq)`。

### 3.3 迁移

- `backend/app/db/migrations.py`：`SCHEMA_VERSION = 3`，两张表与索引加入 `_CORE_DDL`（`CREATE TABLE IF NOT EXISTS`，天然幂等）。
- 既有库升级无需回填：新表为空即可，旧 `interview_reports` 反序列化时 `source` 默认 `offline`。

## 4. 后端接口契约

统一前缀 `/api`，全部 `Depends(get_current_user)`。返回体统一为 `{"session": ..., "messages": [...], "report": ... | null}`（列表接口为 `{"items": [...]}`）。

| 方法 | 路径 | 请求体 | 说明 |
| --- | --- | --- | --- |
| POST | `/interviews` | `{thread_id, job_id}` | 创建或复用未完成会话，返回首个问题 |
| GET | `/interviews/{session_id}` | — | 读取会话与全部消息 |
| GET | `/interviews?thread_id=` | — | 列出该 run 下当前用户的所有演练会话 |
| POST | `/interviews/{session_id}/answers` | `{answer}` | 提交回答，返回即时反馈与下一题或 `ready_to_finish` |
| POST | `/interviews/{session_id}/finish` | — | 生成终局报告并回填 run；幂等 |

字段约束：

- `answer` 去空后不得为空；长度上限 `interview_answer_max_chars`（默认 2000），超限 422。
- `thread_id`、`job_id` 必须存在且属于当前用户；跨用户一律 404，不泄露存在性。
- 仅当岗位画像成功且评审成功时允许创建（`job_profile.status == 'ok'` 且有当前 `review`），否则 422 `interview_job_not_ready`。

## 5. 会话流程与规则

### 5.1 创建

1. 校验 run 归属（`get_owned_run`）。
2. 通过 `graph.aget_state(thread_config(thread_id))` 读取 state，校验 `job_id` 在 `jobs` 中且画像/评审可用。
3. 若同一 `(user_id, thread_id, job_id)` 已有 `active` 或 `ready_to_finish` 会话，直接返回该会话（不调用模型）。
4. 快照 `goal / job_profile / resume_text（优先最新 variant）/ variant_version`；简历长度超过 `max_message_chars` 时用 `build_resume_digest` 压缩。
5. 调用 `interview_questioner` 生成第 1 题；校验非空后写库：`asked_count=1`、`current_question_no=1`、`followups_used=0`、`status='active'`。

### 5.2 提交回答

1. 会话必须 `active` 且最后一条是面试官问题/追问，否则 409。
2. 先在内存中构造 transcript（含本次回答），调用 1 次 `interview_questioner`，返回 `feedback/score/next_question/dimension/focus/is_followup/done`。
3. 模型成功后再一次性事务写入：候选人回答、面试官反馈、下一题（若有）。
4. 推进规则（系统强制，非模型自决）：
   - 主问题达 `planned_count`（5）且刚回答完最后一题 → 不再出题，`status='ready_to_finish'`。
   - 未达 5 题：若模型要求追问且 `followups_used < max_followups` → 记为 `followup`，`followups_used += 1`，题号不变；否则记为新主问题，`asked_count += 1`、`current_question_no += 1`、`followups_used = 0`。
   - 最后一题不再追问，保证 5 题必结束。
5. 模型失败或返回空题 → 502，不写库，用户可重试。

### 5.3 结束与报告

1. `finish` 在 `ready_to_finish`（正常完成）或 `active`（提前结束）时可用；`completed` 直接返回已存报告（幂等）。
2. 至少 1 条候选人回答，否则 422 `interview_no_answers`。
3. 调用 1 次 `interview_evaluator`，得到 `overall_score / dimension_averages / highlights / red_flags / improvements / requirement_gaps`；系统补充 `answered_count`、`planned_count`。
4. 报告 `status`：正常完成为 `completed`，提前结束为 `abandoned`；`source='practice'`，`session_id=会话 ID`，`interview_thread_id='practice-<session_id>'`。
5. 复用 `attach_interview_report` 写入 run 并刷新教练建议；写入成功后会话置 `completed` 并保存 `report_json`。报告持久化失败 → 502，会话保持原状态可重试。
6. 写入成功但教练建议刷新失败（返回 `written=true` 且带 `error`）→ 视为完成，报告已落库。

### 5.4 安全与预算

- 复用 `SAFETY_PREFIX` 与 `wrap_untrusted`，简历/JD/回答均作为不可信数据块注入 human 消息。
- Prompt 明确禁止就年龄、性别、婚育、健康、民族、宗教、政治面貌、籍贯提问或评分；出现则忽略。
- 单场模型调用上限：1（首题）+ 5（回答，含追问最多 4 次）+ 1（终评）= 7 次；用 `context.semaphore` 限并发，不新增限流器。
- 所有回答与消息内容入库前做长度裁剪。

## 6. Prompt 契约

### 6.1 `prompts/interview_questioner.md`

- 系统段：单题面试官，逐题提问，基于 `session_meta_json` 决定是否追问，最多一次；只输出一个 JSON。
- Human 模板占位符：`[[goal]]`、`[[profile_json]]`、`[[resume_text]]`、`[[session_meta_json]]`、`[[transcript_json]]`。
- 输出 JSON：`{"feedback":"", "score":null, "done":false, "next_question":"", "dimension":"", "focus":"", "is_followup":false}`。
- 约束：transcript 为空时输出第 1 题且 `feedback=""`、`score=null`；提问不得编造简历外事实。

### 6.2 `prompts/interview_evaluator.md`

- 系统段：终局评估者，只依据 transcript 与简历评分，不得虚高，不涉及敏感话题。
- Human 模板占位符：`[[goal]]`、`[[profile_json]]`、`[[resume_text]]`、`[[session_meta_json]]`、`[[transcript_json]]`。
- 输出 JSON：`{"overall_score":0, "dimension_averages":{}, "highlights":[], "red_flags":[], "improvements":[], "requirement_gaps":[]}`；不输出 `answered_count/planned_count`。

### 6.3 角色注册

- `backend/app/prompts/loader.py`：`ROLES` 追加两个角色；`UNTRUSTED_PLACEHOLDERS` 追加 `session_meta_json`、`transcript_json`。
- `backend/app/config/model_router.py`：`ROLES` 同步追加；`models.yaml` 不改，未配置时回落 `default`。

## 7. 前端交互

### 7.1 入口

- [JobCard.vue](file:///d:/python/Agent/career_assistant/frontend/src/components/JobCard.vue) 新增 `threadId` 属性与 `practice` 事件，在面试区块/岗位头提供「开始演练」按钮；失败岗位不显示。
- [RunResults.vue](file:///d:/python/Agent/career_assistant/frontend/src/components/RunResults.vue) 负责调用 `createInterviewSession`，成功后 `router.push({name:'interview', params:{sessionId}})`；按钮 loading 与错误提示就地展示。
- 报告来源标签：`practice` 显示「真人演练」，`offline` 显示「离线预评估」。

### 7.2 对话页 `/interviews/:sessionId`

- 顶部：岗位名、进度「第 x / 5 题」、状态徽章、返回该 run 的链接。
- 消息区：面试官问题（衬线、左侧、硬边卡片）；即时反馈（等宽小字 + 分数）；用户回答（右侧、暖纸底色）。
- 底部输入：多行文本、字数提示、提交按钮；请求中禁用并提示「面试官正在评估…」。
- `ready_to_finish`：显示「生成评估报告」主按钮；`completed`：展示报告卡（总分、亮点、风险、缺口、改进）与返回链接。
- 错误：复用 `ErrorNotice`，404 显示「会话不存在或已失效」。

### 7.3 文件

- 新增 `frontend/src/api/interviews.ts`、`frontend/src/composables/useInterviewSession.ts`、`frontend/src/views/InterviewView.vue`。
- `frontend/src/api/types.ts` 增补类型；`frontend/src/api/client.ts` 增补错误码文案；`frontend/src/router/index.ts` 增补路由（`requiresAuth: true`）。

## 8. 错误码

| 码 | 状态 | 场景 |
| --- | --- | --- |
| `interview_not_found` | 404 | 会话不存在或不属于当前用户 |
| `interview_job_not_ready` | 422 | 岗位画像/评审不可用 |
| `interview_closed` | 409 | 会话已完成或不可再作答 |
| `interview_waiting_question` | 409 | 最后一条不是面试官问题 |
| `interview_answer_blank` | 422 | 回答为空 |
| `interview_answer_too_long` | 422 | 回答超长 |
| `interview_generation_failed` | 502 | 提问/反馈模型失败 |
| `interview_no_answers` | 422 | 无任何回答就结束 |
| `interview_report_failed` | 502 | 终评或报告写入失败 |

## 9. 测试与验收

### 后端

- 新增 `backend/tests/test_interview_sessions.py`：
  1. 创建会话生成首题；回答推进到 `ready_to_finish`；追问命中上限后转为新主问题。
  2. 第 5 题答完自动停止出题；`finish` 生成 `source='practice'` 报告并写回 run，岗位卡可读。
  3. `finish` 幂等（第二次不重复调用模型、不重复写 state）。
  4. 空回答、超长回答 422；已完成会话答题 409。
  5. 跨用户访问 404；未知岗位 422；画像失败的 run 创建被拒。
  6. 终评模型失败返回 502，会话保持 `ready_to_finish` 可重试。
- 更新 `backend/tests/test_prompts.py` 的角色集合与数量断言（8 → 10）。
- 若 `test_db_migration.py` 断言 `SCHEMA_VERSION`，同步更新。
- 命令：`python -m pytest backend/tests -q`。

### 前端

- 新增 `frontend/tests/interview-session.test.ts`：composable 的加载、答题追加、结束、错误分支。
- 命令：`npm run typecheck`、`npm run test`、`npm run build`。

### 浏览器 E2E

- 登录测试账号 → 打开已完成 run → 岗位卡点「开始演练」→ 答 2–3 题（含一次追问）→ 提前结束 → 报告出现并标注「真人演练」→ 刷新页面状态保留。

## 10. 兼容与回滚

- 新表与新增字段均为增量，旧数据不受影响；`InterviewReportSummary.source/session_id` 有默认值。
- 回滚只需不挂载新路由、不展示入口，存量表与数据可保留。

## 11. 决策记录

- D1：采用独立会话，不改造主图；主图现有离线自评保留并标注 `offline`。
- D2：每题最多 1 次追问，仅前 4 题可追问，第 5 题答完即结束，保证确定性。
- D3：`finish` 显式调用，不自动生成报告，避免最后一答请求超长或部分失败。
- D4：同一岗位存在未完成会话时复用，避免重复创建与浪费模型调用。
