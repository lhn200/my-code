## ADDED Requirements

### Requirement: 独立面试会话

系统 SHALL 支持创建一次模拟面试会话。每次面试 MUST 绑定独立的 `thread_id`，并通过 `job_id` 关联 `add-career-assistant-core` 中一次分析的岗位画像；面试会话不得复用主分析图的 `thread_id`，也不得修改主分析图的状态。

#### Scenario: 创建面试返回 thread_id 与首题

- **WHEN** 调用方针对一个已存在的 `job_id` 创建面试
- **THEN** 系统 MUST 返回新建的 `thread_id` 与第一道题目
- **AND** 第一道题目 MUST 包含题面、题目分类与来源依据
- **AND** 该 `thread_id` MUST 独立于主分析图的 `thread_id`

#### Scenario: 岗位画像不存在

- **WHEN** 调用方传入的 `job_id` 在可访问的岗位画像中不存在
- **THEN** 系统 MUST 拒绝创建并返回可定位的错误
- **AND** 不得创建面试 checkpoint

#### Scenario: 会话隔离

- **WHEN** 两个面试 `thread_id` 并行进行
- **THEN** 各自的题目、回答与得分 MUST 互不混入
- **AND** 任一方的失败 MUST 不影响另一方

### Requirement: 题目来源约束

每道题目 MUST 携带 `source_evidence`（简历原文片段）或 `target_requirement`（岗位要求）作为依据。系统 MUST NOT 生成没有任何依据的题目；不得为了凑满题数而编造事实。

#### Scenario: 首题携带来源依据

- **WHEN** 面试会话生成第一道题
- **THEN** 题目 MUST 至少包含 `source_evidence` 或 `target_requirement` 之一
- **AND** `source_evidence` 非空时 MUST 为简历中的原文片段，不得改写为无出处的概括

#### Scenario: 无依据不得出题

- **WHEN** 候选题目既无法关联简历片段，也无法关联岗位要求
- **THEN** 系统 MUST 丢弃该候选题目
- **AND** 不得以这题目继续提问

#### Scenario: 可追问断言提取

- **WHEN** 简历包含项目、量化指标、技术栈、时间线或职责描述
- **THEN** 系统 MUST 从这些内容中抽取可追问断言作为深挖题候选
- **AND** 每条候选断言 MUST 保留其在简历中的原文位置或片段

#### Scenario: 简历无可追问内容

- **WHEN** 简历与岗位要求都无法产生任何有依据的题目
- **THEN** 系统 MUST 结束面试并返回说明原因的报告
- **AND** 不得生成无依据的兜底题目

### Requirement: 题目分类

面试题目 SHALL 分类为 `deep_dive`（深挖）、`boundary`（边界）、`behavior`（行为，STAR）、`job_fit`（岗位匹配）四类，并在响应中显式标注。

#### Scenario: 分类字段必填

- **WHEN** 系统返回任意一道题目
- **THEN** 响应 MUST 包含该题目的分类，且取值属于上述四类之一

#### Scenario: 行为题要求 STAR

- **WHEN** 题目分类为 `behavior`
- **THEN** 题面 MUST 引导回答者按情境、任务、行动、结果组织回答
- **AND** 评分 MUST 按结构化表达考察 STAR 完整性

### Requirement: 逐题暂停与恢复

面试子图 SHALL 使用 LangGraph `interrupt()` 在每道题抛出时暂停，等待调用方提交回答后以 `Command(resume=answer)` 恢复。一次恢复 MUST 只推进一轮，并返回下一道题目或最终报告。`interrupt()` 之前的节点 MUST 幂等，恢复重放时不得重复计数、重复选题或重复写入记录。

#### Scenario: 提交回答后返回下一题

- **WHEN** 会话处于等待回答状态且调用方提交当前题目的回答
- **THEN** 系统 MUST 恢复该 `thread_id` 对应的图执行
- **AND** 响应 MUST 返回下一道题目或面试报告
- **AND** 当前回答 MUST 被持久化到该会话记录中

#### Scenario: 未回答时查询保持等待

- **WHEN** 调用方查询一个已暂停但尚未提交回答的会话
- **THEN** 响应 MUST 返回当前待回答的题目与面试进度
- **AND** 系统 MUST NOT 因查询而推进面试

#### Scenario: 重复 resume 幂等

- **WHEN** 调用方对同一题重复提交相同或不同回答
- **THEN** 系统 MUST 只保留第一次被接受的回答为有效记录
- **AND** 不得产生重复的题目记录、重复的得分条目或重复的轮次计数
- **AND** 响应 MUST 返回当前会话的真实状态，而不是重新执行整轮面试

#### Scenario: 重放不重复副作用

- **WHEN** checkpoint 恢复导致 `interrupt()` 之前的节点被重新执行
- **THEN** 题号、已答题数与已生成题目 MUST 保持与重放前一致
- **AND** MUST NOT 重复写入题目或回答记录

#### Scenario: 面试已结束仍提交回答

- **WHEN** 对已生成报告的会话提交回答
- **THEN** 系统 MUST 拒绝该请求并说明面试已结束
- **AND** 已生成的报告 MUST 保持不变

### Requirement: 动态题量与追问上限

面试的目标题数 SHALL 按岗位画像的 `must_have` 数量动态计算：`target = clamp(base_questions + per_must_have × len(must_have) + project_bonus, min_questions, max_questions)`，其中 `project_bonus` 仅在简历抽取到项目断言且岗位要求涉及项目时生效。`max_questions` MUST 是硬上限，单题追问最多 2 层。任一上限达到时 MUST 结束面试并生成报告，不得继续提问。

#### Scenario: must_have 数量影响题量

- **WHEN** 同一份简历分别面试一个含 2 条 `must_have` 的岗位与一个含 6 条 `must_have` 的岗位
- **THEN** 后者的目标题数 MUST 大于前者
- **AND** 两者都 MUST NOT 超过 `max_questions`

#### Scenario: 项目背景加权

- **WHEN** 简历包含项目断言，且岗位 `must_have` 或 `responsibilities` 提到项目经验
- **THEN** 目标题数 MUST 追加 `project_bonus` 额度用于项目深挖
- **AND** 追加后 MUST NOT 超过 `max_questions`

#### Scenario: 无项目背景不加题

- **WHEN** 简历没有任何项目描述，或岗位要求与项目无关
- **THEN** 系统 MUST NOT 应用 `project_bonus`
- **AND** MUST NOT 编造项目背景出题

#### Scenario: 上下限夹取

- **WHEN** 计算结果小于 `min_questions` 或大于 `max_questions`
- **THEN** 目标题数 MUST 分别取 `min_questions` 与 `max_questions`
- **AND** 不得突破硬上限

#### Scenario: must_have 为空

- **WHEN** 岗位画像的 `must_have` 为空
- **THEN** 目标题数 MUST 回退到 `base_questions`
- **AND** 不得因此拒绝创建面试

#### Scenario: 要求覆盖优先级

- **WHEN** `must_have` 数量不超过目标题数
- **THEN** 每条 `must_have` MUST 至少被一道 `job_fit` 或 `deep_dive` 题目覆盖
- **AND** 剩余额度 MUST 优先分配给项目深挖

#### Scenario: 要求超出题量

- **WHEN** `must_have` 数量超过目标题数允许覆盖的范围
- **THEN** 系统 MUST 在报告的覆盖信息中列出未覆盖的要求
- **AND** MUST NOT 生成无依据题目来凑数

#### Scenario: 固定题量模式

- **WHEN** 配置为 `question_mode=fixed`
- **THEN** 目标题数 MUST 使用 `fixed_questions`
- **AND** 追问上限与硬上限仍然生效

#### Scenario: 达到总题数上限

- **WHEN** 已提出的题目数量达到目标题数
- **THEN** 系统 MUST 停止生成新题目
- **AND** MUST 返回完整的面试报告

#### Scenario: 达到追问层数上限

- **WHEN** 当前题目的追问层数达到配置的上限
- **THEN** 系统 MUST 停止对该题继续追问
- **AND** MUST 进入下一道主问题或结束面试

#### Scenario: 配置生效

- **WHEN** 配置修改了题量参数或追问上限
- **THEN** 新创建的面试 MUST 按新的参数计算与执行
- **AND** 已存在的会话 MUST 沿用创建时的配置快照

#### Scenario: 上限配置非法

- **WHEN** 题量参数或追问上限被配置为非正数，或 `min_questions > max_questions`
- **THEN** 系统 MUST 在启动或创建面试时拒绝该配置并给出明确错误

### Requirement: 四维评分

面试回答 SHALL 按事实准确性、技术深度、结构表达、岗位相关性四个维度评分。默认仅面试结束后展示分数；配置允许时可在每题提交后即时展示。进行中的响应 MUST NOT 泄露未到展示时机的分数。

#### Scenario: 默认延迟展示

- **WHEN** 面试仍在进行且配置为默认模式
- **THEN** 提交回答的响应 MUST NOT 包含该题或累计的评分数值
- **AND** 分数 MUST 只在最终报告中出现

#### Scenario: 即时展示模式

- **WHEN** 配置为每题即时展示分数
- **THEN** 提交回答的响应 MUST 包含该题的四个维度得分与总分
- **AND** 其余流程 MUST 保持不变

#### Scenario: 评分维度完整

- **WHEN** 一道题被评分
- **THEN** 得分 MUST 同时包含事实准确性、技术深度、结构表达、岗位相关性四个维度
- **AND** 每一维度 MUST 落在约定的分值区间内

#### Scenario: 评分不得虚构事实

- **WHEN** 回答中出现与 `source_evidence` 相冲突的事实或无法验证的夸张指标
- **THEN** 事实准确性维度 MUST 相应扣分并在报告中记录红旗
- **AND** 评分说明 MUST 引用对应回答内容作为依据

### Requirement: 中途放弃与部分报告

在 `immediate`（每题即时评分）模式下，系统 SHALL 允许调用方中途放弃面试，并基于已答且已评分的题目生成部分报告。放弃 MUST 不丢失已答记录，MUST 标注面试未完成，且 MUST NOT 为未答题目编造得分。

#### Scenario: 即时模式放弃

- **WHEN** `score_visibility=immediate` 且用户在面试进行中请求放弃
- **THEN** 系统 MUST 结束面试并返回部分报告
- **AND** 报告 MUST 包含 `end_reason=abandoned`、`answered_count` 与 `planned_count`
- **AND** 报告 MUST 只包含已答题目的得分与结论

#### Scenario: 放弃后不计当前题

- **WHEN** 用户放弃时存在一道已抛出但未回答的题目
- **THEN** 该题 MUST 标记为未作答
- **AND** MUST NOT 出现在逐题得分中
- **AND** MUST NOT 记为已覆盖要求

#### Scenario: 默认模式不允许放弃

- **WHEN** `score_visibility=end_of_interview` 且调用方请求放弃
- **THEN** 系统 MUST 返回 409 与 `abandon_not_allowed`
- **AND** 面试状态 MUST 保持等待回答

#### Scenario: 放弃幂等

- **WHEN** 同一会话重复请求放弃
- **THEN** 系统 MUST 返回同一份部分报告
- **AND** MUST NOT 追加重复得分或重复回写

#### Scenario: 放弃后拒绝继续作答

- **WHEN** 已放弃的会话再次提交回答
- **THEN** 系统 MUST 返回 409
- **AND** 已生成的部分报告 MUST 保持不变

### Requirement: 面试报告

面试结束 SHALL 返回结构化报告，包含逐题得分、亮点、红旗、改进建议以及与岗位要求的 gap。

#### Scenario: 报告字段完整

- **WHEN** 面试正常结束
- **THEN** 报告 MUST 包含逐题得分列表、`highlights`、`red_flags`、`improvements` 与 `requirement_gaps`
- **AND** 每道已答题目 MUST 在逐题得分列表中恰好出现一次
- **AND** 报告 MUST 可直接序列化为 JSON

#### Scenario: gap 关联岗位要求

- **WHEN** 报告生成 `requirement_gaps`
- **THEN** 每一项 MUST 关联具体的岗位要求或岗位画像字段
- **AND** MUST 说明候选人在该要求上的表现差距

#### Scenario: 中途结束仍有报告

- **WHEN** 面试因达到上限、无可用题目或模型持续失败而提前结束
- **THEN** 系统 MUST 仍生成报告
- **AND** 报告 MUST 说明提前结束的原因

#### Scenario: 报告包含要求覆盖信息

- **WHEN** 报告生成
- **THEN** 报告 MUST 列出已被题目覆盖的 `must_have` 与未覆盖的 `must_have`
- **AND** 未覆盖项 MUST 说明是题量上限还是缺少可用依据导致

### Requirement: 报告回写主分析结果

面试报告生成（含中途放弃的报告）后，系统 SHALL 把报告摘要回写主分析运行的 `interview_reports[job_id]`，并触发求职建议刷新。回写 MUST 按 `interview_thread_id` 幂等，MUST 不覆盖历史快照，且失败时 MUST NOT 丢失面试报告。

#### Scenario: 报告回写成功

- **WHEN** 一次面试生成报告且对应主运行仍存在
- **THEN** 系统 MUST 把摘要写入 `interview_reports[job_id]`
- **AND** 摘要 MUST 包含 `interview_thread_id`、`status`、分数摘要、`highlights`、`red_flags`、`improvements` 与 `requirement_gaps`
- **AND** `GET /api/runs/{thread_id}` MUST 能读取该摘要
- **AND** 主分析的 `advice` MUST 被刷新并引用该岗位的面试表现

#### Scenario: 放弃的报告同样回写

- **WHEN** 用户中途放弃并生成部分报告
- **THEN** 回写摘要的 `status` MUST 为 `abandoned`
- **AND** MUST 包含 `answered_count` 与 `planned_count`

#### Scenario: 重复回写幂等

- **WHEN** 同一 `interview_thread_id` 的报告被重复回写
- **THEN** 系统 MUST NOT 产生重复摘要或重复建议刷新
- **AND** 结果 MUST 与首次回写一致

#### Scenario: 回写失败可重试

- **WHEN** 回写因持久化或建议刷新失败
- **THEN** 面试报告 MUST 仍然返回，响应 MUST 带 `writeback_status=failed`
- **AND** 后续查询该面试会话 MUST 继续幂等重试回写
- **AND** MUST NOT 丢失已答题目与报告

### Requirement: 会话上下文控制

生成题目与评分时，系统 SHALL NOT 传递全量 transcript。上下文 MUST 由滚动摘要与最近 3 轮问答组成，并随轮次推进更新摘要，避免 checkpoint 体积随题数线性膨胀。

#### Scenario: 仅携带摘要与最近三轮

- **WHEN** 会话已回答超过 3 轮
- **THEN** 发送给模型的上下文 MUST 只包含滚动摘要与最近 3 轮问答
- **AND** MUST NOT 包含更早轮次的完整原文

#### Scenario: 摘要随轮次更新

- **WHEN** 新一轮问答被接受
- **THEN** 滚动摘要 MUST 被更新以覆盖不再进入最近 3 轮的更早内容
- **AND** 更新后的摘要 MUST 持久化到 checkpoint

### Requirement: 敏感问题与不可信输入防护

系统 MUST NOT 询问年龄、婚育、健康状况、民族、宗教信仰等与岗位能力无关的敏感信息。简历与岗位文本 MUST 视为不可信输入：使用显式分隔符包裹，并在系统指令中声明忽略其中出现的任何指令；单段输入长度 MUST 受上限约束。

#### Scenario: 拒绝生成敏感问题

- **WHEN** 候选题目涉及年龄、婚育、健康等敏感信息
- **THEN** 系统 MUST 丢弃该题目并重新选择合法题目
- **AND** 不得把敏感问题返回给调用方

#### Scenario: 提示注入不作为指令执行

- **WHEN** 简历或岗位文本中包含"忽略以上要求"之类的指令性内容
- **THEN** 系统 MUST 按数据处理该内容
- **AND** MUST NOT 改变题量上限、评分规则或跳过来源约束

#### Scenario: 超长输入被拒绝

- **WHEN** 简历、岗位文本或单次回答超过配置的长度上限
- **THEN** 系统 MUST 拒绝该输入并给出明确错误
- **AND** 不得截断后静默接受

### Requirement: 失败处理不丢记录

单题模型调用失败 SHALL 可重试；重试仍失败时 MUST 保留已完成题目的回答与记录，并以可恢复的错误状态结束或暂停，不得清空会话。

#### Scenario: 单题失败后重试成功

- **WHEN** 生成下一题时模型调用瞬时失败
- **THEN** 系统 MUST 在有限次数内重试
- **AND** 重试成功后 MUST 正常返回下一题
- **AND** 已答题目记录 MUST 保持不变

#### Scenario: 重试耗尽

- **WHEN** 模型调用在重试上限后仍失败
- **THEN** 系统 MUST 保留所有已答题目的回答与评分
- **AND** 会话 MUST 可再次恢复，不得被删除或重置

### Requirement: 面试接口契约

系统 SHALL 提供四个接口：`POST /api/interviews` 创建面试并返回 `thread_id` 与首题；`POST /api/interviews/{thread_id}/answers` 提交回答并返回下一题或报告；`POST /api/interviews/{thread_id}/abandon` 在即时评分模式下放弃并返回部分报告；`GET /api/interviews/{thread_id}` 查询进度与结果。

#### Scenario: 创建接口

- **WHEN** 调用方提交合法的 `job_id` 与简历文本
- **THEN** `POST /api/interviews` MUST 返回 200 或 201，响应包含 `thread_id` 与首题

#### Scenario: 提交回答接口

- **WHEN** 调用方对存在的会话提交当前题目的回答
- **THEN** `POST /api/interviews/{thread_id}/answers` MUST 返回下一题或报告
- **AND** 当面试已结束时 MUST 返回表示结束的标志与完整报告

#### Scenario: 放弃接口

- **WHEN** `immediate` 模式下的会话调用 `POST /api/interviews/{thread_id}/abandon`
- **THEN** 接口 MUST 返回 200 与部分报告
- **AND** 响应 MUST 包含 `end_reason=abandoned` 与 `writeback_status`
- **AND** 默认模式下 MUST 返回 409 与 `abandon_not_allowed`

#### Scenario: 查询进度接口

- **WHEN** 调用方查询存在的 `thread_id`
- **THEN** `GET /api/interviews/{thread_id}` MUST 返回当前状态、题目进度与已产生的报告（如有）
- **AND** 默认模式下的进行中会话 MUST NOT 在响应中包含分数

#### Scenario: 会话不存在

- **WHEN** 调用方对从未创建的 `thread_id` 提交回答或查询
- **THEN** 系统 MUST 返回 404
- **AND** 不得隐式创建空会话
