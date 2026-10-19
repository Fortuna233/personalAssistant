"""Reject secrets and personal/runtime artifacts in staged files or the tracked tree.

This is a narrow guardrail, not a replacement for manual review or a full secret scanner.
Only offending paths are printed, never matched secret values.
"""

import argparse
import re
import subprocess
from pathlib import Path, PurePosixPath

PRIVATE_PREFIXES = ("runtime/", "data/", ".venv/", "backups/", "dist/")
PRIVATE_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".pem", ".key", ".p12", ".pfx")
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\b(?:ghp|gho|github_pat)_[A-Za-z0-9_]{30,}\b"),
    re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b"),
)


def problems(name, content):
    path = PurePosixPath(name)
    issues = []
    if (
        name.startswith(PRIVATE_PREFIXES)
        or name == "config/local.json"
        or (path.name.startswith(".env") and path.name != ".env.example")
        or name.lower().endswith(PRIVATE_SUFFIXES)
        or "__pycache__" in path.parts
        or any(part.endswith(".egg-info") for part in path.parts)
    ):
        issues.append("私人配置、运行文件或密钥文件不得入库")
    if len(content) > 5_000_000:
        issues.append("超过 5MB：原始资料应保存在资料库，不应提交代码仓库")
    if any(pattern.search(content) for pattern in SECRET_PATTERNS):
        issues.append("发现疑似凭据；请移除并检查是否需要撤销")
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true")
    args = parser.parse_args()
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    command = (
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"]
        if args.staged
        else ["git", "ls-files", "-z"]
    )
    names = subprocess.check_output(command, cwd=root).decode("utf-8").split("\0")
    failures = []
    for name in filter(None, names):
        if args.staged:
            content = subprocess.check_output(["git", "show", ":" + name], cwd=root)
        else:
            path = root / name
            if path.is_symlink():
                failures.append(name + ": 不允许提交符号链接")
                continue
            content = path.read_bytes()
        failures.extend(name + ": " + issue for issue in problems(name, content))
    if failures:
        print("\n".join(failures))
        raise SystemExit(1)
    print("Repository guard passed")


if __name__ == "__main__":
    main()
