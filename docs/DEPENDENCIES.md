# 依赖说明

本文档列出项目运行、开发与测试所需的依赖，以及版本约束和升级注意事项。

## 运行时要求

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| Python | 3.12+ | 后端 `requires-python = ">=3.12"`，使用 `X \| None` 等新语法 |
| Node.js | 18+（推荐 20 LTS / 22） | Vite 6 要求 Node 18+ |
| npm | 9+ | 使用 `package-lock.json` 复现安装 |
| SQLite | Python 内置 | 业务表与 LangGraph checkpoint 同库，启用 WAL |
| 模型服务 | OpenAI 兼容 | 默认对接阿里云百炼 DashScope 兼容模式，需 `LLM_API_KEY` |

项目不依赖外部向量数据库、Redis、消息队列或 ffmpeg；所有状态持久化在单个 SQLite 文件中。

## 后端依赖

依赖声明见 `backend/pyproject.toml`，版本为**最低版本约束**，不是锁定版本。

### 运行依赖

| 包 | 版本约束 | 用途 |
| --- | --- | --- |
| `fastapi` | >=0.115 | Web 框架、依赖注入、请求校验 |
| `uvicorn[standard]` | >=0.30 | ASGI 服务器 |
| `pydantic` | >=2.8 | 请求 / 响应模型与结构化输出校验 |
| `pydantic-settings` | >=2.4 | `.env` 与环境变量加载 |
| `langgraph` | >=1.0 | 多智能体状态图、`Send`、`Command`、`interrupt` |
| `langgraph-checkpoint-sqlite` | >=2.0 | 基于 SQLite 的 checkpoint 持久化与快照回放 |
| `langchain-openai` | >=0.2 | OpenAI 兼容模型客户端（会传递安装 `langchain-core`） |
| `pyyaml` | >=6.0 | 解析 `app/config/models.yaml` 模型路由 |
| `pypdf` | >=5.0 | 提取 PDF 文本 |
| `python-docx` | >=1.1 | 提取 DOCX 文本 |
| `pypdfium2` | >=4.30 | 将扫描版 PDF 逐页渲染为图片，供 OCR |
| `rapidocr-onnxruntime` | >=1.3 | 图片与扫描件 OCR（自带 ONNX 模型，首次加载较慢） |
| `Pillow` | >=10.0 | 图片读取、预处理与格式转换 |
| `python-multipart` | >=0.0.9 | 简历上传的 multipart 表单解析 |
| `argon2-cffi` | >=21.3 | Argon2 密码哈希 |
| `pyjwt` | >=2.8 | 签发与校验 access token |

### 可选依赖

| 包 | 安装方式 | 用途 |
| --- | --- | --- |
| `tiktoken` | `pip install -e ".[tokens]"` | 精确 token 计数；未安装时回退为字符估算，上下文预算仍然生效 |

### 开发与测试依赖

| 包 | 版本约束 | 用途 |
| --- | --- | --- |
| `pytest` | >=7 | 单元与接口测试 |
| `pytest-asyncio` | >=0.24 | 异步用例（`asyncio_mode = "auto"`） |
| `httpx` | >=0.27 | FastAPI `TestClient` 的底层 HTTP 客户端 |

安装：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"        # 含运行 + 测试依赖
# 需要精确 token 统计时追加：
pip install -e ".[dev,tokens]"
```

## 前端依赖

依赖声明见 `frontend/package.json`，精确版本由 `package-lock.json` 锁定。

### 运行依赖

| 包 | 版本约束 | 用途 |
| --- | --- | --- |
| `vue` | ^3.5.13 | 视图层与 Composition API |
| `vue-router` | ^4.5.0 | 路由与登录守卫 |
| `marked` | ^15.0.7 | 渲染建议等 Markdown 文本 |
| `dompurify` | ^3.2.4 | 净化 Markdown 渲染结果，防 XSS |

### 开发依赖

| 包 | 版本约束 | 用途 |
| --- | --- | --- |
| `vite` | ^6.0.11 | 开发服务器与生产构建 |
| `@vitejs/plugin-vue` | ^5.2.1 | Vue 单文件组件编译 |
| `typescript` | ~5.7.3 | 类型系统 |
| `vue-tsc` | ^2.2.0 | 类型检查（`npm run typecheck`） |
| `vitest` | ^3.0.5 | 单元测试 |
| `@vue/test-utils` | ^2.4.6 | 组件挂载与交互测试 |
| `happy-dom` | ^16.7.2 | 测试环境 DOM 实现 |
| `jsdom` | ^31.0.1 | 备用 DOM 环境 |
| `@types/node` | ^22.13.1 | Node 类型（Vite 配置使用） |

安装：

```powershell
cd frontend
npm ci          # 严格按 package-lock.json 安装
# 或首次开发时
npm install
```

## 外部服务与资源

| 资源 | 是否必需 | 说明 |
| --- | --- | --- |
| 模型 API | 必需 | 通过 `LLM_API_KEY`、`LLM_BASE_URL` 配置；模型名见 `backend/app/config/models.yaml` |
| Google Fonts | 否 | 前端引入 Noto Serif SC / Noto Sans SC / IBM Plex Mono，离线时回退系统字体 |
| 本地中文字体 | 否 | 打印简历时可使用系统宋体 / 黑体 |

## 版本管理建议

- 后端目前只有下限约束，生产部署前建议用 `uv lock`、`pip-tools` 或 `pip freeze` 生成锁文件，并纳入发布产物。
- 前端已提交 `package-lock.json`，CI 与部署请使用 `npm ci`，避免浮动升级。
- 升级 LangGraph 时需重点回归：`Send` 并行分发、`Command(goto)` 汇聚、`interrupt` / `Command(resume)`、checkpoint 读取。
- 升级 Pydantic 时需回归全部请求模型与结构化输出 schema（项目使用 v2 API）。
- 升级 Vite / vue-tsc 时同时检查 Node 版本要求与 `typecheck`、`build`。

## 已知注意事项

- `rapidocr-onnxruntime` 首次识别会加载 ONNX 模型，内存占用与首包延迟高于纯文本解析；可通过 `OCR_MAX_PAGES` 限制页数。
- 未安装 `tiktoken` 时，上下文预算按字符估算，极端长文本下可能与真实 token 数存在偏差。
- 模型服务不可达时，运行会失败并在 `runs` 表标记状态；秒级重试由 `NODE_RETRY_ATTEMPTS` 控制，不进行无限重试。
- `data/` 目录（数据库、上传文件、审计日志）不纳入版本管理。
