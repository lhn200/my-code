## ADDED Requirements

### Requirement: 匹配评分

简历评审 SHALL 针对单个岗位画像输出 0–100 的整数匹配分、维度分、命中项、缺失项与问题清单。

#### Scenario: 输出完整评分结构

- **WHEN** 对一个已完成分析的岗位执行评审
- **THEN** 输出 MUST 包含 `score`（0–100 整数）、`dimensions`、`matched`、`missing`、`issues`
- **AND** `score` MUST 与 `dimensions` 的加权结果一致，不得出现分数与维度明显矛盾

#### Scenario: 高分岗位

- **WHEN** 简历覆盖该岗位全部硬性要求
- **THEN** `score` MUST 不低于阈值
- **AND** 该岗位 MUST 不进入优化回路

#### Scenario: 低分岗位

- **WHEN** 简历缺少该岗位的关键硬性要求，导致得分低于阈值
- **THEN** 该岗位 MUST 被标记为需要优化
- **AND** `missing` MUST 列出缺失的具体要求

### Requirement: 评分不虚构事实

评审 MUST 只依据简历与岗位画像中实际出现的内容，不得假设用户具备未提及的经历或技能。

#### Scenario: 简历未提及某项技术要求

- **WHEN** 岗位要求某项技术但简历完全没有相关描述
- **THEN** 该项 MUST 出现在 `missing` 中
- **AND** 不得出现在 `matched` 中

#### Scenario: 简历描述模糊

- **WHEN** 简历提到相关经历但没有可验证的产出或指标
- **THEN** 评审 MUST 在 `issues` 中指出证据不足
- **AND** 不得自行补全具体数字或成果

### Requirement: 岗位间独立评审

每个岗位的评审 SHALL 相互独立，不得用其他岗位的结论影响当前岗位的评分。

#### Scenario: 多岗位评审

- **WHEN** 一次运行包含多个岗位
- **THEN** 每个岗位 MUST 生成独立的评审结果
- **AND** 任一岗位的分数变化 MUST 不影响其他岗位的已有分数
