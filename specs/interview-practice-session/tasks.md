# 任务清单：AI 面试官实时演练会话

> 依据 `specs/interview-practice-session/spec.md` 执行。每完成一项在提交说明中引用任务编号。

## T1 配置与迁移

- [x] `backend/app/config/__init__.py`：新增
  - `interview_planned_count: int = Field(default=5, ge=1, le=10)`
  - `interview_followup_limit: int = Field(default=1, ge=0, le=3)`
  - `interview_answer_max_chars: int = Field(default=2000, ge=50)`
- [x] `backend/app/db/migrations.py`：`SCHEMA_VERSION = 3`；`_CORE_DDL` 增加 `interview_sessions`、`interview_messages` 及索引与唯一约束。
- [x] 检查 `backend/tests/test_db_migration.py` 是否断言版本号，必要时更新。

## T2 数据访问层

- [x] 新建 `backend/app/db/interviews.py`，提供：
  - `create_session(connection, ...)`
  - `get_session(connection, session_id)`
  - `find_open_session(connection, user_id, thread_id, job_id)`
  - `list_sessions(connection, user_id, thread_id)`
  - `update_session(connection, session_id, **fields)`（字段白名单）
  - `append_message(connection, session_id, role, kind, question_no, content, score=None, strengths=None, improvements=None)`
  - `list_messages(connection, session_id)`
- [x] JSON 字段统一 `json.dumps(ensure_ascii=False)` 存储，读取时容错解析。
- [x] `backend/app/db/__init__.py` 不强制导出，服务层直接 `from ..db.interviews import ...`。

## T3 Prompt 角色

- [x] `backend/app/prompts/loader.py`：`ROLES` 追加 `interview_questioner`、`interview_evaluator`；`UNTRUSTED_PLACEHOLDERS` 追加 `session_meta_json`、`transcript_json`。
- [x] `backend/app/config/model_router.py`：`ROLES` 同步追加。
- [x] 新建 `backend/app/prompts/interview_questioner.md`（系统段 + `--- HUMAN TEMPLATE ---`，占位符 `goal/profile_json/resume_text/session_meta_json/transcript_json`）。
- [x] 新建 `backend/app/prompts/interview_evaluator.md`（同占位符，输出终评 JSON）。

## T4 领域模型

- [x] `backend/app/state.py`：`InterviewReportSummary` 增加
  - `source: Literal["offline", "practice"] = "offline"`
  - `session_id: str = ""`
- [x] `backend/app/graph/nodes.py`：离线报告显式 `source="offline"`（行为不变）。

## T5 服务层

- [x] 新建 `backend/app/services/interview_sessions.py`：
  - `InterviewSessionError(status_code, code, message)`
  - `TurnOutput`、`EvaluationOutput`（Pydantic，`extra="ignore"`）
  - `create_session(graph, context, db_path, user_id, thread_id, job_id) -> dict`
  - `submit_answer(graph, context, db_path, user_id, session_id, answer) -> dict`
  - `finish_session(graph, context, db_path, user_id, session_id) -> dict`
  - `get_session_payload(db_path, user_id, session_id) -> dict`
  - `list_session_payloads(db_path, user_id, thread_id) -> list[dict]`
- [x] 归属校验：先按 session 查，再 `get_owned_run`；失败统一 `interview_not_found`。
- [x] 创建时读 `graph.aget_state(thread_config(thread_id))`，校验岗位与画像/评审可用，快照 goal/profile/resume/variant_version；简历超长用 `build_resume_digest`。
- [x] 复用未完成会话（`active`/`ready_to_finish`）。
- [x] 回答流程：模型成功后再事务写入回答 + 反馈 + 下一题；强制 5 题上限与每题 1 次追问；最后一题答完置 `ready_to_finish`。
- [x] 结束流程：调用 `attach_interview_report`；报告 `source='practice'`、`session_id`、`interview_thread_id='practice-<id>'`；成功保存 `report_json` 并置 `completed`；失败 502 且状态不变。
- [x] 列表返回统一 `{"session","messages","report"}` 结构。

## T6 接口层

- [x] `backend/app/api/schemas.py`：新增 `InterviewCreateRequest`、`InterviewAnswerRequest`（去空、必填）。
- [x] 新建 `backend/app/api/interviews.py`：`POST /interviews`、`GET /interviews/{id}`、`GET /interviews`、`POST /interviews/{id}/answers`、`POST /interviews/{id}/finish`。
- [x] `backend/app/main.py`：挂载 `interviews_router`。
- [x] 将 `InterviewSessionError` 转为 `ApiError`（或复用现有异常处理器模式）。

## T7 前端数据层

- [x] `frontend/src/api/types.ts`：新增 `InterviewSession`、`InterviewSessionMessage`、`InterviewSessionPayload`、`InterviewSessionListResponse`；`InterviewReportSummary` 增加 `source?`、`session_id?`。
- [x] 新建 `frontend/src/api/interviews.ts`：5 个请求函数。
- [x] `frontend/src/api/client.ts`：`KNOWN_CODES` 增补 spec 第 8 节错误码中文文案。

## T8 前端页面

- [x] 新建 `frontend/src/composables/useInterviewSession.ts`：`load/answer/finish/cancel`、`session/messages/report/isLoading/isSubmitting/error`。
- [x] 新建 `frontend/src/views/InterviewView.vue`：
  - 顶部岗位名、进度、状态、返回 run 链接
  - 消息列表（问题/反馈/回答三态样式）
  - 输入区与字数提示、提交中禁用
  - `ready_to_finish` 生成报告按钮；`completed` 报告卡
  - `ErrorNotice` 与 404 空状态
- [x] `frontend/src/router/index.ts`：新增 `/interviews/:sessionId`（`requiresAuth: true`）。

## T9 结果页入口

- [x] `JobCard.vue`：新增 `threadId` 属性与 `practice` 事件；非失败岗位显示「开始演练」；报告来源标签「真人演练 / 离线预评估」。
- [x] `RunResults.vue`：承接 `practice` 事件，调用 `createInterviewSession` 并跳转；按钮 loading/错误就地提示。

## T10 测试

- [x] 新增 `backend/tests/test_interview_sessions.py`（覆盖 spec 第 9 节 6 组场景），在 `tests/fakes.py` 增加 `interview_questioner` / `interview_evaluator` 可配置 handler。
- [x] 更新 `backend/tests/test_prompts.py`：角色集合与数量 8 → 10。
- [x] 新增 `frontend/tests/interview-session.test.ts`（composable 关键状态与错误分支）。
- [x] 运行 `python -m pytest backend/tests -q`。
- [x] 运行 `npm run typecheck`、`npm run test`、`npm run build`。

## T11 浏览器验收

- [x] 登录 `e2e-20261123@example.com / CareerE2E-2026!`。
- [x] 打开已完成 run → 岗位卡「开始演练」→ 答 2–3 题（触发一次追问）→ 结束 → 报告显示「真人演练」。
- [x] 刷新对话页与结果页确认状态持久化；截图核对。
- [x] 汇报结果，等待用户指示后再提交 Gitee。

## 验收标准

- [x] 5 题 + 每题至多 1 次追问，流程确定可复现。
- [x] 刷新不丢消息；跨用户不可见。
- [x] 报告可区分 `offline` / `practice`，并刷新岗位卡与教练建议。
- [x] 全部后端与前端测试、typecheck、build 通过。
