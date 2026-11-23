## ADDED Requirements

### Requirement: 会话记忆命名空间隔离

系统 SHALL 以 `user_id + thread_id` 作为会话记忆的命名空间。会话轮次、摘要、摘要版本与预算统计 MUST 属于唯一一个 `thread_id` 且归属唯一 `user_id`；读取 MUST 同时校验归属，MUST NOT 跨会话拼接轮次，MUST NOT 跨用户返回任何摘要、轮次或"已总结"信号。

#### Scenario: 恢复会话只加载本会话记忆

- **WHEN** 已登录用户恢复自己创建的 `thread_id`
- **THEN** 载入的摘要与最近轮次 MUST 全部来自该 `thread_id`
- **AND** MUST NOT 混入该用户其他 `thread_id` 的摘要或轮次
- **AND** 载入的摘要 MUST 携带版本号与更新时间

#### Scenario: 同一用户多会话互不污染

- **WHEN** 同一用户同时进行两个不同 `thread_id` 的会话
- **THEN** 两个会话的摘要版本、轮次计数与预算统计 MUST 相互独立
- **AND** 其中一个会话的摘要失败 MUST NOT 影响另一个会话

#### Scenario: 跨用户读取被拒绝

- **WHEN** 用户 A 请求用户 B 的 `thread_id` 的摘要状态
- **THEN** 系统 MUST 返回 `404`
- **AND** MUST NOT 返回摘要正文、版本、轮次或是否已总结的任何信息

#### Scenario: 归属与请求用户不一致

- **WHEN** `runs` 表中某 `thread_id` 的 `user_id` 与当前请求用户不一致
- **THEN** 系统 MUST 拒绝加载该会话的摘要与轮次
- **AND** MUST NOT 回退为匿名读取或以其他用户身份读取

### Requirement: 恢复会话的上下文装配

系统 SHALL 在恢复会话时只加载本会话摘要与最近轮次，不得回放完整历史 transcript。已总结内容 MUST 只以摘要形式进入上下文，最近轮次 MUST 以原文进入上下文，同一轮 MUST NOT 同时以摘要和原文重复计入。

#### Scenario: 摘要加最近轮次

- **WHEN** 一个会话已有摘要且最近轮次数为 6
- **THEN** 装配结果 MUST 包含该摘要与最近 6 轮原文
- **AND** MUST NOT 包含更早轮次的完整原文

#### Scenario: 未总结轮次全部保留

- **WHEN** 会话轮次总数未达到摘要触发阈值
- **THEN** 装配结果 MUST 包含全部轮次原文，且摘要部分为空

#### Scenario: 摘要与轮次不重复

- **WHEN** 摘要的 `summarized_through_turn` 为 12 且当前总轮次为 18
- **THEN** 装配结果 MUST 只包含第 13 至 18 轮原文
- **AND** 第 1 至 12 轮 MUST NOT 以原文形式出现

#### Scenario: 空会话恢复

- **WHEN** 恢复一个尚无轮次与摘要的会话
- **THEN** 装配结果 MUST 使用空摘要与空轮次，且不报错
- **AND** 预算统计 MUST 记录轮次数为 0

### Requirement: 上下文预算分配

系统 SHALL 按可配置的 `SESSION_CONTEXT_BUDGET`（默认 8000 tokens）为每次模型调用分配会话窗口预算：长期记忆 800、会话摘要 1200、最近轮次 4800、当前输入 1200。四段预算 MUST 可独立配置；启动时 MUST 校验均为正整数且总和不超过总预算。

#### Scenario: 默认预算分配

- **WHEN** 服务使用默认配置启动并组装一次上下文
- **THEN** 总预算 MUST 为 8000 tokens
- **AND** 四段上限 MUST 分别为 800、1200、4800、1200

#### Scenario: 自定义预算生效

- **WHEN** 把 `CONTEXT_RECENT_TURNS_TOKENS` 改为 3000 且总预算仍为 8000
- **THEN** 新请求的最近轮次预算 MUST 为 3000
- **AND** 已持久化的历史状态 MUST NOT 被改写

#### Scenario: 非法预算配置阻止启动

- **WHEN** 任一段预算被配置为 0 或负数，或四段之和超过总预算
- **THEN** 服务 MUST 启动失败并给出明确错误
- **AND** MUST NOT 以部分配置启动后静默运行

#### Scenario: 预算统计可观测

- **WHEN** 一次模型调用完成上下文装配
- **THEN** 状态中的 `context_budget_meta` MUST 记录各段实际 token 数、丢弃轮次数与是否发生截断
- **AND** 元信息 MUST NOT 包含简历原文或对话原文

### Requirement: 超预算裁剪优先级

当装配结果超过预算时，系统 SHALL 按固定顺序裁剪：先减少长期记忆条数并压缩单条长度，再从最旧轮次开始丢弃，再压缩摘要；最近轮次 MUST 保底保留 2 轮，当前输入 MUST NOT 被丢弃。裁剪后仍超限时 MUST 返回明确的 `context_overflow` 错误而不是发送超限提示词。

#### Scenario: 优先裁剪长期记忆

- **WHEN** 装配结果超出预算且存在长期记忆
- **THEN** 系统 MUST 先减少记忆条数或压缩单条记忆
- **AND** MUST NOT 在记忆尚未降到 0 条前丢弃最近轮次

#### Scenario: 最近轮次保底

- **WHEN** 裁剪到需要丢弃轮次
- **THEN** 系统 MUST 从最旧轮次开始丢弃
- **AND** MUST 至少保留最近 2 轮原文

#### Scenario: 摘要最后压缩

- **WHEN** 记忆已降为 0 条且轮次已降到保底值后仍超预算
- **THEN** 系统 MUST 压缩摘要长度
- **AND** MUST NOT 删除整个摘要

#### Scenario: 仍超限时拒绝调用

- **WHEN** 完成全部裁剪后估算 token 仍超过预算
- **THEN** 系统 MUST 返回 `context_overflow` 错误并记录各段 token
- **AND** MUST NOT 把超限提示词发送给模型
- **AND** 当前输入 MUST NOT 被丢弃或替换为空

### Requirement: 长消息截断与显式标记

单条普通对话消息超过 `MAX_MESSAGE_CHARS`（默认 4000 字符）时，系统 SHALL 保留头 70% 与尾 30%，并在中间插入形如 `...[已截断 N 字]...` 的显式标记。截断 MUST 只作用于送入模型的消息副本，MUST NOT 修改状态中的原始字段。

#### Scenario: 超长消息被截断

- **WHEN** 一条对话消息长度超过 4000 字符
- **THEN** 进入模型上下文的消息 MUST 只包含头 70% 与尾 30%
- **AND** MUST 包含可识别的截断标记与截断字符数

#### Scenario: 原文保持不变

- **WHEN** 一条消息在上下文装配中被截断
- **THEN** 状态中对应的原始字段 MUST 保持完整
- **AND** 后续需要原文的节点 MUST 仍能读取到完整内容

#### Scenario: 短消息不截断

- **WHEN** 消息长度未超过 4000 字符
- **THEN** 进入模型上下文的消息 MUST 与原文一致
- **AND** MUST NOT 出现截断标记

#### Scenario: 截断可观测

- **WHEN** 任一消息发生截断
- **THEN** 结构化日志 MUST 记录 `thread_id` 与截断字符数
- **AND** MUST NOT 记录被截断的正文内容

### Requirement: 关键输入不得静默丢弃

岗位 JD 与简历 MUST NOT 被普通消息截断规则静默丢弃。超出预算时系统 SHALL 使用 `jd_digest`（不超过 800 字符，保留职责、硬性要求与关键词）或 `resume_digest`（不超过 1500 字符，保留经历、技能与量化指标）表示，或使用已有的结构化字段。原始全文 MUST 保留在状态的既有字段中，MUST 只由明确需要该内容的节点读取。

#### Scenario: 超长 JD 使用摘要

- **WHEN** 岗位 JD 超出当前输入预算
- **THEN** 系统 MUST 使用 `jd_digest` 作为送入模型的岗位表示
- **AND** `jd_digest` MUST 保留职责、硬性要求与关键词
- **AND** 状态中的原始 JD MUST 保持不变

#### Scenario: 超长简历使用摘要

- **WHEN** 简历文本超出当前请求所需预算
- **THEN** 系统 MUST 使用 `resume_digest` 作为送入模型的简历表示
- **AND** `resume_digest` MUST 保留经历、技能与量化指标
- **AND** 状态中的 `resume_text` MUST 保持不变

#### Scenario: 摘要生成失败降级

- **WHEN** `jd_digest` 或 `resume_digest` 生成失败
- **THEN** 系统 MUST 退化为结构化字段加显式截断标记
- **AND** MUST 记录 `digest_fallback=true`
- **AND** 当必须保留的结构化字段为空时 MUST 返回明确错误，而不是传入空字符串

#### Scenario: 岗位分析不读取简历与记忆

- **WHEN** 岗位分析节点组装提示词
- **THEN** MUST NOT 包含 `resume_text`、`resume_digest`、长期记忆或会话摘要中的简历细节
- **AND** MUST 只使用岗位 JD 与岗位画像所需字段

### Requirement: token 计数与降级策略

系统 SHALL 使用 token 计数器约束上下文。优先使用 `tiktoken` 的 `cl100k_base` 编码；不可用时 MUST 降级为轻量估算：CJK 字符每字 1 token、其他字符按 3.5 字符/token 向上取整，每条消息额外计入 4 tokens。估算值 MUST 乘以 1.15 作为安全余量。降级原因 MUST 在启动日志中记录一次且不影响功能。

#### Scenario: 使用 tiktoken 计数

- **WHEN** 运行环境可导入 `tiktoken` 且编码可用
- **THEN** 预算判断 MUST 使用 `cl100k_base` 的编码结果
- **AND** MUST NOT 记录降级日志

#### Scenario: 缺少 tiktoken 时降级

- **WHEN** `tiktoken` 不可导入或指定编码不可用
- **THEN** 系统 MUST 使用轻量估算继续工作
- **AND** MUST 在启动日志中记录降级原因一次
- **AND** 接口 MUST 保持可用

#### Scenario: 计数异常不中断主流程

- **WHEN** token 计数遇到空字符串、超长文本或编码异常
- **THEN** 系统 MUST 返回可用的保守计数值而不是抛出未捕获异常
- **AND** MUST 继续执行上下文装配

### Requirement: 滚动摘要触发条件

当会话未总结轮次数达到 `SUMMARY_TRIGGER_TURNS`（默认 12）时，系统 SHALL 生成或更新摘要。每次 MUST 最多总结最早的 6 轮，总结后 MUST 保留最近 `RECENT_TURNS_KEEP`（默认 6）轮原文，并 MUST 更新 `summarized_through_turn` 以避免重复总结。

#### Scenario: 达到阈值触发摘要

- **WHEN** 未总结轮次数达到 12
- **THEN** 系统 MUST 触发一次摘要
- **AND** 摘要 MUST 覆盖最早的 6 轮
- **AND** `summarized_through_turn` MUST 前进 6

#### Scenario: 未达阈值不触发

- **WHEN** 未总结轮次数为 11
- **THEN** 系统 MUST NOT 触发摘要
- **AND** 上下文 MUST 使用全部轮次原文

#### Scenario: 单次总结数量受限

- **WHEN** 未总结轮次数为 24
- **THEN** 单次摘要 MUST 最多处理 6 轮
- **AND** 剩余未总结轮次 MUST 留待后续触发，MUST NOT 在一次调用中处理全部轮次

#### Scenario: 已总结轮次不重复

- **WHEN** 摘要成功写入且 `summarized_through_turn` 为 6
- **THEN** 下一次摘要 MUST 从第 7 轮开始
- **AND** MUST NOT 再次总结第 1 至 6 轮

### Requirement: 摘要内容与版本

摘要 SHALL 为结构化 JSON，包含 `facts`、`open_questions`、`preferences`、`constraints`、`decisions`，并 MUST 包含 `version`、`updated_at` 与 `summarized_through_turn`。摘要 MUST 保留已确认事实、未解决问题、用户偏好与约束；MUST NOT 编造未在轮次中出现的事实。摘要正文 MUST 不超过 `SUMMARY_MAX_CHARS`（默认 1200 字符）。

#### Scenario: 摘要字段完整

- **WHEN** 一次摘要成功生成
- **THEN** 摘要 MUST 同时包含 `facts`、`open_questions`、`preferences`、`constraints`、`decisions`
- **AND** MUST 包含 `version`、`updated_at` 与 `summarized_through_turn`
- **AND** MUST 可序列化为 JSON

#### Scenario: 版本递增

- **WHEN** 对已有摘要再次生成摘要
- **THEN** `version` MUST 等于上一版本加 1
- **AND** `updated_at` MUST 更新为本次生成时间

#### Scenario: 摘要不得编造

- **WHEN** 轮次中未出现某项事实、偏好或约束
- **THEN** 摘要 MUST NOT 新增该内容
- **AND** 摘要中的事实项 MUST 可追溯到已有轮次

#### Scenario: 摘要长度受限

- **WHEN** 生成的摘要超过 1200 字符
- **THEN** 系统 MUST 压缩到上限以内
- **AND** MUST 保留 `facts` 与 `open_questions` 中已确认的内容
- **AND** MUST NOT 以静默丢段的方式返回空摘要

### Requirement: 摘要持久化与恢复续用

摘要 MUST 写入 checkpoint 中的 `AgentState`。恢复会话后系统 MUST 沿用同一摘要及其版本继续装配上下文，MUST NOT 从零重建。`session_memory_meta` 投影表只用于展示与查询，不是摘要的真相来源。

#### Scenario: 进程重启后恢复摘要

- **WHEN** 服务重启后按 `thread_id` 恢复一个已有摘要的会话
- **THEN** 装配结果 MUST 使用持久化的摘要与版本
- **AND** MUST NOT 重新生成摘要或重置版本

#### Scenario: 投影缺失时以 checkpoint 为准

- **WHEN** `session_memory_meta` 中没有该 `thread_id` 但 checkpoint 中存在摘要
- **THEN** 系统 MUST 使用 checkpoint 中的摘要
- **AND** MUST 尽力补写投影，补写失败不影响运行

#### Scenario: 投影与 checkpoint 不一致

- **WHEN** 投影中的 `summary_version` 小于 checkpoint 中的版本
- **THEN** 系统 MUST 以 checkpoint 为准
- **AND** MUST 修正投影版本

### Requirement: 摘要失败降级

摘要生成失败 MUST NOT 阻塞主流程。系统 MUST 保留上一版摘要，继续以"旧摘要 + 最近 N 轮"装配上下文，标记 `summary_status=failed`，并在后台或下一次触发时重试，最多 2 次。MUST NOT 清除已总结内容或删除轮次。

#### Scenario: 模型超时导致摘要失败

- **WHEN** 摘要模型调用超时或返回非法结构
- **THEN** 系统 MUST 保留上一版摘要
- **AND** MUST 继续使用最近 N 轮原文装配上下文
- **AND** MUST 标记 `summary_status=failed`
- **AND** 主流程 MUST 正常继续或正常结束

#### Scenario: 重试后成功

- **WHEN** 首次摘要失败且随后重试成功
- **THEN** 系统 MUST 写入新摘要并递增版本
- **AND** `summary_status` MUST 变为成功状态

#### Scenario: 重试耗尽仍可继续会话

- **WHEN** 重试 2 次后仍失败
- **THEN** 会话 MUST 仍可继续提问或恢复
- **AND** 已有摘要与轮次 MUST 保持不变
- **AND** 系统 MUST NOT 删除 checkpoint

### Requirement: 摘要执行方式与并发控制

单轮运行结束后，系统 SHALL 通过 FastAPI `BackgroundTasks` 异步执行摘要，响应 MUST NOT 等待摘要完成。基于 interrupt 的多轮图 SHALL 在 `summarize` 节点内联执行摘要，并受 `SUMMARY_TIMEOUT_SECONDS`（默认 20 秒）约束。同一 `thread_id` 的摘要 MUST 串行执行，回写时 MUST 携带 `expected_version` 做乐观校验，版本不匹配时 MUST 放弃写入。

#### Scenario: 响应先于摘要返回

- **WHEN** 一次单轮运行结束并触发后台摘要
- **THEN** 运行响应 MUST 在摘要完成前返回
- **AND** 摘要成功后再更新 checkpoint 与投影

#### Scenario: 版本冲突不覆盖新摘要

- **WHEN** 后台摘要回写时 `expected_version` 与当前版本不一致
- **THEN** 系统 MUST 放弃本次写入
- **AND** MUST NOT 覆盖较新的摘要
- **AND** MUST 记录版本冲突日志

#### Scenario: 多轮图内联摘要超时

- **WHEN** 面试子图在 `summarize` 节点调用摘要超过 20 秒
- **THEN** 系统 MUST 中止本次摘要并按失败降级
- **AND** MUST 继续提出下一道题

#### Scenario: 后台任务丢失可懒补偿

- **WHEN** 进程重启导致后台摘要任务丢失
- **THEN** 系统 MUST NOT 在启动时全表扫描
- **AND** 下一次读取该会话时若未总结轮次达到阈值，MUST 重新触发摘要

### Requirement: 摘要状态与正文查询

系统 SHALL 提供 `GET /api/sessions/{thread_id}/summary`，返回该会话的摘要元信息与结构化正文：`summarized`、`version`、`updated_at`、`summarized_through_turn`、`summary_status` 与 `summary`（`facts`、`open_questions`、`preferences`、`constraints`、`decisions`）。该接口 MUST 要求登录并校验归属，MUST NOT 返回轮次原文。

#### Scenario: 已总结会话返回元信息与正文

- **WHEN** 用户查询自己一个已有摘要的 `thread_id`
- **THEN** 响应 MUST 包含 `summarized=true`、版本、更新时间、已总结轮次与 `summary_status`
- **AND** 响应 MUST 包含结构化 `summary` 正文
- **AND** 响应 MUST NOT 包含轮次原文

#### Scenario: 未总结会话

- **WHEN** 用户查询自己一个尚无摘要的 `thread_id`
- **THEN** 响应 MUST 返回 `summarized=false`
- **AND** `summary` MUST 为空或 `null`
- **AND** 版本与已总结轮次 MUST 为初始值

#### Scenario: 查询他人会话摘要状态

- **WHEN** 用户 A 查询用户 B 的 `thread_id`
- **THEN** 系统 MUST 返回 `404`
- **AND** MUST NOT 泄露是否已总结或任何摘要正文

#### Scenario: 正文不写日志与本地缓存

- **WHEN** 摘要正文被读取并返回前端
- **THEN** 结构化日志 MUST NOT 记录正文
- **AND** 前端 MUST NOT 把正文写入 `localStorage`

### Requirement: 手动重新生成摘要

系统 SHALL 提供 `POST /api/sessions/{thread_id}/summary/regenerate`，在同一 `thread_id` 的摘要锁内，用"现有摘要 + 最早不超过 6 个未总结轮次"增量重算摘要，并在成功后递增版本。没有未总结轮次时 MUST 返回 `regenerated=false` 且不改变版本。并发冲突 MUST NOT 覆盖较新摘要；失败 MUST 保留旧摘要。

#### Scenario: 有未总结轮次时重新生成

- **WHEN** 用户对自己已有摘要且存在未总结轮次的会话请求重新生成
- **THEN** 系统 MUST 用现有摘要与最早不超过 6 个未总结轮次重算
- **AND** 响应 MUST 返回 `regenerated=true`、递增后的 `version` 与新的结构化 `summary`
- **AND** `summarized_through_turn` MUST 前进到本次覆盖的最后一轮

#### Scenario: 无未总结轮次

- **WHEN** 用户对没有未总结轮次的会话请求重新生成
- **THEN** 系统 MUST 返回 `regenerated=false`
- **AND** 版本、摘要与 `summarized_through_turn` MUST 保持不变
- **AND** 响应 MUST 返回当前摘要正文供前端展示

#### Scenario: 并发冲突不覆盖新版本

- **WHEN** 重新生成期间后台摘要已写入更高版本
- **THEN** 系统 MUST 放弃本次写入
- **AND** MUST 返回 `409 summary_conflict` 与当前最新摘要
- **AND** MUST NOT 回退版本

#### Scenario: 重新生成失败保留旧摘要

- **WHEN** 摘要模型超时或返回非法结构
- **THEN** 系统 MUST 返回 `502 summary_failed`
- **AND** 上一版摘要与轮次 MUST 保持不变
- **AND** MUST NOT 删除 checkpoint

#### Scenario: 重复点击串行执行

- **WHEN** 同一会话的重新生成请求尚未完成时再次请求
- **THEN** 两个请求 MUST 串行执行
- **AND** 后一个请求在无未总结轮次时 MUST 返回 `regenerated=false`

#### Scenario: 未登录或非本人

- **WHEN** 未携带 token，或请求他人会话的重新生成
- **THEN** 系统 MUST 分别返回 `401` 与 `404`
- **AND** MUST NOT 触发摘要模型调用

### Requirement: 摘要注入边界

会话摘要 MUST 只作为带分隔符的参考数据进入 human message，标签形如 `<session_summary>`；MUST NOT 进入 system prompt。摘要中出现的指令性文本 MUST NOT 被当作指令执行。渲染 MUST 限制长度与控制字符，并声明标签内内容为数据。

#### Scenario: system prompt 不含摘要

- **WHEN** 任一节点组装 system prompt
- **THEN** system prompt MUST NOT 包含会话摘要正文或摘要标签
- **AND** 摘要 MUST 只出现在 human message 中

#### Scenario: 摘要内注入不生效

- **WHEN** 摘要文本包含"忽略以上要求"或"修改评分规则"等指令性内容
- **THEN** 系统 MUST 将其作为数据处理
- **AND** MUST NOT 改变评分规则、预算、轮次上限或工具调用行为

#### Scenario: 超长摘要被压缩

- **WHEN** 摘要文本超过配置的摘要预算
- **THEN** 渲染 MUST 压缩或截断并保留截断标记
- **AND** MUST NOT 直接把超长摘要发送给模型

### Requirement: AgentState 字段向后兼容

新增状态字段 SHALL 只增不改：`session_turns`、`session_summary`、`session_summary_version`、`session_summary_updated_at`、`summarized_through_turn`、`memory_context`、`memory_context_meta`、`context_budget_meta`。旧 checkpoint 缺少这些键时 MUST 由默认值填充，MUST NOT 因字段缺失导致恢复失败；既有字段类型、语义与 reducer MUST 保持不变。

#### Scenario: 旧 checkpoint 可直接恢复

- **WHEN** 用一个不包含任何新增字段的历史 checkpoint 恢复会话
- **THEN** 系统 MUST 用默认值补齐新增字段
- **AND** MUST 正常继续运行
- **AND** MUST NOT 要求数据迁移或重建 thread

#### Scenario: 新增字段默认值

- **WHEN** 读取到的状态缺少摘要相关键
- **THEN** `session_summary` MUST 默认为空字符串
- **AND** `session_summary_version` 与 `summarized_through_turn` MUST 默认为 0
- **AND** `session_turns` 与 `memory_context` MUST 默认为空列表

#### Scenario: 记忆上下文不累积

- **WHEN** 同一会话连续进行多轮
- **THEN** `memory_context` MUST 在每轮装配时整体重建
- **AND** MUST NOT 追加历史记忆条目
- **AND** 条目数 MUST 不超过配置的 top-k 上限

#### Scenario: 既有字段语义不变

- **WHEN** 旧代码或既有节点读取 `resume_text`、`jobs`、`reviews` 等字段
- **THEN** 这些字段的值与 reducer 行为 MUST 与本 change 之前一致
- **AND** 预算裁剪 MUST NOT 修改这些字段

### Requirement: 会话记忆与长期记忆解耦

关闭长期记忆 MUST NOT 关闭会话摘要与上下文预算裁剪。会话摘要属于会话内上下文管理，MUST 始终启用；长期记忆开关只影响记忆写入与检索。

#### Scenario: 关闭记忆后摘要仍然生效

- **WHEN** 用户关闭长期记忆且会话未总结轮次达到 12
- **THEN** 系统 MUST 仍然生成或更新会话摘要
- **AND** MUST 仍然按摘要加最近轮次装配上下文

#### Scenario: 关闭记忆后预算仍然生效

- **WHEN** 用户关闭长期记忆且上下文超出预算
- **THEN** 系统 MUST 仍然执行裁剪与截断
- **AND** 记忆段 MUST 直接按 0 条处理
