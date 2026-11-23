## ADDED Requirements

### Requirement: 运行输入校验

系统 SHALL 在启动图之前校验一次分析请求：求职目标非空、岗位数量在 1 到 `MAX_JOBS`（默认 5）之间、简历文本非空。任一条件不满足时 MUST 拒绝请求并返回可定位的错误信息，不得创建 checkpoint。

#### Scenario: 缺少简历文本

- **WHEN** 请求未提供简历文本或内容为空白
- **THEN** 系统 MUST 返回 422 并说明缺少简历
- **AND** 不得创建 thread_id 或 checkpoint

#### Scenario: 缺少岗位

- **WHEN** 请求的岗位列表为空
- **THEN** 系统 MUST 返回 422 并说明至少需要一个岗位

#### Scenario: 输入合法

- **WHEN** 求职目标、岗位数量和简历文本均有效
- **THEN** 系统 MUST 创建本次运行并进入 Supervisor 路由

#### Scenario: 岗位数超过硬上限

- **WHEN** 请求包含 6 个岗位且 `MAX_JOBS` 为默认值 5
- **THEN** 系统 MUST 返回 422，错误码为 `too_many_jobs`
- **AND** MUST NOT 启动图或创建 checkpoint

#### Scenario: 岗位数恰好等于上限

- **WHEN** 请求包含 5 个岗位且 `MAX_JOBS` 为 5
- **THEN** 系统 MUST 正常创建运行
- **AND** MUST NOT 把上限判定为超限

### Requirement: Supervisor 路由

工作流 SHALL 由 Supervisor 节点根据当前状态决定下一个执行分支，节点不得自行跳转到与状态不符的分支。

#### Scenario: 初次进入路由到岗位分析

- **WHEN** 运行刚开始且尚无岗位分析结果
- **THEN** Supervisor MUST 把每个待分析岗位分发到岗位分析子图

#### Scenario: 有岗位尚未评审

- **WHEN** 存在岗位分析结果但缺少对应变体的简历评审结果
- **THEN** Supervisor MUST 路由到简历评审

#### Scenario: 存在低分岗位

- **WHEN** 存在评审分低于阈值且未达到回流上限的岗位
- **THEN** Supervisor MUST 只把这些岗位逐个分发到简历优化
- **AND** MUST NOT 把已达标岗位送入优化

#### Scenario: 部分岗位低分

- **WHEN** 3 个岗位中只有 1 个低于阈值
- **THEN** Supervisor MUST 只为该岗位触发优化
- **AND** 其余 2 个岗位 MUST 保留当前评审与基线简历

#### Scenario: 所有岗位完成

- **WHEN** 所有岗位均已完成评审且无需继续回流
- **THEN** Supervisor MUST 路由到求职教练
- **AND** 教练节点结束后图 MUST 终止

### Requirement: 多岗位并行分析

系统 SHALL 在一次运行中并行处理多个岗位，每个岗位使用独立的岗位分析子图实例，实例之间不得共享可变状态。

#### Scenario: 三个岗位并行扇出

- **WHEN** 请求包含 3 个岗位
- **THEN** 系统 MUST 并发启动 3 个岗位分析实例
- **AND** 聚合结果 MUST 恰好包含 3 条按 `job_id` 稳定排序的岗位结果

#### Scenario: 单个岗位失败不影响其他岗位

- **WHEN** 其中一个岗位的分析或评审抛出异常
- **THEN** 其他岗位 MUST 继续完成各自流程
- **AND** 失败岗位 MUST 在结果中以错误标记呈现，而不是让整次运行失败

#### Scenario: 重复运行同一岗位集合

- **WHEN** 使用相同岗位集合重复运行
- **THEN** 岗位结果的顺序 MUST 保持一致，不受并发完成先后影响

### Requirement: 状态聚合

并行分支产生的岗位结果与定制简历变体 SHALL 通过状态 reducer 合并到统一状态，不得由某个分支直接覆盖其他分支的产出。

#### Scenario: 并发写入不同岗位结果

- **WHEN** 多个岗位实例同时写入各自的评审结果
- **THEN** 合并后的状态 MUST 保留所有岗位结果，不得丢失或互相覆盖

#### Scenario: 同一岗位重复写入

- **WHEN** 同一岗位因回流产生新变体与新一轮评审
- **THEN** 状态 MUST 保留该岗位的历史变体与轮次，并以最新变体作为当前结论

#### Scenario: 不同岗位的变体互不覆盖

- **WHEN** 两个岗位并行生成定制简历
- **THEN** 每个变体 MUST 按 `job_id` 单独保存
- **AND** 一个岗位的写入 MUST NOT 修改另一个岗位的变体文本或版本号

#### Scenario: 已达标岗位保持基线

- **WHEN** 某岗位未触发优化
- **THEN** 该岗位的当前简历 MUST 继续指向基线
- **AND** 状态中 MUST NOT 出现该岗位的空变体

### Requirement: 运行结果结构

一次运行结束 SHALL 返回结构化结果：每个岗位的分析画像、当前使用的简历（基线或定制变体）、当前匹配评分、评审问题、该岗位的变体与优化历史（如有）以及一段自然语言求职建议。

#### Scenario: 正常完成

- **WHEN** 所有岗位完成评审并生成建议
- **THEN** 返回结果 MUST 包含岗位结果列表与求职建议文本
- **AND** 每个岗位结果 MUST 标明当前使用的是基线还是某个变体版本
- **AND** 结果 MUST 可直接序列化为 JSON 返回给调用方

#### Scenario: 多版定制简历输出

- **WHEN** 两个岗位触发了优化
- **THEN** 结果 MUST 为这两个岗位分别返回定制简历文本与版本号
- **AND** MUST NOT 只返回一份共享的优化稿

#### Scenario: 部分失败完成

- **WHEN** 部分岗位失败但至少一个岗位成功
- **THEN** 返回结果 MUST 包含成功岗位的完整结果与失败岗位的错误标记
- **AND** 整体运行状态 MUST 标记为部分成功
