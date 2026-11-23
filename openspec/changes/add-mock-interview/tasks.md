## 1. 前置检查与配置

- [ ] 1.1 确认 `add-career-assistant-core` 已 apply：`AgentState`（含 `interview_reports`）、`thread_id` 语义、SQLite saver、`model-routing` 与 `attach_interview_report` 回写服务可用，否则中止本 change
- [ ] 1.2 在 `backend/app/config/models.yaml` 新增 `interviewer` 角色，并在需要时支持 `interview_evaluator`，未配置时回退全局默认模型
- [ ] 1.3 扩展角色白名单与启动校验，使 `interviewer` / `interview_evaluator` 与非空 `model`、`temperature` 区间校验一致
- [ ] 1.4 新增面试配置项并做启动校验：`question_mode`（`adaptive` / `fixed`）、`base_questions`（默认 4）、`per_must_have`（默认 1）、`project_bonus`（默认 2）、`min_questions`（默认 5）、`max_questions`（默认 12，硬上限）、`fixed_questions`（默认 8）、`max_followups`（默认 2）、`score_visibility`（`end_of_interview` / `immediate`）、`max_input_chars`、模型重试次数；非正数、非法枚举或 `min_questions > max_questions` 必须启动失败

## 2. 状态与契约定义

- [ ] 2.1 在 `backend/app/state.py` 定义独立 `InterviewState`：`job_id`、`resume_text`、`question_mode`、`base_questions`、`per_must_have`、`project_bonus`、`min_questions`、`max_questions`、`fixed_questions`、`target_questions`、`must_have_count`、`project_bonus_applied`、`max_followups`、`score_visibility`、`questions`、`answers`、`current_question`、`question_count`、`followup_depth`、`rolling_summary`、`recent_turns`、`scores`、`coverage`、`report`、`end_reason`、`writeback_status`、`status`、`errors`
- [ ] 2.2 定义题目结构：`question_id`、`question`、`category`（`deep_dive` / `boundary` / `behavior` / `job_fit`）、`source_evidence`、`target_requirement`、`followup_depth`，并约定至少一个依据字段非空
- [ ] 2.3 定义响应模型：创建响应（`thread_id` + 首题）、回答响应（下一题或 `finished` 标志 + 报告）、查询响应（状态、进度、报告），确保默认模式下进行中响应不含分数字段
- [ ] 2.4 定义状态版本号字段与配置快照，用于并发 resume 的乐观校验和"创建时配置固化"；创建时固化 `target_questions`、`must_have_count` 与 `project_bonus_applied`，后续改配置不影响已存在会话

## 3. 题目生成与过滤

- [ ] 3.1 实现 `prepare` 节点：载入简历文本、按 `job_id` 读取岗位画像快照、校验输入长度，输出确定性结果以支持重放
- [ ] 3.2 实现简历断言抽取：从项目、量化指标、技术栈、时间线、职责中提取可追问断言，并保留原文片段作为 `source_evidence`
- [ ] 3.3 实现 `plan_questions` 节点：结合断言与岗位要求生成候选题目，按 `deep_dive` / `boundary` / `behavior` / `job_fit` 分类，并输出题目依据
- [ ] 3.4 实现候选过滤：丢弃 `source_evidence` 与 `target_requirement` 均为空的题目、分类非法的题目，以及涉及年龄/婚育/健康/民族/宗教的敏感题目
- [ ] 3.5 实现"无可用候选"分支：不得生成兜底题，直接结束并生成带原因的说明报告
- [ ] 3.6 为题目生成与过滤编写单元测试：首题必有依据、无依据被丢弃、敏感题被拒绝、分类字段合法
- [ ] 3.7 实现动态题量计算：`target = clamp(base_questions + per_must_have × len(must_have) + project_bonus, min_questions, max_questions)`；`project_bonus` 仅在简历含项目断言且岗位要求涉及项目时生效；`must_have` 为空回退 `base_questions`；`question_mode=fixed` 使用 `fixed_questions`
- [ ] 3.8 实现题目分配：优先保证每条 `must_have` 至少被一道 `job_fit` 或 `deep_dive` 覆盖，剩余额度优先分配项目深挖；无法覆盖的要求写入 `coverage`，不生成无依据题目凑数
- [ ] 3.9 为动态题量补测试：2 条 vs 6 条 `must_have` 题量递增、项目背景加题、无项目不加题、上下限夹取、`must_have` 为空回退、`fixed` 模式、覆盖优先级与未覆盖项

## 4. interrupt 循环与幂等

- [ ] 4.1 实现 `ask_question` 节点：仅在存在合法待问题目时调用 `interrupt()`，payload 包含题面、分类、依据、题号与追问深度
- [ ] 4.2 实现 `accept_answer` 节点：校验回答长度与必填，按 `question_id` 幂等写入，重复提交只保留首次接受值
- [ ] 4.3 实现 `summarize` 节点：更新滚动摘要，`recent_turns` 只保留最近 3 轮，摘要持久化到 checkpoint
- [ ] 4.4 实现条件边：达到 `max_questions`、达到 `max_followups`、无可用题目或评分失败耗尽时进入 `report`，否则回到 `plan_questions`
- [ ] 4.5 实现状态版本号校验：并发或陈旧 resume 请求返回 409，且不推进面试、不产生重复记录
- [ ] 4.6 保证 `interrupt()` 之前全部节点幂等：以输入哈希复用已生成题目与断言，重放不增加 `question_count`、不重复写题目或回答
- [ ] 4.7 实现模型失败重试：生成或评分节点内有限重试（默认 2 次），耗尽后保留已答记录并保持会话可恢复
- [ ] 4.8 编写中断/恢复测试：逐题暂停、`Command(resume=answer)` 推进一轮、重复 resume 幂等、重放后计数不变

## 5. 评分与报告

- [ ] 5.1 实现 `evaluate` 节点：按事实准确性、技术深度、结构表达、岗位相关性四维评分（0–5），每维附理由
- [ ] 5.2 实现事实一致性校验：回答与 `source_evidence` 冲突或出现无法验证的夸张指标时扣减事实准确性并记录红旗
- [ ] 5.3 实现评分可见性：默认 `end_of_interview` 时进行中响应剥离分数；`immediate` 时在回答响应中返回该题四维得分
- [ ] 5.4 实现 `report` 节点：汇总逐题得分（每题恰好一次）、`highlights`、`red_flags`、`improvements`、`requirement_gaps`、`coverage`（已覆盖 / 未覆盖 `must_have` 及原因），并说明提前结束原因
- [ ] 5.5 `requirement_gaps` 每项必须关联具体岗位要求或岗位画像字段，并描述差距
- [ ] 5.6 编写评分与报告测试：报告字段完整、每题一条得分、默认模式不泄露分数、即时模式返回分数、提前结束仍有报告
- [ ] 5.7 实现中途放弃：仅 `immediate` 模式开放；当前待答题目标记为未作答，基于已答且已评分的题目生成 `end_reason=abandoned` 的部分报告，包含 `answered_count`、`planned_count`；默认模式返回 409 `abandon_not_allowed`
- [ ] 5.8 实现报告回写：报告生成（含放弃）后调用 core 的 `attach_interview_report(thread_id, job_id, summary)`，按 `interview_thread_id` 幂等；失败时保留报告并写 `writeback_status=failed`
- [ ] 5.9 编写放弃与回写测试：放弃只含已答题目、未答题不计分、重复放弃返回同一报告、放弃后拒绝继续作答、回写成功 / 重复幂等 / 失败可重试

## 6. 接口实现

- [ ] 6.1 实现 `POST /api/interviews`：校验 `job_id` 与简历文本（404/422 语义），创建独立 `thread_id`，返回首题
- [ ] 6.2 实现 `POST /api/interviews/{thread_id}/answers`：恢复图执行并返回下一题或报告；已结束会话返回 409
- [ ] 6.3 实现 `GET /api/interviews/{thread_id}`：返回状态、进度与报告；不存在的 `thread_id` 返回 404 且不创建会话
- [ ] 6.4 在路由层禁止业务判断，只做入参校验、`thread_id` 注入与 `Command(resume=...)` 转发
- [ ] 6.5 保证接口层不返回内部状态字段，响应结构可直接序列化
- [ ] 6.6 实现 `POST /api/interviews/{thread_id}/abandon`：仅 `immediate` 模式可放弃，返回部分报告与 `writeback_status`；默认模式返回 409，已结束会话返回 409
- [ ] 6.7 在报告生成路径统一触发回写并透传 `writeback_status`；回写失败不得改变面试响应状态码

## 7. 安全与合规

- [ ] 7.1 简历与岗位文本使用显式分隔符包裹，系统指令声明忽略其中任何指令
- [ ] 7.2 单段输入（简历、岗位文本、单次回答）超过 `max_input_chars` 时拒绝并返回明确错误，不静默截断
- [ ] 7.3 在生成、过滤、评分三处约束敏感话题，补充注入攻击与敏感问题的测试用例
- [ ] 7.4 结构化日志按 `thread_id` 记录节点、角色、模型、耗时与重试次数，不记录简历与回答原文

## 8. 端到端验证

- [ ] 8.1 用假模型跑通"创建 → 达到目标题数 → 报告"完整流程，断言报告字段、动态题量与硬上限
- [ ] 8.2 验证追问 2 层后停止追问并推进下一题
- [ ] 8.3 验证进程重启后按 `thread_id` 查询与恢复，已答题目与摘要不丢失
- [ ] 8.4 验证重复提交同一题不产生重复记录与重复计分
- [ ] 8.5 验证会话不存在返回 404、已结束会话提交返回 409
- [ ] 8.6 运行 `openspec validate add-mock-interview --strict` 并确认通过
- [ ] 8.7 验证动态题量：两个不同 `must_have` 数量的岗位题量不同且不超 `max_questions`；含项目背景时加题；`fixed` 模式题量固定
- [ ] 8.8 验证中途放弃：`immediate` 模式放弃生成部分报告且仅含已答题目；默认模式返回 409；重复放弃幂等
- [ ] 8.9 验证报告回写：面试结束后主运行 `GET /api/runs/{thread_id}` 返回 `interview_reports` 且 `advice` 引用面试表现；重复回写不重复刷新；回写失败时可重试
