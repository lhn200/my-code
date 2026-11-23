## ADDED Requirements

### Requirement: 前端工程基线

系统 SHALL 在 `frontend/` 提供基于 Vue 3 + Vite + TypeScript 的前端工程，组件使用 Composition API 与 `<script setup>`，并至少提供开发、构建、预览与类型检查四个 npm 脚本。

#### Scenario: 本地启动工程

- **WHEN** 开发者在 `frontend/` 执行依赖安装后运行开发脚本
- **THEN** 本地开发服务器 MUST 正常启动并渲染应用根布局
- **AND** 控制台 MUST NOT 出现未处理的编译错误

#### Scenario: 生产构建与类型检查

- **WHEN** 开发者执行构建脚本与类型检查脚本
- **THEN** 构建 MUST 成功产出静态资源
- **AND** 类型检查 MUST 以零错误退出

#### Scenario: 技术栈边界

- **WHEN** 检查 `frontend/package.json` 的依赖清单
- **THEN** MUST NOT 引入 UI 组件库或 Pinia
- **AND** 跨页面共享状态 MUST 通过路由参数与页面级 composable 表达

### Requirement: 路由与全局布局

前端 SHALL 使用 Vue Router 提供三个页面路由：`/` 创建分析、`/runs/:threadId` 结果页、`/runs` 按 `thread_id` 查询入口，并由统一全局布局承载导航与页面内容。

#### Scenario: 访问创建页

- **WHEN** 用户访问 `/`
- **THEN** 页面 MUST 渲染创建分析表单
- **AND** 全局布局的导航 MUST 可见

#### Scenario: 通过链接直达结果页

- **WHEN** 用户直接访问或刷新 `/runs/<thread_id>`
- **THEN** 路由 MUST 解析出 `threadId` 参数
- **AND** 结果页 MUST 以该参数发起状态查询，而不是要求用户重新输入

#### Scenario: 访问查询入口

- **WHEN** 用户访问 `/runs`
- **THEN** 页面 MUST 渲染 `thread_id` 查询入口
- **AND** MUST NOT 自动跳转到某个具体会话

#### Scenario: 访问未知路径

- **WHEN** 用户访问未定义的路由
- **THEN** 前端 MUST 展示可返回首页的提示页，或重定向到 `/`
- **AND** MUST NOT 渲染空白页面

### Requirement: API 客户端与类型契约

前端 SHALL 在 `src/api/` 提供统一的 API 客户端，基地址通过 `VITE_API_BASE_URL` 配置，并手写与 `add-career-assistant-core` 状态契约对齐的 TypeScript 类型。

#### Scenario: 配置后端基地址

- **WHEN** 构建时设置 `VITE_API_BASE_URL` 为后端地址
- **THEN** 所有 API 请求 MUST 以该地址为前缀
- **AND** 未设置时 MUST 使用同源相对路径访问 `/api/...`

#### Scenario: 调用运行接口

- **WHEN** 前端发起创建、恢复、查询或快照请求
- **THEN** MUST 分别使用 `POST /api/runs`、`POST /api/runs/{thread_id}/resume`、`GET /api/runs/{thread_id}`、`GET /api/runs/{thread_id}/snapshots`、`GET /api/runs/{thread_id}/snapshots/{checkpoint_id}`
- **AND** 请求与响应 MUST 经过统一客户端封装，页面组件不得直接调用 `fetch`

#### Scenario: 类型与后端字段一致

- **WHEN** 读取运行结果类型定义
- **THEN** 类型 MUST 覆盖 `thread_id`、`job_profiles`、`reviews`、`optimization_history`、`advice`、`errors` 等后端状态字段
- **AND** 创建请求类型 MUST 使用 `goal`、`resume_text`、`jobs[{job_id?, title, original_position_text}]`，MUST NOT 包含顶层 `thread_id`
- **AND** 若页面内部使用 `positionText` 等更短命名，MUST 只在 `api/types.ts` 做映射，不得要求后端改名
- **AND** 类型 MUST 手工维护，不引入代码生成流程

### Requirement: 统一错误处理与错误码映射

前端 SHALL 将后端错误与网络故障统一转换为用户可读的提示，并根据 HTTP 状态码区分处理，不得直接向用户展示原始响应体、堆栈或 HTML。

#### Scenario: 入参校验失败

- **WHEN** 后端返回 422
- **THEN** 前端 MUST 解析 `error.fields`，按 `field` 路径把错误映射到对应输入项
- **AND** `field` 形如 `jobs[0].original_position_text` 时 MUST 定位到第 1 个岗位的原始 JD 输入框
- **AND** 无法映射的字段错误 MUST 汇总展示在表单顶部
- **AND** MUST NOT 直接展示原始响应体或堆栈

#### Scenario: 会话不存在

- **WHEN** 后端对查询或恢复请求返回 404
- **THEN** 前端 MUST 提示会话不存在或已失效
- **AND** MUST 保持当前页面可用，便于用户重新输入 `thread_id`

#### Scenario: 服务端内部错误

- **WHEN** 后端返回 500
- **THEN** 前端 MUST 展示通用失败提示
- **AND** 若响应中包含 `thread_id`，MUST 一并展示以便后续按会话排查

#### Scenario: 网络不可达或超时

- **WHEN** 请求因网络错误或超时未获得响应
- **THEN** 前端 MUST 提示网络或超时问题并给出重试入口
- **AND** MUST NOT 将其误报为业务校验失败

### Requirement: 加载态与长请求反馈

所有异步操作 SHALL 暴露明确的加载状态；提交类操作在请求进行中 MUST 防止重复触发，长请求 MUST 提供持续反馈。

#### Scenario: 提交中的界面状态

- **WHEN** 用户触发一次创建或恢复请求
- **THEN** 触发控件 MUST 进入加载态并禁用重复点击
- **AND** 页面 MUST 展示当前正在进行的操作说明

#### Scenario: 请求时间较长

- **WHEN** 请求持续时间超过预设提示阈值
- **THEN** 页面 MUST 提示分析仍在进行
- **AND** 超时后 MUST 结束加载态并展示可重试的错误提示

### Requirement: 样式通过 CSS 变量引用颜色

页面与组件的颜色 SHALL 通过 `var(--...)` 引用 CSS 变量，变量集中在样式层定义；组件与页面样式中 MUST NOT 出现颜色字面量。主题取值与切换由 `add-dark-mode` 提供，本 change 不实现主题逻辑。

#### Scenario: 新增页面或组件

- **WHEN** 开发者新增使用颜色的样式规则
- **THEN** 颜色 MUST 使用 `var(--...)` 引用
- **AND** MUST NOT 出现 `#`、`rgb(`、`hsl(` 等颜色字面量

#### Scenario: 缺少所需变量

- **WHEN** 页面引用的变量在样式层尚未定义
- **THEN** MUST 在样式层的变量定义处补齐变量名
- **AND** MUST NOT 在组件内以颜色字面量兜底

#### Scenario: 主题职责边界

- **WHEN** 检查本 change 的前端代码
- **THEN** MUST NOT 包含 `[data-theme]` 切换分支、主题持久化或系统主题监听
- **AND** MUST NOT 修改 `add-dark-mode` 的 spec 与实现
