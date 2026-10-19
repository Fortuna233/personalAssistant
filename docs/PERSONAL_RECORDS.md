# 个人记录独立 Git 仓库

## 已建立的边界

| 仓库/存储 | 当前或目标位置 | 内容 |
|---|---|---|
| 助手代码仓库 | `/Users/renhan/AgenticProjects/personalAssistant` | 应用、脚本、能力契约、通用规则、脱敏测试 |
| 个人记录仓库 | `/Users/renhan/Documents/Notes` | Obsidian Markdown、实验记录、protocol、小型结果文件与关联图片 |
| 运行数据库 | 助手主机的 runtime，不纳入任一 Git 仓库跟踪 | 索引、阅读状态、审批、执行与版本管理作业状态 |
| 大型资料与原始数据 | 主机的 Books / Experiments 或独立数据目录 | PDF、EPUB、大型仪器数据；独立备份，不默认进入记录 Git |

两个仓库独立初始化，不嵌套、不作为 submodule，不将个人仓库 bundle、原文、diff 或访问凭据复制到代码仓库。个人仓库尚无远程地址，未上传任何内容。

当前已在 Mac 个人记录目录创建 `main` 与初始提交，保留原文件内容；只纳入笔记、小型关联图片和仓库配置。Obsidian 插件/布局、同步元数据、数据库、常见密钥文件、书籍和原始大数据目录已忽略。初始导入仅选择白名单格式且单文件不超过 10MB；这不是一个持续运行的大小拦截器。

## 三种机制各自负责什么

- Syncthing：传播当前文件状态，支持 Obsidian 本地离线使用和同步冲突副本。
- 记录 Git：保存明确的历史版本、修改原因和可追溯的 protocol 修订。
- 独立备份：保存数据库、Git 历史与大数据的可恢复副本。

Syncthing 的 `.git` 忽略规则必须在每台设备生效。不得通过 Syncthing 同步 Git 对象、引用、锁和索引。个人仓库的 `.gitignore`、`.gitattributes` 可以作为普通文件同步；它们不包含 Git 内部状态。

推荐只有 Windows 常开主机负责自动生成记录提交，Mac、Android 继续编辑同步文件。当前初始仓库在 Mac，转交 Windows 时必须克隆同一段历史，而不是在 Windows 再初始化一个无关仓库。若未来需要各端独立 Git，必须用 Git fetch/push 交换提交，并明确如何避免与文件同步重复合并；第一版不采用两套自动合并并行运行。

## 迁移到 Windows 的步骤（尚未执行）

1. 先完成同步测试与全量备份，暂停编辑和同步。
2. 在 Mac 记录仓库检查并提交需要保留的修改。将完整 bundle 导出到两个仓库之外，例如独立备份盘：

   ```bash
   git -C /Users/renhan/Documents/Notes bundle create /Volumes/Backup/records.bundle --all
   ```

   该文件含私人记录及完整历史，不放进助手代码目录或上传到代码远程。
3. 在 Windows 将 bundle 克隆到新的、空的本地记录目录，例如 `D:\PersonalRecords`；原目录若已存在则先备份，不能直接覆盖。

   ```powershell
   git clone E:\RecordBackups\records.bundle D:\PersonalRecords
   ```

4. 核对提交历史和文件后，把该目录配置成 Windows 的 study-notes 同步集合。Mac、Android 保留 `.git` 忽略规则，先核对差异再恢复同步。
5. Windows 接管提交责任；Mac 的现有 `.git` 保留作为本地历史副本，不再同时执行自动提交/checkout。其 working tree 因同步变化而显示修改是预期现象。

只有同步进入空闲且不存在 `.sync-conflict-*` 文件时，才适合生成主机快照；“空闲”仍不是全局一致事务保证。自动提交服务需校验文件在读取期间未变化，检测到变化则重试，不能将半写入文件标为成功快照。

## 版本管理接口（目标设计，尚未实现）

在 adapters 中增加 `RecordsVersionStore` 的本地 Git 实现，向业务层公开：

- `status(repository_id)`：待提交、冲突、仓库状态。
- `checkpoint(paths, reason, task_id)`：仅提交明确范围，返回提交 SHA。
- `history(path)` / `diff(path, before, after)`：查询历史和变更。
- `read_revision(commit, path)`：为引用读取指定版本。
- `restore_revision(path, commit)`：预览差异并按策略确认后恢复指定内容，追加新提交。

业务用例不拼接 shell，不操作 `.git` 内部文件。适配器使用参数化进程调用、资料目录边界校验、应用层单写队列和 Git 锁保护；遇到已有 Git 操作、冲突、身份配置缺失或仓库异常时停止并报告，不强行清理锁，不自动重写历史。

用户在网页完成文件操作后，可排队创建一个限定路径的 checkpoint；多次 Obsidian 编辑可以按稳定窗口合并为快照。不要每个按键都提交，也不要使用覆盖整个工作区的 `git add -A` 纳入无关资料。对外部同步引起的删除，需保留删除路径集合，才能正确记录版本。

文件操作与 Git 提交不是原子事务：提交失败时保留用户已完成的编辑，记录 `version_pending` 并允许重试，不擅自恢复旧文件。文件操作成功与历史保存成功在状态上区分；进入代码远程的日志不得包含私人 diff。

恢复历史不得使用整个仓库的 `reset --hard` 或强制覆盖同步目录。先检查当前文件版本与未提交修改，展示指定文件/目录将发生的变化；确认后追加恢复提交，再由 Syncthing 传播。protocol 被既有实验使用时建议追加新版本并标记旧版，不默认改写已使用版本的证据。

## 与能力、资料引用的关系

- 通用执行说明和脱敏规则进入代码/能力仓库；个人偏好、实验细节和私人 protocol 进入记录仓库。
- 能力包以受控参数或 `repository_id + commit_sha + path + locator` 引用个人资料，不把私人内容打包进能力源码。
- 任务使用某个 protocol 时保存所用修订；原文件后来变化，旧任务仍能解释当时依据。
- 检索索引可保存当前版本映射，Git 提供文本历史。未提交的新修改使用内容哈希表示，不能伪装为已有提交版本。
- 个人仓库历史不等于能力激活记录；更新 protocol 不会自行授予发送、提交或运行脚本权限。
- 小型 CSV、图片可按需纳入 Git。PDF、EPUB、大型二进制不默认加入；确需历史时单独评估对象版本、Git LFS 或数据版本工具，不能宣称记录 Git 已覆盖它们。

## 当前可用与待实现

已完成：Mac 独立本地仓库、初始提交、忽略规则与行尾约定；未移动或修改现有笔记正文。

当前可手动运行：

```bash
cd /Users/renhan/Documents/Notes
git status
git diff -- 实验记录/你的文件.md
git add -- 实验记录/你的文件.md
git commit -m "Update experiment record"
git log --oneline
```

尚未实现：Windows 接管、自动 checkpoint、Git 历史网页、任务 protocol 版本引用、恢复操作审批。远程托管和任何定时自动化尚未配置。

验收需覆盖：代码仓库无私人原文、记录修改能 diff、protocol 历史可读取、同步不传播 `.git`、并发编辑不生成不一致快照、提交失败不丢工作区、历史恢复追加提交、转移主机后历史连续。

新的存储布局使用互不嵌套的 `D:\PersonalRecords` 和 `D:\StudyLibrary\Media`，迁移步骤见 [Zotero 与同步](ZOTERO_SYNC.md)。旧目录不会自动搬迁。
