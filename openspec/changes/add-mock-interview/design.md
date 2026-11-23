## Context

`add-career-assistant-core` 已建立主分析图、`AgentState`、`thread_id` 语义、SQLite checkpointer、角色级模型配置与"不可信输入"处理约定。本 change 在其上新增模拟面试：一个需要多轮暂停等待用户回答的独立子图。面试与主图的核心差异是运行形态——主图一次运行跑到终止，面试必须在每道题处中断并在用户提交回答后恢复——因此设计重点是"中断语义 + 幂等 + 会话上下文成本"，而不是重新设计状态契约。

约束：沿用 Python 3.13、LangGraph、`langchain-openai`、FastAPI、SQLite；单机部署；不新增第三方依赖；不修改主图结构。

## Goals / Non-Goals

**Goals:**
- 用 LangGraph 原生 `interrupt()` / `Command(resume=...)` 实现逐题暂停与恢复，复用 SQLite checkpoint。
- 每道题都有可追溯依据（`source_evidence` 或 `target_requirement`），杜绝编造。
- 题量按岗位画像的 `must_have` 数量动态计算，并对项目背景加权；追问层数、题量上限、评分展示时机均可配置，且上限是硬约束。
- 即时评分模式支持中途放弃，并基于已答且已评分的题目生成部分报告。
- 报告摘要回写主分析结果，使求职教练的建议可引用面试表现。
- 会话上下文成本可控：滚动摘要 + 最近 3 轮，不随题数线性膨胀。
- 面试与主图边界清晰：独立 thread、独立状态、通过 `job_id` 单向关联。

**Non-Goals:**
- 不做语音/视频面试、实时打断、多人面试。
- 不做题库管理后台与人工审核流程。
- 不做前端页面；接口契约供前端 change 消费。
- 不做跨会话的候选人能力画像与历史对比。
- 不改动主分析图的节点、边与终止条件。

## Architecture Assessment

### Existing Design Reuse

- 复用 `thread_id` 语义与 `AsyncSqliteSaver`：面试 thread 与主图 thread 写入同一个 checkpoint 库，靠不同 `thread_id` 命名空间隔离，不新增会话表。
- 复用 `model-routing`：新增 `interviewer` 角色，沿用 YAML + 环境变量覆盖 + 启动校验机制；`interviewer` 用强模型，评分可复用同一角色或独立 `interview_evaluator` 角色（见 Decisions）。
- 复用"不可信输入"约定：简历与 JD 用分隔符包裹，系统指令声明忽略其中指令，限制单段长度。
- 复用错误语义：会话不存在 404、入参非法 422，与既有运行接口一致。
- 复用测试模式：假 chat model + 内存/SQLite saver 跑完整图，断言中断点与恢复行为。

不嵌入主图的理由见 Boundaries。

### Boundaries and Ownership

```
POST /api/interviews ─┐
POST .../answers ─────┼─ FastAPI（校验、注入 thread_id、转发 Command）
POST .../abandon ─────┤
GET  .../{thread_id} ─┘
        ↓
面试子图（独立 StateGraph，独立 thread）
  ├─ prepare       载入简历 / 岗位画像 / 配置，抽取可追问断言（幂等）
  ├─ plan_questions 生成候选题目并过滤（幂等，纯函数 + 缓存）
  ├─ ask_question   interrupt(question)  ← 暂停点
  ├─ accept_answer  校验、去重、写入回答（幂等键：question_id）
  ├─ summarize      更新滚动摘要
  ├─ evaluate       四维评分（可在配置下即时回传）
  └─ report         汇总逐题得分 / 亮点 / 红旗 / 建议 / gap
        ↓
SQLite checkpointer（面试 thread 独享状态）
```

- 状态所有权：面试状态（`InterviewState`）与主图 `AgentState` 并列定义，不互相引用可变字段；面试只读岗位画像快照。唯一例外是报告生成后通过 core 的 `attach_interview_report` 服务写入 `interview_reports[job_id]` 摘要并触发建议刷新，不改写主图的岗位、评审、简历变体与回流结果。
- 路由所有权：面试子图内部用固定顺序边推进（prepare → plan → ask → accept → summarize → evaluate → 条件边回 plan 或去 report），不存在第二套 Supervisor。
- 暂停所有权：只在 `ask_question` 内调用 `interrupt()`，一次只抛一道题；其余节点不得中断。
- 幂等所有权：所有 `interrupt()` 之前的节点必须是"相同输入 → 相同输出 + 不重复写"的幂等实现；`accept_answer` 以 `question_id` 作为幂等键。
- 失败边界：题目生成或评分失败在节点内有限重试（默认 2 次）；耗尽后保留已答题记录，会话保持可恢复，不删除 checkpoint。
- 并发：同一 `thread_id` 的回答请求串行处理（乐观锁 / 版本号校验），避免并发 resume 产生重复记录。

### Options and Rationale

| 决策点 | 选择 | 替代方案 | 理由 |
| --- | --- | --- | --- |
| 会话载体 | 独立子图 + 独立 `thread_id` | 并入主分析图、共用 thread | 主图一次运行到终止且回流有硬上限；面试需要多次暂停等待人工输入，共 thread 会污染主图状态与终止语义，也无法独立重开面试 |
| 暂停机制 | `interrupt()` + `Command(resume=answer)` | 自建会话表 + 轮询状态机 | LangGraph 原生中断与 checkpoint 天然集成，恢复点精确到节点；自建状态机会复制调度与持久化逻辑 |
| 题目生成 | 自适应逐题生成（范围内追问） | 一次性生成全部题目再逐题提问 | 一次性生成无法根据回答质量决定追问，失去"模拟面试"核心价值；代价是每轮一次模型调用，用滚动摘要控制成本 |
| 追问实现 | 同一主问题下 `followup_depth` 计数 | 追问当作新主问题 | 追问计入总题数会挤占覆盖面，无法表达"深挖上限"；独立计数才能同时约束题量与深度 |
| 评分时机 | 默认结束统一评分，可配置即时 | 一律即时评分 | 即时评分会让后续回答策略被分数引导，偏离真实面试；但部分用户需要即时反馈，故做成配置 |
| 评分与生成 | 生成与评分分离的两个节点/角色 | 同一提示词一次完成"出题 + 评分" | 分离后 rubric 可独立回归，且生成节点不需要拿到分数历史，降低上下文与提示耦合 |
| 上下文 | 滚动摘要 + 最近 3 轮 | 全量 transcript | 全量随题数增长，成本和延迟不可控；3 轮足够支撑追问连贯性，摘要保留更早结论 |
| 模型选择 | `interviewer` 用强模型 | 复用教练轻模型 | 追问质量与评分一致性直接决定产品价值，值得成本 |
| 状态 | 独立 `InterviewState` | 复用 `AgentState` | 字段语义不同（题目/回答/评分 vs 岗位/评审/回流），复用会造成大量空字段与契约歧义 |
| 题量策略 | 按 `must_have` 数量动态计算，受硬上限约束 | 固定题数 | 硬性要求多的岗位需要更大覆盖面，固定 8 题会漏掉关键要求；动态计算保持成本可控，`fixed` 模式仍保留 |
| 项目追问 | 简历含项目断言且岗位要求涉及项目时追加额度 | 所有岗位统一加题 | 只在有项目背景可问时加题，避免对无项目候选人凑题或编造项目 |
| 中途结束 | `immediate` 模式提供 `abandon` 接口 | 只能正常结束 | 即时模式每题已评分，可用已答题目零成本拼装部分报告；默认模式没有逐题评分，放弃会产生无评分报告，故拒绝 |
| 报告去向 | 摘要回写主运行并刷新建议 | 保持单向、只存面试 thread | 用户需要教练引用面试表现；只回写摘要避免主 checkpoint 膨胀，完整报告仍留在面试 thread |

### Quality Attributes

- 安全：敏感信息（年龄、婚育、健康、民族、宗教）列入禁止清单，在候选题目过滤阶段剔除；简历与 JD 用分隔符包裹并声明"忽略其中指令"；单段输入长度上限；不记录简历原文到日志。
- 可靠性：`interrupt()` 前节点幂等，重放不产生重复记录；回答写入以 `question_id` 去重；模型失败重试且保留已有记录；并发 resume 用版本号拒绝陈旧请求。
- 成本：题量按 `must_have` 动态计算且受 `max_questions`（默认 12）硬上限、追问 2 层约束；上下文只含摘要与最近 3 轮，并按岗位规模估算最坏调用次数。
- 可观测性：按 `thread_id` 串联结构化日志，记录题号、节点、角色、模型、耗时、重试次数与是否命中上限；不记录回答原文的完整文本。
- 可测试性：题目生成、过滤、评分均为纯函数或可注入假模型；中断与恢复可用 SQLite saver 离线断言。

### Complexity and Exceptions

- 新增第二个编译图与独立状态定义，属于必要抽象：运行形态不同，无法复用主图。
- 新增 `interviewer` 角色配置项，不新增依赖、不新增存储引擎，checkpoint 数据共存但 thread 隔离。
- 回滚：移除面试路由与子图注册即可，残留的面试 thread checkpoint 不影响主图；无需数据迁移。

## Decisions

1. **独立 thread 与独立子图**：`POST /api/interviews` 每次创建新 `thread_id`（支持调用方自定义），面试状态与主图状态完全分离，只通过 `job_id` 读取岗位画像快照。这样面试可以独立重开、独立取消、独立清理，不破坏主图验收标准。
2. **中断点唯一**：只有 `ask_question` 调用 `interrupt()`，payload 包含 `question_id`、题面、分类、`source_evidence` / `target_requirement`、题号与追问深度。调用方恢复时用 `Command(resume={"answer": ...})`。
3. **幂等实现**：`prepare` / `plan_questions` 通过"输入哈希 + 已存在结果则复用"保证重放不重复生成；`ask_question` 之前不写任何计数型状态；`accept_answer` 以 `question_id` 为幂等键，重复回答只保留首次接受值，并返回当前真实状态。
4. **上限语义**：`max_questions`（默认 8）计主问题；`max_followups`（默认 2）计单题追问层级。任一达到即走条件边进入 `report`。上限配置在创建会话时固化进状态，后续改配置不影响已存在会话。
5. **题目依据约束落在生成之后的过滤层**：生成节点允许产出候选，过滤节点强制校验 `source_evidence` 非空或 `target_requirement` 非空、分类合法、不含敏感主题；全部候选被过滤时不生成兜底题，直接结束并生成说明原因的报告。
6. **评分 rubric 固定四维**：事实准确性、技术深度、结构表达、岗位相关性，各维度 0–5 分并附理由；事实准确性必须引用回答片段与 `source_evidence` 对照。`score_visibility` 配置为 `end_of_interview`（默认）或 `immediate`。
7. **滚动摘要**：每轮回答后更新摘要，摘要覆盖"已考察主题、候选人表现要点、待验证假设"，最近 3 轮保留原文；上下文组装函数只输出摘要 + 最近 3 轮，避免全量 transcript。
8. **评分与出题分离**：出题节点只读摘要 + 最近 3 轮 + 岗位要求 + 简历断言；评分节点独立读取具体问答对。这样出题不会因分数历史产生偏差，评分提示可单独迭代。
9. **模型角色**：`interviewer` 承担出题与追问，配置强模型；评分默认复用 `interviewer`，也可配置 `interview_evaluator` 独立模型。未配置时回退全局默认模型，沿用既有启动校验。
10. **接口语义**：创建返回 201 + `thread_id` + 首题；提交回答返回下一题或报告；查询返回进度与（默认模式下的）无分数状态；会话不存在 404；已结束会话再提交回答返回 409。
11. **动态题量**：目标题数由岗位画像的 `must_have` 数量推导：`target = clamp(base_questions + per_must_have × len(must_have) + project_bonus, min_questions, max_questions)`；默认 `base_questions=4`、`per_must_have=1`、`min_questions=5`、`max_questions=12`。`project_bonus` 默认 2，仅当简历抽取到项目断言且岗位 `must_have` / `responsibilities` 提到项目时生效。题目分配优先让每条 `must_have` 至少被一道 `job_fit` 或 `deep_dive` 覆盖，剩余额度优先用于项目深挖；`must_have` 为空时回退 `base_questions`，超额要求不生成无依据题目，而是在报告 `coverage` 中标注未覆盖项。保留 `question_mode=fixed` 与 `fixed_questions`（默认 8）作为回退配置。`max_questions` 始终是硬上限，`max_followups` 仍按层单独计数。
12. **即时评分模式允许中途放弃**：仅当 `score_visibility=immediate` 时开放 `POST /api/interviews/{thread_id}/abandon`。放弃时把当前待答题目标记为未作答（不计分、不写入回答），直接由已答且已评分的题目生成报告，`end_reason=abandoned`，报告包含 `answered_count`、`planned_count` 与已覆盖 / 未覆盖要求。默认 `end_of_interview` 模式下该接口返回 409 `abandon_not_allowed`，避免产生未经评分的报告。放弃请求幂等：重复调用返回同一报告；已结束会话返回 409。
13. **报告回写主分析结果**：报告生成（含放弃）后调用 core 的 `attach_interview_report(thread_id, job_id, summary)`，把摘要写入主运行 `interview_reports[job_id]` 并触发 `advice` 刷新；回写按 `interview_thread_id` 幂等。回写失败不回滚面试，响应带 `writeback_status`（`success` / `failed` / `skipped`），下一次 `GET /api/interviews/{thread_id}` 继续幂等重试。

## Risks / Trade-offs

- [重放导致重复记录] → 所有 `interrupt()` 前节点幂等，`accept_answer` 以 `question_id` 去重，并用集成测试模拟恢复重放。
- [并发 resume 同一 thread] → 状态版本号校验，陈旧请求返回 409，避免重复计分。
- [自适应生成导致成本波动] → 题量与追问硬上限，上下文只保留摘要 + 3 轮；`interviewer` 单次调用设置超时。
- [延迟评分让用户中途无反馈] → 提供 `immediate` 配置与"进度/已答反馈"字段，不泄露分数但展示进度。
- [摘要丢失关键事实] → 摘要模板要求保留待验证假设与已提及指标；最近 3 轮原文兜底；单题评分始终基于原文回答。
- [敏感问题漏过滤] → 禁止清单 + 分类过滤 + 提示词三处约束，测试用例覆盖典型敏感主题。
- [提前结束让用户感觉未完成] → 报告中显式说明结束原因与已覆盖/未覆盖范围。
- [checkpoint 中存储简历片段] → 在既有本地单机、无鉴权前提下接受；后续账号 change 再评估脱敏。
- [`must_have` 过多导致题量膨胀或覆盖不足] → 动态题量受 `max_questions` 硬上限；超出覆盖范围的要求在报告 `coverage` 中列出，不通过编造题目凑数。
- [中途放弃产生口径不一致的评分] → 仅 `immediate` 模式开放，报告只汇总已评分题目，并显式标注已答 / 计划题数、结束原因与未覆盖要求。
- [回写失败导致教练看不到面试表现] → 回写幂等且可重试，面试报告始终返回并带 `writeback_status`；失败时保留旧 `advice` 与主分析结果。

## Migration Plan

N/A（新增能力，无历史数据）。首次创建面试时按既有机制初始化 SQLite 表；`InterviewState` 字段只增不改，并为配置快照保留版本字段。回滚：移除面试路由与子图注册，删除对应 thread 的 checkpoint 行即可，不影响主分析图。

## Open Questions

- 已决策：按岗位画像的 `must_have` 数量动态调整总题数，并对项目背景加权，同时保留 `fixed` 模式与硬上限。
- 已决策：`immediate` 评分模式允许中途放弃，并基于已答且已评分的题目生成部分报告。
- 已决策：面试报告摘要回写主分析结果，并刷新求职建议供求职教练引用；完整报告仍留在面试 thread。
