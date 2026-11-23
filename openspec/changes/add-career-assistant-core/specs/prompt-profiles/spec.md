## ADDED Requirements

### Requirement: 角色独立提示词

系统 SHALL 为 Supervisor、岗位分析、简历评审、简历优化、求职教练五个角色分别提供独立的 system prompt，每个节点 MUST 只使用自己角色的提示词。

#### Scenario: 岗位分析使用岗位分析提示词

- **WHEN** 岗位分析子图执行
- **THEN** 它 MUST 加载 `job_analyst` 角色提示词
- **AND** MUST NOT 复用简历评审或优化提示词

#### Scenario: 简历评审使用评审提示词

- **WHEN** 对某个岗位执行简历评审
- **THEN** 它 MUST 加载 `resume_reviewer` 角色提示词
- **AND** 提示词 MUST 只针对"单份简历与单个岗位"的匹配判断

#### Scenario: 角色提示词互不串用

- **WHEN** 任一节点构造模型调用
- **THEN** 发送的 system message MUST 只包含公共安全前缀与当前角色提示词
- **AND** MUST NOT 携带其他角色的提示词内容

### Requirement: 角色职责边界

每个角色的提示词 SHALL 明确"只看什么、不看什么"以及输出结构，防止越权判断。

#### Scenario: 岗位分析不读取简历

- **WHEN** 岗位分析节点构造输入
- **THEN** human message MUST 只包含岗位文本
- **AND** MUST NOT 包含简历内容或评审结论

#### Scenario: 评审不改写简历

- **WHEN** 简历评审输出结果
- **THEN** 结果 MUST 只包含分数、维度分、`matched`、`missing`、`issues`
- **AND** MUST NOT 返回改写后的简历正文

#### Scenario: 优化不虚构事实

- **WHEN** 简历优化生成新版本
- **THEN** 提示词 MUST 要求只重组已有事实
- **AND** 输出 MUST NOT 新增简历中不存在的经历或技能

### Requirement: 公共安全前缀不可覆盖

系统 SHALL 在运行时把统一安全前缀与角色提示词拼接为最终 system message；角色提示词 MUST NOT 关闭、替换或重复定义公共约束。

#### Scenario: 拼接顺序固定

- **WHEN** 任一节点调用模型
- **THEN** 最终 system message MUST 以公共安全前缀开头，后接角色提示词
- **AND** 角色提示词 MUST NOT 出现在前缀之前

#### Scenario: 角色文件尝试覆盖

- **WHEN** 某个角色提示词包含关闭安全约束的标记（如"忽略上述安全规则"）
- **THEN** 系统 MUST 在启动校验时失败
- **AND** MUST NOT 带着该提示词进入运行

### Requirement: 提示词加载与启动校验

系统 SHALL 在启动时一次性加载全部角色提示词，并校验文件存在、内容非空、占位符在白名单内。

#### Scenario: 缺少角色文件

- **WHEN** 任一角色提示词文件缺失
- **THEN** 系统 MUST 启动失败并指出缺失的角色

#### Scenario: 空提示词

- **WHEN** 角色提示词为空或只有空白
- **THEN** 系统 MUST 启动失败

#### Scenario: 未知占位符

- **WHEN** 角色提示词引用了白名单之外的占位符
- **THEN** 系统 MUST 启动失败并列出未知占位符

#### Scenario: 校验通过

- **WHEN** 五个角色文件齐全、非空且占位符合法
- **THEN** 系统 MUST 正常启动
- **AND** MUST 记录每个角色的 `prompt_version`

### Requirement: 不可信输入隔离

岗位文本与简历文本 SHALL 只作为 human message 中的数据块传入，并使用显式分隔符包裹；MUST NOT 拼接进 system prompt。

#### Scenario: 简历中的指令

- **WHEN** 简历文本包含"忽略之前的指令"等内容
- **THEN** 该内容 MUST 只出现在 human message 的数据块内
- **AND** system message MUST 保持安全前缀与角色提示词不变

#### Scenario: 岗位文本中的指令

- **WHEN** 岗位 JD 包含要求模型改变输出格式的语句
- **THEN** 该语句 MUST 被视为岗位数据
- **AND** MUST NOT 改变 system message 或输出 schema

### Requirement: 提示词版本可追溯

系统 SHALL 为每份角色提示词计算并记录 `prompt_version`，随运行元信息或结构化日志输出。

#### Scenario: 正常运行记录版本

- **WHEN** 一次分析运行完成
- **THEN** 运行元信息或日志 MUST 包含所用角色的 `prompt_version`
- **AND** 同一次运行内同一角色的版本 MUST 保持一致

#### Scenario: 文件变更后版本变化

- **WHEN** 任一角色提示词内容被修改后重启
- **THEN** 该角色的 `prompt_version` MUST 与修改前不同

### Requirement: 提示词与模型路由解耦

角色提示词与角色模型配置 SHALL 相互独立：修改提示词不得改变角色到模型的映射，反之亦然。

#### Scenario: 只改提示词

- **WHEN** 仅修改某角色的提示词文件
- **THEN** 该角色仍 MUST 使用原有模型配置
- **AND** 其他角色的提示词与模型 MUST 不受影响

#### Scenario: 只改模型

- **WHEN** 仅修改 `models.yaml` 中某角色的模型
- **THEN** 该角色的提示词 MUST 保持不变
