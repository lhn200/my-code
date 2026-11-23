## 1. 前置检查

- [ ] 1.1 确认 `add-career-assistant-core` 已 apply，五个接口（`POST /api/resumes` 与四个运行接口）可访问，且 `goal`、`resume_text`、`jobs`、`job_profiles`、`reviews`、`optimization_history`、`advice`、`errors` 字段已在响应中可用；未满足则停止本 change
- [ ] 1.2 核对核心契约：`POST /api/runs` 不接受顶层 `thread_id`，岗位原始文本字段为 `original_position_text`；实现前再次对照核心代码，若前端内部命名不同，只在 `src/api/types.ts` 做映射，不修改后端字段
- [ ] 1.3 检查 `frontend/` 是否已存在；若存在，记录已有脚手架、依赖与样式约定，避免重复创建
- [ ] 1.4 确认项目未引入 UI 组件库与 Pinia；若已引入，先与本 change 的范围对齐再继续

## 2. 工程脚手架

- [ ] 2.1 创建 `frontend/package.json`，声明 `vue`、`vue-router`、`marked`、`dompurify` 运行时依赖与 `vite`、`typescript`、`vue-tsc`、`vitest`、`@vue/test-utils`、`happy-dom` 开发依赖
- [ ] 2.2 添加 `dev`、`build`、`preview`、`typecheck`、`test` 五个 npm 脚本
- [ ] 2.3 创建 `frontend/vite.config.ts`、`frontend/tsconfig.json`、`frontend/src/env.d.ts`，启用 Vue 单文件组件与路径别名
- [ ] 2.4 创建 `frontend/index.html` 与 `frontend/src/main.ts`，挂载根组件并注册路由
- [ ] 2.5 添加 `.env.example`，说明 `VITE_API_BASE_URL` 的用途与默认同源行为
- [ ] 2.6 创建 `frontend/src/styles/tokens.css` 中性占位变量与 `frontend/src/styles/base.css`，仅定义变量名与基础排版，不包含 `[data-theme]` 分支

## 3. 路由与全局布局

- [ ] 3.1 创建路由表：`/`、`/runs`、`/runs/:threadId`，未知路径重定向到 `/`
- [ ] 3.2 创建 `frontend/src/App.vue` 全局布局，包含顶部导航与主内容区，导航可到达创建页与查询页
- [ ] 3.3 创建三个页面占位组件，确认路由切换与结果页 `threadId` 参数可读取
- [ ] 3.4 为页面添加基础响应式布局与可访问的主内容标题层级

## 4. API 客户端与类型

- [ ] 4.1 创建 `frontend/src/api/types.ts`：定义运行请求（`goal`、`resume_text`、`jobs[{job_id?, title, original_position_text}]`，无顶层 `thread_id`）、运行响应、单个岗位结果、评审、优化历史、错误标记、快照列表与整体状态类型，字段与核心 `AgentState` 对齐
- [ ] 4.2 创建 `frontend/src/api/client.ts`：读取 `VITE_API_BASE_URL`（为空时使用同源 `/api`），统一 JSON 请求、超时与 `AbortController` 取消
- [ ] 4.3 在 `client.ts` 实现 `ApiError` 归一化：解析 422 的 `error.fields`（`field`、`type`、`message`）、404 会话不存在、500 附带 `thread_id`、网络错误与超时分别标记；结构异常时回退为 `message`
- [ ] 4.4 创建 `frontend/src/api/runs.ts`，封装 `POST /api/runs`、`POST /api/runs/{thread_id}/resume`、`GET /api/runs/{thread_id}`、`GET /api/runs/{thread_id}/snapshots`、`GET /api/runs/{thread_id}/snapshots/{checkpoint_id}`
- [ ] 4.5 为 `client.ts` 补单元测试：422 字段错误（`missing` / `string_type` / `unexpected_field`）、422 结构异常回退、404、500、网络失败、超时、基地址覆盖均返回可读的 `ApiError`
- [ ] 4.6 创建 `frontend/src/api/resumes.ts`：用 `FormData` 调用 `POST /api/resumes`，定义响应类型 `{ file_id, file_url?, text, source_type, pages, used_ocr, char_count, low_confidence }`，映射解析类 422 错误码

## 5. 页面状态与共享展示

- [ ] 5.1 创建 `useAnalysisForm`：求职目标、岗位列表、简历内容（粘贴或解析文本）、字段级错误、增删岗位、稳定 `job_id` 生成与提交前校验
- [ ] 5.2 创建 `useRunDetail`：按 `threadId` 拉取状态、恢复会话、加载态、错误态，并在卸载时中止未完成请求
- [ ] 5.3 创建 `useSnapshots`：拉取快照列表、加载态、错误与重试，支持外部触发刷新
- [ ] 5.4 创建 `useRunQuery`：校验 `thread_id` 输入、查询状态、404 与网络错误处理
- [ ] 5.5 创建共享组件：加载态、错误提示、空状态、岗位卡片、评分展示，统一使用样式变量
- [ ] 5.6 创建 Markdown 渲染组件：使用 `marked` 解析并以 `DOMPurify` 过滤，渲染失败时降级为纯文本
- [ ] 5.7 为 Markdown 组件补单元测试：标题与列表正常渲染，`<script>` 与事件属性被过滤，空输入展示空状态
- [ ] 5.8 创建 `useResumeIntake`：输入方式（粘贴 / 上传）、文件选择、类型与大小预校验、上传状态、解析结果、错误码映射、取消请求与重置
- [ ] 5.9 创建 `ResumeUploader.vue`：选择与拖拽上传、文件名与大小展示、上传加载态、解析文本可编辑预览、`used_ocr` 与低置信度提示

## 6. 创建分析页

- [ ] 6.1 实现创建表单 UI：求职目标、岗位区块、简历输入（粘贴 / 上传切换），所有控件有关联 `<label>` 与字段级错误提示
- [ ] 6.2 实现多岗位动态增删：新增保留已填内容，删除只移除目标岗位，至少保留一行
- [ ] 6.3 实现前端校验：目标、岗位数在 1 到 5 之间、每个岗位的标题与 JD、简历内容（粘贴文本或成功解析结果）均为非空白；不通过时不发请求
- [ ] 6.4 实现提交：按 `goal`、`resume_text`、`jobs[{job_id?, title, original_position_text}]` 组装请求体（不发送 `thread_id`），成功后用响应中的 `thread_id` 跳转 `/runs/<thread_id>`
- [ ] 6.5 实现提交加载态与防重复：请求期间禁用按钮，连续点击只产生一次请求
- [ ] 6.6 实现长请求提示与超时：超过 10 秒提示仍在分析；超过 180 秒结束加载，提示后端可能仍在执行，保留表单与重试入口，不展示伪造的 `thread_id`
- [ ] 6.7 为表单逻辑补单元测试：空目标、无岗位、岗位超过 5 个、岗位缺 JD、空简历均被拦截；三个岗位提交三条记录；同标题不同 JD 不合并；删除岗位后顺序正确
- [ ] 6.8 实现页面关闭保护：请求进行中注册 `beforeunload`，并在 `localStorage` 写入 30 分钟有效的待确认标记；应用启动时读取并展示"上次分析可能仍在进行"，关闭后清除
- [ ] 6.9 实现字段级错误定位：把 `jobs[0].original_position_text` 映射到第一个岗位的原始 JD 输入框，多个错误同时展示并在顶部汇总，无法映射的错误回退顶部；补对应单元测试
- [ ] 6.10 实现粘贴 / 上传两种简历输入方式切换，切换保留目标与岗位等字段，提交以当前方式为准
- [ ] 6.11 接入上传：调用 `uploadResume`，上传成功后把解析文本填入可编辑区，并展示页数与 `used_ocr`
- [ ] 6.12 上传态处理：上传中禁用提交与重复选择，支持取消；失败时保留表单其他内容
- [ ] 6.13 错误码提示：`resume_no_text`、`resume_encrypted`、`resume_unreadable`、类型不支持与超限分别给出可操作文案
- [ ] 6.14 OCR 提示：`used_ocr=true` 标注来源，`low_confidence=true` 时提示先核对再提交
- [ ] 6.15 为上传流程补单元测试：类型拦截、超限拦截、上传失败、低置信度提示、切换输入方式、解析后提交不重复上传

## 7. 结果页

- [ ] 7.1 进入 `/runs/:threadId` 时请求运行状态，展示加载态；404 展示会话不存在与返回查询入口
- [ ] 7.2 实现岗位卡片：标题、公司（空值占位）、`score`、`missing`、`issues`；评分 0 与 100 正确显示，缺失项为空时展示"无缺失项"
- [ ] 7.3 实现岗位失败卡片：展示该岗位错误原因，不展示默认分或编造数据
- [ ] 7.4 实现优化历史区域：按轮次升序展示涉及岗位与优化前后分数，无记录时展示空状态，标出达到上限仍未达标的风险
- [ ] 7.5 实现求职建议区域：Markdown 渲染 `advice`，空值或渲染失败时降级为纯文本或空状态
- [ ] 7.6 实现整体状态提示：区分成功、部分成功、失败；部分失败时成功岗位与失败卡片同时可见
- [ ] 7.7 实现会话恢复按钮：未完成会话可点击恢复，恢复中禁用并展示加载态，成功后重新拉取状态，失败时保留已有结果
- [ ] 7.8 实现快照区域：调用快照接口并按时间顺序列出标识，处理加载、空列表与失败重试；恢复成功后刷新快照
- [ ] 7.9 为结果页补组件测试：正常三岗位、部分失败、评分边界、优化历史空状态、快照空状态

## 8. 查询页

- [ ] 8.1 实现 `/runs` 查询表单：输入 `thread_id`，空值前端拦截，提交时展示加载态
- [ ] 8.2 查询成功后展示结果或跳转 `/runs/<thread_id>`；404 与网络错误保留输入并给出重试提示
- [ ] 8.3 结果页快照区域：列出快照后可选择某项，调用 `GET /api/runs/{thread_id}/snapshots/{checkpoint_id}` 以只读方式展示历史状态，并标注"历史快照，非当前状态"；404 时保留当前结果

## 9. 样式与边界约束

- [ ] 9.1 检查所有页面与组件样式，颜色只通过 `var(--...)` 引用，`tokens.css` 之外不得出现 `#`、`rgb(`、`hsl(` 颜色字面量
- [ ] 9.2 确认前端代码不包含 `[data-theme]` 分支、主题持久化、`prefers-color-scheme` 监听，也不修改 `add-dark-mode` 的文件
- [ ] 9.3 为表单错误、整体错误与恢复结果添加 `aria-live` 或等效可访问提示，确认键盘可完成创建与查询流程
- [ ] 9.4 检查评分展示不只依赖颜色，风险与失败状态有文字说明
- [ ] 9.5 品牌色与排版暂不定稿：只使用 `tokens.css` 的中性占位值，不锁定色号与字体组合，待页面生成后统一调整

## 10. 验证

- [ ] 10.1 运行 `npm run typecheck` 与 `npm run build`，确认零类型错误且构建成功
- [ ] 10.2 运行 `npm run test`，确认 API 客户端、表单校验、上传流程、Markdown 过滤与结果页组件测试全部通过
- [ ] 10.3 连接已 apply 的后端，手工验证"目标 + 3 个岗位 + 简历"创建成功、跳转结果页且三张岗位卡片与建议正常展示
- [ ] 10.4 手工验证 404、500、网络中断与超时四种失败路径，确认提示可读、页面不崩溃、表单内容不丢失
- [ ] 10.5 手工验证按 `thread_id` 查询、从结果页恢复未完成会话、快照列表刷新、选择快照查看历史状态四个流程
- [ ] 10.6 按 `add-career-assistant-core` 的实际响应复核 `src/api/types.ts` 与字段名；发现偏差时只修改 API 层并重新跑 10.1
- [ ] 10.7 手工验证上传：PDF、DOCX、图片各上传一次，确认解析预览、OCR 标记与低置信度提示，且提交不重复上传
- [ ] 10.8 手工验证长请求：提交中关闭页面出现浏览器确认；超时后保留表单且不展示伪造 `thread_id`；重开应用出现待确认提示并可关闭
- [ ] 10.9 验证回滚：删除 `frontend/` 后后端接口与数据文件不受影响，仓库仍可正常启动
