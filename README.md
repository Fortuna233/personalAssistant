# 沈轻媞

Windows 10 常开主机上的个人学习资料中心。Windows、Mac、Android 使用本地 Obsidian，通过 Syncthing 在校园网双向同步；主机提供统一 API，主要通过命令行对话使用；网页对话按需打开资料、论文和笔记工作区。后续 Linux 可加入相同同步集合。

当前是可运行的第一版实现，不表示三台真实设备已配置或验收。未修改现有 `/Users/renhan/Documents/Notes`。

## 当前能力

- Markdown / TXT / CSV 正文检索，返回原文路径、行范围、SHA-256 版本；PDF 按页索引，EPUB 按章索引。
- 检测资料新增、修改、删除；默认 60 秒轮询，可手动扫描。扫描版 PDF 需要后续 OCR。
- Markdown 安全渲染与本地图片、PDF 浏览器阅读、EPUB 正文按出版顺序阅读、CSV 文本查看和图片预览。
- 阅读位置持久化，跨设备共享，版本冲突返回 409；批注保存原文版本、位置、摘录和笔记，可导出 JSON。
- 文件列表显示名称、类型、大小、创建日期和最近修改日期；支持升降序排序与目录导航。
- 文件树支持新建 Markdown/TXT/CSV、文件夹、重命名、移动、复制、可恢复删除；不覆盖目标，移动保留阅读记录。
- 网页登录、HttpOnly 会话、变更请求校验；无外部 CDN、统计或跟踪图片。
- Windows 安装、开机任务、网络检查、备份脚本；Syncthing 本地 API 配置工具。

## 快速开发

Python 3.11+ 推荐（最低 3.9，SQLite 需支持 FTS5 trigram）。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-lock.txt -e '.[dev]'
cp config/example.json config/local.json
```

修改 `config/local.json` 的 `library`、`database` 和 `token`。密钥至少 24 字符，不得使用示例占位值；可用 `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` 在自己的终端生成。默认监听 `127.0.0.1:8765`，校园网访问需改为主机校园网 IP 或 `0.0.0.0` 并限制防火墙来源。

```bash
.venv/bin/python -m assistant --config config/local.json
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src tests scripts
.venv/bin/python -m ruff format --check src tests scripts
```

Windows 命令见 [今晚部署与验收](docs/TONIGHT.md)。`library`、`database` 相对路径以配置文件所在目录的上一级解析，默认配置位于 `config/`；不要把数据库放进文件同步目录。修改配置后重启服务。项目采用 setuptools 打包，静态页面包含在 Python 包中。

## 目录

```text
src/assistant/       应用 API、索引、阅读状态与本地网页
scripts/            Windows 部署、Syncthing 配置、网络检查与备份
config/example.json 可提交的配置示例；local.json 不提交
tests/             索引、安全、EPUB、跨设备状态回归测试
docs/              架构、限制、部署、验收和后续路线
```

## 数据和限制

阅读与索引不会改写原文；文件管理操作会实际创建、移动或移除原路径，并通过 Syncthing 同步。删除文件保存在主机 `.study-trash`，可从网页回收区恢复；目标重名时拒绝覆盖。重命名与移动暂不改写笔记中的双链或相对链接。增量索引保留一份当前原文提取文本。PDF 页码通过页面上方手动保存，浏览器原生阅读器的实际翻页无法自动捕获。EPUB 为正文阅读版，暂不保留出版社版式、插图、DRM 内容。网页需要主机在线，不提供离线网页阅读；Obsidian 本地资料可离线编辑。

笔记/protocol 放在独立 Git 记录目录；PDF、EPUB、实验数据放在 Media 目录。两者分别同步，论文与书籍可按设备设置忽略规则或拆分课程集合，不提供云盘式占位符。三分屏阅读与 Zotero 官方元数据同步 + 本机附件桥接配置见 [Zotero 与同步](docs/ZOTERO_SYNC.md)。

资料搜索保持有来源的文本检索。“文献”已接入可配置模型、全文初稿、逐节问答和阅读规则版本。邮件、表单提交与 Temporal 工作流仍属后续阶段，尚未实现。见 [路线与架构决策](docs/ARCHITECTURE.md)。

校园网内 HTTP 登录与文件传输不提供 HTTPS 保密性；真实私人资料部署应通过本地反向代理配置可信 HTTPS，或先仅使用 localhost 试验网页。Syncthing 自身文件传输有设备认证与加密。数据库内含笔记文本和批注，运行目录应限制在自己的账户权限内。

Syncthing 是同步，不是完整备份；主机本地修改不会由其本机版本管理自动保留。请定期运行 `scripts/backup.py` 到同步树之外的备份磁盘，并做恢复测试。

## Git 与贡献

使用短期分支、检查后合并 main。开发约定、提交 hooks 与远程保护建议见 [CONTRIBUTING.md](CONTRIBUTING.md)，版本变化见 [CHANGELOG.md](CHANGELOG.md)。当前仅本地仓库，尚未连接远程；GitHub CI 和 Dependabot 配置将在接入 GitHub 后运行。

文件创建日期使用主机文件系统提供的时间；不支持时标记 `*` 并使用首次发现时间，不能视为源设备的创建日期。文件操作限制在资料库、拒绝隐藏路径和符号链接；Syncthing 同步根目录不能从网页重命名或删除。回收区记录保存在数据库，文件保存在 `.study-trash`，备份和恢复时应保留两者。

## 能力成长的目标架构

成功流程和用户纠正将通过“候选 → 验证 → 启用 → 自动匹配 → 固定版本执行 → 反馈”复用。能力包由 Git 管理，运行状态由服务器持久化；能力启用不等于外部操作审批。[完整设计](docs/CAPABILITIES.md)及 [ADR](docs/adr/0001-capability-lifecycle.md)已纳入架构，通用机制尚未实现；文献模块已实现固定能力快照与阅读规则的跨任务加载。

## 个人记录版本管理

笔记、实验记录和 protocol 由独立的个人 Git 仓库管理，不进入助手代码仓库。Mac 初始仓库已建立，Windows 统一提交的目标设计与迁移步骤见 [个人记录 Git](docs/PERSONAL_RECORDS.md)。Syncthing 不同步 `.git`；文献笔记已支持自动限定路径提交；通用 checkpoint 与历史页面尚未实现。

## 文献阅读

打开“文献”，在“模型与规则”配置 OpenAI / DeepSeek / Kimi 或兼容服务，主机通过环境变量读取密钥。导入/选文件只在本机提取信息，点击后才调用模型。全文初稿、原文小标题对照、逐节提问、五列主题表、个人想法保护、独立 Git 提交及阅读规则版本已实现。详细配置、使用流程、best practice 与限制见 [文献阅读说明](docs/LITERATURE_READING.md)。未配置密钥不会显示虚假分析结果。

默认是独屏对话；文献「逐节阅读」在左侧保留对话，右侧显示论文与笔记。右上角「同步」显示 Zotero 桥接状态与本机 PDF/EPUB 接收选择。Zotero 桥接需启用本机 API 并配置明确的附件目录；尚未完成真实多设备验收。

主要入口：`.venv/bin/python -m assistant chat --config config/local.json`；主机使用 `serve`，旧的 `--config` 启动命令保持兼容。终端操作、模型设置、对话持久化与按需工作区见 [对话与命令行](docs/CONVERSATION_CLI.md)。
