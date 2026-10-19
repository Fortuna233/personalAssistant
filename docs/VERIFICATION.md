# 验证记录 · 2026-10-19

## 开发机已执行

- Python 3.9：11 项 pytest 回归通过。
- Python 3.12：核心 9 项回归通过（另两项 Syncthing 空响应回归随后在 Python 3.9 执行）。
- Ruff 静态检查、格式检查通过；Node 对前端 JavaScript 语法检查通过。
- 本地浏览器人工操作：登录 → 资料列表 → EPUB 阅读 → 下一章 → 保存进度 → 保存批注；结果在页面显示。合成演示数据，不是个人原库。截图见本目录。
- 官方 Syncthing v2.1.6，macOS ARM64，两个临时独立实例：配置重复运行无重复集合；LAN-only 选项、错时版本、忽略规则检查通过；测试 Markdown 正反方向内容同步通过。
- 临时 Syncthing 实例测试结束后已退出，未配置设备开机启动，未连接真实资料库。

## 可复现命令

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src tests scripts
.venv/bin/python -m ruff format --check src tests scripts
node --check src/assistant/static/app.js
.venv/bin/python scripts/verify_syncthing.py --binary /absolute/path/to/syncthing
```

最后一条启动临时本地实例，需要空闲端口 18384、18385、22000、22001。不要在正式主机 Syncthing 运行时执行，会先检查端口占用并退出。测试生成的独立临时目录用于排查日志，不读取任何现有资料库。测试二进制请从官方发行版获取。

## 待真实设备验证

- Windows 10 PowerShell 安装与 S4U 开机任务，未登录时运行。
- Windows / Mac / Android 三端配对、离线恢复、冲突、版本恢复。
- Android 分支安装、后台权限、Obsidian 目录访问。
- 校园网防火墙和跨子网设备互通。
- Android 浏览器 PDF 显示；不支持内嵌时可打开原文件，自动 PDF 页码捕获尚未实现。
- 真实 PDF/EPUB/Obsidian 附件兼容性、资料规模性能。
- 正式资料的可信 HTTPS 配置。

未验证事项不视为验收通过；逐项记录在 TONIGHT.md。

## Git 管理补充验证

- 新增私人配置与疑似凭据检查回归，总计 13 项 pytest 通过。
- 本地 pre-commit 启用：敏感文件检查、Ruff、格式、测试；main 禁止直接提交。
- CI 配置已创建，但未连接远程，不能声称 GitHub CI 已执行。
- Actions 使用已核实的官方完整提交 SHA：checkout v7.0.1、setup-python v7.0.0。

## 文件浏览器改动验证

- 共 32 项 pytest 回归通过，新增文件元数据、路径限制、符号链接、创建、移动、目录复制、独立身份、保留进度、删除恢复、恢复检索、同名冲突、过期版本和同步根目录保护测试。
- Ruff 静态/格式检查和前端 JavaScript 语法检查通过。
- 本地浏览器已观察到文件树、列表日期、排序与新建文件成功后的即时更新。完整移动/复制/恢复流程通过 API 与服务层回归验证；尚未声称三端真实同步测试通过。
- 文件操作仅在合成演示目录和临时测试目录执行，未接入 `/Users/renhan/Documents/Notes`。

## 文献阅读实现验证

- 共 51 项 pytest 回归通过：全文快照、小标题与引用校验、失败续跑、去重缓存、规则跨会话加载、旧快照保留、章节问答、独立 Git 输出、个人区域保护、暂存区保护、Git 失败保留文件、取消、请求上限、空扫描 PDF 与单 Worker 锁。
- OpenAI Responses、DeepSeek/Kimi Chat Completions 的 HTTP 请求/响应契约通过 MockTransport 测试；未使用真实云端账号测试。
- 本机浏览器已实际验证“文献”五列表格、Methods 小标题切换、原文/证据对照、个人想法保存、Git 提交成功和表格更新。
- 演示条目明确标识为本地合成测试，不是真实论文分析；个人想法与笔记写入独立临时 Git 仓库，未修改真实个人 Notes 仓库。
- 本机未配置模型 API Key。云端分析质量、账号模型兼容性、Windows/Android 和校园网三端行为仍需真实环境验证。
