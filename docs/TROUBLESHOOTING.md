# 常见故障与恢复

| 错误/现象 | 行为与处理 |
|---|---|
| DEPENDENCY_MISSING / LARK_ENTRY_MISSING | 检查 Python、PowerShell 7、Node 和 CLI 安装；在本地配置填写实际路径，不改源码 |
| LARK_ERROR:authorization | 检查 CLI 对应身份权限、应用 scope 和 Base 编辑权限；bot 不通过用户登录修复 |
| TARGET_WORK_NOT_FOUND / AMBIGUOUS | 停止；核对 Chrome 登录账号、完整标题、秒级发布时间。不能放宽匹配来“修复” |
| export_complete 后同步失败 | 已保存新证据。再次运行同一作品只同步该证据，不重新导出 |
| capture_uncertain | 上次导出超时/中断，结果未知。检查下载目录、浏览器和身份后再解除阻塞；不会自动点击第二次 |
| CREATE_OUTCOME_UNCERTAIN | 先查飞书是否已经创建；找到同业务键记录会复用。查无记录仍不盲建，核实后处理 runtime 下该创建检查点 |
| REMOTE_COMPLETED_EVIDENCE_CONFLICT | 远端完成记录与本地证据不同。停止并人工核对，不覆盖已完成记录 |
| BUSY_RETRY_LATER | 同一个安装实例有另一任务工作。等待后调用同一 run 入口；不能删除 OS 锁文件解锁 |
| READBACK_VALUE_MISMATCH | 写入后回读不一致，未记为完成。检查字段类型、权限或外部修改，不用命令退出0冒充验收 |
| 开机后没有执行 | 核对任务已启用、项目路径和用户登录；执行 run 走同一恢复逻辑。不伪造历史时点 |
| STALE_REVIEW_EVIDENCE | 使用 review 的当前证据重新分析，不能提交过期结论 |

人工核对后解除一次捕获阻塞（不会立即采集）：

```powershell
.\.venv\Scripts\python.exe tools/creator.py reset-capture YOUR_WORK_ID --node 72小时 --reason "已核对账号和下载，本次允许重新采集"
```

注意：这可能取得更晚的累计值，系统会使用真实采集时间并标记延迟；不得回填为原时点。

提交 Issue 仅包含系统/依赖版本、命令名、脱敏错误代码、可复现步骤。不要上传 config.local.json、runtime 原目录、Excel、账号ID、评论者信息或日志全集。
