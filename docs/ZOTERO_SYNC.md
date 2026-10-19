# 三分屏与 Zotero 附件同步

## 存储与责任

```text
PersonalRecords/                  独立 Git 仓库 + study-notes 同步集合
  文献阅读/论文/                   助手生成笔记与个人想法
  文献阅读/主题/                   五列汇总
  Protocols/                       Obsidian 手工维护的 protocol
Media/                            普通目录 + study-media 同步集合
  Papers/Zotero/users-0/<key>/     按稳定附件 key 保存文件
  Books/
  Experiments/
assistant/runtime/                本机运行状态，不同步
Zotero/                           Zotero 自己管理，不同步整个目录
```

记录仓库和 Media 必须互不嵌套，也不放在代码仓库内。正文文件经 Syncthing 同步；`.git` 只留在负责提交的常开主机。Mac 原有仓库可保留作历史副本，不能同时自动 checkout。protocol 的既有编辑仍由用户在 Obsidian 完成；助手不会自动改写它们或自动提交所有外部编辑。

Zotero 的条目、作者、标签、笔记和附件记录由 **Zotero 官方数据同步**维护。每台电脑登录同一账号并启用自动同步。文件同步可关闭，附件不使用 Zotero Storage；本实现不需要 Zotero API Key。Zotero 官方数据同步需联网，校园网文件同步并不意味着元数据可以脱离 Zotero 服务器跨端更新。

附件由 `ZoteroBridge` 只读访问本机 API 后复制到 Media，Syncthing 再传播到常开 Windows。Mac 新增条目后：

1. Zotero 官方同步传播新条目和附件记录。
2. Mac 桥接程序发现本机附件，将其原子复制到 `Media/Papers/Zotero/...`。
3. Syncthing 将附件送到 Windows；Windows 助手扫描并建立索引。
4. Windows 本机 Zotero 收到同一附件记录后，如配置了 `storage_root`，桥接程序会补齐缺失的 **stored attachment** 文件。已有双方修改冲突时停止覆盖并显示错误。
5. 手机通过助手网页阅读，或选择接收文件后用本地应用阅读。

Android Zotero 内部离线缓存不由此桥接管理；手机 Zotero App 自己保存的独有附件目前不能从其沙盒自动导入。手机新条目可经官方同步到主机，但若附件只在 Android 沙盒，应先导出到 Syncthing 目录，或使用 Zotero 自带附件同步。桌面 `linked_file` 通过本机 API 可读取，但缺失链接不会凭空重建；推荐用各端相同的链接附件基目录手工关联同步副本。当前不回写 Zotero 批注和附件 MD5 等元数据；Zotero 阅读器新改动会在下一轮稳定扫描后传播，文件变更不等于 Zotero 元数据已更新。

## 配置电脑桥接

Zotero 中打开「设置 → 高级 → 允许此计算机上的其他应用程序与 Zotero 通信」。保持 Zotero 桌面程序运行；本机 API 仅访问 `127.0.0.1:23119`，不要开放此端口给校园网。

常开主机的 `config/local.json` 中增加（路径换成本机实际路径）：

```json
{
  "zotero": {
    "enabled": true,
    "kind": "users",
    "library_id": "0",
    "allowed_roots": ["D:/Zotero/storage"],
    "storage_root": "D:/Zotero/storage",
    "interval_seconds": 60,
    "max_attachment_bytes": 2000000000
  },
  "sync": {"media_folder_id": "study-media"}
}
```

`allowed_roots` 是允许读取和更新附件的目录白名单，可增加自己使用的链接附件目录。不要填整块磁盘。`storage_root` 必须是 Zotero 实际的 `storage` 子目录；留空则不补齐 Zotero 本机缺失附件，只提供助手资料副本。配置路径必须绝对，不能依赖进程工作目录。个人库 `0` 指当前账号；各电脑必须用同一个账号与同一种 ID（不能一端用 0、一端用实际用户 ID）；群组则填写 `groups` 和群组数字 ID。切换 Zotero 账号前使用新的 Media/运行数据库隔离资料。

网页右上角「同步」可启停后台桥接、立即扫描并查看逐附件状态。此设置作用于 **运行该助手实例的电脑**，不是浏览网页的手机。开启后台自动扫描后，无需保持对话窗口或网页打开。Zotero 未启动、API 未启用、目录未授权时，显示错误并保留上次元数据与已有文件。

Mac 等产生附件的电脑安装项目依赖后，可只运行桥接，不运行完整网页。配置文件放在代码仓库外，例如 `/Users/renhan/.config/shenqingti/bridge.json`：

```json
{
  "library": "/Users/renhan/Documents/StudyMedia",
  "database": "/Users/renhan/Library/Application Support/ShenQingTi/bridge.db",
  "zotero": {
    "kind": "users",
    "library_id": "0",
    "allowed_roots": ["/Users/renhan/Zotero/storage"],
    "storage_root": "/Users/renhan/Zotero/storage",
    "interval_seconds": 60
  }
}
```

```bash
.venv/bin/python scripts/zotero_bridge.py --config /Users/renhan/.config/shenqingti/bridge.json --watch
```

生成启动文件：

```bash
.venv/bin/python scripts/install-zotero-bridge.py --config /Users/renhan/.config/shenqingti/bridge.json
```

此命令用 `scripts/install-zotero-bridge.py` 生成 Mac LaunchAgent 或 Windows 登录任务脚本，再按输出命令安装。桥接依赖登录后的 Zotero 桌面程序，Windows 在未登录状态运行的助手无法替代它；Zotero 应设为登录后启动。主机 App 已启用桥接时，不要在同一台电脑再启动第二个桥接进程。

## 两个同步集合

Syncthing 已安装后，在每台电脑执行（密钥仅在本机环境变量中）：

```bash
python scripts/configure_sync.py --root /绝对路径/Media --records-root /绝对路径/PersonalRecords --device DEVICE-ID=Windows=校园网IP
```

Windows 使用自己的盘符路径。相同 folder ID `study-notes` 和 `study-media` 可映射到各端不同路径。该工具不会自动搬移旧数据、重置记录 Git 或覆盖旧集合路径。

**已有 Notes / Books / Experiments 三集合的迁移**：先独立备份并暂停所有设备同步，提交个人记录；保留已有个人 Git 历史，将笔记目录与 Media 分开。确认文件完整后，在 Syncthing 界面移除旧集合配置（保留本机文件），再创建两个新集合并核对预览后接收。不能在仍启用的旧集合之上创建重叠根目录，脚本会拒绝。

记录和实验数据默认全部同步；论文和 EPUB 可选。常开主机建议全部接收。在各端自己的助手实例配置 `SYNCTHING_API_KEY` 后，可通过「同步」勾选 PDF/EPUB 并应用到对应本机 Syncthing。设置只改动 `assistant-selective` 标记内的忽略规则，保留用户原有规则，不删除已下载文件，也不改变其他设备配置。这个入口列出本机已索引文件，不提供云盘占位符；尚未下载的文件应提前使用以下目录规则或独立课程集合控制。

手机没有运行助手实例时，在手机 Syncthing 的 Media 集合中配置忽略规则，例如只收某篇论文和某本书：

```text
!/Papers/Zotero/users-0/ABCDEFGH/document.pdf
!/Books/某本书.epub
/Papers
/Books
```

实验数据目录仍接收全部。取消同步不会回收磁盘空间；删除本地文件会被正常文件同步传播，不能把“删除”当成“仅取消本机离线”。规则按设备设置，主机不要套用手机筛选规则。Android 具体 Syncthing 客户端的忽略设置入口需实机验证。

## 阅读界面

文献 → 逐节阅读进入三分屏：左上论文（PDF 用浏览器原生阅读器，其他文本显示来源块）、左下针对当前节的 Agent 对话、右侧笔记与个人想法。小屏幕纵向排列三窗。笔记「保存到 Git」使用版本校验，其他设备改动后拒绝覆盖；生成正文仍可在 Obsidian 修改，后续生成遇到修改会停止覆盖。PDF 小节选择只切换问答上下文及笔记，不自动定位 PDF 页码；可用原生阅读器定位。

桥接复制按 SHA-256 判断是否变化，重复扫描不重写相同文件；支持单端变更传播。两端都变且不一致时保留双方、提示人工核对。当前不自动传播 Zotero 删除，不会从 Media 清除旧附件；Syncthing 自身仍按正常规则传播文件删除。大型附件每轮会读取校验，可调大扫描间隔。运行数据库在本机盘，单进程部署；不共享 SQLite 文件给各设备。

## 验证边界

自动化测试使用本机 API 的 HTTP mock 和临时目录；覆盖新增、幂等、单端更新、双端冲突、缺失附件补齐、路径边界、断线保留、分页一致性和选择规则。尚未连接真实 Zotero 资料库，也未声称 Mac / Windows / Android 实机端到端验收完成。

官方依据：[数据同步与文件同步](https://www.zotero.org/support/sync)、[本机 API](https://www.zotero.org/support/dev/web_api/v3/local_api)、[Syncthing 忽略规则](https://docs.syncthing.net/users/ignoring.html)。
