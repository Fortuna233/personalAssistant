"""Markdown projections and limited-path commits into a separate personal repository."""

import hashlib
import html
import json
import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path

FIELDS = [
    ("background", "背景、目的以及意义"),
    ("methods", "研究设计与方法"),
    ("results", "结果与结论"),
    ("author_discussion", "作者讨论"),
    ("assistant_analysis", "助手分析"),
    ("suggested_questions", "建议思考"),
    ("limitations", "未覆盖与待核对"),
]
TABLE_HEADERS = ["作者信息", "背景、目的以及意义", "主要方法及结果", "讨论", "想法"]
IDEAS_START = "<!-- user:ideas:start -->"
IDEAS_END = "<!-- user:ideas:end -->"


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def text(value):
    return html.escape(str(value), quote=False).replace("|", "\\|")


def block(result, fields):
    lines = []
    for section in result["sections"]:
        body = []
        for field in fields:
            for item in section["analysis"].get(field, []):
                body.append(text(item))
        if body:
            lines.append("**" + text(section["title"]) + "**\n" + "\n".join(body))
    return "\n\n".join(lines)


def row_cells(result, detail_link, ideas=""):
    meta = result["metadata"]
    author = "\n".join(
        filter(
            None,
            [
                meta["title"],
                "作者：" + "；".join(meta["authors"]),
                "单位：" + "；".join(meta["affiliations"]),
                "日期：" + meta["published_date"],
                "平台：" + meta["venue"],
                "DOI：" + meta["doi"],
            ],
        )
    )
    cells = [
        text(author) + "\n" + detail_link,
        block(result, ["background"]),
        block(result, ["methods", "results"]),
        block(result, ["author_discussion", "assistant_analysis", "limitations"]),
        text(ideas),
    ]
    if not ideas:
        cells[-1] = "（留给你填写）"
    suggestions = block(result, ["suggested_questions"])
    if suggestions:
        cells[3] += "\n\n**建议思考（助手）**\n" + suggestions
    return [cell.replace("\r", "").replace("\n", "<br>") for cell in cells]


def detail_markdown(job):
    result = job["result"]
    metadata = result["metadata"]
    lines = [
        "# " + text(metadata["title"]),
        "",
        "状态：待核对（不表示用户已读完）",
        "作者：" + text("；".join(metadata["authors"])),
        "单位：" + text("；".join(metadata["affiliations"])),
        "日期：" + text(metadata["published_date"]),
        "平台：" + text(metadata["venue"]),
        "DOI：" + text(metadata["doi"]),
        "原文：" + text(result["source_path"]),
        "原文版本：`" + result["revision"] + "`",
        "能力版本："
        + str(result["capability"]["version"])
        + " / `"
        + result["capability"]["digest"]
        + "`",
        "阅读目的：" + text(job["purpose"] or "全文阅读"),
        "",
    ]
    if result["limitations"]:
        lines += ["## 覆盖边界"] + ["- " + text(item) for item in result["limitations"]] + [""]
    for section in result["sections"]:
        lines += ["## " + text(section["title"]), ""]
        for field, title in FIELDS:
            values = section["analysis"].get(field, [])
            if values:
                lines += ["### " + title] + ["- " + text(item) for item in values] + [""]
        if section["analysis"].get("evidence"):
            source = {b["id"]: b for b in section["blocks"]}
            lines += ["### 原文证据"]
            for evidence in section["analysis"]["evidence"]:
                b = source[evidence["block_id"]]
                lines += [
                    "- " + text(b["location"]) + " / `" + b["id"] + "`：" + text(evidence["quote"])
                ]
            lines += [""]
    return "\n".join(lines).strip()


class NoteConflict(ValueError):
    pass


class NoteExporter:
    def __init__(self, store, records_root=None, code_root=None):
        self.store = store
        self.root = Path(records_root).resolve() if records_root else None
        self.code_root = Path(code_root or Path(__file__).resolve().parents[3]).resolve()
        self.lock = threading.RLock()

    def git(self, *args):
        try:
            process = subprocess.run(
                ["git", "-C", str(self.root), *args], capture_output=True, timeout=45
            )
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError("Git 不可用或执行超时；不会丢弃工作区修改") from None
        if process.returncode:
            raise ValueError("Git 操作失败；请检查仓库身份、锁或索引状态。已写入文件不会回滚丢弃。")
        return process.stdout.decode("utf-8", errors="replace").strip()

    def readiness(self):
        if self.root is None:
            return {
                "ready": False,
                "reason": "请在本机配置 literature.records_root 为独立个人 Git 仓库",
            }
        if self.root == self.code_root or self.root.is_relative_to(self.code_root):
            return {"ready": False, "reason": "个人记录仓库不能位于项目代码仓库内"}
        if not self.root.is_dir():
            return {"ready": False, "reason": "个人记录目录不存在"}
        try:
            if Path(self.git("rev-parse", "--show-toplevel")).resolve() != self.root:
                raise ValueError("目录不是独立 Git 仓库根目录")
        except ValueError as exc:
            return {"ready": False, "reason": str(exc)}
        return {"ready": True, "reason": ""}

    def safe(self, relative):
        path = self.root / relative
        current = self.root
        for part in Path(relative).parts:
            if part in {".", ".."} or part.startswith("."):
                raise ValueError("笔记路径不允许")
            current = current / part
            if current.is_symlink():
                raise ValueError("笔记输出路径不能经过符号链接")
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("笔记路径越界")
        return path

    def paths(self, job):
        paper_key = job["document_id"]
        with self.store.library.connect() as db:
            prior = db.execute(
                "SELECT note_path FROM literature_saved WHERE paper_key=? LIMIT 1", (paper_key,)
            ).fetchone()
        title = (
            re.sub(r"[^\w\-\u4e00-\u9fff]+", "-", job["result"]["metadata"]["title"]).strip("-")[
                :70
            ]
            or "论文"
        )
        note = prior["note_path"] if prior else f"文献阅读/论文/{title}-{paper_key[:12]}.md"
        topic = re.sub(r"[^\w\-\u4e00-\u9fff]+", "-", job["topic"]).strip("-")[:60] or "主题"
        table = f"文献阅读/主题/{topic}-{digest(job['topic'])[:8]}.md"
        return note, table

    @staticmethod
    def ideas(content):
        if content.count(IDEAS_START) == 1 and content.count(IDEAS_END) == 1:
            return content.split(IDEAS_START, 1)[1].split(IDEAS_END, 1)[0].strip()
        return ""

    def preview(self, job):
        status = self.readiness()
        if not status["ready"]:
            return {**status, "markdown": detail_markdown(job), "ideas": "", "notes_revision": None}
        note, table = self.paths(job)
        path = self.safe(note)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        return {
            **status,
            "note_path": note,
            "table_path": table,
            "markdown": detail_markdown(job),
            "ideas": self.ideas(existing),
            "notes_revision": digest(existing),
        }

    def replace_managed(self, relative, key, body):
        path = self.safe(relative)
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        start = f"<!-- assistant:{key}:start -->"
        end = f"<!-- assistant:{key}:end -->"
        managed = start + "\n" + body.strip() + "\n" + end
        with self.store.library.connect() as db:
            saved = db.execute(
                "SELECT managed_digest FROM literature_exports WHERE path=?", (relative,)
            ).fetchone()
        if current:
            if current.count(start) != 1 or current.count(end) != 1:
                raise NoteConflict("已有笔记缺少唯一的助手区域，不会覆盖：" + relative)
            old = current[current.index(start) : current.index(end) + len(end)]
            if not saved or digest(old) != saved["managed_digest"]:
                raise NoteConflict("助手区域已在外部修改，请先核对，未覆盖：" + relative)
            updated = current.replace(old, managed, 1)
        else:
            updated = managed + "\n"
        return updated, digest(managed)

    def save(self, job, ideas=None, expected_notes_revision=None):
        with self.lock:
            readiness = self.readiness()
            if not readiness["ready"]:
                raise ValueError(readiness["reason"])
            if self.git("diff", "--cached", "--name-only"):
                raise NoteConflict("个人仓库已有暂存修改，请先提交或取消暂存；本次未写入")
            note, table = self.paths(job)
            note_path = self.safe(note)
            original = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
            if ideas is not None and digest(original) != expected_notes_revision:
                raise NoteConflict("笔记已由其他设备修改，请重新打开预览后保存")
            detail, detail_digest = self.replace_managed(
                note, "paper-" + job["document_id"], detail_markdown(job)
            )
            if original:
                if original.count(IDEAS_START) != 1 or original.count(IDEAS_END) != 1:
                    raise NoteConflict("个人想法区域已调整，未覆盖；请恢复区域标记后重试")
            else:
                detail += "\n## 我的想法\n" + IDEAS_START + "\n\n" + IDEAS_END + "\n"
            if ideas is not None:
                start = detail.index(IDEAS_START) + len(IDEAS_START)
                end = detail.index(IDEAS_END)
                if IDEAS_START in ideas or IDEAS_END in ideas:
                    raise ValueError("想法中不能包含区域控制标记")
                detail = detail[:start] + "\n" + ideas.strip() + "\n" + detail[end:]
            with self.store.library.connect() as db:
                saved = [
                    dict(row)
                    for row in db.execute(
                        "SELECT * FROM literature_saved WHERE topic=? ORDER BY paper_key",
                        (job["topic"],),
                    )
                ]
            records = {r["paper_key"]: r for r in saved}
            records[job["document_id"]] = {
                "paper_key": job["document_id"],
                "result": json.dumps(job["result"], ensure_ascii=False),
                "note_path": note,
            }
            lines = [
                "# " + text(job["topic"]),
                "",
                "| " + " | ".join(TABLE_HEADERS) + " |",
                "| " + " | ".join(["---"] * 5) + " |",
            ]
            for key, record in records.items():
                result = json.loads(record["result"])
                content = (
                    detail
                    if key == job["document_id"]
                    else self.safe(record["note_path"]).read_text(encoding="utf-8")
                    if self.safe(record["note_path"]).exists()
                    else ""
                )
                link = (
                    "[详细笔记](../论文/" + Path(record["note_path"]).name.replace(" ", "%20") + ")"
                )
                lines.append("| " + " | ".join(row_cells(result, link, self.ideas(content))) + " |")
            table_content, table_digest = self.replace_managed(
                table, "topic-" + digest(job["topic"])[:12], "\n".join(lines)
            )
            # All conflicts are checked before either file changes.
            for relative, content in [(note, detail), (table, table_content)]:
                path = self.safe(relative)
                path.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(prefix=".reading-", dir=path.parent)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                        stream.write(content)
                    os.replace(temporary, path)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            with self.store.library.connect() as db:
                db.execute(
                    "INSERT OR REPLACE INTO literature_saved VALUES(?,?,?,?,?)",
                    (
                        job["document_id"],
                        job["topic"],
                        job["id"],
                        json.dumps(job["result"], ensure_ascii=False),
                        note,
                    ),
                )
                for path, value in [(note, detail_digest), (table, table_digest)]:
                    db.execute(
                        "INSERT OR REPLACE INTO literature_exports VALUES(?,?)", (path, value)
                    )
            try:
                self.git("add", "--", note, table)
                if self.git("diff", "--cached", "--name-only"):
                    # --only confines the commit even if an external actor stages unrelated files.
                    self.git(
                        "commit",
                        "--only",
                        "-m",
                        "Update literature reading notes",
                        "--",
                        note,
                        table,
                    )
                commit = self.git("rev-parse", "HEAD")
                return {
                    "saved": True,
                    "version_pending": False,
                    "commit": commit,
                    "note_path": note,
                    "table_path": table,
                }
            except ValueError as exc:
                return {
                    "saved": True,
                    "version_pending": True,
                    "error": str(exc),
                    "note_path": note,
                    "table_path": table,
                }
