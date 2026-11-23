## ADDED Requirements

### Requirement: 简历输入方式

系统 SHALL 支持四种简历输入：纯文本、`.pdf`、`.docx`、图片（`.png` / `.jpg` / `.jpeg` / `.webp`）。所有方式 MUST 归一化为同一份文本，并进入同一套分析流程与状态契约。

#### Scenario: 提交纯文本简历

- **WHEN** 调用方在分析请求中提供非空 `resume_text`
- **THEN** 系统 MUST 直接使用该文本进入 `intake` 校验
- **AND** MUST NOT 要求额外上传文件

#### Scenario: 上传文件简历

- **WHEN** 调用方调用 `POST /api/resumes` 上传受支持类型的文件
- **THEN** 系统 MUST 返回归一化文本、`source_type`、页数与 `used_ocr`
- **AND** 调用方 MUST 能把该文本作为 `resume_text` 发起分析

#### Scenario: 不同输入方式结果结构一致

- **WHEN** 同一份简历分别以纯文本、PDF、DOCX、图片提交
- **THEN** 后续岗位评审结果的结构 MUST 一致
- **AND** 差异只可能来自文本抽取或 OCR 造成的空白与断行

### Requirement: PDF 文本层与 OCR 兜底

对 `.pdf`，系统 SHALL 先用 `pypdf` 逐页抽取文本层；某页为空时 MUST 用 `pypdfium2` 渲染该页并执行 OCR，混合文档逐页补齐。

#### Scenario: 纯文本层 PDF

- **WHEN** 上传的 PDF 每页都有文本层
- **THEN** 系统 MUST 按页码顺序拼接文本
- **AND** `used_ocr` MUST 为 `false`

#### Scenario: 扫描件 PDF

- **WHEN** 上传的 PDF 每页都是图片、文本层为空
- **THEN** 系统 MUST 渲染每页并 OCR
- **AND** 返回文本 MUST 非空，`used_ocr` MUST 为 `true`

#### Scenario: 混合 PDF

- **WHEN** PDF 中部分页有文本层、部分页是扫描图
- **THEN** 系统 MUST 对有文本的页直接抽取、对空白页 OCR
- **AND** 最终文本 MUST 保持原页码顺序

### Requirement: DOCX 解析

对 `.docx`，系统 SHALL 读取正文段落与表格中的文本，并按文档顺序拼接。

#### Scenario: 含表格的 DOCX

- **WHEN** 上传的 DOCX 包含段落与表格
- **THEN** 返回文本 MUST 同时包含段落文字与表格单元格文字
- **AND** MUST NOT 只返回段落而丢失表格内容

#### Scenario: 旧版 DOC 文件

- **WHEN** 上传扩展名为 `.doc` 的文件
- **THEN** 系统 MUST 返回 422 并说明仅支持 `.docx`

### Requirement: 图片 OCR

对图片文件，系统 SHALL 直接执行 OCR 并返回识别文本；OCR MUST NOT 用于猜测图片中不存在的文字。

#### Scenario: 清晰的简历截图

- **WHEN** 上传一张文字清晰的 PNG 简历截图
- **THEN** 系统 MUST 返回识别文本，`source_type` 为 `image`
- **AND** `used_ocr` MUST 为 `true`

#### Scenario: 图片识别为空

- **WHEN** 图片中没有可识别文字
- **THEN** 系统 MUST 返回 422，错误码为 `resume_no_text`
- **AND** 提示 MUST 建议改用文本粘贴或更清晰的图片

### Requirement: 文件校验

系统 SHALL 只接受白名单类型，校验扩展名与 MIME 一致、大小不超过配置上限（默认 5MB）、内容非空，并限制单次 OCR 页数（默认 10 页）。

#### Scenario: 不支持的文件类型

- **WHEN** 上传 `.txt`、`.doc`、`.zip` 等不在白名单内的文件
- **THEN** 系统 MUST 返回 422 并列出支持的扩展名

#### Scenario: 文件超过大小上限

- **WHEN** 上传文件超过 `RESUME_MAX_FILE_MB`
- **THEN** 系统 MUST 返回 422 并给出上限值
- **AND** MUST NOT 读取或解析文件内容

#### Scenario: 空文件

- **WHEN** 上传 0 字节文件
- **THEN** 系统 MUST 返回 422

#### Scenario: 超过 OCR 页数上限

- **WHEN** 扫描件 PDF 需要 OCR 的页数超过上限
- **THEN** 系统 MUST 返回 422 并说明页数上限
- **AND** MUST NOT 静默截断后继续分析

### Requirement: 不可解析输入的错误语义

对于加密、损坏、类型伪装或 OCR 后仍无有效文本的输入，系统 MUST 返回可区分的 422 错误码与可操作提示，不得返回空文本。

#### Scenario: 加密 PDF

- **WHEN** 上传的 PDF 需要密码才能打开
- **THEN** 系统 MUST 返回 422，错误码为 `resume_encrypted`
- **AND** MUST NOT 尝试破解或绕过加密

#### Scenario: 损坏的文件

- **WHEN** 文件无法被对应解析器打开
- **THEN** 系统 MUST 返回 422，错误码为 `resume_unreadable`
- **AND** MUST NOT 暴露解析库堆栈信息

#### Scenario: 扩展名与实际内容不符

- **WHEN** 文件扩展名为 `.pdf` 但内容不是 PDF
- **THEN** 系统 MUST 按类型伪装处理并返回 422

### Requirement: OCR 结果可核对

系统 SHALL 在响应中提供 `used_ocr`、页数与识别字符数；当 OCR 文本过短或明显异常时 MUST 标记低置信度，提示调用方先让用户校对。

#### Scenario: OCR 结果过短

- **WHEN** 图片或扫描件 OCR 后字符数低于阈值
- **THEN** 响应 MUST 标记 `low_confidence=true`
- **AND** 不得直接判定为成功而不给出提示

#### Scenario: 非 OCR 路径

- **WHEN** 输入是纯文本或文本层完整的 PDF / DOCX
- **THEN** `used_ocr` MUST 为 `false`
- **AND** `low_confidence` MUST 为 `false`

### Requirement: 原件以引用方式保存

系统 SHALL 把上传的原始文件保存到独立目录（默认 `data/uploads/`，UUID 命名），响应与状态只保留 `file_id` 与可选 `file_url`；MUST NOT 把文件二进制或 base64 写入状态或 checkpoint。

#### Scenario: 上传成功返回文件引用

- **WHEN** 一次上传解析成功
- **THEN** 响应 MUST 包含 `file_id`，并可选包含 `file_url`
- **AND** MUST NOT 返回文件二进制或 base64 内容

#### Scenario: checkpoint 只保存引用与文本

- **WHEN** 上传后以返回文本发起分析
- **THEN** checkpoint MUST 只包含 `resume_text` 与 `resume_file_id` / `resume_file_url`
- **AND** MUST NOT 出现文件二进制、base64 或可执行路径

#### Scenario: 原始文件名不参与路径

- **WHEN** 上传文件带有含 `../` 或特殊字符的文件名
- **THEN** 系统 MUST 使用服务端生成的 UUID 作为存储名
- **AND** MUST NOT 用原始文件名拼接路径

#### Scenario: 解析失败清理文件

- **WHEN** 文件已写入 `UPLOAD_DIR` 但后续解析失败
- **THEN** 系统 MUST 删除该文件，不留下孤儿文件

#### Scenario: 删除会话清理原件

- **WHEN** 会话删除流程按 `file_id` 请求清理
- **THEN** 系统 MUST 删除对应原件
- **AND** 重复删除 MUST 幂等，不报错

### Requirement: 上传与分析解耦

上传接口 SHALL 只负责校验与文本归一化，不创建 thread 或启动图；分析运行仍由 `POST /api/runs` 发起。

#### Scenario: 上传失败不产生会话

- **WHEN** 上传返回 422
- **THEN** 系统 MUST NOT 创建任何 `thread_id` 或 checkpoint

#### Scenario: 上传成功后再发起分析

- **WHEN** 上传成功返回文本，调用方随后用该文本调用 `POST /api/runs`
- **THEN** 系统 MUST 按正常分析流程执行
- **AND** 上传阶段 MUST NOT 触发任何模型调用
