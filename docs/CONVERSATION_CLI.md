# 对话与命令行

## 主要用法：终端客户端

常开 Windows 主机先运行服务，原来的启动命令继续兼容：

```powershell
.\.venv\Scripts\python.exe -m assistant serve --config config/local.json
```

Mac 在项目目录运行（演示服务使用 `runtime/demo/config.json`；真实配置使用 `config/local.json`）：

```bash
.venv/bin/python -m assistant chat --config runtime/demo/config.json
```

也可在安装/更新包后使用 `shenqingti chat --config ...`。`chat` 是客户端，不启动索引器或后台模型工作进程。退出终端，服务器上的任务继续执行；常开主机必须保持运行。

连接 Windows 时使用 `--url http://WINDOWS_IP:8765`，访问密钥从本机私人配置的 `token` 或环境变量 `ASSISTANT_TOKEN` 读取，不能写在 URL 或命令参数里。客户端不跟随重定向转发密钥。校园网 HTTP 的安全限制与原部署文档相同；正式私人资料请沿用可信 HTTPS 配置。

客户端也可以只用环境变量与 `--url`，无需复制主机包含磁盘路径的完整配置；不要将私人配置提交到代码 Git。

```text
你> 我要进行文献阅读
沈轻媞：已打开文献阅读……
工作区：http://主机:8765/#literature
你> /files tau
你> /read Papers/Tau研究.pdf | Tau 文献阅读
<任务 ID>  queued
你> /tasks
你> /job <任务 ID>
<列出原文小标题与章节 ID>
你> /ask <任务 ID> <章节 ID> 关键对照是否充分？
你> /notes <任务 ID>
你> /quit
```

终端不依赖网页完成上述步骤；`/web literature` 输出图形工作区地址，便于需要查看 PDF 或编辑个人想法时打开。终端中的“打开工作区”只返回链接，不会远程操纵另一台设备的浏览器，也不代表后台阅读已开始；`/read` 才会创建阅读任务。阅读、逐节问答、笔记保存复用原 API 与队列，不依赖某个终端常开。

普通自然语言对话会调用已配置的云端模型。明确的“我要进行文献阅读”、`/files`、`/tasks` 可在没有模型时使用；此时不会伪装成模型推理。当前助手对话可以打开文献、文件和任务界面；没有实现任意命令执行、邮件发送等新工具。

### 常用命令

| 命令 | 用途 |
|---|---|
| `/help` | 查看所有命令 |
| `/files [关键词]` | 列出资料 ID 与完整路径；同名文件需用完整路径 |
| `/read 文件路径 \| 主题` | 提交整篇阅读；重复任务使用现有缓存规则 |
| `/tasks`、`/job ID` | 查看进度、失败原因、章节列表和问答结果 |
| `/ask 任务ID 章节ID 问题` | 提交可在退出后继续执行的分节问答 |
| `/notes 任务ID` | 写入并限定路径提交到个人 Git；失败会显示 Git 待处理 |
| `/model` | 查看主机的模型与密钥配置状态 |
| `/model openai 模型名` | 配置模型；也支持 deepseek、kimi；密钥在主机环境变量中设置 |
| `/rules`、`/rule 规则内容` | 查看规则或追加并启用规则；旧任务保留原有快照 |
| `/web literature` | 输出文献工作区地址；还支持 files、tasks |
| `/new`、`/quit` | 新建对话或退出终端 |

非交互命令：

```bash
.venv/bin/python -m assistant chat --config config/local.json --message '我要进行文献阅读'
.venv/bin/python -m assistant read 'Papers/Tau研究.pdf' --topic 'Tau 文献阅读' --config config/local.json
.venv/bin/python -m assistant tasks --config config/local.json
.venv/bin/python -m assistant sessions --config config/local.json
.venv/bin/python -m assistant chat --session <对话ID> --config config/local.json
```

对话 ID 在交互启动时显示；`sessions` 可列出已有对话。网页下拉菜单也可选择主机上同一份对话。当前各客户端不自动切换到另一客户端新建的对话，需主动选择/恢复相同 ID。网页与终端的工作区显示独立，对话文本与任务结果共享。

## 网页交互

原「文献」导航改为「对话」。普通状态只有对话一屏；说“我要进行文献阅读”后，左侧保留对话，右侧打开文献工作区。选择已有阅读任务后，右侧显示论文和笔记；提问自动携带当前原文小节，结果及证据返回左侧对话。新建或切换对话会收起工作区，避免把另一篇论文的上下文带入新会话。

也能通过对话打开文件管理或任务进度；「收起工作区」回到独屏对话。小屏幕上下排列。文献内容、笔记 Git、Zotero 桥接和选择同步仍沿用既有服务。

## 架构边界

```text
终端 CLI ─┐                         ┌─ 资料索引 / 文件管理
          ├─ 已认证 HTTP API ─ 对话服务 ├─ 文献阅读 / 持久任务队列
网页客户端 ┘                         └─ 笔记与独立 Git
                 ↓
           本机 SQLite 对话历史
```

对话服务将回复限制为文本和白名单工作区指令，验证资料 ID 后才导航。模型输出不会作为命令执行，也不会被用作任意导航地址；创建阅读、保存笔记等写操作仍通过各自受约束的 API。普通对话仅向模型提供最近 12 条消息（每条至多 3000 字）、至多 200 条资料路径和当前阅读偏好，不自动上传全部原文。进入原文阅读问答才发送相应小节。

消息带请求 ID，已完成请求重试会复用结果；同 ID 不同内容会拒绝。主机重启时未完成模型调用可以重试，但外部模型调用和 SQLite 不是原子事务，不能保证异常中断绝不产生重复计费。历史在本机运行数据库，不放进个人笔记 Git，也不与其他设备复制 SQLite；各端通过 API 访问同一主机。

当前图形导航支持三个工作区；将来增加工具时增加受约束用例及 API，再注册相应工作区，不把业务逻辑写进终端解析器。Zotero 与文件同步不依赖对话会话运行。
