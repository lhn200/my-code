## ADDED Requirements

### Requirement: 创建运行请求模型

`POST /api/runs` SHALL 只接受 `goal`、`resume_text`、`jobs` 三个顶层字段，且 MUST NOT 接受 `thread_id`。`jobs` 中每个岗位 MUST 使用固定字段名 `job_id`（可选）、`title`、`original_position_text`。

#### Scenario: 合法请求

- **WHEN** 请求体包含非空 `goal`、非空 `resume_text`、1 到 `MAX_JOBS` 个岗位，且每个岗位包含 `title` 与 `original_position_text`
- **THEN** 系统 MUST 接受请求并创建运行

#### Scenario: 顶层出现 thread_id

- **WHEN** 请求体顶层包含 `thread_id`
- **THEN** 系统 MUST 返回 422
- **AND** `fields` MUST 包含 `{"field": "thread_id", "type": "unexpected_field"}`
- **AND** MUST NOT 创建运行或 checkpoint

#### Scenario: 缺少原始岗位文本

- **WHEN** 第二个岗位缺少 `original_position_text`
- **THEN** 系统 MUST 返回 422
- **AND** `fields` MUST 包含 `jobs[1].original_position_text`，类型为 `missing`

#### Scenario: 字段类型错误

- **WHEN** `jobs[0].original_position_text` 传入数字
- **THEN** 系统 MUST 返回 422
- **AND** `fields` MUST 包含 `jobs[0].original_position_text`，类型为 `string_type`

#### Scenario: 字段为空白

- **WHEN** `title` 或 `original_position_text` 去除首尾空白后为空
- **THEN** 系统 MUST 返回 422
- **AND** 对应字段类型 MUST 为 `blank`

#### Scenario: 使用旧字段名

- **WHEN** 岗位对象使用 `jd`、`description` 或 `position_text` 等非约定字段
- **THEN** 系统 MUST 返回 422
- **AND** `fields` MUST 指出该未知字段

#### Scenario: 可选 job_id

- **WHEN** 岗位未提供 `job_id`
- **THEN** 服务端 MUST 生成稳定且唯一的 `job_id`
- **AND** 响应中的岗位结果 MUST 使用该 `job_id`

#### Scenario: 多个字段错误

- **WHEN** 请求同时存在缺少岗位文本与岗位数超限
- **THEN** 系统 MUST 一次性返回全部可定位错误
- **AND** `fields` 顺序 MUST 稳定可复现

### Requirement: 字段级 422 响应结构

所有 422 响应 SHALL 使用统一结构：`{"error": {"code": string, "message": string, "fields": [{"field": string, "type": string, "message": string}]}}`。

#### Scenario: 字段错误可定位

- **WHEN** 任一字段校验失败
- **THEN** `fields` MUST 给出点号与数组下标形式的路径
- **AND** `type` MUST 为稳定枚举，供前端映射到控件
- **AND** `message` MUST 为可直接展示的说明

#### Scenario: 非字段级业务错误

- **WHEN** 岗位数超过 `MAX_JOBS`
- **THEN** 响应 MUST 返回 422 与 `code = "too_many_jobs"`
- **AND** `fields` MAY 为空数组
- **AND** `message` MUST 说明上限值

#### Scenario: 不得返回堆栈

- **WHEN** 任一 422 响应返回
- **THEN** 响应体 MUST NOT 包含异常堆栈、SQL 或内部路径

### Requirement: 创建响应身份字段

`POST /api/runs` 成功响应 SHALL 包含服务端生成的 `thread_id`，且该值 MUST 与 checkpoint 使用的 `thread_id` 一致。

#### Scenario: 响应返回 thread_id

- **WHEN** 运行成功或部分成功
- **THEN** 响应 MUST 包含 `thread_id`
- **AND** 后续状态查询与快照读取 MUST 能使用该值

#### Scenario: 失败响应不返回 thread_id

- **WHEN** 请求在入参校验阶段被拒绝
- **THEN** 响应 MUST NOT 返回 `thread_id`
- **AND** MUST NOT 存在对应 checkpoint
