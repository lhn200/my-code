## ADDED Requirements

### Requirement: 面试报告回写主分析结果

系统 SHALL 支持把一次模拟面试的报告摘要回写到对应的主分析运行状态。回写 MUST 以 `job_id` 为键写入 `interview_reports`，只保留该岗位最近一次报告；完整报告仍保留在面试会话中。回写 MUST NOT 重跑岗位分析、评审或简历优化节点。

#### Scenario: 回写完成的面试报告

- **WHEN** 一次面试生成报告且其 `job_id` 属于目标运行的 `job_profiles`
- **THEN** 系统 MUST 把该报告摘要写入 `interview_reports[job_id]`
- **AND** 摘要 MUST 包含 `interview_thread_id`、`status`、`generated_at`、四维均分、`highlights`、`red_flags`、`improvements` 与 `requirement_gaps`
- **AND** `status` MUST 为 `completed` 或 `abandoned`

#### Scenario: 同一面试重复回写

- **WHEN** 同一 `interview_thread_id` 的报告被再次回写
- **THEN** 系统 MUST 按 `interview_thread_id` 幂等处理
- **AND** MUST NOT 产生重复条目或重复的教练建议刷新

#### Scenario: 岗位不属于该运行

- **WHEN** 回写的 `job_id` 不在目标运行的 `job_profiles` 中
- **THEN** 系统 MUST 拒绝回写并返回可定位的错误
- **AND** MUST NOT 修改运行状态

#### Scenario: 运行不存在

- **WHEN** 回写指向的 `thread_id` 在 checkpoint 中不存在
- **THEN** 系统 MUST 拒绝回写并返回 404 语义
- **AND** MUST NOT 隐式创建运行

#### Scenario: 回写不破坏历史快照

- **WHEN** 回写成功
- **THEN** 系统 MUST 追加新的 checkpoint
- **AND** 回写前的历史快照 MUST 保持可读且内容不变
- **AND** 岗位画像、评审结果、简历变体与优化历史 MUST 保持不变

#### Scenario: 回写失败不影响面试报告

- **WHEN** 回写过程中发生持久化或教练重跑错误
- **THEN** 面试报告 MUST 仍然返回给调用方
- **AND** 响应 MUST 标明回写未完成，供调用方幂等重试
- **AND** 既有 `advice` MUST 保持可读

### Requirement: 运行详情包含面试报告

`GET /api/runs/{thread_id}` SHALL 在响应中返回 `interview_reports`，使调用方可以按 `job_id` 读取该岗位最近一次面试报告摘要。

#### Scenario: 无面试报告

- **WHEN** 运行尚未收到任何面试报告
- **THEN** 响应中的 `interview_reports` MUST 为空对象或空映射
- **AND** MUST NOT 编造面试结论

#### Scenario: 按岗位读取报告摘要

- **WHEN** 某岗位已完成一次面试
- **THEN** 响应 MUST 在该 `job_id` 下返回最近一次报告摘要
- **AND** 摘要 MUST 与面试会话中的报告一致
