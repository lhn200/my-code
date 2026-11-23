## ADDED Requirements

### Requirement: 创建分析表单与校验

前端 SHALL 在 `/` 提供创建分析表单，包含求职目标、1 到 5 个岗位（标题与 JD 文本）以及简历内容（粘贴的纯文本，或上传文件解析后的文本），并在提交前执行本地校验；校验不通过时 MUST NOT 发起请求。

#### Scenario: 求职目标为空

- **WHEN** 用户未填写求职目标，或只输入空白字符后提交
- **THEN** 页面 MUST 在求职目标字段附近展示必填错误
- **AND** MUST NOT 发起 `POST /api/runs`

#### Scenario: 岗位信息不完整

- **WHEN** 岗位列表为空，或任一岗位缺少标题或 JD 文本
- **THEN** 页面 MUST 指出具体缺失项与对应岗位
- **AND** MUST NOT 发起 `POST /api/runs`

#### Scenario: 岗位数超过上限

- **WHEN** 用户尝试添加第 6 个岗位
- **THEN** 页面 MUST 阻止添加并提示单次最多 5 个岗位
- **AND** MUST NOT 发起 `POST /api/runs`

#### Scenario: 后端返回岗位超限

- **WHEN** `POST /api/runs` 返回 422 `too_many_jobs`
- **THEN** 页面 MUST 展示岗位数上限提示
- **AND** MUST 保留已填写内容

#### Scenario: 后端返回字段类型错误

- **WHEN** 422 响应的 `fields` 包含 `jobs[0].original_position_text` 且类型为 `string_type`
- **THEN** 页面 MUST 在第一个岗位的原始 JD 输入框附近展示该错误
- **AND** MUST 展示后端给出的可读说明

#### Scenario: 多个字段错误

- **WHEN** 422 响应的 `fields` 包含多个字段
- **THEN** 页面 MUST 在每个可定位字段附近分别展示错误
- **AND** MUST 同时在表单顶部汇总错误数量

#### Scenario: 无法定位的字段错误

- **WHEN** 422 的 `field` 路径在前端表单中找不到对应控件
- **THEN** 页面 MUST 在表单顶部展示通用错误提示
- **AND** MUST NOT 丢弃或静默忽略该错误

#### Scenario: 简历内容为空

- **WHEN** 用户既未粘贴简历文本，也没有成功解析的上传文件
- **THEN** 页面 MUST 提示需要提供简历内容
- **AND** MUST NOT 发起 `POST /api/runs`

#### Scenario: 修正后重新提交

- **WHEN** 用户补齐此前报错的字段并再次提交
- **THEN** 对应错误提示 MUST 清除
- **AND** 输入合法的表单 MUST 发起一次创建分析请求

### Requirement: 简历文件上传与解析预览

创建页 SHALL 提供"粘贴文本"与"上传文件"两种简历输入方式；上传 MUST 调用 `POST /api/resumes` 由后端解析，前端 MUST 展示解析结果并允许在提交前编辑。

#### Scenario: 上传受支持的文件

- **WHEN** 用户选择一个 `.pdf`、`.docx`、`.png`、`.jpg`、`.jpeg` 或 `.webp` 文件
- **THEN** 页面 MUST 展示文件名与大小，并调用 `POST /api/resumes`
- **AND** 成功后 MUST 展示解析文本、页数、`used_ocr`，并把文本填入可编辑的简历输入区

#### Scenario: 前端拦截不支持的类型

- **WHEN** 用户选择白名单之外的文件
- **THEN** 页面 MUST 提示支持的格式
- **AND** MUST NOT 发起上传请求

#### Scenario: 前端拦截超过大小上限的文件

- **WHEN** 文件大小超过与后端一致的默认上限（5MB）
- **THEN** 页面 MUST 提示大小限制
- **AND** MUST NOT 发起上传请求

#### Scenario: 上传中防止重复提交

- **WHEN** 上传请求尚未结束
- **THEN** 提交分析按钮与上传入口 MUST 进入禁用或加载态
- **AND** 连续操作 MUST NOT 产生第二个上传请求

#### Scenario: OCR 结果提示核对

- **WHEN** 上传响应中 `used_ocr=true`
- **THEN** 页面 MUST 标明该文本来自 OCR
- **AND** 当 `low_confidence=true` 时 MUST 提示用户先核对识别结果再提交

#### Scenario: 解析失败

- **WHEN** 上传返回 422（`resume_no_text`、`resume_encrypted`、`resume_unreadable`、类型不支持或超限）
- **THEN** 页面 MUST 按错误码展示可操作提示
- **AND** MUST 保留已粘贴文本、岗位与求职目标等其他表单内容

#### Scenario: 切换输入方式

- **WHEN** 用户在上传成功与粘贴之间切换
- **THEN** 提交 MUST 使用当前选中方式的内容
- **AND** 切换 MUST NOT 清空求职目标、岗位列表等其他字段

#### Scenario: 提交不重复上传

- **WHEN** 文件已解析成功且用户点击提交分析
- **THEN** 前端 MUST 直接使用解析文本调用 `POST /api/runs`
- **AND** MUST NOT 再次上传同一文件

#### Scenario: 刷新不保留文件

- **WHEN** 用户刷新页面
- **THEN** 前端 MUST NOT 自动重新上传或保留上一次的原始文件与解析结果

### Requirement: 多岗位编辑与提交

表单 SHALL 支持动态增删岗位，并为每个岗位生成稳定且唯一的 `job_id`；提交时 MUST 发送当前所有岗位，不得只提交第一个岗位或按标题去重。

#### Scenario: 新增岗位不丢失已有输入

- **WHEN** 用户已填写第一个岗位并点击新增岗位
- **THEN** 页面 MUST 追加一行空白岗位输入
- **AND** 已填写的内容 MUST 保持不变

#### Scenario: 删除指定岗位

- **WHEN** 用户删除列表中的某个岗位
- **THEN** 该岗位 MUST 从提交数据中移除
- **AND** 其余岗位的内容与顺序 MUST 保持不变

#### Scenario: 提交三个岗位

- **WHEN** 用户填写三个岗位并提交
- **THEN** 请求体中的 `jobs` MUST 包含三条记录
- **AND** 每条记录 MUST 带有各自的 `job_id` 与原始 JD 文本
- **AND** 顺序 MUST 与表单展示顺序一致

#### Scenario: 重复标题的不同岗位

- **WHEN** 用户填写两个标题相同但 JD 不同的岗位
- **THEN** 两者 MUST 作为两个独立岗位提交
- **AND** MUST NOT 因标题重复而被合并

### Requirement: 提交加载、超时与运行标识

提交分析 SHALL 展示明确的加载状态并防止重复提交；前端 MUST NOT 在 `POST /api/runs` 请求体中发送 `thread_id`，并 MUST 按核心契约提交 `goal`、`resume_text`、`jobs`。长请求 MUST 持续提示，页面关闭或刷新时 MUST 给出警告，超时后 MUST 给出可操作的后续指引。

#### Scenario: 提交请求体符合契约

- **WHEN** 用户提交创建分析
- **THEN** 请求体 MUST 只包含 `goal`、`resume_text`、`jobs`
- **AND** 每个岗位 MUST 包含 `title` 与 `original_position_text`
- **AND** MUST NOT 包含顶层 `thread_id`
- **AND** 若前端内部使用 `positionText` 命名，MUST 只在 `api/types.ts` 映射为 `original_position_text`

#### Scenario: 提交中禁止重复触发

- **WHEN** 用户点击提交且请求尚未结束
- **THEN** 提交按钮 MUST 进入加载态并禁用
- **AND** 连续点击 MUST NOT 产生第二个 `POST /api/runs` 请求

#### Scenario: 长请求持续提示

- **WHEN** 请求持续时间超过预设提示阈值
- **THEN** 页面 MUST 提示分析仍在进行
- **AND** MUST 保持加载态直至成功、失败或超时

#### Scenario: 请求超时

- **WHEN** 请求超过配置的超时时间仍未返回
- **THEN** 页面 MUST 结束加载态并提示请求超时
- **AND** MUST 说明后端可能仍在执行，暂时无法确认结果
- **AND** MUST 保留用户已填写的表单内容并给出重试入口
- **AND** MUST NOT 伪造或展示前端生成的 `thread_id`

#### Scenario: 请求进行中关闭页面

- **WHEN** 请求尚未结束时用户尝试关闭或刷新页面
- **THEN** 浏览器 MUST 触发离开确认提示
- **AND** 前端 MUST 在本地记录一条待确认的运行标记（含提交时间，默认 30 分钟内有效）

#### Scenario: 重新打开后的待确认提示

- **WHEN** 用户重新打开应用且本地存在未过期的待确认运行标记
- **THEN** 页面 MUST 展示"上次分析可能仍在进行"的提示
- **AND** MUST 提供前往会话列表查看的入口（会话列表可用时）或稍后重试指引
- **AND** 用户关闭提示后 MUST 清除该标记

#### Scenario: 创建成功

- **WHEN** 后端返回成功并包含服务端生成的 `thread_id`
- **THEN** 前端 MUST 跳转到 `/runs/<thread_id>` 展示结果
- **AND** MUST NOT 停留在创建表单页等待用户手动操作

### Requirement: 结果页岗位卡片与评分

结果页 SHALL 为每个岗位展示独立卡片，至少包含岗位标题、公司（可为空）、0–100 的匹配评分、缺失项与问题清单；评分 MUST 直接使用后端返回值，前端不得重新计算。

#### Scenario: 正常结果渲染

- **WHEN** 运行返回三个已完成评审的岗位
- **THEN** 页面 MUST 渲染三张岗位卡片
- **AND** 每张卡片 MUST 展示 `score` 的整数分值
- **AND** 缺失项来自 `missing`，问题来自 `issues`

#### Scenario: 评分边界值

- **WHEN** 某岗位评分为 0 或 100
- **THEN** 页面 MUST 分别展示 0 与 100，不得将其当作缺失值或进行截断
- **AND** MUST NOT 修改后端返回的分值

#### Scenario: 缺失项为空

- **WHEN** 某岗位的 `missing` 为空数组
- **THEN** 卡片 MUST 展示"无缺失项"类提示
- **AND** MUST NOT 渲染为错误或空白区域

#### Scenario: 岗位分析失败

- **WHEN** 某岗位没有可用评审结果并带有错误标记
- **THEN** 该岗位卡片 MUST 展示失败原因
- **AND** MUST NOT 展示编造或默认为 0 的评分

### Requirement: 优化历史与求职建议

结果页 SHALL 展示按轮次升序的优化历史，以及后端返回的 Markdown 求职建议；Markdown 渲染 MUST 防止脚本注入，渲染失败时 MUST 降级为纯文本。

#### Scenario: 展示优化历史

- **WHEN** 运行结果包含至少一轮优化
- **THEN** 页面 MUST 按轮次升序列出每一轮
- **AND** 每轮 MUST 展示涉及岗位与优化前后分数
- **AND** MUST 标出达到轮数上限仍未达标的岗位风险

#### Scenario: 未触发优化

- **WHEN** 运行结果中没有优化记录
- **THEN** 页面 MUST 展示"未触发简历优化"类空状态
- **AND** MUST NOT 伪造优化轮次

#### Scenario: 渲染教练建议

- **WHEN** 后端返回非空 Markdown `advice`
- **THEN** 页面 MUST 渲染标题、列表与强调等 Markdown 结构
- **AND** 建议中的 HTML 标签 MUST 被转义或过滤，不得执行脚本

#### Scenario: 建议为空或渲染失败

- **WHEN** `advice` 为空，或 Markdown 渲染抛出异常
- **THEN** 页面 MUST 展示原始文本或空状态提示
- **AND** MUST NOT 使整个结果页崩溃

### Requirement: 部分失败与整体状态

结果页 SHALL 同时呈现成功岗位与失败岗位，并根据后端整体运行状态展示成功、部分成功或失败提示，不得因单个岗位失败而隐藏其他结果。

#### Scenario: 部分岗位失败

- **WHEN** 三个岗位中一个失败、两个成功
- **THEN** 页面 MUST 展示两张完整岗位卡片与一张失败卡片
- **AND** MUST 展示"部分成功"的整体提示

#### Scenario: 全部成功

- **WHEN** 所有岗位均完成评审
- **THEN** 页面 MUST 展示成功提示
- **AND** MUST NOT 展示失败或部分成功提示

#### Scenario: 整体失败

- **WHEN** 运行结果没有任何可用岗位结果
- **THEN** 页面 MUST 展示整体失败提示与错误信息
- **AND** MUST 保留 `thread_id` 以便重试或排查

### Requirement: 按 thread_id 查询运行

前端 SHALL 在 `/runs` 提供 `thread_id` 查询入口，调用 `GET /api/runs/{thread_id}` 获取状态，并对空输入、404 与网络错误给出明确反馈。

#### Scenario: 查询存在的会话

- **WHEN** 用户输入有效 `thread_id` 并提交查询
- **THEN** 前端 MUST 请求 `GET /api/runs/{thread_id}`
- **AND** 成功后 MUST 展示该会话结果或跳转到 `/runs/<thread_id>`

#### Scenario: 查询不存在的会话

- **WHEN** 后端返回 404
- **THEN** 页面 MUST 提示该 `thread_id` 不存在
- **AND** MUST 保留输入框内容以便修改后重试

#### Scenario: 未填写 thread_id

- **WHEN** 用户未输入 `thread_id` 就点击查询
- **THEN** 页面 MUST 提示需要填写 `thread_id`
- **AND** MUST NOT 发起请求

### Requirement: 会话恢复

结果页 SHALL 支持对未完成或已中断的会话调用 `POST /api/runs/{thread_id}/resume` 继续执行，恢复过程中 MUST 防止重复触发，成功后 MUST 刷新页面数据。

#### Scenario: 直接打开结果页

- **WHEN** 用户访问 `/runs/<thread_id>`
- **THEN** 前端 MUST 先请求该会话的当前状态
- **AND** 查询中 MUST 展示加载态，查询成功后 MUST 渲染结果

#### Scenario: 恢复未完成会话

- **WHEN** 当前会话存在未完成步骤且用户点击恢复
- **THEN** 前端 MUST 调用 `POST /api/runs/{thread_id}/resume`
- **AND** 恢复期间 MUST 禁用恢复按钮并展示加载态
- **AND** 成功后 MUST 重新拉取状态并更新页面

#### Scenario: 恢复失败

- **WHEN** 恢复请求返回 404 或 500
- **THEN** 页面 MUST 展示对应错误提示
- **AND** MUST 保持已有结果可见，不得清空页面

#### Scenario: 会话不存在

- **WHEN** 直接访问的 `thread_id` 在后端不存在
- **THEN** 页面 MUST 展示会话不存在提示
- **AND** MUST 提供返回 `/runs` 重新查询的入口

### Requirement: 快照列表与历史状态

结果页 SHALL 调用 `GET /api/runs/{thread_id}/snapshots` 展示该会话的历史快照，并 SHALL 支持通过 `GET /api/runs/{thread_id}/snapshots/{checkpoint_id}` 读取指定快照的历史状态；读取结果为只读，不得影响当前状态。

#### Scenario: 展示快照列表

- **WHEN** 会话存在多个历史快照
- **THEN** 页面 MUST 按时间顺序列出快照标识
- **AND** 每条快照 MUST 可识别其顺序或时间信息

#### Scenario: 查看某个历史快照

- **WHEN** 用户选择列表中的某个快照
- **THEN** 前端 MUST 调用 `GET /api/runs/{thread_id}/snapshots/{checkpoint_id}`
- **AND** MUST 以只读方式展示该时刻的岗位结果、评分与建议
- **AND** MUST 明确标注"历史快照，非当前状态"

#### Scenario: 快照不存在

- **WHEN** 读取快照返回 404
- **THEN** 页面 MUST 提示该快照不存在或已失效
- **AND** MUST 保留当前结果与快照列表可见

#### Scenario: 无历史快照

- **WHEN** 快照接口返回空列表
- **THEN** 页面 MUST 展示空状态提示
- **AND** MUST NOT 将其视为请求失败

#### Scenario: 快照加载失败

- **WHEN** 快照请求失败或超时
- **THEN** 页面 MUST 展示错误提示与重试入口
- **AND** 岗位结果与建议 MUST 保持可见

#### Scenario: 恢复后刷新快照

- **WHEN** 用户成功恢复会话
- **THEN** 前端 MUST 重新请求快照列表
- **AND** 新产生的快照 MUST 出现在列表中

### Requirement: 展示以后端结果为准

前端 SHALL 只负责呈现后端返回的状态、评分、优化历史与建议，不得在前端重新计算评分、推断回流结论或改写建议内容。

#### Scenario: 评分与阈值

- **WHEN** 后端返回的评分低于任何前端已知阈值
- **THEN** 页面 MUST 原样展示该评分
- **AND** MUST NOT 自行决定重新评分或隐藏该岗位

#### Scenario: 优化历史展示

- **WHEN** 后端返回优化历史
- **THEN** 页面 MUST 按返回内容展示轮次与分数
- **AND** MUST NOT 合并、重排或补全不存在的轮次
