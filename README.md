# Career Dossier · 大模型求职分析助手

基于 **LangGraph 多智能体编排** 的求职分析应用。输入求职目标、简历与多个岗位 JD，系统会逐岗位解析要求、给出匹配评分、按缺口迭代优化简历、自动进行模拟面试，并汇总为一份可回访的「职业档案」。在此基础上还提供真实作答的模拟面试演练，以及围绕分析结果持续追问的 AI 教练。

后端 FastAPI + SQLite（业务表与 checkpoint 同库），前端 Vue 3 + TypeScript，界面采用「档案室」视觉体系。

## 功能

- **多岗位并行分析**：`supervisor` 通过 `Send` 并行分发给岗位解析、简历评审、简历优化、模拟面试节点，再由 `Command(goto)` 汇聚到建议节点。
- **评分与优化闭环**：按维度评分，未达阈值自动进入下一轮简历优化，轮次上限可配置，避免无限模型调用。
- **自动模拟面试**：每个岗位生成多轮问答与评分，达到阈值或轮次上限后结束，输出亮点、风险、改进项与需求缺口。
- **模拟面试演练**：在分析结果页按岗位发起真实作答，逐题获得反馈与追问，结束后生成评估报告并回填岗位卡，与离线预评估可区分。
- **AI 模拟教练**：独立教练页，默认引用最近一次完成的分析，也可切换或解绑；支持多轮追问、历史会话、重命名与删除。
- **简历摄入**：支持 PDF、DOCX 与图片（OCR），解析文本可编辑，低置信度会显式提示。
- **账号与安全**：注册 / 登录、JWT、Argon2 密码哈希、登录限流、资源归属校验。
- **会话管理**：目录搜索、分页、活跃 / 回收站切换、恢复与永久删除。
- **快照回放**：基于 LangGraph checkpoint，可查看任意步骤的状态与结果。
- **长期记忆与摘要**：记忆可开关、编辑、归档；会话按轮次生成带版本的摘要，注入前按上下文预算裁剪。
- **响应式前端**：桌面、平板、手机三档断点，减少动态效果偏好下自动降级。

## 技术栈

| 层 | 选型 |
| --- | --- |
| 编排 | LangGraph 1.x、LangChain、OpenAI 兼容模型接口 |
| 后端 | Python 3.12、FastAPI、Pydantic v2、SQLite、Uvicorn |
| 存储 | SQLite（业务表 + LangGraph checkpoint，WAL 模式） |
| 认证 | PyJWT、argon2-cffi、内存登录限流 |
| 文档解析 | pypdf、python-docx、pypdfium2、RapidOCR + Pillow |
| 前端 | Vue 3、TypeScript、Vite 6、Vue Router、marked + DOMPurify |
| 测试 | pytest、pytest-asyncio、Vitest、happy-dom、vue-tsc |

依赖的完整说明见 [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md)。

## 目录结构

```text
career_assistant/
├─ backend/
│  ├─ app/
│  │  ├─ api/          # 认证、运行、会话、摘要、记忆、简历上传、模拟面试、AI 教练、健康检查
│  │  ├─ auth/         # JWT、密码哈希、登录限流、依赖注入
│  │  ├─ checkpoint/   # LangGraph SQLite checkpointer
│  │  ├─ config/       # Settings、models.yaml 模型路由
│  │  ├─ db/           # 建表、迁移、用户 / 运行记录、演练与教练会话
│  │  ├─ graph/        # 主图、岗位子图、节点实现
│  │  ├─ memory/       # 记忆写入、检索、摘要、上下文预算
│  │  ├─ prompts/      # 各角色提示词（版本化）
│  │  └─ services/     # 简历解析、OCR、结果构建、面试报告、面试演练、教练对话
│  ├─ scripts/         # legacy checkpoint 清理等运维脚本
│  └─ tests/           # 后端测试
├─ frontend/
│  ├─ src/
│  │  ├─ api/          # 手写类型契约与请求封装
│  │  ├─ auth/         # token 存储与路由守卫
│  │  ├─ components/   # 岗位卡、结果区、快照、记忆、摘要等
│  │  ├─ composables/  # 表单、运行详情、快照、会话、记忆、面试演练、教练对话等数据逻辑
│  │  ├─ router/       # 路由表
│  │  ├─ styles/       # 设计 token 与基础样式
│  │  └─ views/        # 登录、注册、创建、结果、目录、查询、记忆设置、面试演练、AI 教练
│  └─ tests/           # Vitest 用例
├─ evals/              # 提示词离线评测（数据集、基线、运行器）
├─ design/             # UI 设计稿
├─ docs/               # 依赖说明等项目文档
├─ resume-deliverables/# 三份 A/B 对照简历（HTML，可打印）
└─ .env.example        # 环境变量参考
```

## 快速开始

### 1. 环境要求

- Python **3.12+**
- Node.js **18+**（推荐 20 LTS）与 npm
- 可用的 OpenAI 兼容模型服务（默认面向阿里云百炼 DashScope 兼容模式）

### 2. 启动后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # macOS / Linux: source .venv/bin/activate
pip install -e ".[dev]"

# 配置密钥：backend/.env（模板见根目录 .env.example）
#   LLM_API_KEY=...
#   LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
#   JWT_SECRET=<足够长的随机串>

python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：`GET /api/health`
- `JWT_SECRET` 为空时服务启动会直接失败，这是有意的快速失败设计。

### 3. 启动前端

```powershell
cd frontend
npm install
npm run dev
```

打开 <http://localhost:5173>，Vite 会把 `/api` 代理到 `http://127.0.0.1:8000`。生产或独立域名部署时，在 `frontend/.env` 中设置 `VITE_API_BASE_URL`。

### 4. 关键环境变量

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `LLM_API_KEY` | 是 | 模型服务密钥 |
| `LLM_BASE_URL` | 否 | OpenAI 兼容接口地址，留空用 SDK 默认值 |
| `JWT_SECRET` | 是 | JWT 签名密钥，空值会导致启动失败 |
| `CHECKPOINT_DB_PATH` | 否 | SQLite 路径，默认 `data/checkpoints.sqlite3` |
| `UPLOAD_DIR` | 否 | 简历上传目录，默认 `data/uploads` |
| `RESUME_MATCH_THRESHOLD` | 否 | 匹配分通过线，默认 70 |
| `MAX_OPTIMIZATION_ROUNDS` | 否 | 单岗位最多优化轮数，默认 2 |
| `INTERVIEW_SCORE_THRESHOLD` | 否 | 面试通过线，默认 70 |
| `MAX_INTERVIEW_ROUNDS` | 否 | 单岗位最多面试轮数，默认 2 |
| `MAX_JOBS` | 否 | 单次运行岗位上限，默认 5 |
| `MEMORY_ENABLED_DEFAULT` | 否 | 记忆默认开关，默认关闭 |

完整列表与默认值见根目录 [.env.example](.env.example) 与 `backend/app/config/__init__.py`。

模型按角色路由，配置在 `backend/app/config/models.yaml`，可用 `DEFAULT_MODEL`、`MODEL_<ROLE>` 环境变量覆盖。

## 工作流

```text
START → intake → supervisor
                   ├─ 无岗位画像          → Send 并行 analyze_job（按岗位）     → supervisor
                   ├─ 缺当前版本评审      → Send 并行 review_job（按岗位）      → supervisor
                   ├─ 未达标且轮次未用尽  → Send 并行 optimize_resume（按岗位） → supervisor
                   └─ 全部处理完成        → coach
                                              ├─ 有岗位需继续面试 → Send 并行 interview（按岗位）→ supervisor
                                              └─ 无需面试         → END
```

- `supervisor` 每次只选择一个**阶段**，阶段内按岗位并行（`Send`）；四个节点不会同时执行。
- 优先级为：岗位解析 → 简历评审 → 简历优化 → 生成建议；评审与优化完成后都会回到 `supervisor` 重新判断。
- `coach` 生成建议后，若仍有岗位需要面试（未达面试轮次，或上次面试分低于阈值），会并行发起面试；面试结果回到 `supervisor`，低分岗位可再次进入优化。
- 评分低于阈值且未达轮次上限时，`supervisor` 继续分发优化任务。
- 每个节点的状态都写入 checkpoint，可按 `thread_id` + `checkpoint_id` 回放。
- 运行结束后异步提取长期记忆并生成会话摘要，失败不会影响主流程结果。
- 模拟面试演练与 AI 教练独立于主图：按各自的会话表读写，不改变上述工作流；教练绑定分析时只读取其状态作为上下文。

## API 概览

所有接口以 `/api` 为前缀，除注册、登录和健康检查外均需 `Authorization: Bearer <token>`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/auth/register` | 注册 |
| POST | `/auth/login` | 登录并获取 token |
| POST | `/auth/logout` | 退出 |
| GET | `/auth/me` | 当前用户 |
| POST | `/runs` | 创建分析任务并在后台执行 |
| POST | `/runs/{thread_id}/resume` | 恢复未完成的运行 |
| GET | `/runs/{thread_id}` | 运行状态与结果 |
| GET | `/runs/{thread_id}/snapshots` | 快照列表 |
| GET | `/runs/{thread_id}/snapshots/{checkpoint_id}` | 指定快照 |
| GET | `/sessions` | 会话目录（活跃 / 回收站） |
| PATCH | `/sessions/{thread_id}` | 重命名 |
| DELETE | `/sessions/{thread_id}` | 移入回收站 |
| POST | `/sessions/{thread_id}/restore` | 恢复会话 |
| DELETE | `/sessions/{thread_id}/purge` | 永久删除 |
| GET | `/sessions/{thread_id}/summary` | 读取会话摘要 |
| POST | `/sessions/{thread_id}/summary/regenerate` | 重新生成摘要 |
| POST | `/interviews` | 创建或复用某个岗位的模拟面试演练 |
| GET | `/interviews` | 列出某分析下的演练会话 |
| GET | `/interviews/{session_id}` | 演练详情与消息 |
| POST | `/interviews/{session_id}/answers` | 提交回答，返回反馈与下一题 |
| POST | `/interviews/{session_id}/finish` | 生成演练评估报告并回填岗位卡 |
| POST | `/coach/sessions` | 新建教练会话（可绑定分析） |
| GET | `/coach/sessions` | 教练会话列表（可按分析过滤） |
| GET | `/coach/sessions/{session_id}` | 教练会话与全部消息 |
| PATCH | `/coach/sessions/{session_id}` | 重命名或改绑 / 解绑分析 |
| DELETE | `/coach/sessions/{session_id}` | 删除教练会话 |
| POST | `/coach/sessions/{session_id}/messages` | 发送消息并获取教练回复 |
| GET / PUT | `/memories/settings` | 读取 / 更新记忆开关 |
| GET / DELETE | `/memories` | 列出 / 清空记忆 |
| PATCH / DELETE | `/memories/{memory_id}` | 编辑 / 删除单条记忆 |
| POST | `/resumes` | 上传并解析简历（multipart） |
| GET | `/health` | 健康检查 |

## 测试与评测

```powershell
# 后端（当前 312 项用例）
cd backend
python -m pytest

# 前端
cd frontend
npm run typecheck
npm run test        # 12 个文件、76 个用例
npm run build

# 提示词离线评测（需要可用模型配置）
python -m evals.run
```

评测的指标、基线与样本扩展方式见 [evals/README.md](evals/README.md)。

## 数据与运维

- 业务表（用户、运行记录、记忆、摘要元数据、演练与教练会话）与 LangGraph checkpoint 共用 `data/checkpoints.sqlite3`。
- 简历上传文件位于 `data/uploads/`。
- `data/` 已被 `.gitignore` 忽略，请勿提交数据库与上传文件。
- 清理无主 checkpoint：

```powershell
cd backend
python -m scripts.cleanup_legacy_checkpoints          # 默认 dry-run
python -m scripts.cleanup_legacy_checkpoints --yes    # 确认后执行
```

更多参数与安全建议见 [backend/scripts/README.md](backend/scripts/README.md)。

## 设计

界面为「档案室」风格：暖纸底、墨黑正文、朱砂强调色，衬线标题搭配等宽数据字体，使用 2px 圆角与硬边阴影。设计稿位于 [design/ui-design-draft.html](design/ui-design-draft.html)，可直接在浏览器打开。

## 注意事项

- 一次完整分析包含多次模型调用，耗时取决于所选模型与网络，建议先设置合理的 `MAX_JOBS`、`MAX_OPTIMIZATION_ROUNDS` 与 `MAX_INTERVIEW_ROUNDS`。
- 提示词按角色版本化，修改 `backend/app/prompts/` 后建议运行 `python -m evals.run` 对比基线。
- `openspec/` 为本地规格流程目录，已在 `.gitignore` 中排除。
