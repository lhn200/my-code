# 任务清单：AI 模拟教练（多轮对话）

> 依据 `specs/ai-coach-chat/spec.md` 执行。每完成一项在汇报中引用任务编号。

## T1 迁移与数据访问层

- [x] `backend/app/db/migrations.py`：`SCHEMA_VERSION = 4`；`_CORE_DDL` 追加 `coach_sessions`、`coach_messages` 表、`ix_coach_sessions_user` 索引与 `ux_coach_messages_seq` 唯一索引。
- [x] 新建 `backend/app/db/coach.py`：
  - `new_session_id()`
  - `create_session(connection, *, session_id, user_id, thread_id, title)`
  - `get_session(connection, session_id)`
  - `list_sessions(connection, user_id, thread_id=None)`（含 `message_count`）
  - `update_session(connection, session_id, **fields)`（字段白名单 `title/thread_id/updated_at`）
  - `delete_session(connection, session_id)`（依赖外键级联；连接需开启外键或显式删消息）
  - `next_seq(connection, session_id)`
  - `append_message(connection, *, session_id, role, content)`
  - `list_messages(connection, session_id)`
  - `session_to_dict(row)`、`message_to_dict(row)`

## T2 Prompt 与模型注册

- [x] `backend/app/prompts/loader.py`：`ROLES` 追加 `coach_chat`；`UNTRUSTED_PLACEHOLDERS` 追加 `coach_context_json`、`user_message`。
- [x] `backend/app/config/model_router.py`：`ROLES` 追加 `coach_chat`。
- [x] `backend/app/config/models.yaml`：新增 `coach_chat`（qwen-plus, temperature 0.5）。
- [x] 新建 `backend/app/prompts/coach_chat.md`：系统段 + `--- HUMAN TEMPLATE ---`，human 段使用 `[[coach_context_json]]`、`[[user_message]]`。

## T3 服务层

- [x] 新建 `backend/app/services/coach_chat.py`：
  - `CoachError(status_code, code, message)`
  - `create_session(db_path, user_id, thread_id, title) -> dict`
  - `list_sessions(db_path, user_id, thread_id) -> list[dict]`
  - `get_session_payload(db_path, user_id, session_id) -> dict`
  - `update_session(db_path, user_id, session_id, *, title=None, thread_id=UNSET) -> dict`
  - `delete_session(db_path, user_id, session_id) -> None`
  - `send_message(graph, context, db_path, user_id, session_id, content) -> dict`
  - 私有：`_owned_session`、`_validate_thread`、`_build_context`、`_clip_resume`、`_history`
- [x] `_build_context` 读取 `graph.aget_state(thread_config(thread_id)).values`，用 `current_review`、`current_variant` 与 `interview_reports` 汇总；用 `retrieve_memories` 取记忆；任何读取异常降级为 `analysis: null`。
- [x] `send_message` 组装 `system + 历史 human/ai + human(上下文+最新消息)`，`call_text` 失败抛 502；成功后事务写入用户消息与教练回复，空标题用首条消息截 40 字。

## T4 接口层

- [x] `backend/app/api/schemas.py`：新增 `CoachSessionCreateRequest`、`CoachSessionUpdateRequest`、`CoachMessageRequest`（`extra="forbid"`，title/content 去空校验，title 长度上限）。
- [x] 新建 `backend/app/api/coach.py`：六个端点；`CoachError → ApiError` 翻译。
- [x] `backend/app/main.py`：`include_router(coach_router, prefix=settings.api_prefix)`。

## T5 前端数据层

- [x] `frontend/src/api/types.ts`：新增 `CoachMessageRole`、`CoachSession`、`CoachMessage`、`CoachSessionPayload`、`CoachSessionListResponse`。
- [x] 新建 `frontend/src/api/coach.ts`：`createCoachSession`、`listCoachSessions`、`getCoachSession`、`updateCoachSession`、`deleteCoachSession`、`sendCoachMessage`。
- [x] `frontend/src/api/client.ts`：`KNOWN_CODES` 增补 5 个 `coach_*` 文案。

## T6 前端页面与路由

- [x] 新建 `frontend/src/composables/useCoachChat.ts`：`sessions/active/messages/isLoading/isSending/error`；`loadSessions/select/create/rename/remove/send/apply`。
- [x] 新建 `frontend/src/views/CoachView.vue`：分析选择器、历史列表（新建/重命名/删除）、对话区（用户右侧、教练左侧）、「思考中」占位、输入区（Ctrl/Cmd+Enter）。
- [x] `frontend/src/router/index.ts`：新增 `/coach`（name `coach`，requiresAuth）。
- [x] `frontend/src/App.vue`：导航增加「AI 教练」。

## T7 测试

- [x] `backend/tests/fakes.py`：支持 `coach_chat` 文本 handler 与消息捕获。
- [x] 新增 `backend/tests/test_coach_chat.py`：覆盖 spec 第 9 节 7 组场景。
- [x] `backend/tests/test_prompts.py`：角色集合/数量 10 → 11。
- [x] `backend/tests/test_db_migration.py`：版本断言使用 `SCHEMA_VERSION` 常量，无需改动。
- [x] 新增 `frontend/tests/coach-chat.test.ts`：composable 新建/发送/失败/删除。
- [x] 运行 `python -m pytest backend/tests -q`、`npm run typecheck`、`npm run test`、`npm run build`。

## T8 本地运行与验收

- [x] 复用已在后台运行的 uvicorn（127.0.0.1:8000）与 Vite（5173），不重复启动；若未运行再启动。
- [x] 浏览器 E2E：登录 → AI 教练 → 选择分析 → 新建 → 发送 2 条 → 重命名 → 刷新 → 删除。
- [x] 汇报结果，不自动提交 Git。

## 验收标准

- [x] 教练多轮对话可用，刷新不丢消息；跨用户不可见。
- [x] 默认引用最近完成分析，可切换/解绑；绑定上下文包含岗位评分与面试报告摘要。
- [x] 会话可重命名、删除；删除返回 204。
- [x] 后端与前端测试、typecheck、build 全部通过。
