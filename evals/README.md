# 提示词离线评测

离线回归岗位分析、简历评审与简历优化三个角色的提示词质量。评测不启动 FastAPI、不读写
`data/checkpoints.sqlite3` 或 `data/uploads/`，也不调用运行接口。

## 运行

在仓库根目录执行：

```bash
python -m evals.run                      # 基线评测并执行门禁
python -m evals.run --no-gate            # 只出报告，不因回退失败
python -m evals.run --prompt-version <hash> --prompts-dir <归档目录>
python -m evals.run --ab-prompts-dir <另一套提示词目录>
```

- 评测温度固定为 `0.0`（见 `evals/run.py` 的 `EVAL_TEMPERATURE`），不继承生产配置。
- `--prompt-version` 会校验实际加载的提示词哈希与请求值一致，不一致直接以退出码 2 失败。
  A/B 时用 `--prompts-dir` 指定 A，`--ab-prompts-dir` 指定 B。
- 报告写入 `evals/reports/report-<UTC 时间>-<mode>.json`，包含 `prompt_version`、各角色
  版本、模型名、数据集哈希、数据集版本、开始时间、耗时、逐样本结果、汇总指标与门禁结果。
- 退出码：`0` 通过；`1` 有指标低于基线允许跌幅；`2` 数据集/提示词/基线不可用。

生产分支上的常规命令是 `python -m evals.run`，它需要在 `.env` 中配置可用的模型访问。

## 指标

| 指标 | 含义 | 方向 |
| --- | --- | --- |
| `schema_pass_rate` | 模型输出能通过对应 schema 校验的样本占比 | 越高越好 |
| `missing_recall` | 期望缺口（岗位硬性要求 / 评审 missing / 优化 remaining_gaps）被识别出的比例 | 越高越好 |
| `hallucination_rate` | 输出中出现样本 `hallucination_guard` 中虚构事实的样本占比 | 越低越好 |
| `score_mae` | 评审加权分与金标期望分的平均绝对误差（仅评审） | 越低越好 |
| `avg_latency_ms` | 单样本平均耗时 | 越低越好 |
| `avg_tokens` | 单样本平均 token 消耗（优先取响应 `usage_metadata`，否则按字符估算） | 越低越好 |

单条样本失败（非法 JSON、schema 不符）只计为该样本 schema 失败，不中断整轮评测。

## 新增样本

在 `evals/datasets/` 对应任务文件中追加样本，并提升该文件 `version`：

- 必须包含 `id`、`input`、`expected`；
- `input` 的键与提示词占位符一致：
  - 岗位分析：`job_title`、`job_text`；
  - 简历评审：`goal`、`profile_json`、`resume_text`；
  - 简历优化：`goal`、`profile_json`、`review_json`、`baseline_resume`；
- `expected` 使用任务对应的召回键：`must_have`、`missing`、`remaining_gaps`；
- `expected.hallucination_guard` 列出**输入中不存在**、因此绝不能出现在输出中的事实词；
- 评审样本可选 `expected.score`（0–100 的系统加权分）。

样本必须是合成或脱敏内容，不得包含真实姓名、联系方式或公司内部信息。数据集内容变化会
改变报告中的 `dataset_hash`。

## 更新基线

1. 用评审过的提示词运行 `python -m evals.run --no-gate`；
2. 人工确认指标变化符合预期；
3. 修改 `evals/baseline.json` 中的 `baseline` 与 `tolerance`：
   - `higher_is_better: true` 时，实际值低于 `baseline - tolerance` 即回退；
   - `higher_is_better: false` 时，实际值高于 `baseline + tolerance` 即回退。

基线只应随经过评审的提示词或数据集变更而更新，不要为了通过门禁而放宽阈值。

## 解读 A/B 报告

`comparison.deltas` 逐角色逐指标给出 A、B 值与差值，`winner` 依据指标方向判断；
`comparison.verdict` 汇总为「A is better」「B is better」「no significant difference」
或「mixed results; review the metric deltas」。`comparison.gate` 分别给出两套提示词的
门禁违规项。内容相同的两套提示词在固定温度下应得到全零差值。
