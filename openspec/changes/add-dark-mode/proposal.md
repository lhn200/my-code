## Why

项目规划为 Vue 3 + Vite 的前后端分离前端，但目前仓库只有 `.env`，前端尚未搭建。暗色模式属于基础体验能力，若等页面写完再补，会迫使所有组件返工替换硬编码颜色；在搭建阶段就把主题 token 纳入设计，成本最低。

求职场景下用户会长时间阅读岗位分析、简历匹配报告和求职建议等大段文本，浅色界面在低光环境下容易疲劳，暗色模式能直接改善阅读体验。

## What Changes

- 新增全局主题能力：`light` / `dark` / `system` 三态，默认 `system`。
- 首屏在渲染前应用主题，避免浅色闪烁（FOUC）。
- 处于 `system` 模式时监听 `prefers-color-scheme` 变化并实时切换。
- 用户手动选择后写入 `localStorage`，刷新与重开页面保持选择。
- 提供主题切换入口（浅色 / 深色 / 跟随系统），并展示当前生效模式。
- 颜色统一走 CSS 变量（design tokens），组件不直接写死色值。
- 不涉及后端 API、SQLite checkpoint、LangGraph 工作流与 Docker/Nginx 配置变更。

## Capabilities

### New Capabilities
- `theme-switching`: 全局主题模式的选择、首屏应用、持久化与系统主题联动规则。

### Modified Capabilities
<!-- 当前 openspec/specs/ 下没有既有 capability，无修改项 -->

## Architecture Impact

架构影响局限在前端展示层：

- 与规划中的 Vue 3 前端设计系统共享一套 token 体系，后续新页面默认继承，不新增第二套样式方案。
- 主题状态放在独立 composable 中，避免散落在各组件；根元素通过 `data-theme` 属性驱动变量切换。
- 后端、数据模型、checkpoint、部署配置均无变化；静态资源仍由 Nginx 原样提供。

## Impact

- `frontend/index.html`：首屏内联脚本，读取持久化主题并写入根元素属性。
- `frontend/src/styles/`（tokens / 全局样式）：新增浅色与深色两套变量及基础底色、文字色定义。
- `frontend/src/composables/useTheme.ts`：主题状态、持久化、系统主题监听。
- `frontend/src/components/`（导航栏或设置区）：主题切换控件。
- `frontend/src/App.vue` 及全局布局：接入主题属性与背景/文字基础样式。
- 依赖：无新增运行时依赖。
