# 架构与阶段边界

## 已确认需求

- Windows 10 常开主机；允许安装、开机运行、关闭休眠。
- Windows / macOS / Android 均以 Obsidian 编辑 Markdown；恢复联网后自动同步。
- 当前仅校园网；不使用北大网盘、不做公网发布。
- 笔记几 MB，书籍几 GB，实验数据几十 MB，单文件可能几百 MB（容量为用户估计，待扫描确认）。
- 手机完整离线笔记与内嵌图片，书籍、大数据按需；统一阅读入口和共享阅读状态。
- 当前真实 Mac 库为 `/Users/renhan/Documents/Notes`，不是整个 Documents。

## 选择

采用模块化单体，文件同步交给成熟的 Syncthing。同步、阅读、索引互不承担对方的状态职责：

```text
Windows 本地 Obsidian ─┐
Mac 本地 Obsidian ─────┼─ Syncthing（设备认证、LAN直连、冲突文件）
Android 本地 Obsidian ─┘             │
                         Windows 全部资料目录
                                  │ 只读扫描
                          Library 索引服务
                                  │
                      FastAPI + SQLite WAL + 静态网页
                                  │
                         浏览器阅读 / 状态 / 批注
```

先不引入 PostgreSQL、Temporal、Redis 或 Kubernetes。当前是单用户单主机索引与阅读，SQLite 的事务、WAL、数据库备份能满足已实现用例；邮箱长任务和复杂审批实现时再引入工作流运行时。此前建议的 PostgreSQL + Temporal 为完整助手的演进方向，不是本阶段必需安装项。

## 个人记录版本管理

笔记、实验记录、protocol 与小型关联附件使用独立 Git 仓库，与本项目代码仓库分开。Mac 当前记录仓库位于 `/Users/renhan/Documents/Notes`，已建立初始本地版本；未设置远程。

目标部署中由 Windows 常开主机统一生成历史快照，Syncthing 只传播资料文件并忽略 `.git`。运行数据库、书籍与大型原始数据各自保存和备份，不与代码或记录历史混装。

未来通过 RecordsVersionStore 适配器提供限定路径的 checkpoint、history、diff 和受控恢复。资料引用可携带个人仓库 ID、提交 SHA、路径与原文位置；能力源码只保存引用，不复制私人内容。当前自动提交、历史 UI 和版本引用集成尚未实现。详见 [个人记录 Git 边界与迁移](PERSONAL_RECORDS.md)。

## 能力固化与自动加载（目标架构，尚未实现）

新增 capabilities 模块，负责将成功任务与用户纠正形成版本化能力包，并在新任务中匹配、加载。能力复用与某个聊天窗口解耦。

```text
成功执行 + 用户纠正 → 候选能力 → 验证 → 授权范围内启用
                                           ↓
新任务 → 适用性筛选与匹配 → 固定能力/规则快照 → 持久化工作流
                                              ↓
                                业务用例 → 操作审批 → 执行 → 反馈
```

能力内容（契约、步骤、脚本、规则引用、脱敏验收样例）用 Git 管理；运行数据库保存启用记录、匹配依据和任务快照。只加载已验证且处于启用范围内的版本，缺参数才追问；未命中则正常规划。能力文件更改不热更新执行中任务，也不能自动扩大操作权限。

模块边界：capabilities 管能力版本与装配，policies 管纠正规则，workflows 管持久化执行，approvals 管最终动作授权。各模块通过用例接口组合，不跨模块读写内部 SQL。先使用 SQLite 和现有部署结构，不新增微服务、向量数据库或通用插件引擎。

详见 [能力固化与自动加载](CAPABILITIES.md) 与 [ADR 0001](adr/0001-capability-lifecycle.md)。文档里的模块、API 与表是实施契约，不表示代码已具备这些能力。

## 模块契约

- `library.py`：路径安全、原文枚举、哈希、解析、索引与来源。只读原文。
- `files.py`：限制在资料库范围的文件管理、元数据、回收与身份迁移；与扫描共享进程内锁。
- `app.py`：身份认证、请求校验、状态事务、API、索引生命周期。
- `static/`：浏览器入口，只依赖 HTTP API。
- `configure_sync.py`：Syncthing 本机 API 适配器。应用 API 不拥有或覆盖同步状态。
- 阅读数据库与文件分开；同步任何设备的 SQLite 数据库都是禁止的。
- 新文件使用随机稳定 ID，既有文件保留 ID。网页重命名或移动（包括目录）显式迁移路径，保留阅读记录；复制分配独立 ID。外部工具重命名时，仅唯一相同内容且旧路径消失的文件可自动关联；同时改名改内容仍可能无法识别。
- 进程内锁协调扫描和文件操作，修改前核对 stat 版本、目标冲突、Windows 文件名与路径边界。该锁不控制 Obsidian/Syncthing 外部进程，无法承诺跨进程文件系统事务；避免多端同时移动同一路径。
- 可恢复删除将原文件/目录移至主机 `.study-trash` 并保存回收映射；不提供永久删除接口。恢复拒绝覆盖同名路径，缺失父目录需先创建或恢复。崩溃发生于文件系统与数据库操作之间时可能需人工恢复；当前未实现跨资源事务日志。
- 文件修订号 SHA-256；批注保存当时修订号与摘录，原文更新后显示旧版本标记。索引不保存完整历史原文，查看历史依赖备份和 Syncthing 版本记录。
- 进度写入使用乐观锁；批注以追加记录存储，不自动覆盖。

## 需求变化的扩展点

1. 新格式：扩展解析器，输出 `(原文位置, 文本)`，索引和搜索 API 不变。
2. 模型问答：在检索上增加模型适配器，回答保留 doc_id / revision / location；限制外传资料范围，增加预算与测试集。
3. 邮箱：独立模块保存 provider_message_id、同步游标、草稿版本、审批；外部发送需幂等策略和不确定状态核查。
4. 长任务：引入 Temporal 承担等待、定时、恢复；模型与工具调用作为 Activities；进度和副作用记录不交给 LLM 控制。
5. 数据库增长/多用户：拆分 repository 接口，迁移 PostgreSQL 并增加用户/权限隔离；当前单用户密钥不是多用户权限系统。
6. 互联网：先验证 Tailscale 等网络层，再配置 HTTPS；不改变同步和阅读业务接口。
7. 规则学习与能力复用：按 [能力生命周期](CAPABILITIES.md) 提炼候选、验证并在授权范围内启用；新任务匹配后固定版本执行，纠正产生新候选。检索旧对话不能替代规则执行。

## 已知边界

- 尚未进行 Windows、Android 或真实校园网测试，PowerShell 脚本仅静态审查。
- Windows 开机任务采用 S4U，只访问本地资料目录；账户策略可能影响创建任务，需重启后验证未登录执行。
- 手机后台权限与校园网客户端隔离会影响自动同步；需要设备实测。
- 本地 HTTP 默认仅监听回环，LAN 需主动配置；可信 HTTPS 尚未自动配置。
- 大 PDF 解析在后台线程执行，尚无独立解析进程资源隔离。不要导入来源不明的恶意文件。
- 文件快照备份非跨文件事务；备份时应暂停资料编辑；SQLite 使用在线一致性备份。

## 参考

- https://martinfowler.com/bliki/MonolithFirst.html
- https://alistair.cockburn.us/hexagonal-architecture
- https://docs.syncthing.net/users/autostart.html
- https://docs.syncthing.net/users/versioning.html
- https://docs.syncthing.net/users/ignoring.html
- https://docs.syncthing.net/rest/config.html
- https://github.com/researchxxl/syncthing-android
- https://obsidian.md/help/sync-notes

## 文献阅读实现进展

`literature/` 是首个按业务能力独立组织的模块，包含 contracts、sources、models、store、service、notes、api 和 worker。通过模型网关替换 OpenAI/兼容服务，通过 NoteExporter 写独立个人 Git 仓库。后台在服务器生命周期中独立于浏览器运行，步骤结果、原文和能力快照持久化。

当前已实现文献固定能力 ID、规则版本、显式任务触发与快照自动加载；通用能力提炼与语义匹配仍未实现。文献模块的阅读偏好版本保存在运行库，默认流程和约束由代码 Git 管理；不把这一阶段误标为完整 CAPABILITIES.md 已落地。详见 [文献阅读](LITERATURE_READING.md)。
