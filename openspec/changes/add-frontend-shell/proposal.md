## Why

后端已经规划了完整的 LangGraph 分析闭环与 `POST /api/runs` 等接口契约，但仓库里没有任何前端代码。用户目前只能手工构造 HTTP 请求才能使用「多岗位分析 + 简历匹配 + 优化历史 + 求职建议」，无法完成一次真实的求职决策流程，也无法直观看到评分、缺失项与优化前后差异。

在账号体系、部署与暗色模式之前先落地前端骨架与核心工作台，可以把 API 契约真正跑通，并为后续 change 提供稳定的页面结构、样式变量基线与路由约定，避免每个后续能力各自新建一套壳。

## What Changes

- 新增 Vue 3 + Vite + TypeScript 前端工程（`frontend/`），使用 Composition API + `<script setup>` 与 Vue Router，不引入 UI 组件库与 Pinia。
- 新增全局布局、路由与三份页面：`/` 创建分析、`/runs/:threadId` 结果页、`/runs` 按 `thread_id` 查询入口。
- 新增 API 客户端与手写 TypeScript 类型，对接 `POST /api/resumes`、`POST /api/runs`、`POST /api/runs/{thread_id}/resume`、`GET /api/runs/{thread_id}`、`GET /api/runs/{thread_id}/snapshots`；基地址通过 `VITE_API_BASE_URL` 配置。
- 新增创建分析表单：求职目标、可增删的多个岗位（1–5 个，标题 + JD）、简历输入（粘贴纯文本，或上传 PDF / DOCX / 图片经 `POST /api/resumes` 解析后回填可编辑文本），含前端校验、提交中 loading、长请求提示与超时提示。
- 新增结果视图：岗位卡片、0–100 匹配评分、缺失项与问题清单、优化历史、教练建议 Markdown 渲染；支持部分失败状态展示。
- 新增会话能力：按 `thread_id` 查询状态、从快照恢复会话、展示快照列表。
- 统一错误处理：把后端 422 / 404 / 500 映射为可读提示，并保留 `thread_id` 便于排查。
- 样式使用原生 CSS + CSS 变量，颜色一律通过 `var(--...)` 引用；token 由 `add-dark-mode` 提供，本 change 不实现主题切换。
- 明确不做：注册登录（留给 `add-auth-sessions`）、主题切换实现（留给 `add-dark-mode`）、浏览器内 PDF / DOCX 解析与 OCR（统一由后端解析）、流式输出（SSE/WebSocket）、E2E 测试框架。

## Capabilities

### New Capabilities
- `frontend-shell`: Vite 工程脚手架、路由与全局布局、API 客户端与 TypeScript 类型契约、统一错误处理与加载态。
- `analysis-workspace-ui`: 创建分析表单、简历粘贴或上传解析预览、多岗位提交、结果页渲染、部分失败展示、`thread_id` 查询与恢复、快照列表。

### Modified Capabilities
<!-- openspec/specs/ 下没有既有 capability，且 add-dark-mode 的 theme-switching 不在本 change 修改范围内，无修改项 -->

## Architecture Impact

前端为纯展示与编排层，不复制后端业务规则：

- 页面只消费后端返回的状态结构（`job_profiles`、`reviews`、`optimization_history`、`advice`、`errors`），不在前端重新计算评分或回流结论。
- 状态所有权：表单草稿与请求状态放在页面级 composable 中，跨页面共享的只有路由参数（`threadId`）；不引入全局 store。
- 样式所有权：所有颜色引用 `add-dark-mode` 定义的 CSS 变量；本 change 只保证组件不硬编码色值，不定义主题信号与持久化逻辑。
- 数据获取：首版使用同步请求 + 请求超时控制，不引入轮询或流式；后端接口形态变化不影响路由与组件结构，只影响 `src/api/` 与类型定义。
- 简历解析边界：前端只负责选择文件、调用上传接口与展示解析结果，不在浏览器内解析 PDF / DOCX 或执行 OCR；原始文件不持久化到浏览器，刷新即丢弃，如需引用只保留服务端返回的 `file_id`。
- 鉴权边界：本 change 假设接口无鉴权；`add-auth-sessions` 落地时在 API 客户端集中注入凭据，页面层不改动。

依赖顺序：必须先 apply `add-career-assistant-core`（提供全部接口与状态字段）；`add-dark-mode` 需在本 change 之后 apply（本 change 建立 `frontend/` 骨架与变量使用约定）。

## Impact

- `frontend/index.html`、`frontend/vite.config.ts`、`frontend/tsconfig.json`、`frontend/package.json`：工程脚手架与 `VITE_API_BASE_URL`。
- `frontend/src/main.ts`、`frontend/src/App.vue`、`frontend/src/router/`：入口、全局布局与路由表。
- `frontend/src/api/`：`client.ts`、`types.ts`、`runs.ts`、`resumes.ts` 与五个接口封装。
- `frontend/src/composables/`：分析表单、简历摄入、运行详情、快照列表等页面级状态。
- `frontend/src/views/`、`frontend/src/components/`：创建页、结果页、查询页、简历上传与岗位卡片等展示组件。
- `frontend/src/styles/`：布局与基础样式，颜色只引用 `var(--...)`。
- 依赖：`vue`、`vue-router`、`marked`、`dompurify`，以及 `vite`、`typescript`、`vue-tsc`、`vitest` 等开发依赖；不新增 UI 组件库与状态管理库。
