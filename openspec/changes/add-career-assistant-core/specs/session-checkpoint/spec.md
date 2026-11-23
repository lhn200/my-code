## ADDED Requirements

### Requirement: thread_id 由服务端生成

每次分析运行 SHALL 绑定一个由服务端生成的唯一 `thread_id`，并在创建响应中返回。`POST /api/runs` 的请求体 MUST NOT 接受 `thread_id` 字段。

#### Scenario: 创建时生成 thread_id

- **WHEN** 调用方发起一次新的分析且请求体只包含 `goal`、`resume_text`、`jobs`
- **THEN** 服务端 MUST 生成唯一 `thread_id`
- **AND** 响应 MUST 返回该 `thread_id` 与运行结果

#### Scenario: 请求体携带 thread_id

- **WHEN** `POST /api/runs` 请求体顶层出现 `thread_id`
- **THEN** 系统 MUST 返回 422
- **AND** `fields` MUST 包含 `thread_id`，类型为未知字段
- **AND** MUST NOT 创建运行或 checkpoint

#### Scenario: 不接受复用已有会话创建

- **WHEN** 调用方希望继续一个已有会话
- **THEN** MUST 使用 `POST /api/runs/{thread_id}/resume`
- **AND** `POST /api/runs` MUST 每次都创建新的 `thread_id`

### Requirement: SQLite 持久化 checkpoint

运行状态 SHALL 持久化到 SQLite，进程重启后仍可通过 `thread_id` 读取。

#### Scenario: 进程重启后恢复

- **WHEN** 服务重启后按已有 `thread_id` 查询状态
- **THEN** 系统 MUST 返回该会话最后一次持久化的状态
- **AND** 不得因为内存清空而返回不存在

#### Scenario: 运行中断后继续

- **WHEN** 一次运行在评审阶段中断
- **THEN** 调用方 MUST 能按同一 `thread_id` 恢复运行
- **AND** 恢复后 MUST 从断点继续，不得重复已完成岗位的分析与评审

#### Scenario: 恢复后保留各岗位定制简历

- **WHEN** 两个岗位已各自生成定制变体后中断并恢复
- **THEN** 状态 MUST 仍能按 `job_id` 返回各自的当前变体与版本号
- **AND** MUST NOT 退化为单一共享简历或丢失变体历史

### Requirement: 状态查询与历史快照

系统 SHALL 支持查询某 `thread_id` 的当前状态、历史 checkpoint 列表，以及按 `checkpoint_id` 读取该时刻的完整状态。

#### Scenario: 查询当前状态

- **WHEN** 调用方查询存在的 `thread_id`
- **THEN** 返回 MUST 包含当前状态值与下一步待执行节点

#### Scenario: 查询历史快照

- **WHEN** 调用方请求某会话的快照列表
- **THEN** 返回 MUST 按时间顺序列出该会话的 checkpoint 标识
- **AND** 每个标识 MUST 可用于读取对应时刻的状态

#### Scenario: 按 checkpoint 读取历史状态

- **WHEN** 调用方请求 `GET /api/runs/{thread_id}/snapshots/{checkpoint_id}`
- **THEN** 系统 MUST 返回该 checkpoint 对应的完整状态
- **AND** 状态 MUST 包含当时的岗位结果、简历版本、评审与下一步节点
- **AND** 读取操作 MUST NOT 创建新的 checkpoint 或改变当前状态

#### Scenario: checkpoint 不属于该会话

- **WHEN** 请求的 `checkpoint_id` 不存在或属于其他 `thread_id`
- **THEN** 系统 MUST 返回 404
- **AND** MUST NOT 返回其他会话的任何状态

#### Scenario: 查询不存在的 thread_id

- **WHEN** 调用方查询一个从未创建的 `thread_id`
- **THEN** 系统 MUST 返回 404，不得创建空会话

### Requirement: 会话隔离

不同 `thread_id` 的运行 SHALL 相互隔离，不得读取或写入彼此的岗位结果与评分。

#### Scenario: 并发运行两个会话

- **WHEN** 两个不同 `thread_id` 同时运行
- **THEN** 各自的状态与结果 MUST 互不混入
- **AND** 任一方的失败 MUST 不影响另一方
