# Creator Ops

一个面向 Windows 的抖音作品复盘助手：采集自己的作品数据、同步飞书、关联已确认素材，让 AI 依据真实证据分析，而不是凭印象猜测。

版本：`0.2.0-beta.1`，公开测试版。不是零配置软件，也不承诺零 bug；真实验证范围见 [验收记录](docs/ACCEPTANCE.md)。

## 能做什么

- 五节点追踪：发布后12/24/48/72小时和7天，通过日常 Chrome 导出创作者中心 Excel。
- 秒级发布时间与规范化标题唯一匹配，核心指标校验；错过时点不倒填、延迟采集保留真实时间。
- 飞书知识库：自动创建内容项目、作品数据快照、观众问题与回复草稿三张表，以及九组件“未来”主题仪表盘。
- 数据证据查询和同阶段比较；缺失指标不补零。72小时/7天分析由当前 AI 完成，再通过指纹校验回写飞书。
- 已确认资产归档、内容指纹、版本保护与索引恢复。
- 评论上下文和回复草稿状态记录；不发送评论。
- 可靠性保护：已下载文件与证据先落地；飞书故障只重试同步，不重复导出；导出结果不确定时停止自动点击。

这些模块不内置大模型调用。分析和拟稿由使用者当前的 AI 助手执行。

## 开始使用

**下载源码不等于安装完成。** 自动采集必须额外加载随项目提供的 Chrome 扩展，并登录自己的抖音创作者账号；同步与仪表盘需要自己的飞书应用及权限。下列准备必须在首次真实运行前完成，不能使用作者的登录态或密钥。

| 必备项 | 是否随源码提供 | 使用者需要做什么 |
| --- | --- | --- |
| Windows 10/11、Python 3.11+、PowerShell 7 | 否 | 自行安装；不是 macOS 自动采集版本 |
| Google Chrome | 否 | 安装并登录自己的抖音创作者中心 |
| 导出桥扩展 | 提供源码，不会自动安装 | 在 Chrome 开发者模式中加载 `extension` 文件夹 |
| Python 库 | 提供锁定依赖清单 | 运行安装脚本联网下载到项目虚拟环境 |
| Node.js、飞书 CLI | 否 | 安装 Node.js 及文档指定版本的 CLI |
| 飞书应用、授权、数据表 | 不提供作者账号配置 | 自行配置应用权限，再运行初始化命令建表 |
| AI 助手 | 不包含模型服务 | 分析、拟稿时使用自己的 AI 助手；采集程序不内置大模型 |

需要 Windows 10/11、Python 3.11+、PowerShell 7、Chrome、Node.js 和飞书 CLI。首次需要自行登录自己的账号并加载扩展，**不需要修改源码或复制作者的配置**。

```powershell
pwsh -NoProfile -File scripts/setup.ps1
```

完整步骤见 [安装与新用户验收](docs/INSTALL.md)。使用 AI 时，让它先读本项目的 AGENTS.md；更换聊天窗口后仍读同一数据目录，而不是依赖旧对话记忆。

## 本地测试

需要 Python 3.11 或更高版本。在本目录运行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tools -p 'test_creator*.py'
.\.venv\Scripts\python.exe -m unittest discover -s tests
node tests/extension/export_core.test.js
node tests/extension/background.test.js
.\.venv\Scripts\python.exe tools/release_check.py
```

## 边界

见 [发布审核清单](docs/RELEASE_REVIEW.md)。此包不包含使用者的真实数据、素材、密钥、日志或聊天记录。运行状态保存在本地，不提交到仓库。

本项目不提供播放预测、小时监控、固定聊天自动推送或无人审批的评论发送。电脑关机、休眠或退出登录期间不能采集；浏览器页面变化和权限失效可能需要维护。单个安装实例运营一个账号，不支持多机同时写同一数据区。

采用 [MIT License](LICENSE)。项目来源与外部依赖见 [PROVENANCE](docs/PROVENANCE.md)，隐私与报告规则见 [SECURITY](SECURITY.md)。
