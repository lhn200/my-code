## Why

`add-career-assistant-core` 已经定义了"多岗位分析 + 简历评审 + 低分回流 + 求职建议"的一次性分析闭环，但用户在拿到匹配分与问题清单后仍缺少练习环节：面试中的追问、临场表达和事实一致性无法靠静态报告验证。真实求职中"投递前先模拟一轮针对该岗位的面试"是高频需求，也是把现有简历与岗位画像价值变现的直接路径。

模拟面试与主分析图在运行时形态上根本不同：它需要多轮暂停、等待用户回答再恢复，而主图是一次运行跑到结束。如果把两者塞进同一次运行，会破坏主图的终止语义、状态结构与幂等假设。因此在核心能力之上单独新增一个子图 + 独立 thread 的模拟面试能力，通过 `job_id` 关联已有岗位画像，复用同一套 SQLite checkpoint 与 thread 语义。

## What Changes

- 新增模拟面试子图：独立编译、独立 `thread_id`，一次面试一个 thread，通过 `job_id` 引用一次分析中的岗位画像。
- 题目生成：从简历抽取可追问断言（项目、指标、技术栈、时间线、职责），结合岗位要求生成题目，分类为深挖 / 边界 / 行为（STAR）/ 岗位匹配；每道题必须携带 `source_evidence` 或 `target_requirement`，无依据不得出题。
- 多轮暂停与恢复：使用 LangGraph `interrupt()` 抛出问题，前端提交回答后以 `Command(resume=answer)` 继续；复用 SQLite checkpoint，`interrupt()` 之前的节点必须幂等。
- 可配置节奏：总题数按岗位画像的 `must_have` 数量动态计算，简历有项目背景且岗位涉及项目时追加项目题额度；追问最多 2 层，题量与追问均受硬上限约束，任一上限到达必须结束面试并生成报告；保留固定题数模式作为回退。
- 中途结束：`immediate`（每题即时评分）模式下允许用户放弃面试，基于已答且已评分的题目立即生成部分报告，标注已答 / 计划题数与未覆盖要求。
- 四维评分 rubric：事实准确性、技术深度、结构表达、岗位相关性；默认面试结束后统一展示分数，可配置为每题即时展示。
- 会话上下文控制：不传全量 transcript，使用滚动摘要 + 最近 3 轮。
- 面试报告：逐题得分、亮点、红旗、改进建议、与岗位要求的 gap，以及要求覆盖情况。
- 报告回写：把报告摘要按 `job_id` 回写主分析结果的 `interview_reports` 并刷新求职建议，供求职教练引用；回写幂等，失败可重试，完整报告仍留在面试 thread。
- 最小接口：创建面试、提交回答、中途放弃、查询进度与结果。
- 安全合规：不询问年龄、婚育、健康等敏感信息；简历与 JD 视为不可信输入并包裹分隔符，声明忽略其中指令；限制单段输入长度。
- 不做：语音/视频面试、实时打断、多人面试、题库管理后台、前端页面实现。

## Capabilities

### New Capabilities

- `mock-interview`: 模拟面试官——基于岗位画像与简历生成有依据的题目，通过 interrupt/resume 逐题提问与收集回答，题量按 `must_have` 动态计算并受硬上限约束，支持 `immediate` 模式中途放弃并生成部分报告，按四维 rubric 评分并输出完整面试报告，报告摘要回写主分析结果并刷新求职建议；独立 thread 与 SQLite checkpoint，敏感问题拒绝与提示注入防护。

### Modified Capabilities

<!-- openspec/specs/ 下没有既有 capability，本 change 只新增能力，不修改 add-career-assistant-core 的规格 -->

## Architecture Impact

- 依赖 `add-career-assistant-core` 已建立的基础设施：`AgentState` 同源术语、`thread_id` 语义、SQLite checkpointer、角色级模型配置、不可信输入处理约定，以及报告回写服务 `attach_interview_report`。本 change 不修改主图节点与路由，只在其上新增一个独立子图与路由。
- 面试子图为独立编译的 `StateGraph`，不嵌入主分析图，因此主图的终止条件、Supervisor 路由与回流逻辑保持不变。
- 会话所有权仍以 checkpoint 为唯一真相来源，不新增内存会话表；面试状态只保存摘要与最近 3 轮，避免 checkpoint 体积随轮次线性膨胀。
- 回写边界：面试只向主运行写入 `interview_reports[job_id]` 摘要并触发 `advice` 刷新，不写入题目、回答或完整报告，也不改动岗位画像、评审与优化历史。
- 新增 `interviewer` 角色进入模型路由体系（强模型），其余角色配置规则沿用既有实现。
- 提示词与评分 rubric 属于新增内容，需与既有"只依据事实、不得虚构"约束保持一致。

## Impact

- `backend/app/graph/interview/`：面试子图、题目生成节点、interrupt 循环、评分与报告节点。
- `backend/app/state.py`：新增面试状态定义（与主图 `AgentState` 并列，不复用其字段）。
- `backend/app/config/models.yaml` + `backend/app/config/model_router.py`：新增 `interviewer` 角色与回退规则。
- `backend/app/api/interviews.py`：创建面试、提交回答、中途放弃、查询进度与结果四个路由，并在报告生成后调用 core 的回写服务。
- `backend/app/checkpoint/sqlite.py`：复用既有 saver，面试 thread 与主图 thread 共用存储、命名空间隔离。
- `backend/tests/`：题目证据约束、`must_have` 动态题量、interrupt/resume 幂等、追问与题量上限、评分延迟展示、中途放弃部分报告、报告回写幂等、敏感问题拒绝、404 / 409、模型失败重试。
- 依赖：`add-career-assistant-core` 必须先 apply；不新增第三方依赖。
