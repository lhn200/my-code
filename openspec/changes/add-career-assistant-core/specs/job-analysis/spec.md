## ADDED Requirements

### Requirement: 岗位结构化画像

岗位分析子图 SHALL 把一份原始 JD 转换为结构化岗位画像，包含岗位标识、标题、公司、硬性要求、加分要求、职责要点与关键词。

#### Scenario: 正常解析 JD

- **WHEN** 输入一份包含职责与要求的 JD
- **THEN** 输出 MUST 包含 `job_id`、`title`、`company`、`must_have`、`nice_to_have`、`responsibilities`、`keywords`
- **AND** 列表型字段 MUST 为字符串数组

#### Scenario: JD 信息不完整

- **WHEN** JD 未提供公司名或职级信息
- **THEN** 对应字段 MUST 为空值或空数组，不得编造
- **AND** 解析 MUST 继续完成，不得因此中断

#### Scenario: JD 内容无法识别为岗位描述

- **WHEN** 输入文本与招聘岗位无关，无法提取任何要求
- **THEN** 该岗位 MUST 标记为解析失败并附带原因
- **AND** 不得进入后续评审

### Requirement: 岗位分析独立于简历

岗位分析子图 SHALL 只依赖岗位输入，不读取用户简历内容。

#### Scenario: 相同岗位不同简历

- **WHEN** 同一岗位分别与两份不同简历组合运行
- **THEN** 两次得到的岗位画像字段结构 MUST 一致
- **AND** 画像内容不得出现只属于某份简历的信息

### Requirement: 子图边界

岗位分析 MUST 作为独立子图在主管图中被调用，子图内部状态不得直接读取主管图中与评审相关的字段。

#### Scenario: 子图只接收岗位输入

- **WHEN** Supervisor 把一个岗位分发到岗位分析子图
- **THEN** 子图 MUST 只接收该岗位原始文本与 `job_id`
- **AND** 输出 MUST 以 `job_id` 关联回主管图状态

#### Scenario: 子图输出可序列化

- **WHEN** 子图执行结束
- **THEN** 输出 MUST 为 JSON 可序列化结构，可写入 checkpoint
