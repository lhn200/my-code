## ADDED Requirements

### Requirement: 用户与会话数据表

系统 MUST 在 SQLite 中维护 `users` 与 `runs` 两张业务表。

- `users` MUST 至少包含 `id`（主键）、`email`（唯一，大小写不敏感）、`password_hash`、`created_at`。
- `runs` MUST 至少包含 `thread_id`（主键）、`user_id`（外键指向 `users.id`）、`title`、`status`、`created_at`、`updated_at`、`deleted_at`（可空）。
- `runs.thread_id` MUST 与 LangGraph checkpoint 使用的 `thread_id` 语义完全一致，两者一对一关联。
- `deleted_at` 非空表示会话位于回收站；为空表示活跃会话。

#### Scenario: 注册写入 users

- **WHEN** 用户注册成功
- **THEN** `users` 表 MUST 新增一行
- **AND** `email` 唯一约束 MUST 阻止同一邮箱重复插入

#### Scenario: 创建运行写入 runs

- **WHEN** 已登录用户成功发起一次分析
- **THEN** `runs` 表 MUST 新增一行，`thread_id` 为本次运行标识
- **AND** `user_id` MUST 为当前登录用户
- **AND** `created_at` 与 `updated_at` MUST 被写入
- **AND** `deleted_at` MUST 为空

#### Scenario: 运行状态取值受约束

- **WHEN** 写入或更新 `runs.status`
- **THEN** 取值 MUST 限于 `running`、`completed`、`partial`、`failed` 之一
- **AND** 非法取值 MUST 被拒绝

### Requirement: 运行接口按当前用户隔离

`POST /api/runs`、`POST /api/runs/{thread_id}/resume`、`GET /api/runs/{thread_id}`、`GET /api/runs/{thread_id}/snapshots` MUST 要求登录，并 MUST 只允许访问属于当前用户的会话。任何跨用户访问 MUST 返回 `404`，MUST NOT 返回 `403` 或任何表明该 `thread_id` 存在的信号。

#### Scenario: 访问自己的会话

- **WHEN** 用户携带合法 token 访问自己创建的 `thread_id`
- **THEN** 系统 MUST 正常返回该会话的状态、快照或执行恢复

#### Scenario: 访问他人的会话

- **WHEN** 用户 A 携带自己的合法 token 访问用户 B 的 `thread_id`
- **THEN** 系统 MUST 返回 `404`
- **AND** 响应 MUST 与"该 `thread_id` 从未存在"完全一致

#### Scenario: 查询不存在的 thread_id

- **WHEN** 用户查询一个不存在于 `runs` 表的 `thread_id`
- **THEN** 系统 MUST 返回 `404`
- **AND** MUST NOT 创建空会话记录

#### Scenario: 访问回收站中的会话

- **WHEN** 用户访问自己已软删除的 `thread_id` 的状态、快照或 resume
- **THEN** 系统 MUST 返回 `404`
- **AND** MUST NOT 因 checkpoint 仍存在而返回历史状态

#### Scenario: 未登录调用运行接口

- **WHEN** 未携带 token 调用任一 `/api/runs` 接口
- **THEN** 系统 MUST 返回 `401`
- **AND** MUST NOT 调用 LangGraph 或写入 checkpoint

#### Scenario: 创建运行自动归属

- **WHEN** 已登录用户调用 `POST /api/runs` 且未指定 `thread_id`
- **THEN** 系统 MUST 生成唯一 `thread_id`
- **AND** MUST 将其与当前用户绑定后返回

### Requirement: 会话列表分页与搜索

系统 SHALL 提供 `GET /api/sessions`，返回当前用户的会话列表，按 `updated_at` 倒序排列。接口 MUST 支持分页、标题搜索与回收站过滤，默认只返回活跃会话。

- 查询参数：`page`（默认 1）、`page_size`（默认 20，最大 100）、`q`（可选，按标题搜索）、`trashed`（默认 `false`）。
- 响应 MUST 包含 `items`、`total`、`page`、`page_size`。
- `q` 搜索 MUST 只匹配当前用户的标题，大小写不敏感，并 MUST 转义 `%` 与 `_` 等通配符。

#### Scenario: 列出自己的会话

- **WHEN** 用户请求会话列表
- **THEN** 返回项 MUST 全部属于当前用户
- **AND** 每项 MUST 包含 `thread_id`、`title`、`status`、`created_at`、`updated_at`
- **AND** 排序 MUST 按 `updated_at` 从新到旧

#### Scenario: 分页返回

- **WHEN** 用户有 25 个活跃会话并请求 `page=2&page_size=10`
- **THEN** 返回 `items` MUST 恰好 10 条
- **AND** `total` MUST 为 25
- **AND** `page` 与 `page_size` MUST 原样回显

#### Scenario: 页码越界

- **WHEN** 请求的 `page` 超过总页数
- **THEN** 系统 MUST 返回 `200` 与空 `items`
- **AND** `total` MUST 仍为真实总数

#### Scenario: 非法分页参数

- **WHEN** `page < 1` 或 `page_size < 1` 或 `page_size > 100`
- **THEN** 系统 MUST 返回 `422`

#### Scenario: 按标题搜索

- **WHEN** 用户请求 `q=前端` 且其会话标题包含"前端"
- **THEN** 结果 MUST 只包含匹配的会话
- **AND** 搜索 MUST 不区分大小写

#### Scenario: 搜索不跨用户

- **WHEN** 用户 A 搜索的关键词命中用户 B 的会话标题
- **THEN** A 的结果 MUST NOT 包含 B 的任何会话

#### Scenario: 通配符按字面匹配

- **WHEN** 用户搜索 `q=%`
- **THEN** 系统 MUST 按字面 `%` 匹配标题
- **AND** MUST NOT 返回全部会话

#### Scenario: 默认不返回回收站

- **WHEN** 用户存在软删除会话并请求默认列表
- **THEN** 结果 MUST NOT 包含 `deleted_at` 非空的会话

#### Scenario: 查看回收站

- **WHEN** 用户请求 `trashed=true`
- **THEN** 结果 MUST 只包含 `deleted_at` 非空的会话
- **AND** 排序 MUST 按 `deleted_at` 从新到旧

#### Scenario: 会话列表隔离

- **WHEN** 用户 A 与用户 B 各自拥有会话并分别请求列表
- **THEN** A 的结果 MUST NOT 出现 B 的任何 `thread_id`
- **AND** B 的结果 MUST NOT 出现 A 的任何 `thread_id`

#### Scenario: 空会话列表

- **WHEN** 新注册用户请求会话列表
- **THEN** 系统 MUST 返回 `200` 与空 `items`
- **AND** `total` MUST 为 0

#### Scenario: 运行后排序更新

- **WHEN** 用户对较早的会话执行 resume 或重新运行
- **THEN** 该会话的 `updated_at` MUST 被更新
- **AND** 下次列表请求中该会话 MUST 排在更靠前的位置

### Requirement: 会话重命名

系统 SHALL 提供 `PATCH /api/sessions/{thread_id}`，允许会话所有者修改 `title`。标题 MUST 去除首尾空白后非空，长度 MUST 有上限（默认 100 字符）。

#### Scenario: 重命名自己的会话

- **WHEN** 用户对自己的会话提交合法标题
- **THEN** 系统 MUST 更新 `title` 与 `updated_at` 并返回 `200`
- **AND** 后续列表请求 MUST 展示新标题

#### Scenario: 重命名他人的会话

- **WHEN** 用户尝试重命名不属于自己的 `thread_id`
- **THEN** 系统 MUST 返回 `404`
- **AND** MUST NOT 修改任何数据

#### Scenario: 重命名回收站中的会话

- **WHEN** 用户尝试重命名自己已软删除的会话
- **THEN** 系统 MUST 返回 `404`
- **AND** MUST NOT 修改任何数据

#### Scenario: 标题为空或超长

- **WHEN** 提交去除首尾空白后为空的标题，或超过长度上限的标题
- **THEN** 系统 MUST 返回 `422`
- **AND** MUST NOT 修改原记录

### Requirement: 会话软删除与回收站

系统 SHALL 提供 `DELETE /api/sessions/{thread_id}`，将当前用户的会话移入回收站：设置 `deleted_at`，MUST NOT 立即删除 `runs` 行或 LangGraph checkpoint。

#### Scenario: 删除进入回收站

- **WHEN** 用户删除自己的活跃会话
- **THEN** 系统 MUST 返回 `204` 或 `200`
- **AND** `runs.deleted_at` MUST 被设置为当前时间
- **AND** 该 `thread_id` 的 checkpoint MUST 仍然存在
- **AND** 默认会话列表 MUST 不再包含该会话

#### Scenario: 回收站中仍可见

- **WHEN** 用户请求 `GET /api/sessions?trashed=true`
- **THEN** 已删除的会话 MUST 出现在结果中

#### Scenario: 删除他人的会话

- **WHEN** 用户尝试删除不属于自己的 `thread_id`
- **THEN** 系统 MUST 返回 `404`
- **AND** MUST NOT 修改任何 `runs` 行或 checkpoint

#### Scenario: 删除已在回收站的会话

- **WHEN** 用户重复删除同一个已软删除的会话
- **THEN** 系统 MUST 幂等地返回成功或 `404`
- **AND** MUST NOT 改变 `deleted_at`

#### Scenario: 软删除后不可查询

- **WHEN** 软删除成功后按原 `thread_id` 调用 `GET /api/runs/{thread_id}`、resume 或 snapshots
- **THEN** 系统 MUST 返回 `404`

### Requirement: 从回收站恢复

系统 SHALL 提供 `POST /api/sessions/{thread_id}/restore`，将当前用户回收站中的会话恢复为活跃状态。

#### Scenario: 恢复自己的会话

- **WHEN** 用户恢复自己回收站中的会话
- **THEN** 系统 MUST 清空 `deleted_at` 并更新 `updated_at`
- **AND** 该会话 MUST 重新出现在默认列表
- **AND** 原有 checkpoint MUST 仍可读取

#### Scenario: 恢复活跃会话

- **WHEN** 用户恢复一个未删除的会话
- **THEN** 系统 MUST 返回 `409`，错误码为 `not_trashed`
- **AND** MUST NOT 修改数据

#### Scenario: 恢复他人的会话

- **WHEN** 用户尝试恢复不属于自己的 `thread_id`
- **THEN** 系统 MUST 返回 `404`

### Requirement: 永久删除与过期清理

系统 SHALL 提供 `DELETE /api/sessions/{thread_id}/purge`，仅允许永久删除回收站中的会话；永久删除 MUST 在同一事务中删除该 `thread_id` 的 checkpoint 数据与 `runs` 行。系统 SHALL 定义 `TRASH_RETENTION_DAYS`（默认 30），过期回收站会话可被运维命令清理。

#### Scenario: 永久删除回收站会话

- **WHEN** 用户对回收站中的会话调用 purge
- **THEN** 系统 MUST 删除该 `thread_id` 的 checkpoint 数据与 `runs` 行
- **AND** 任一删除失败 MUST 回滚并返回 `500`
- **AND** 之后按该 `thread_id` 查询 MUST 返回 `404`

#### Scenario: 永久删除活跃会话

- **WHEN** 用户对未软删除的会话调用 purge
- **THEN** 系统 MUST 返回 `409`，错误码为 `not_trashed`
- **AND** MUST NOT 删除任何数据

#### Scenario: 永久删除他人的会话

- **WHEN** 用户尝试 purge 不属于自己的 `thread_id`
- **THEN** 系统 MUST 返回 `404`

#### Scenario: 过期回收站清理

- **WHEN** 运维命令以清理模式运行且某会话 `deleted_at` 早于保留天数
- **THEN** 该会话的 checkpoint 与 `runs` 行 MUST 被删除
- **AND** 未过期的回收站会话 MUST 保持不变

### Requirement: legacy checkpoint 不可见

`runs` 表中不存在对应记录的 LangGraph checkpoint MUST 被视为 legacy。legacy checkpoint MUST NOT 出现在任何用户的会话列表中，MUST NOT 通过任一运行接口被查询、恢复或删除。

#### Scenario: legacy checkpoint 不出现在列表

- **WHEN** 任一用户请求会话列表
- **THEN** 结果 MUST 只来自 `runs` 表
- **AND** 仅有 checkpoint 而无 `runs` 记录的 `thread_id` MUST NOT 出现

#### Scenario: 直接访问 legacy thread_id

- **WHEN** 用户以 legacy `thread_id` 调用状态查询、snapshots 或 resume
- **THEN** 系统 MUST 返回 `404`
- **AND** MUST NOT 返回 checkpoint 中的历史状态

#### Scenario: 尝试删除 legacy thread_id

- **WHEN** 用户调用删除或 purge 接口并传入 legacy `thread_id`
- **THEN** 系统 MUST 返回 `404`
- **AND** MUST NOT 删除该 checkpoint

#### Scenario: 迁移不追溯归属

- **WHEN** 本 change 上线时数据库中已存在无主 checkpoint
- **THEN** 系统 MUST NOT 自动将其分配给任何用户
- **AND** 运行接口 MUST NOT 删除这些 checkpoint 数据

### Requirement: legacy checkpoint 运维清理

系统 SHALL 提供命令行运维工具清理 legacy checkpoint，不通过 HTTP API 暴露。工具 MUST 默认只做 dry-run，只有显式确认时才执行删除，且 MUST 只删除 `thread_id` 不在 `runs` 表中的 checkpoint。

- 命令：`python -m backend.scripts.cleanup_legacy_checkpoints`
- 参数：`--older-than-days`（默认 30）、`--batch-size`（默认 500）、`--dry-run`（默认开启）、`--yes`（执行删除）、`--audit-log`（默认 `data/audit/legacy_cleanup.log`）、`--purge-expired-trash`（按 `TRASH_RETENTION_DAYS` 清理过期回收站）。

#### Scenario: 默认 dry-run

- **WHEN** 不带 `--yes` 运行工具
- **THEN** 工具 MUST 只输出将删除的 `thread_id` 数量与批次摘要
- **AND** MUST NOT 删除任何 checkpoint 或 `runs` 行

#### Scenario: 只清理无主 checkpoint

- **WHEN** 工具以 `--yes` 运行
- **THEN** 只有不存在 `runs` 行的 `thread_id` MUST 被删除
- **AND** 存在 `runs` 行的会话（包括回收站中的会话）MUST NOT 被删除

#### Scenario: 按批次执行

- **WHEN** legacy checkpoint 数量超过 `--batch-size`
- **THEN** 工具 MUST 分批删除并在每批后提交
- **AND** 中途失败 MUST 保留已提交批次并输出失败批次

#### Scenario: 审计记录

- **WHEN** 工具执行删除
- **THEN** MUST 向审计日志追加时间、模式、批次大小、删除数量与失败数量
- **AND** MUST NOT 记录简历文本或 checkpoint 内容

#### Scenario: 重复执行

- **WHEN** 在已清理过的数据库上再次运行
- **THEN** 工具 MUST 幂等地报告 0 条待清理
- **AND** MUST NOT 报错
