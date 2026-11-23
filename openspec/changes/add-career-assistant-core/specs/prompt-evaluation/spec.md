## ADDED Requirements

### Requirement: 金标评测数据集

系统 SHALL 在 `evals/datasets/` 提供带版本的金标数据集，至少覆盖岗位分析、简历评审、简历优化三类任务，每条样本包含输入、期望关键字段与缺口清单。

#### Scenario: 数据集覆盖三类任务

- **WHEN** 运行评测
- **THEN** 数据集 MUST 同时包含岗位分析、简历评审、简历优化样本
- **AND** 每条样本 MUST 声明其任务类型与期望字段

#### Scenario: 样本不含真实个人信息

- **WHEN** 数据集被提交到仓库
- **THEN** 所有样本 MUST 为合成或脱敏内容
- **AND** MUST NOT 包含真实姓名、联系方式或公司内部信息

#### Scenario: 数据集版本化

- **WHEN** 数据集内容发生变化
- **THEN** 其版本号或哈希 MUST 随之变化
- **AND** 评测报告 MUST 记录所用数据集版本

### Requirement: 离线评测执行

评测 SHALL 通过独立命令执行，复用角色提示词与模型配置，但 MUST NOT 启动 FastAPI、写入生产 checkpoint 或调用运行接口。

#### Scenario: 指定提示词版本评测

- **WHEN** 执行评测命令并指定 `prompt_version`
- **THEN** 系统 MUST 只加载对应版本的提示词
- **AND** MUST 输出该版本的逐样本结果与汇总指标

#### Scenario: 不触碰生产数据

- **WHEN** 评测运行
- **THEN** MUST NOT 读写 `data/checkpoints.sqlite` 或 `data/uploads/`
- **AND** MUST 把结果写入 `evals/reports/`

### Requirement: 评测指标

评测 SHALL 至少计算：结构化输出通过率、缺口识别召回率、虚构率、分数与基线的平均绝对误差、时延与 token 消耗。

#### Scenario: 结构化输出失败

- **WHEN** 某样本的模型输出不符合 schema
- **THEN** 该样本 MUST 计为 schema 失败
- **AND** MUST NOT 因单条失败中断整轮评测

#### Scenario: 虚构事实

- **WHEN** 输出中出现金标简历中不存在的事实
- **THEN** 该样本 MUST 计入虚构率

#### Scenario: 指标汇总

- **WHEN** 一轮评测完成
- **THEN** 报告 MUST 包含各项指标的总体值
- **AND** MUST 可按角色或任务类型拆分

### Requirement: 评分基线与回归门禁

系统 SHALL 在 `evals/baseline.json` 记录各角色各指标的基线值与允许跌幅；评测结果低于门禁时命令 MUST 以非零码退出。

#### Scenario: 基线达标

- **WHEN** 所有指标均在允许跌幅内
- **THEN** 命令 MUST 以 0 退出
- **AND** 报告 MUST 标记为通过

#### Scenario: 指标回退超限

- **WHEN** 任一指标低于基线减去允许跌幅
- **THEN** 命令 MUST 以非零码退出
- **AND** 报告 MUST 标出回退的指标与差值

### Requirement: A/B 对比

系统 SHALL 支持在同一数据集上对比两个提示词版本，输出逐指标差异与结论。

#### Scenario: 两个版本对比

- **WHEN** 指定版本 A 与版本 B 运行 A/B
- **THEN** 报告 MUST 包含每个指标的 A、B 值与差值
- **AND** MUST 给出基于门禁规则的胜负结论

#### Scenario: 同版本对比

- **WHEN** A/B 的两个版本内容相同
- **THEN** 指标差异 MUST 接近零
- **AND** 报告 MUST 标注为无显著差异

### Requirement: 结果可复现与可追溯

每份评测报告 MUST 记录 `prompt_version`、模型名、数据集哈希、运行时间与关键参数，使结果可复现。

#### Scenario: 报告包含溯源信息

- **WHEN** 一次评测结束
- **THEN** 报告 MUST 包含本次使用的提示词版本、模型与数据集哈希
- **AND** 相同输入与参数重复运行 MUST 得到一致的样本集合与顺序

#### Scenario: 温度固定

- **WHEN** 执行评测
- **THEN** 评测 MUST 使用固定的低温度配置
- **AND** MUST NOT 继承生产环境可能更高的温度
