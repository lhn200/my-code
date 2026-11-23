## Why

当前仓库只有 `.env`，OpenSpec 里唯一的变化是前端暗色模式，核心业务——"多岗位分析 + 简历匹配 + 低分回流优化 + 求职建议"——没有任何 spec 或契约。缺少这一层，后续的账号体系、前端页面和部署都无从对齐输入输出，容易各自猜测状态结构。

求职的真实决策是"在多个岗位之间做取舍"，而不是对单个 JD 做一次问答；匹配分低时自动回流优化是 LangGraph 状态图最关键的工程价值。先把图结构、状态契约、回流退出条件和会话恢复语义定清楚，后续能力才能按同一套契约叠加。

## What Changes

- 新增 LangGraph 工作流核心：Supervisor 路由 → 岗位分析子图 → 简历评审 → 低分回流简历优化 → 求职教练。
- 每个角色 / 子图使用独立 system prompt：岗位分析、简历评审、简历优化、求职教练、Supervisor 各自一份，公共安全前缀由框架统一注入。
- 简历摄入支持粘贴纯文本与上传文件：PDF 先抽文本层、扫描页转 OCR，DOCX 读取段落与表格，图片直接 OCR，统一归一化为文本后进入同一分析流程。
- 支持一次请求并行分析多个岗位：Supervisor 用 `Send` 扇出，各岗位子图实例并发执行，结果通过 reducer 聚合；单次运行岗位数受 `MAX_JOBS`（默认 5）硬限制。
- 低分回路：每个低于可配置阈值（默认 70）的岗位独立触发优化，只生成该岗位的定制简历并重新评审；每岗位最多回流 2 轮，达到上限仍未达标则带风险标记输出；基线简历始终不可变。
- 提示词离线回归：提供带版本的金标数据集、评分基线与 A/B 对比命令，指标覆盖 schema 通过率、缺口召回、虚构率、分数 MAE 与成本。
- thread_id + SQLite checkpoint：一次分析由服务端生成唯一 thread_id，支持中途恢复、查询当前状态、列出快照与按 checkpoint 读取历史状态。
- 面试报告回写：模拟面试报告可在岗位维度回写主分析结果（只保留最近一次摘要），并刷新求职建议供面试教练引用；回写不重跑主图节点，只追加新 checkpoint。
- 按角色分配模型：supervisor、job_analyst、resume_reviewer、resume_optimizer、career_coach 五个角色独立配置 provider / model / temperature，未配置的角色回退全局默认模型。
- 提供最小的 FastAPI 运行接口：创建并启动一次分析、按 thread_id 恢复、查询运行状态、读取指定快照；不含鉴权。
- 请求体不接受顶层 `thread_id`，岗位字段固定为 `job_id` / `title` / `original_position_text`；422 统一返回字段级错误。
- 不做：注册登录与分析空间、Vue 前端、Docker Compose / Nginx 部署。这些留给后续独立 change。

## Capabilities

### New Capabilities
- `workflow-orchestration`: Supervisor 路由、并行扇出、子图边界、状态聚合、岗位数上限、终止条件。
- `job-analysis`: 岗位分析子图，把原始 JD 转为结构化岗位画像。
- `resume-review`: 简历与单个岗位画像的匹配评分、维度分与问题清单。
- `resume-optimization`: 按岗位独立的低分回流、定制简历变体、阈值与轮数上限、优化后再评分、基线不可变。
- `career-advice`: 汇总多岗位结果，生成自然语言求职建议与投递优先级。
- `session-checkpoint`: thread_id 语义、SQLite checkpoint、会话恢复、快照列表与按 checkpoint 读取历史状态。
- `api-contract`: 运行请求模型、字段命名、字段级 422 错误结构与快照读取契约。
- `model-routing`: 角色级模型配置、回退规则与启动校验。
- `resume-ingestion`: 简历纯文本、PDF / DOCX 上传、图片与扫描件 OCR、文本归一化、原件引用（`file_id`）、文件校验与错误语义。
- `prompt-profiles`: 五个角色的独立 system prompt、公共安全前缀、启动校验与版本追溯。
- `prompt-evaluation`: 金标数据集、离线评测指标、评分基线门禁与 A/B 对比。
- `interview-report`: 面试报告摘要按岗位回写主运行、按 `interview_thread_id` 幂等、运行详情只读返回 `interview_reports`、回写后刷新求职建议。

### Modified Capabilities
<!-- openspec/specs/ 下没有既有 capability，无修改项 -->

## Architecture Impact

本 change 是全新后端核心，无既有 specs、模块或接口可复用：

- 引入 LangGraph `StateGraph` 主图与岗位分析子图，共享一份 Pydantic 状态定义；并行结果通过 reducer 合并，而非各子图互相调用。
- 状态所有权集中在图内，HTTP 层只负责入参校验、注入 thread_id、转发 checkpoint，不在路由层做业务判断。
- 文件解析在 HTTP 层完成后才进入图，图节点只接收文本与文件引用；原始二进制不进入状态、不写 checkpoint，状态中只保存 `resume_file_id` / `resume_file_url`。
- SQLite checkpoint 是会话恢复的唯一来源；后端不额外维护内存态会话表。
- 模型配置与业务逻辑解耦：角色 → 模型映射来自配置文件与环境变量，图节点只声明自己属于哪个角色。
- 提示词按角色拆分到 `app/prompts/<role>.md`，启动时加载并校验；节点只组合自己的角色提示词，公共安全前缀由框架注入，角色不得覆盖。
- 本 change 的接口契约（请求体、状态结构、错误语义）将成为后续账号、前端与部署 change 的依赖基础；鉴权与用户空间在后续 change 中叠加到同一路由之上。

## Impact

- `backend/app/state.py`：状态 schema 与 reducer 定义。
- `backend/app/graph/`：主图、Supervisor 路由、岗位分析子图、评审 / 优化 / 教练节点、回流条件边。
- `backend/app/config/models.yaml` + `backend/app/config/model_router.py`：角色级模型映射与校验。
- `backend/app/checkpoint/sqlite.py`：SQLite saver 初始化与 thread 快照读取。
- `backend/app/api/runs.py`：创建运行、恢复运行、查询状态。
- `backend/app/api/resumes.py`：简历上传与文本抽取接口。
- `backend/app/services/resume_parser.py`：按类型分流（PDF / DOCX / 图片）并归一化为文本。
- `backend/app/services/interview_reports.py`：面试报告摘要回写、`job_id` 校验、按 `interview_thread_id` 幂等与建议刷新。
- `backend/app/services/ocr.py`：PDF 页面渲染与 OCR 识别。
- `backend/app/prompts/<role>.md`：Supervisor、岗位分析、简历评审、简历优化、求职教练五份角色提示词。
- `backend/app/prompts/loader.py`：启动加载、占位符校验与 `prompt_version` 计算。
- `evals/datasets/`：版本化金标样本（合成或脱敏）。
- `evals/run.py`、`evals/baseline.json`、`evals/reports/`：离线评测、基线门禁与 A/B 报告。
- `data/uploads/`：上传原件目录（UUID 命名），状态只保存 `file_id` / URL。
- `backend/tests/`：路由、并行聚合、回路退出、checkpoint 恢复、模型配置校验。
- 依赖：`langgraph`、`langgraph-checkpoint-sqlite`、`langchain-openai`、`fastapi`、`pydantic`、`pyyaml`、`pypdf`、`python-docx`、`pypdfium2`、`rapidocr-onnxruntime`、`Pillow`、`python-multipart`、`pytest`。
