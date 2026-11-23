## Context

仓库当前只有 `.env`，前端尚未创建；规划中的前端为 Vue 3 + Vite（`frontend/`），无既有样式体系、无既有 specs 可复用。暗色模式因此是一次"随前端骨架一起落地"的基础能力建设，而不是在成熟代码上做局部改造。技术栈未包含 Tailwind / CSS-in-JS，样式按原生 CSS + CSS 自定义属性规划。

## Goals / Non-Goals

**Goals:**
- 建立一套可被所有页面继承的浅色 / 深色 token 变量层。
- 实现 `light` / `dark` / `system` 三态选择、持久化、首屏无闪烁与系统联动。
- 让主题逻辑集中在一处，组件层只消费变量，降低后续新增页面的适配成本。

**Non-Goals:**
- 不做主题自定义（自定义强调色、字体缩放、"高对比度"模式）。
- 不做服务端持久化（主题偏好属于设备级偏好，不进入用户账号或后端 API）。
- 不改动后端、LangGraph 工作流、SQLite checkpoint、Docker / Nginx 配置。
- 不在本次范围内为图表、PDF 预览等第三方渲染内容做深度配色适配。

## Architecture Assessment

### Existing Design Reuse

无既有前端代码与 specs 可复用。设计按"新建前端骨架时的第一批基础模块"处理，所有路径以规划中的 `frontend/` 为准；若实际脚手架目录名不同（如 `web/`），按同等结构迁移即可。

### Boundaries and Ownership

- 状态所有权：`useTheme` composable 是主题模式的唯一写入口；组件不得直接读写 `localStorage` 或修改根元素属性。
- 呈现所有权：`html[data-theme="light|dark"]` 是唯一主题信号；token 变量只在样式层定义，组件只引用 `var(--...)`。
- 首屏所有权：`index.html` 内联脚本负责"挂载前"应用主题，属于唯一的脚本级重复实现（无法等待 Vue 启动）。
- 失败边界：`localStorage` 读写包在 try/catch 中，失败时降级为内存态，不阻塞渲染；`matchMedia` 不支持时回退为浅色。

### Options and Rationale

| 决策点 | 选择 | 替代方案 | 理由 |
| --- | --- | --- | --- |
| 主题信号载体 | `html[data-theme]` + CSS 变量 | 切换 `<link>` 样式表；CSS-in-JS 运行时 | 变量方案零依赖、可首屏内联、切换无网络请求；属性选择器比 class 语义更清晰，也不与工具类冲突 |
| 状态管理 | 独立 composable + `ref` | Pinia store | 主题是单一标量状态，引入 store 属过度设计；若前端后续已用 Pinia，可无痛把 composable 内部实现替换为 store |
| 持久化 | `localStorage`（key `career-assistant-theme`） | Cookie；后端用户设置 | 无需随请求发送，无跨端同步需求；Cookie 会污染 API 请求且受 Nginx 配置影响 |
| 三态建模 | 存储 `light`/`dark`/`system`，生效值由 `system` + `matchMedia` 推导 | 只存布尔 `isDark` | 布尔值无法表达"跟随系统"，且系统切换后无法自动恢复联动 |
| 首屏防闪烁 | `index.html` 内联同步脚本 | Vue 插件在 `setup` 中初始化；`v-cloak` | 只有内联脚本能在首次绘制前执行；插件方式必然产生浅色闪帧 |
| 切换控件形态 | 导航栏内的三态分段控件（浅色/深色/跟随系统） | 单个开关按钮循环切换 | 三态用开关表达会产生"当前是系统还是手动"的认知歧义 |

### Quality Attributes

- 可访问性：正文与背景对比度 ≥ 4.5:1；控件提供 `aria-pressed` 或 `aria-checked` 与可见文本标签，不只用颜色区分状态。
- 性能：内联脚本 < 1KB、无网络请求；主题切换只改一个属性，不触发组件重渲染（Vue 状态不参与样式计算）。
- 可测试性：`useTheme` 的纯逻辑（存储值解析、生效主题推导）可脱离 DOM 单测；DOM 行为可用 Vitest + happy-dom 覆盖。
- 可维护性：颜色只在 tokens 文件出现一次；新增组件的验收标准是"不写主题分支也能在两种模式下可读"。

### Complexity and Exceptions

不新增抽象层、不新增运行时依赖、不新增服务或存储。唯一的重复实现是首屏内联脚本与 `useTheme` 的解析逻辑，属于"为了避免闪烁必须接受的少量重复"；控制方式是把解析规则收敛到同一份常量注释并在 tasks 中要求两侧规则一致。

## Decisions

1. **主题信号用 `data-theme` 属性 + CSS 变量**。`system` 模式不写属性值，而是解析为 `light`/`dark` 后写入，保证样式层只有两种状态分支。
2. **`useTheme` 单向数据流**：`mode`（用户选择）→ 解析 `resolvedTheme` → 写 `data-theme` → 写 `localStorage`；任何 UI 只调用 `setMode`。
3. **首屏内联脚本与 composable 共享解析规则**：读取 key、校验枚举、非法值回退 `system`、`system` 再按 `matchMedia` 解析。
4. **系统联动只在 `system` 模式挂监听**：`matchMedia('(prefers-color-scheme: dark)')` 的 `change` 事件在组件卸载时移除，避免重复监听。
5. **切换控件放在全局导航/顶栏**，三态分段控件；当前生效主题以文字标签展示，避免"图标含义需要猜测"。
6. **不做主题过渡动画的默认开启**：仅在颜色属性上提供短过渡，并尊重 `prefers-reduced-motion`。

## Risks / Trade-offs

- [前端骨架尚未创建，change 无法直接 apply] → 在 tasks 中把"前端脚手架就绪"列为前置检查；若未就绪，先完成脚手架再执行本 change。
- [首屏脚本与 composable 规则漂移导致行为不一致] → 两侧使用同一 key 与枚举，tasks 中要求对照验证四个场景（无值 / 非法值 / dark / light）。
- [第三方组件（图表、富文本、PDF 预览）不继承变量] → 明确列为 Non-Goal，后续单独提案；本次只保证自研 UI 可读。
- [深色下低对比度风险] → 在验收任务中加入对比度检查与截图核对。
- [存储不可用（隐私模式）] → 降级为内存态，仅在当前会话生效，不报错。

## Migration Plan

N/A（新增能力，无数据迁移）。若前端骨架先于本 change 完成，则本 change 直接叠加；若本 change 先执行，需先产出最小 Vue 3 + Vite 脚手架（`index.html`、`src/main.ts`、根布局、tokens 文件）。回滚方式：移除 `data-theme` 写入与内联脚本，恢复单一浅色 tokens，即回到无暗色模式状态，不涉及数据清理。

## Open Questions

- 已决策：品牌色与排版规范暂不定稿，本 change 只约束 token 机制（新增深色变量与 `data-theme` 切换），不锁定具体色号与字体组合；待 `add-frontend-shell` 产出页面后按实际效果统一调整。
- 是否需要为简历预览 / 报告长文提供"纯深色阅读模式"（更高对比、更弱强调色）？当前按普通深色处理，后续可单独立项。
