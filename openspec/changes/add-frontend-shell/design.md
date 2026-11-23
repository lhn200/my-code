## Context

`add-career-assistant-core` 已经定义 LangGraph 工作流、`AgentState` 字段（`goal`、`resume_text`、`jobs`、`job_profiles`、`reviews`、`optimization_history`、`advice`、`errors` 等）、五个运行接口与简历上传解析接口，但仓库没有前端。`add-dark-mode` 已规划 `theme-switching`，并将建立前端样式 token，但它依赖一个可运行的 `frontend/` 骨架。

本 change 因此承担"第一条可见产品链路"：把同步运行接口变成可操作的创建页、结果页与会话恢复入口，同时建立后续 change 可复用的工程结构、API 客户端、类型与样式引用约定。约束是 Vue 3 + Vite + TypeScript、Composition API、Vue Router、原生 CSS + CSS 变量；不引入 UI 组件库与 Pinia；不做鉴权、浏览器内文件解析与 OCR、流式输出与主题切换。

## Goals / Non-Goals

**Goals:**
- 建立可开发、可构建、可类型检查的 `frontend/` 工程与三页路由骨架。
- 用一个 API 模块封装五个运行接口，手写与后端状态契约一致的类型，页面不直接发请求。
- 完成"填写目标 + 多个岗位 + 简历 → 提交 → 查看评分/缺失项/优化历史/建议"的闭环。
- 用同步请求 + 客户端超时 + 本地待确认标记处理长耗时，并支持会话查询、恢复、快照列表与按 checkpoint 读取历史状态。
- 所有颜色从 CSS 变量读取，为 `add-dark-mode` 留出零返工的接入点。

**Non-Goals:**
- 不做注册、登录、用户空间与按用户隔离（留给 `add-auth-sessions`）。
- 不实现主题切换、主题持久化与系统主题监听（留给 `add-dark-mode`）。
- 不做浏览器内 PDF / DOCX 解析与 OCR（统一调用后端 `POST /api/resumes`）、不做流式输出（SSE/WebSocket）。
- 不做 E2E 测试框架、不做组件库、不做全局状态管理。
- 不在前端重新计算评分、回流结论或改写建议。

## Architecture Assessment

### Existing Design Reuse

- 复用 `add-career-assistant-core` 的接口路径、`thread_id` 语义与状态字段命名，前端类型直接按该契约手写，不另造领域模型。
- 复用 `add-dark-mode` 的样式变量方案与 `frontend/src/styles/` 目录约定；本 change 只消费 `var(--...)`，不建立第二套主题机制。
- 复用后续 `add-auth-sessions` 预期需要的集中请求入口：所有请求经 `src/api/client.ts`，将来只在该文件注入凭据，页面无需改动。
- 无可复用的现有 Vue 代码、组件或 store。

### Boundaries and Ownership

```
views/                页面编排：读取路由参数、组合 composable、渲染布局
  └─ composables/     页面级状态：表单草稿、运行详情、快照、查询
       └─ api/        client.ts（基地址/超时/错误映射）+ runs.ts（五个运行接口）+ resumes.ts（上传解析）+ types.ts
            └─ 后端 FastAPI（唯一业务真相来源）
router/               路由表与 thread_id 参数解析
styles/               基础排版与变量引用
```

- 状态所有权：表单草稿属于创建页，运行详情与快照属于结果页，查询输入属于查询页；跨页面唯一共享状态是路由参数 `threadId`，通过 URL 传递，不使用全局 store。
- 数据所有权：岗位评分、缺失项、优化历史、建议、整体状态均由后端返回，前端只做展示与空值处理。
- 请求所有权：只有 `api/client.ts` 负责基地址、超时、JSON 解析和错误归一化；组件不得直接调用 `fetch`。
- 失败边界：核心结果请求失败显示整体错误；快照请求失败只影响快照区域；Markdown 渲染失败降级为纯文本；单岗位错误在卡片内呈现，不阻塞其他卡片。
- 超时与取消：GET 请求在组件卸载时通过 `AbortController` 取消；提交请求超时后中止本地等待，保留表单与本地待确认标记，不假设后端已停止执行。
- 重复触发：所有提交/恢复按钮在请求期间禁用；提交不携带 `thread_id`，请求进行中注册 `beforeunload` 警告，避免关闭页面或重复点击产生两个运行。

### Options and Rationale

| 决策点 | 选择 | 替代方案 | 理由 |
| --- | --- | --- | --- |
| 工程形态 | Vue 3 + Vite + TS，`<script setup>` | Nuxt；Vue CLI | 纯 SPA、无 SSR 需求；Vite 启动与构建快，配置最少 |
| 状态管理 | 页面级 composable + 路由参数 | Pinia；provide/inject 全局单例 | 共享状态只有一个 `threadId`，引入 store 属过度设计；composable 易测试、易按页面卸载释放 |
| 路由职责 | `/runs/:threadId` 为结果页唯一入口 | 用 query 参数或内存变量传结果 | 可刷新、可分享、可直接查询；避免刷新后状态丢失 |
| HTTP 客户端 | 轻量 `fetch` 封装 + 手写类型 | axios；OpenAPI 代码生成 | 五个接口规模小；手写类型显式可控，不引入生成链路；封装保留后续替换空间 |
| 类型来源 | `src/api/types.ts` 手写并与后端对齐 | 从后端 Pydantic 生成 TS | 后端当前无稳定 OpenAPI 产物；手写类型配合类型检查与契约核对任务足够 |
| 执行方式 | 同步请求 + 客户端超时 + 本地待确认标记 | 轮询任务状态；SSE 流式 | 后端首版就是同步接口；轮询会增加状态机与后端改动；超时后提示用户稍后查看，不用客户端伪造标识 |
| 简历解析位置 | 前端上传文件，后端解析并返回文本 | 浏览器用 pdf.js / mammoth.js 解析 | 与后端解析能力保持单一实现；OCR 无法在浏览器可靠完成；前端只负责预览与人工校对 |
| thread_id | 服务端生成，响应返回 | 前端提交前生成并随请求发送 | 请求体不接受 `thread_id`，避免客户端伪造与冲突；代价是超时后无法立即定位会话，用 30 分钟本地待确认标记兜底 |
| Markdown | `marked` 解析 + `DOMPurify` 过滤 | 纯文本 `pre-wrap`；自己写解析器 | 建议含标题与列表，纯文本损失结构；自写解析器易出安全问题；两个小依赖成本可控 |
| 样式 | 原生 CSS + CSS 变量，按页面/组件拆分 | Tailwind；CSS Modules；UI 库 | 与 `add-dark-mode` 既有方案一致；变量层是唯一颜色来源，组件不写死色值 |
| 错误处理 | 集中在客户端归一化为 `ApiError` | 每个页面自行判断 `response.status` | 避免 422/404/500 文案散落；页面只消费 `status`、`message`、`threadId` |
| 测试层次 | Vitest 单测 composable / 客户端 / 渲染 | 引入 Playwright 跑 E2E | 本 change 明确不做 E2E；关键映射逻辑可脱离浏览器测试 |

### Quality Attributes

- 安全：简历与 JD 只作为文本展示，不使用 `v-html`；`advice` 必须经 `DOMPurify` 过滤后渲染；日志与错误提示不得打印简历原文。接口无鉴权，因此仅用于本地/内网。
- 可靠性：请求超时与组件卸载时正确结束加载态；关闭/刷新进行中的页面有警告；快照失败不影响主结果；单岗位失败可在卡片内降级。
- 可用性：表单错误定位到字段；加载态禁用重复提交；长请求有持续提示；错误提供重试或返回入口；评分不只靠颜色表达。
- 可维护性：接口路径与字段名只在 `src/api/` 出现一次；页面通过 composable 获取数据，替换执行方式（轮询/SSE）时页面不变。
- 可测试性：表单校验、错误映射、超时处理、Markdown 过滤均可作为纯逻辑单测；组件测试覆盖空状态与部分失败。
- 可访问性：表单控件有 `<label>`；错误提示通过 `aria-live` 或关联 `aria-describedby` 暴露；结果卡片标题层级稳定。

### Complexity and Exceptions

新增一个前端工程与两个运行时依赖（`vue`、`vue-router`）以及开发依赖（`vite`、`typescript`、`vue-tsc`、`vitest`、`@vue/test-utils`、`happy-dom`）；`marked`、`dompurify` 为建议文本渲染所需。均为本能力的必要成本，不引入 UI 框架或状态库。

为在 `add-dark-mode` 落地前保持页面可读，本 change 允许在 `frontend/src/styles/tokens.css` 放一组中性占位变量，但 MUST NOT 包含 `[data-theme]` 分支、主题持久化或系统主题监听；`add-dark-mode` 接管该文件后替换取值并新增深色变量。除此之外不新增服务、存储或协议。回滚方式：删除 `frontend/` 目录，后端无改动。

## Decisions

1. **目录与路由固定为 `frontend/` + 三页结构**：`/` 创建、`/runs` 查询、`/runs/:threadId` 详情；未知路由重定向首页。`threadId` 只从路由参数读取，结果页刷新后重新请求后端，不依赖内存传值。
2. **API 客户端集中封装**：`VITE_API_BASE_URL` 为空时使用同源 `/api`；统一设置 `Content-Type: application/json`、超时与 JSON 解析；将 HTTP 状态归一化为 `ApiError { status, code, message, fields: FieldError[], threadId? }`。422 解析后端 `error.fields`，按 `field` 路径映射到表单控件；无法映射的字段与结构异常回退到顶部汇总文案；404 映射为"会话不存在"；500 附带 `thread_id` 供排查。
3. **`thread_id` 只由服务端生成**：`POST /api/runs` 请求体只包含 `goal`、`resume_text`、`jobs`，不接受顶层 `thread_id`；每个岗位使用后端字段 `original_position_text`，前端内部可叫 `positionText`，但 MUST 只在 `api/types.ts` 一处映射。创建成功后使用响应中的 `thread_id` 跳转详情页。
4. **页面状态全部放在页面级 composable**：`useAnalysisForm`、`useRunDetail`、`useSnapshots`、`useRunQuery` 各自暴露 `data`、`isLoading`、`error` 与操作函数；组件只做展示与事件转发，不直接持有请求逻辑。
5. **结果渲染完全由后端字段驱动**：岗位卡片读取 `job_profiles` 与 `reviews`，评分取 `score`，缺失项取 `missing`，问题取 `issues`，优化历史取 `optimization_history`，建议取 `advice`，失败取 `errors`。空数组展示空状态，不做默认 0 分或补全数据。
6. **长请求采用"同步等待 + 本地待确认标记"**：默认提示阈值 10 秒、超时 180 秒（常量集中定义）；超时不视为后端失败，页面保留表单并提示"后端可能仍在执行"，提供重试入口，不展示伪造的 `thread_id`。请求进行中注册 `beforeunload` 警告，并在 `localStorage` 写入 30 分钟有效的待确认标记；重新打开应用时展示提示，可前往会话列表（认证可用时）或关闭。后续替换为轮询或 SSE 时只改 composable 与客户端。
7. **Markdown 渲染必须过滤**：`marked` 输出后交给 `DOMPurify`，再写入容器；渲染异常或过滤失败时回退为纯文本展示。禁止直接渲染后端字符串。
8. **样式只消费变量，视觉规范暂不定稿**：页面与组件样式统一写 `var(--color-...)`、`var(--space-...)` 等变量；本 change 不读写 `data-theme`、不监听 `prefers-color-scheme`、不写 `localStorage` 主题 key。`add-dark-mode` 负责变量取值与切换。品牌色与排版在页面生成后再定稿，本 change 只使用中性占位值，不锁定具体色号与字体组合。
9. **依赖顺序写死**：执行本 change 前必须先 apply `add-career-assistant-core`；`add-dark-mode` 必须在本 change 之后 apply。tasks 中把两项作为前置检查，避免在缺失接口或骨架的情况下返工。

## Risks / Trade-offs

- [后端请求/响应字段与手写类型漂移] → 所有类型集中在 `src/api/types.ts`，tasks 增加"逐字段核对 `AgentState`"与类型检查；契约变化只改一处。
- [同步接口耗时长，浏览器或代理提前断开] → 客户端超时 + 本地待确认标记 + 重试入口；后续以 SSE/轮询替换，页面结构不变。
- [超时后用户重复提交产生两次运行] → 请求进行中禁用提交并注册 `beforeunload`；超时提示明确"可能仍在执行"，重试前需用户确认。
- [`advice` Markdown 触发 XSS] → `DOMPurify` 过滤，禁止未过滤的 `v-html`；单测覆盖 `<script>` 与事件属性。
- [422 错误体结构与预期不一致] → 以 `error.fields` 为准做字段映射，结构异常时回退顶部汇总；tasks 中用固定样例覆盖 `missing`、`string_type`、`unexpected_field`。
- [占位 token 与 `add-dark-mode` 冲突] → 占位内容只含中性变量，不含主题分支；`add-dark-mode` 覆盖该文件，本 change 不另建颜色文件。
- [无鉴权导致接口暴露] → 明确仅本地/内网使用；`add-auth-sessions` 在客户端集中注入凭据并处理 401。
- [无组件库导致交互一致性成本] → 建立 `components/` 下少量基础展示组件与统一表单样式，避免每页各写一套。
- [只用颜色表达评分] → 分数以文本展示，颜色仅为辅助，并保留风险文字说明。
- [上传或 OCR 耗时导致请求超时] → 前端预校验类型与 5MB 上限，上传与提交分别有加载态和取消；失败时保留已填内容并提示重试或改用粘贴。
- [原始简历文件停留在前端] → 文件只存在于上传函数调用栈与局部状态，不写入全局 store 或 localStorage；解析后仅保留文本与服务端返回的 `file_id`，刷新即丢弃。
- [OCR 识别错误被直接提交] → 展示 `used_ocr` 与低置信度提示，解析文本可编辑，要求用户核对后再提交。

## Migration Plan

N/A（新增前端，无历史数据迁移）。执行顺序：apply `add-career-assistant-core` → 执行本 change 创建 `frontend/` → apply `add-dark-mode` 接管 token 与主题。本 change 不改后端、数据库或部署配置。回滚：删除 `frontend/` 即可，不影响后端与 checkpoint。

## Open Questions

- 已决策：`POST /api/runs` 不接受顶层 `thread_id`；岗位原始文本字段固定为 `original_position_text`，前端只在 `api/types.ts` 适配。
- 已决策：422 为字段级结构 `error.fields`，表单按路径定位错误。
- 已决策：快照接口提供按 `checkpoint_id` 读取历史状态的端点。
- 已决策：长请求在页面关闭时给出警告，重开后展示待确认提示。
- 已决策：品牌色与排版暂不定稿，页面生成后统一调整。
