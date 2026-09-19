# 参与贡献

先运行测试，再提交小范围修改：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tools -p "test_creator*.py"
.\.venv\Scripts\python.exe -m unittest discover -s tests
node tests/extension/export_core.test.js
```

修改采集、身份匹配、状态恢复或飞书同步时，需要增加故障路径测试。不要放宽身份检查使失败测试“变绿”。

Issue 请附：操作系统、Python/Node/飞书CLI版本、命令名、脱敏错误代码和最小复现步骤。不要附真实作品文件、账号信息或运行目录。

集成测试默认关闭；`tests/live_smoke.py` 会在明确指定的专用测试 Base 中写入标注为模拟的数据。`tests/scheduler_smoke.py` 会创建并移除隔离计划任务，不执行 Chrome 导出。不得在公共 CI 中配置个人飞书凭证。
