## ADDED Requirements

### Requirement: 汇总求职建议

求职教练 SHALL 在所有岗位完成评审后，基于各岗位结果生成一段自然语言求职建议，覆盖投递优先级、每个岗位的判断理由、该岗位应投递的简历版本、简历改进重点与能力缺口。

#### Scenario: 多岗位生成优先级

- **WHEN** 一次运行包含 3 个已完成评审的岗位
- **THEN** 建议 MUST 给出明确的投递优先级顺序
- **AND** 每个岗位 MUST 附带排序理由（分数、匹配项或缺口）

#### Scenario: 存在未达标岗位

- **WHEN** 有岗位在达到回流上限后仍低于阈值
- **THEN** 建议 MUST 说明该岗位的风险与差距
- **AND** MUST 给出可执行的补强方向

#### Scenario: 存在失败岗位

- **WHEN** 有岗位分析或评审失败
- **THEN** 建议 MUST 标注该岗位结果不可用
- **AND** 不得对其给出投递结论

### Requirement: 按岗位指明投递简历版本

建议 SHALL 为每个可用岗位标明应投递的简历来源：未优化岗位使用基线，优化过的岗位使用对应的定制变体版本。

#### Scenario: 有定制简历的岗位

- **WHEN** 某岗位存在优化后的变体
- **THEN** 建议 MUST 标明该岗位应使用哪个 `variant_version`
- **AND** 引用的分数 MUST 对应该变体的评审结果

#### Scenario: 已达标岗位

- **WHEN** 某岗位未触发优化
- **THEN** 建议 MUST 标明该岗位使用基线简历
- **AND** MUST NOT 声称该岗位有定制版本

#### Scenario: 多岗位变体不混用

- **WHEN** 两个岗位各自有定制变体
- **THEN** 每个岗位的建议 MUST 只引用自己的变体
- **AND** MUST NOT 让两个岗位共用同一份定制简历

### Requirement: 建议只基于已有结果

求职建议 MUST 基于本次运行产生的岗位画像、各岗位当前变体、评审结果与优化历史，不得引入未出现过的岗位、经历或数据。

#### Scenario: 建议引用分数

- **WHEN** 建议中提及某岗位的匹配情况
- **THEN** 引用的分数 MUST 与该岗位当前变体的评审结果一致

#### Scenario: 无优化记录

- **WHEN** 本次运行没有触发优化
- **THEN** 建议 MUST NOT 声称简历已被优化
- **AND** MUST NOT 虚构变体版本号

### Requirement: 建议输出格式

建议 SHALL 以 Markdown 文本返回，包含优先级列表、每个岗位应投递的简历版本与改进要点，可被前端直接渲染。

#### Scenario: 返回 Markdown

- **WHEN** 图运行结束
- **THEN** `advice` 字段 MUST 为非空 Markdown 字符串
- **AND** MUST 包含至少一个优先级条目、一个简历版本标注与一条改进要点

### Requirement: 建议引用面试报告

当运行的 `interview_reports` 中存在某岗位的报告摘要时，求职教练 SHALL 在建议中引用该岗位的面试表现（亮点、红旗、改进建议与要求差距），并 MUST NOT 改写面试报告的结论或据此调整岗位匹配分。

#### Scenario: 存在完成报告

- **WHEN** 某岗位的 `interview_reports` 中存在 `status=completed` 的报告
- **THEN** 建议 MUST 提及该岗位的面试亮点与至少一条改进方向
- **AND** MUST 说明该结论来自模拟面试，而非简历评审
- **AND** MUST NOT 修改该岗位的 `score` 或评审结果

#### Scenario: 存在中途放弃的报告

- **WHEN** 某岗位的报告 `status=abandoned`
- **THEN** 建议 MUST 说明该次面试未完成，并给出已答题目覆盖到的改进点
- **AND** MUST NOT 把未答题目当作已考察或已通过

#### Scenario: 无面试报告

- **WHEN** 某岗位没有面试报告
- **THEN** 建议 MUST NOT 提及该岗位的面试表现
- **AND** MUST NOT 虚构面试结论

#### Scenario: 回写后刷新建议

- **WHEN** 面试报告回写成功
- **THEN** 系统 MUST 用 `career_coach` 角色重新生成 `advice`
- **AND** 新的 `advice` MUST 纳入本次回写的报告
- **AND** 重新生成 MUST NOT 改变岗位画像、评审结果与优化历史
