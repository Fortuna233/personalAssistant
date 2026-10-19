# 开发与 Git 管理约定

## 分支

使用简单的主干流程：`main` 保持可运行，日常工作在短期分支完成。

- `feat/<topic>`：新增能力，例如 `feat/pdf-reader`。
- `fix/<topic>`：修复问题，例如 `fix/android-offline-conflict`。
- `chore/<topic>`：依赖、工具、文档维护。
- 一个分支解决一个问题；避免长期维护 develop 分支。

```bash
git switch main
git switch -c feat/example
```

首次克隆后，根据 README 安装开发依赖，再启用仓库提供的本地检查：

```bash
git config --local core.hooksPath .githooks
git config --local pull.ff only
git config --local fetch.prune true
```

这些设置只作用于本仓库，不修改全局 Git 配置。hooks 不会随 clone 自动启用，CI 是远程兜底；禁止通过跳过检查来宣称验证通过。

## 提交

使用简洁的英文祈使句，如 `Add EPUB chapter navigation`、`Fix reading progress conflicts`。保持一次提交一个目的；不强制引入复杂提交前缀和自动发版工具。提交前检查 `git diff`、`git diff --cached`，显式选择文件。

```bash
git add src/assistant/library.py tests/test_library.py
git diff --cached --check
git diff --cached
git commit -m "Fix document rename tracking"
```

pre-commit 会拒绝直接向 main 提交，并检查暂存文件泄密风险、Ruff 和测试。开发者仍需确认实际提交内容与已测试工作区一致；暂存后继续修改文件时应重新检查、重新暂存。

## 合并

当前没有远程仓库，采用检查后的本地 fast-forward 合并：

```bash
git switch main
git merge --ff-only feat/example
git branch -d feat/example
```

若 main 已有其他提交，回到自己的未共享分支整理或 rebase，重新测试再合并。不要重写已共享分支历史，不向 main 强制推送。线上故障使用 `git revert <commit>` 追加回退提交。

连接 GitHub 后改为 PR 工作流：描述问题、最终行为、验证证据、配置和数据迁移；界面修改附截图。远程建议只启用 squash merge，并在合并后删除分支。配置 main 规则：禁止 force push 和删除、要求 PR、要求 CI 全部通过；个人项目可不强制他人审批。没有远程仓库时，这些平台规则尚未生效。

## 检查与版本

```bash
python scripts/repo_check.py
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python -m pytest -q
```

GitHub CI 矩阵覆盖 Ubuntu、Windows、macOS 的 Python 3.11 与 3.12；PowerShell 仅做语法解析，Android 与实际校园网仍需手工验收。Action 固定完整 SHA，Dependabot 按周提出依赖更新；更新后测试，不自动合并。

`requirements-lock.txt` 固定当前验证过的依赖版本；变更依赖需更新 pyproject 和锁文件并检查差异。锁文件不提供哈希级供应链验证，不得声称完全可重现。

已验收版本使用带注释的 `vX.Y.Z` 标签，并写 CHANGELOG。未完成三端实测的版本标为 `v0.1.0-alpha.1` 一类预发布。标签发布后不移动；修复用新标签。Git 标签只标识代码，不替代资料与数据库备份。

## 私人资料与凭据

只提交实现、示例配置、规则和脱敏测试。禁止提交原始笔记、实验数据、书籍、运行数据库、访问密钥、同步设备配置及完整日志；这些不上传任何远程仓库。

`.gitignore` 和仓库检查只能降低误提交风险，不能检测所有秘密。发现凭据误入 Git 后先撤销凭据，再处理历史；仅删除当前文件不能删除历史。
