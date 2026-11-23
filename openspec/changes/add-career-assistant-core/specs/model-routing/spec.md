## ADDED Requirements

### Requirement: 角色级模型配置

系统 SHALL 支持为 `supervisor`、`job_analyst`、`resume_reviewer`、`resume_optimizer`、`career_coach` 五个角色分别配置 `provider`、`model`、`temperature`。

#### Scenario: 全部角色独立配置

- **WHEN** 配置文件为五个角色分别指定了模型
- **THEN** 每个角色调用时 MUST 使用各自配置的模型
- **AND** 角色之间不得复用未配置的模型实例

#### Scenario: 只配置部分角色

- **WHEN** 仅 `resume_reviewer` 配置了模型，其余角色未配置
- **THEN** 未配置的角色 MUST 回退到全局默认模型
- **AND** 系统 MUST 正常启动并运行

### Requirement: 环境变量覆盖

角色模型配置 SHALL 支持通过环境变量覆盖配置文件中的取值，环境变量优先。

#### Scenario: 环境变量覆盖默认模型

- **WHEN** 配置文件指定默认模型 A，环境变量指定模型 B
- **THEN** 未单独配置的角色 MUST 使用模型 B

#### Scenario: 环境变量覆盖单个角色

- **WHEN** 环境变量为 `resume_optimizer` 指定了独立模型
- **THEN** 该角色 MUST 使用环境变量中的模型
- **AND** 其他角色 MUST 保持各自的配置或默认值

### Requirement: 启动即校验

系统 SHALL 在启动时校验模型配置：角色名必须属于受支持的五个角色，已配置的 `model` 不得为空白，`temperature` 必须在合法区间内。校验失败 MUST 阻止启动并给出具体错误。

#### Scenario: 配置了未知角色

- **WHEN** 配置文件中出现不属于五个角色之一的名字
- **THEN** 启动 MUST 失败并指出该角色名

#### Scenario: 模型名为空

- **WHEN** 某角色配置了空字符串模型名
- **THEN** 启动 MUST 失败并指出缺失的字段

#### Scenario: 温度为非法值

- **WHEN** 某角色的 `temperature` 超出允许区间
- **THEN** 启动 MUST 失败并指出取值范围

### Requirement: 配置与图结构解耦

模型配置的增减 SHALL 不改变图结构、节点名称与状态字段。

#### Scenario: 更换评审模型

- **WHEN** 把 `resume_reviewer` 的模型从 A 换成 B
- **THEN** 图节点与连线 MUST 保持不变
- **AND** 状态结构与 checkpoint 格式 MUST 兼容已有数据
