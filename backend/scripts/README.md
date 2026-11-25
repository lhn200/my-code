# 运维脚本

## legacy checkpoint 清理

`cleanup_legacy_checkpoints` 只处理 `checkpoints` 表里存在、但 `runs` 表中没有记录的
`thread_id`（即无主 / legacy checkpoint）。有 `runs` 记录的会话——包括回收站中的会话——
一律受保护。

默认行为是 **dry-run**，只输出候选数量并写入审计日志，不删除任何数据：

```powershell
cd backend
python -m scripts.cleanup_legacy_checkpoints
```

确认候选数量无误后，再显式执行删除：

```powershell
python -m scripts.cleanup_legacy_checkpoints --yes
```

常用参数：

- `--older-than-days 30`：只清理最近一次 checkpoint 早于 N 天的 thread；默认 30，传 0 表示不按时间过滤。
- `--batch-size 500`：每批提交的行数。
- `--audit-log data/audit/legacy_cleanup.log`：审计日志路径。
- `--purge-expired-trash`：额外按 `TRASH_RETENTION_DAYS` 清理过期的回收站会话（会物理删除其 checkpoint 与 `runs` 行）。

## 安全建议

- 先 dry-run，确认 `candidates` 数量与预期一致。
- 执行前备份 `data/checkpoints.sqlite3`（以及 `-wal` / `-shm` 文件）。
- 审计日志只记录时间、模式、批次与数量，不记录简历文本或 checkpoint 内容。
- 清理不可回滚；如需恢复，只能从备份中还原数据库。
