## 1. 骨架与依赖

- [x] 1.1 创建 `backend/` Python 包结构（`app/state.py`、`app/graph/`、`app/config/`、`app/checkpoint/`、`app/api/`、`tests/`），并添加 `pyproject.toml`
- [x] 1.2 声明依赖：`langgraph`、`langgraph-checkpoint-sqlite`、`langchain-openai`、`fastapi`、`uvicorn`、`pydantic-settings`、`pyyaml`、`pypdf`、`python-docx`、`pypdfium2`、`rapidocr-onnxruntime`、`Pillow`、`python-multipart`、`pytest`、`pytest-asyncio`
- [x] 1.3 添加 `.env` 读取入口（复用现有 `LLM_API_KEY`），补充 `LLM_BASE_URL`、`RESUME_MATCH_THRESHOLD`、`MAX_OPTIMIZATION_ROUNDS`、`MAX_JOBS`（默认 5）、`MAX_CONCURRENT_JOBS`、`CHECKPOINT_DB_PATH`、`UPLOAD_DIR`（默认 `data/uploads`）、`RESUME_MAX_FILE_MB`（默认 5）、`OCR_MAX_PAGES`（默认 10）、`OCR_MIN_CHARS` 的默认值与说明

## 2. 状态契约

- [x] 2.1 在 `app/state.py` 定义 `JobInput`、`JobProfile`、`ReviewResult`、`ResumeVariant`、`OptimizationRound`、`AgentState`（含不可变基线 `resume_text` 与 `resume_variants: dict[job_id, list[ResumeVariant]]`）
- [x] 2.2 实现 `merge_by_job_id`、`merge_by_review_key(job_id, variant_version)` 与 `merge_variants` 三个 reducer，并补单元测试（去重、保留最新、不同岗位变体互不覆盖、并发写入不丢失）
- [x] 2.3 定义对外输出模型（Pydantic）：岗位结果（含当前定制简历与变体历史）、整体运行状态（成功 / 部分成功 / 失败），供 API 序列化
- [x] 2.4 定义 `InterviewReportSummary` 与 `interview_reports` reducer：按 `job_id` 只保留最近一次报告，按 `interview_thread_id` 去重，默认空映射

## 3. 模型路由与角色提示词

- [x] 3.1 新增 `app/config/models.yaml`，提供 `default` 与五个角色的示例配置
- [x] 3.2 实现 `app/config/model_router.py`：加载 YAML、应用 `MODEL_<ROLE>` 与 `DEFAULT_MODEL` 环境变量覆盖、按角色返回 chat model
- [x] 3.3 启动时校验：未知角色、空模型名、`temperature` 越界均抛错并终止启动；补对应单元测试
- [x] 3.4 创建 `app/prompts/` 下五份角色提示词（`supervisor`、`job_analyst`、`resume_reviewer`、`resume_optimizer`、`career_coach`），每份写明职责边界、只看/不看的内容与输出结构，文件头标注版本
- [x] 3.5 实现 `app/prompts/loader.py`：启动时一次性加载全部文件，校验存在、非空、占位符在白名单内、无覆盖安全约束的标记；计算 `prompt_version`
- [x] 3.6 实现提示词组装：system = 公共安全前缀 + 角色提示词；JD 与简历只用分隔符包裹后放入 human message，禁止拼进 system
- [x] 3.7 补提示词测试：角色互不串用、缺失/空/未知占位符/覆盖标记导致启动失败、内容变更后 `prompt_version` 变化、注入文本只留在 human message

## 4. 岗位分析子图

- [x] 4.1 实现 `app/graph/job_analysis.py` 子图：输入 `job_id` + 原始 JD，输出结构化 `JobProfile`
- [x] 4.2 用 JSON schema / 函数调用约束结构化输出，解析失败重试一次后标记该岗位 `status=failed`
- [x] 4.3 补子图测试：正常 JD、信息缺失 JD、无关文本，确认子图不读取简历字段
- [x] 4.4 子图 MUST 使用 `job_analyst` 角色提示词与对应模型，human message 只放岗位文本

## 5. 业务节点

- [x] 5.1 实现 `review_job` 节点：输入岗位画像 + 该岗位当前变体 + `variant_version`，输出 0–100 分、维度分、`matched` / `missing` / `issues`
- [x] 5.2 在 `resume_reviewer` 角色提示词中固化"只依据事实、不得虚构"与输出 schema，并补测试：简历未提及的技术必须进入 `missing`
- [x] 5.3 实现 `optimize_resume` 节点：只接收单个低分岗位，基于不可变基线与该岗位缺口生成 `variant_version + 1` 的定制简历，写入一条 `OptimizationRound`
- [x] 5.4 补优化测试：只重组基线事实、不得新增技能；无事实可补时缺口保留在 `missing`；两个低分岗位产出两份不同变体且互不覆盖
- [x] 5.5 实现 `coach` 节点：基于岗位画像、各岗位当前变体评审与优化历史生成 Markdown 建议（优先级 + 该岗位应投递的变体 + 理由 + 改进要点 + 风险）
- [x] 5.6 让 `coach` 节点读取 `interview_reports`：有报告时引用该岗位的亮点、红旗、改进方向与要求差距，区分 `completed` 与 `abandoned`，无报告时不提及面试；补对应测试

## 6. 主图与回流

- [x] 6.1 搭建 `app/graph/main.py` 主图：`intake → supervisor → {analyze_job | review_job | optimize_resume | coach} → END`
- [x] 6.2 实现 `intake` 校验：求职目标、岗位数在 1 到 `MAX_JOBS` 之间、简历非空；岗位超限返回 422 `too_many_jobs`；不合法时直接返回 422 语义且不写 checkpoint
- [x] 6.3 实现 `supervisor` 路由：用 `Send` 扇出待分析岗位、用 `Send` 扇出待评审岗位、对每个低分且未达上限的岗位单独扇出优化、全部完成时路由到教练
- [x] 6.4 实现回流判定：逐岗位判断 `score < threshold && rounds_used < max_rounds`；只为该岗位生成新变体，并只对该岗位按新 `variant_version` 重新评审
- [x] 6.5 实现并发上限（`MAX_CONCURRENT_JOBS`，默认 4）与节点内有限重试（默认 2 次）
- [x] 6.6 补图层测试：3 个岗位并行且结果数为 3；单岗位失败不影响其他岗位；两个低分岗位各回流一次后达标即停止；连续 2 轮未达标后退出并标记风险；已达标岗位不产生变体；6 个岗位在入口被拒、5 个通过

## 7. Checkpoint 与会话

- [x] 7.1 实现 `app/checkpoint/sqlite.py`：初始化 `AsyncSqliteSaver`，启用 WAL 与 busy timeout，自动创建数据目录与文件
- [x] 7.2 实现 thread_id 生成：服务端生成 UUID，`POST /api/runs` 请求模型不接受 `thread_id`；续跑只走 resume，不复用创建接口
- [x] 7.3 实现当前状态查询（含下一步节点）与历史快照列表，快照标识可读取对应状态
- [x] 7.4 补持久化测试：运行中断后按 thread_id 恢复不重复已完成岗位；进程重启后仍可查询；不存在的 thread_id 返回 404；两个 thread 并发互不污染
- [x] 7.5 实现 `attach_interview_report(thread_id, job_id, summary)`：校验运行与岗位存在，写入 `interview_reports[job_id]`，按 `interview_thread_id` 幂等，只追加新 checkpoint 且不改写岗位画像、评审与优化历史
- [x] 7.6 回写成功后用 `career_coach` 角色重新生成 `advice`；回写或教练重跑失败时保留旧 `advice` 并返回可重试标记，不阻塞面试报告
- [x] 7.7 补回写测试：正常回写、重复回写幂等、岗位不属于运行、运行不存在、历史快照不变、回写失败仍保留报告与旧建议

## 8. API 层

- [x] 8.1 实现 `POST /api/runs`：严格请求模型（`goal`、`resume_text`、`jobs[{job_id?, title, original_position_text}]`，拒绝顶层 `thread_id`）、校验入参、创建运行、返回 thread_id 与结构化结果（每岗位含当前定制简历与变体历史，含部分成功与失败标记）
- [x] 8.2 实现 `POST /api/runs/{thread_id}/resume`、`GET /api/runs/{thread_id}`、`GET /api/runs/{thread_id}/snapshots`、`GET /api/runs/{thread_id}/snapshots/{checkpoint_id}`
- [x] 8.3 统一错误语义：422 使用 `{"error":{"code","message","fields":[{field,type,message}]}}`（含 `too_many_jobs` 与未知 `thread_id` 字段）、404 会话/快照不存在、500 内部错误附带 thread_id 以便排查且不暴露堆栈
- [x] 8.4 补请求契约测试：缺少 `original_position_text`、类型错误、空白、旧字段名、顶层 `thread_id`、多个错误同时返回、`job_id` 缺省时生成，均断言 `fields` 路径与 `type`
- [x] 8.5 补快照测试：按 checkpoint 读取返回该时刻状态；跨 thread 的 checkpoint 返回 404；读取不产生新 checkpoint
- [x] 8.6 为 JD 与简历文本（含 PDF / DOCX / OCR 抽取结果）添加长度上限与分隔符包裹，降低提示注入风险

## 9. 简历上传与多格式解析

- [x] 9.1 实现 `POST /api/resumes`：接收 multipart 文件，按白名单（`.pdf` / `.docx` / `.png` / `.jpg` / `.jpeg` / `.webp`）校验扩展名与 MIME 一致、大小不超过 `RESUME_MAX_FILE_MB`、内容非空
- [x] 9.2 实现 PDF 解析：用 `pypdf` 逐页抽文本层，空白页用 `pypdfium2` 渲染后 OCR，输出保持原页码顺序
- [x] 9.3 实现 DOCX 解析：用 `python-docx` 按文档顺序读取段落与表格单元格文本；`.doc` 明确拒绝
- [x] 9.4 实现图片 OCR：用 `rapidocr-onnxruntime` 识别 `.png` / `.jpg` / `.jpeg` / `.webp`，并做空白规范化
- [x] 9.5 返回解析元信息：`file_id`、可选 `file_url`、`source_type`、页数、`used_ocr`、识别字符数、`low_confidence`；OCR 页数超过 `OCR_MAX_PAGES` 时返回 422
- [x] 9.6 区分错误语义：不支持类型、超限、空文件、加密 `resume_encrypted`、损坏 `resume_unreadable`、无有效文本 `resume_no_text`、类型伪装，统一 422 且不暴露堆栈
- [x] 9.7 原件写入 `UPLOAD_DIR`（UUID 命名，原始文件名仅作元信息、不参与路径）；状态只保存 `resume_file_id` / `resume_file_url` 与文本，MUST NOT 写入 base64 或二进制；解析失败删除已写入文件
- [x] 9.8 提供按 `file_id` 删除原件的幂等清理函数，供会话删除流程调用
- [x] 9.9 让上传返回的文本与粘贴文本走同一 `intake` 校验与状态路径，并补等价性测试
- [x] 9.10 补测试：文本层 PDF、扫描件 PDF、混合 PDF、含表格 DOCX、清晰图片、无文字图片、加密文件、超大文件、类型伪装、超过 OCR 页数上限、文件名穿越、解析失败清理、checkpoint 不含 base64

## 10. 验证

- [x] 10.1 用假模型跑通端到端图：输入求职目标 + 2 个岗位 + 简历，输出两份岗位结果与一段建议
- [x] 10.2 验证模型配置四种情况：全量配置、部分回退、未知角色启动失败、温度越界启动失败
- [x] 10.3 验证阈值与轮数环境变量生效：阈值 80 时 75 分触发回流；轮数设为 1 时最多回流一次
- [x] 10.4 验证 `advice` 引用的分数与评审结果一致，且无优化时不得声称已优化
- [x] 10.5 验证上传路径：PDF、DOCX、图片抽取出的文本与粘贴同一份内容时，得到结构一致的评审结果
- [x] 10.6 验证 OCR 元信息：扫描件与图片返回 `used_ocr=true`，文本过短时标记 `low_confidence`，非 OCR 路径为 `false`
- [x] 10.7 验证文件引用：响应含 `file_id`，checkpoint 只含 `resume_file_id` / `resume_file_url` 与文本，不含 base64 或二进制
- [x] 10.8 验证清理与回滚：解析失败不留孤儿文件；按 `file_id` 重复删除幂等；删除 `data/uploads/` 后其余模块启动与运行不受影响
- [x] 10.9 验证角色提示词：五个节点各自使用对应提示词，system 以安全前缀开头，注入文本只出现在 human message，日志含 `prompt_version`
- [x] 10.10 验证多版简历：两个低分岗位产出两份不同定制简历，互不覆盖；已达标岗位无变体；恢复会话后各岗位当前变体仍可读
- [x] 10.11 验证岗位上限：6 个岗位返回 422 `too_many_jobs` 且不写 checkpoint；5 个岗位正常运行；修改 `MAX_JOBS` 后行为随配置变化
- [x] 10.12 验证 API 契约：顶层 `thread_id` 与旧岗位字段名返回字段级 422；`original_position_text` 类型错误定位到 `jobs[i].original_position_text`；按 checkpoint 读取历史状态与当前状态一致
- [x] 10.13 验证面试报告回写：回写后 `GET /api/runs/{thread_id}` 返回 `interview_reports` 且 `advice` 引用面试亮点与改进点；重复回写幂等；回写前的历史快照内容与状态不变

## 11. 提示词离线回归与 A/B

- [x] 11.1 建立 `evals/datasets/` 版本化金标集：至少覆盖岗位分析、简历评审、简历优化三类样本，包含输入、期望关键字段与缺口清单；样本必须合成或脱敏
- [x] 11.2 实现 `evals/run.py`：离线加载数据集与指定 `prompt_version`，复用角色提示词与模型配置，不启动 FastAPI、不写生产 checkpoint
- [x] 11.3 实现指标计算：schema 通过率、`missing` 召回、虚构率（输出中出现基线不存在的事实）、分数与基线 MAE、时延与 token 消耗
- [x] 11.4 提供 `evals/baseline.json`：记录各角色各指标的基线值与允许跌幅；低于阈值时命令以非零码退出
- [x] 11.5 实现 A/B 模式：同一数据集跑两个提示词版本，输出逐指标差异与胜负结论，报告写入 `evals/reports/`
- [x] 11.6 报告必须记录 `prompt_version`、模型名、数据集哈希与运行时间；补测试：基线通过、超出跌幅失败、A/B 结果可复现（固定温度）
- [x] 11.7 在 README 或 `evals/README.md` 说明如何新增样本、更新基线与解读报告
