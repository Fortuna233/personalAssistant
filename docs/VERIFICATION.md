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
