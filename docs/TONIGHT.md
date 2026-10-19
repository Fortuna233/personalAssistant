# 今晚：Windows 10 / Mac / Android 部署与验收

本文件是待执行的设备部署步骤；当前开发会话没有访问 Windows 与 Android。先用测试目录，不直接配对已有真实笔记库。

## 1. 准备主机

1. 安装 Python 3.11+（python.org，启用 Python Launcher）、Obsidian、Windows 版 Syncthing。
2. 下载源项目到本地目录，如 `C:\StudyHarbor`。建议使用内置本地磁盘，避免 OneDrive 管理该目录。
3. 在普通 PowerShell 中运行（若 D 盘不存在，将路径改成 C 盘）：

```powershell
cd C:\StudyHarbor
powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1 -Library C:\StudyLibrary
.\.venv\Scripts\python.exe -m assistant --config config/local.json
```

4. 本机访问 `http://127.0.0.1:8765`，从本机 `config/local.json` 复制 token 登录。不要把 token 发到聊天或提交 Git。
5. 先保留 localhost 监听完成自测。要让其他设备访问，修改配置 `host` 为主机校园网 IPv4，重启服务。HTTP 不保密，使用测试资料；正式私人资料需反向代理可信 HTTPS 并设置 `secure_cookie: true`。Syncthing 文件传输与网页 HTTP 是不同通道。

项目与资料目录：

```text
C:\StudyHarbor\                 代码、虚拟环境、配置
C:\StudyHarbor\runtime\         数据库，不同步
C:\StudyLibrary\Notes\          Obsidian 库与笔记内嵌图片
C:\StudyLibrary\Books\          PDF / EPUB，按课程子目录
C:\StudyLibrary\Experiments\    CSV / 图片等原始实验数据
```

默认仅索引上述 library 范围，隐藏目录、越界符号链接不读取。索引后台每 60 秒更新；首次解析几 GB 书籍可能较久，网页显示索引状态。

## 2. 连接检查

Windows 运行 `ipconfig` 找到校园网 IPv4。Mac 运行 `nc -vz WINDOWS_IP 22000`；网页端口测试 `nc -vz WINDOWS_IP 8765`。Android 浏览器打开 `http://WINDOWS_IP:8765`。

先在 Windows 防火墙为实际测试设备 IP 放行 TCP 22000（同步）和 8765（网页）。管理员 PowerShell 示例，必须替换为实际 Mac、Android IP：

```powershell
New-NetFirewallRule -DisplayName "StudyHarbor web" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -RemoteAddress MAC_IP,ANDROID_IP
New-NetFirewallRule -DisplayName "StudyHarbor sync" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 22000 -RemoteAddress MAC_IP,ANDROID_IP
```

保留 Syncthing 管理面板监听 `127.0.0.1:8384`，不要把管理端口开放给校园网。仅允许已配对设备。IP 变化后需更新静态地址/防火墙；跨校园网子网可能被网络策略隔离，不能靠应用配置绕过。若直连失败，记录错误，待调整网络环境；第一版禁用公网发现、中继、NAT 映射。

## 3. 三端安装与配对

- Windows / Mac：Syncthing 官方下载 https://syncthing.net/downloads/ 。Mac 解压后运行；打开本机 `http://127.0.0.1:8384`。
- Android：当前维护的候选为 https://github.com/researchxxl/syncthing-android 。核对其发布页来源安装 Syncthing-Fork；官方旧 Android 应用已停更。安装 Obsidian，允许同步应用访问选择的本地目录、后台运行并解除电池优化。具体 Android 版本兼容性今晚验证。
- 在三端设置中关闭全局发现、中继和 NAT 穿透；监听仅 TCP。可启用局域网发现，但跨子网优先填写 `tcp://WINDOWS_IP:22000`。
- Mac 和 Android 只与 Windows 交换设备 ID，两端都人工确认。不要启用自动接受文件夹或介绍人。
- 删除安装时自动创建的 Default Folder 配置（只移除共享配置，不删除文件），避免误共享用户目录。

## 4. 配置测试资料集合

在 Windows Syncthing 设置中读取本机 API Key（不要复制到文档或 Git）。在同一 PowerShell 临时设置环境变量，然后运行：

```powershell
$env:SYNCTHING_API_KEY = Read-Host "本机 Syncthing API Key"
.\.venv\Scripts\python.exe scripts\configure_sync.py --root C:\StudyLibrary --device "MAC_DEVICE_ID=Mac=MAC_IP" --device "ANDROID_DEVICE_ID=Android=ANDROID_IP"
Remove-Item Env:\SYNCTHING_API_KEY
```

脚本创建 `study-notes`、`study-books`、`study-experiments` 三个集合，启用错时版本管理，并只将其分享给显式指定的设备。已有同 ID 集合保留原路径与配置，仅追加显式设备；已有其他集合管理同一路径则拒绝。脚本不安装 Syncthing、不写客户端二进制、不会复制现有资料。需要重启时从 Syncthing 本机管理页重启。

Mac 接受 `study-notes` 到**新建的测试目录**如 `~/StudyTest/Notes`；Android 接受到 `Documents/StudyTest/Notes`。两端都用 Obsidian 打开对应本地目录。三端文件夹类型均为 Send & Receive。

每台设备都配置忽略项（`.stignore` 本身不会跨设备同步）：

```text
.DS_Store
Thumbs.db
.git
.obsidian
.trash
.study-trash
```

各设备独立保留 `.obsidian` 配置。首次迁移可人工复制熟悉的配置，不自动同步插件密钥和界面状态。每台设备启用文件版本管理；版本管理只保存来自其他设备的替换/删除，不保存本机编辑历史。

### 手机书籍按需

Syncthing 是按集合复制，不是按需占位云盘。Android 初期只接受 Notes 集合；不要接受整个 Books / Experiments。

需要离线某课程时，在 Windows 新建如 `study-books-courseA`，路径 `Books/课程A`，仅分享该集合给手机。在 Windows 的父 Books 集合设置忽略 `课程A` 后，才建立子集合，避免重叠同步。Mac 也按相同集合边界接收。更简单的首版方法：使用网页“打开原文件”另存到手机，作为只读离线副本；这些下载副本不支持文件修改回传，阅读状态仍通过网页在线保存。

不建议用扩展名全局过滤的方式同步 Obsidian 库：容易让笔记内嵌图片或相对路径附件失联。

## 5. 导入现有资料

通过第 7 节测试后：

1. 先备份 Mac `/Users/renhan/Documents/Notes` 到同步范围之外；关闭三端 Obsidian，等待同步空闲。
2. 首次以 Mac 原库为唯一种子：把内容复制到已验证的 Mac 测试 Notes 目录，等待同步到主机，核对文件数和重要笔记。不要同时合并三份已有库。
3. Windows、Android 若已有独立笔记，先分别备份，再通过人工比较合并。不要直接选用“覆盖远端”或“还原本地更改”。
4. 将三端 Obsidian 打开的库切换到新的同步目录。验证成功后保留原库备份；此项目不会自动移动或删除原库。
5. 书籍和原始实验数据按目录逐批复制到 Books / Experiments，再扫描索引。

## 6. Windows 无人值守启动

先手工退出运行中的助手与 Syncthing，避免两个进程占用同一端口/数据库。以**将实际运行服务的同一账户**打开管理员 PowerShell：

```powershell
cd C:\StudyHarbor
powershell -ExecutionPolicy Bypass -File scripts\register-windows-startup.ps1 -SyncthingExe C:\Tools\Syncthing\syncthing.exe
```

脚本创建开机计划任务，接通电源时关闭自动休眠。使用当前账户 S4U 登录类型，不需长期保存密码，只支持本地文件访问。账户策略若拒绝 S4U，需在任务计划程序改为“无论用户是否登录都运行”并在本机提供凭据，不要把密码写入脚本。

重启主机，**尚未登录 Windows** 时从手机验证网页与同步；通过后才能认为无桌面窗口依赖。若失败查看任务计划程序 Last Run Result 和任务 History。

撤销：

```powershell
Unregister-ScheduledTask -TaskName StudyHarbor -Confirm:$false
Unregister-ScheduledTask -TaskName StudySyncthing -Confirm:$false
Remove-NetFirewallRule -DisplayName "StudyHarbor web"
Remove-NetFirewallRule -DisplayName "StudyHarbor sync"
```

恢复休眠参数按你原先设置操作；卸载任务不会删除任何资料。

## 7. 验收清单

所有行在真实设备操作后填写结果；尚未执行不打勾。

| 验收 | 操作与预期 | 结果 |
|---|---|---|
| 三端双向 | Mac 新建 Markdown；Windows、Android 出现；分别追加不同段落并等待同步 | 待验证 |
| 离线 | 手机断网编辑，恢复校园网，Windows/Mac 收到 | 待验证 |
| 图片引用 | 笔记加入相对路径图片和 `![[图片.png]]`；三端 Obsidian 与网页可见 | 待验证 |
| 冲突 | 两端断网修改同一文件再联网；保留冲突副本，手工合并 | 待验证 |
| 删除恢复 | 删除测试文件，确认其他端同步删除，再从另一端版本记录恢复 | 待验证 |
| 原文检索 | 查询中文短词、英文；返回行/页/章与版本；能打开原文件 | 待验证 |
| 索引更新 | 修改/删除测试资料，60秒后搜索更新 | 待验证 |
| EPUB | Mac 阅读至第3章保存，Android 打开显示第3章 | 待验证 |
| PDF | 页码输入7并保存，另一设备打开请求第7页；移动浏览器不支持内嵌则打开原文件 | 待验证 |
| 批注 | 两端分别新增批注，刷新可见；JSON导出包含位置、摘录、原文版本 | 待验证 |
| 进度冲突 | 两端同时打开，A保存后B保存，B收到冲突提示 | 待验证 |
| 认证 | 未登录不能访问文件、检索或批注；退出后旧会话失效 | 待验证 |
| 重启 | Windows重启且未登录，手机仍能连接网页与同步 | 待验证 |
| 备份恢复 | 快照数据库与资料，复制到临时目录启动，核对批注和文件 | 待验证 |

## 8. 备份

关闭编辑，等待同步完成后，备份到同步范围之外，最好另一个物理磁盘：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\backup-windows.ps1 -Destination E:\StudyBackups
```

数据库使用 SQLite backup API 获取一致快照，文件使用只读复制，不改变原文件。每次生成新时间戳目录，暂不自动清理旧备份。恢复时停止服务，把备份的 `assistant.db` 复制到测试运行目录，library 复制到测试资料目录，配置指向两者，验证后再恢复正式环境。不要把 runtime 数据库作为 Syncthing 集合共享。
