# 新用户安装与验收

## 支持范围

首个候选版本面向 Windows 10/11、Python 3.11+、PowerShell 7、Google Chrome、Node.js 及飞书 CLI。非 Windows 只运行离线测试，不承诺自动采集。

已验证飞书 CLI 版本为 1.0.91。安装依赖、登录账号、加载扩展属于首次配置，不需要修改源码。不要在多个项目副本中同时调度同一 Chrome 下载目录。

## 1. 安装程序依赖

先将项目解压到准备长期保留的目录。不要直接在 ZIP 内运行，也不要在启用计划任务后随意移动目录。安装阶段需要网络下载依赖；真实采集与飞书同步也需要联网。

开始前在终端分别运行 `python --version`、`pwsh --version`、`node --version`、`npm --version`，确认命令可用。安装 Python 时需使终端能找到 Python；Windows 自带的 Windows PowerShell 5.1 不等于本项目要求的 PowerShell 7。已实测版本及尚未覆盖环境见 [验收记录](ACCEPTANCE.md)，最低版本声明不等于所有版本都已实测。

安装 Python 3.11+、PowerShell 7、Chrome 和 Node.js。打开 PowerShell 7，在解压后的项目目录运行：

```powershell
pwsh -NoProfile -File scripts/setup.ps1
npm install -g @larksuite/cli@1.0.91
```

setup 仅在项目里建立 `.venv`，不会安装系统服务、修改生产任务或自动上传。

它不会替你安装 Chrome、Python、PowerShell、Node.js 或浏览器扩展，也不会替你登录抖音、创建飞书应用或授予权限。只有脚本显示安装成功，仍不能判定完整业务链已经可用。

## 2. 配置飞书

按飞书 CLI 的官方流程运行 `lark-cli config init`，将应用配置交给 CLI 管理，不把 appSecret/Cookie 写入本项目。定时任务默认使用 bot 身份：应用需要多维表格相关权限，并且能编辑该专用 Base。应用权限须由资源所有者或管理员授予。

如果本机 npm 使用了自定义全局目录，在 `config.local.json` 的 `lark_entry` 中填写已安装 `@larksuite/cli/scripts/run.js` 的绝对路径。其他可配置项见 `config.example.json`；空的 Chrome、PowerShell、Node 路径会自动发现。下载目录必须与 Chrome 实际下载位置一致。

```powershell
.\.venv\Scripts\python.exe tools/creator.py init-feishu --name "我的作品复盘"
```

程序创建独立 Base、三张表和九个“未来”主题组件，并把返回的资源 ID 记入本地配置。不要填写别人的 Base Token，不要把生产 Base 当安装测试区。若由 bot 创建，确认自己能在飞书打开；必要时在飞书中申请/授予编辑权限。

初始化中断后直接重跑会优先复用同名已建资源。创建结果不确定时停止，不会无限重建；按报错核查远端已创建资源，避免重复。

## 3. 配置 Chrome 扩展

1. 用准备运营账号的日常 Chrome 打开 `chrome://extensions`。
2. 打开开发者模式，选择“加载已解压的扩展程序”，选择本项目的 `extension` 目录。
3. 登录抖音创作者中心，人工核对账号是作品发布者。
4. 在 Chrome 下载设置中关闭“下载前询问保存位置”，核对下载目录；采集期间不要手动执行另一次同类导出。

扩展只在带一次性任务参数的创作者中心页面点击唯一可见的“导出数据”，不读取密码、不发送评论、不绕过验证码。扩展可能受浏览器策略限制，需要用户明确加载，不做静默安装。

```powershell
.\.venv\Scripts\python.exe tools/creator.py doctor
```

doctor 检查本地依赖和配置，不会伪称登录态或真实导出已验证。

## 4. 登记作品并启用五节点

由 AI 或使用者核对作品后，按 `examples/metadata.example.json` 填写自己的信息，保存到 runtime 下。`identity_evidence` 应指向保存的身份核对记录；标志为 true 不能代替人工真实核对。

```powershell
.\.venv\Scripts\python.exe tools/creator.py register runtime/my-video.json
.\.venv\Scripts\python.exe tools/creator.py schedule YOUR_WORK_ID
.\.venv\Scripts\python.exe tools/creator.py schedule YOUR_WORK_ID --apply
```

把 `YOUR_WORK_ID` 替换为自己作品的数值 ID。节点固定为12/24/48/72小时及7天。不唤醒电脑、不每小时轮询。登录/解锁/支持的恢复事件后可补最新逾期节点；某些 Modern Standby 设备恢复事件不同，解锁后仍未执行时用下面同一入口手动恢复。

```powershell
.\.venv\Scripts\python.exe tools/creator.py run YOUR_WORK_ID
```

没有到期节点不打开 Chrome。多条作品通过安装目录内的同一 OS 锁串行执行；多个项目副本/多个电脑不能共用该飞书数据区并发写入。计划任务需保留项目、虚拟环境和配置原路径，移动项目后重新预览并注册，人工移除旧路径任务。

## 5. 查看、分析与回复素材

```powershell
.\.venv\Scripts\python.exe tools/creator.py review YOUR_WORK_ID
.\.venv\Scripts\python.exe tools/creator.py compare YOUR_WORK_ID OTHER_WORK_ID --node 72小时
.\.venv\Scripts\python.exe tools/creator.py complete-review runtime/review.json
.\.venv\Scripts\python.exe tools/creator.py comments YOUR_WORK_ID comments.json
.\.venv\Scripts\python.exe tools/creator.py comments YOUR_WORK_ID comments.json --sync-feishu
.\.venv\Scripts\python.exe tools/creator.py archive runtime/asset-confirmation.json
```

comments.json 路径相对 data_dir；其他输入清单路径相对当前终端。AI 使用 `review` 输出作分析，再按 `examples/review.example.json` 回填结论；工具本身不调用付费大模型。评论同步是未发送草稿，不会实际回复。

Windows 任务运行结果保存在 `runtime/task-results`，待分析记录在 `runtime/reviews`。候选版不依赖特定 Codex 聊天 ID，也不把未公开/不稳定的聊天通知命令作为安装前提。自动向固定聊天推送不在本版支持范围内。

## 6. 最低可行性验收

第一次使用请按以下顺序验收，而不是直接让五节点任务无人值守运行：

1. 完成本页第1至3节，并运行 README 中的本地测试。测试通过只证明程序的离线回归通过。
2. 使用自己的专用飞书测试区和一条已发布至少12小时的作品，核对真实身份后登记。不要伪造发布时间来强行触发。
3. 运行 `run YOUR_WORK_ID`，检查新 Excel、实际采集时间、证据以及飞书回读；再执行一次，确认不重复导出。登记很久以前的作品只会取得当前快照，不能恢复历史时点数据。
4. 手动链路通过后，为一条仍有未来节点的作品启用计划任务，保留电脑可用并等待一个真实到期节点，核对任务结果与飞书数据。手动成功不代替自动触发成功。
5. 任一步失败就先停止验收，按 [故障排查](TROUBLESHOOTING.md) 处理；不要把失败标成成功，也不要向维护者发送账号密钥或未脱敏原始文件。

- 在一个新解压目录、独立虚拟环境安装成功，doctor 提示符合实际。
- 自己的飞书三表和九组件建立，重跑初始化不重复建资源。
- 自己账号一条到期作品：生成新 Excel、唯一匹配、保存证据、飞书值回读一致。
- 重复运行同一节点不再次导出；飞书故障后同一证据可重试同步。
- 登录失效或导出不确定必须停止；不得记成功或无限点击。
- 确认终稿后跨任务读取同一资产索引；复盘结论有当前证据指纹。

单元测试、模拟 Excel 和已有作者机器的成功，均不能替代以上最后一公里验收。遇到失败按 TROUBLESHOOTING.md 收集脱敏错误，不需要自行盲改源码。
