"""Confined file management, with recoverable deletion and stable reading identities."""

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


class FileConflict(ValueError):
    pass


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


class FileManager:
    def __init__(self, library):
        self.library = library
        self.root = library.root
        with library.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS file_dates(
                    path TEXT PRIMARY KEY,created REAL,source TEXT);
                CREATE TABLE IF NOT EXISTS trash(
                    id TEXT PRIMARY KEY,path TEXT,deleted_at REAL,
                    documents TEXT,dates TEXT);
            """)

    def path(self, relative, allow_root=False):
        if not relative and allow_root:
            return self.root
        if not relative or relative.startswith("/") or "\\" in relative:
            raise ValueError("请选择资料库内的有效路径")
        parts = relative.split("/")
        for part in parts:
            if (
                not part
                or part.startswith(".")
                or part.endswith((" ", "."))
                or re.search(r'[<>:"|?*\x00-\x1f]', part)
                or re.fullmatch(r"(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?", part, re.I)
            ):
                raise ValueError("名称含隐藏路径或 Windows 不支持的字符")
        current = self.root
        for part in parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("不允许通过符号链接访问资料")
        return self.library.resolve(relative)

    @staticmethod
    def version(path):
        stat = path.stat()
        value = f"{stat.st_ino}:{stat.st_mtime_ns}:{stat.st_size}:{path.is_dir()}"
        return hashlib.sha256(value.encode()).hexdigest()[:24]

    def entries(self):
        with self.library.scan_lock, self.library.connect() as db:
            indexed = {d["path"]: d for d in self.library.documents()}
            result = []
            for parent, directories, files in os.walk(self.root, followlinks=False):
                directories[:] = sorted(
                    d
                    for d in directories
                    if not d.startswith(".") and not (Path(parent) / d).is_symlink()
                )
                for name in directories + sorted(files):
                    candidate = Path(parent) / name
                    relative = candidate.relative_to(self.root).as_posix()
                    try:
                        path = self.path(relative)
                        stat = path.stat()
                        if not path.is_dir() and not path.is_file():
                            continue
                    except (ValueError, OSError):
                        continue
                    date = db.execute(
                        "SELECT * FROM file_dates WHERE path=?", (relative,)
                    ).fetchone()
                    if date is None:
                        birth = getattr(stat, "st_birthtime", None)
                        if birth is None and os.name == "nt":
                            birth = stat.st_ctime
                        created, source = (
                            (birth, "filesystem")
                            if birth is not None
                            else (time.time(), "first_seen")
                        )
                        db.execute(
                            "INSERT INTO file_dates VALUES(?,?,?)", (relative, created, source)
                        )
                    else:
                        created, source = date["created"], date["source"]
                    doc = indexed.get(relative, {})
                    result.append(
                        {
                            "path": relative,
                            "name": name,
                            "parent": ""
                            if "/" not in relative
                            else str(PurePosixPath(relative).parent),
                            "is_dir": path.is_dir(),
                            "kind": "folder" if path.is_dir() else path.suffix.lower(),
                            "size": None if path.is_dir() else stat.st_size,
                            "created_at": timestamp(created),
                            "created_source": source,
                            "modified_at": timestamp(stat.st_mtime),
                            "version": self.version(path),
                            "document_id": doc.get("id"),
                            "error": doc.get("error", ""),
                        }
                    )
            return result

    def validate_source(self, relative, expected_version):
        path = self.path(relative)
        if not path.exists():
            raise FileNotFoundError("文件已不存在，请刷新")
        if not expected_version or self.version(path) != expected_version:
            raise FileConflict("文件已被其他操作或同步更新，请刷新后重试")
        return path

    def ensure_target(self, relative):
        path = self.path(relative)
        if path.exists():
            raise FileConflict("目标名称已存在，不会覆盖已有文件")
        if not path.parent.is_dir():
            raise ValueError("目标文件夹不存在")
        # Case-only names are ambiguous across Windows/macOS/Android.
        if any(child.name.casefold() == path.name.casefold() for child in path.parent.iterdir()):
            raise FileConflict("目标名称与已有文件大小写冲突")
        return path

    def mappings(self, db, source):
        return [
            dict(row)
            for row in db.execute("SELECT * FROM documents")
            if row["path"] == source or row["path"].startswith(source + "/")
        ]

    def move_records(self, source, target):
        with self.library.connect() as db:
            for row in self.mappings(db, source):
                new_path = target + row["path"][len(source) :]
                db.execute("UPDATE documents SET path=? WHERE id=?", (new_path, row["id"]))
            rows = db.execute("SELECT * FROM file_dates").fetchall()
            for row in rows:
                if row["path"] == source or row["path"].startswith(source + "/"):
                    new_path = target + row["path"][len(source) :]
                    db.execute("DELETE FROM file_dates WHERE path=?", (row["path"],))
                    db.execute(
                        "INSERT OR REPLACE INTO file_dates VALUES(?,?,?)",
                        (new_path, row["created"], row["source"]),
                    )

    def operate(self, action, path="", target="", expected_version="", content=""):
        with self.library.scan_lock:
            if action in {"create_file", "create_folder"}:
                destination = self.ensure_target(target)
                if action == "create_folder":
                    destination.mkdir()
                else:
                    if destination.suffix.lower() not in {".md", ".txt", ".csv"}:
                        raise ValueError("新建文件支持 Markdown、TXT 和 CSV")
                    with destination.open("x", encoding="utf-8") as stream:
                        stream.write(content)
            else:
                source = self.validate_source(path, expected_version)
                if (
                    action in {"move", "delete"}
                    and source.is_dir()
                    and (source / ".stfolder").exists()
                ):
                    raise ValueError("这是 Syncthing 同步根目录，请在同步工具中调整，避免中断同步")
                if action in {"move", "copy"}:
                    destination = self.ensure_target(target)
                    if destination.is_relative_to(source):
                        raise ValueError("不能将文件夹放到它自身内部")
                    if action == "move":
                        source.rename(destination)
                        try:
                            self.move_records(path, target)
                        except Exception:
                            destination.rename(source)
                            raise
                    else:
                        if source.is_dir():
                            if any(p.is_symlink() for p in source.rglob("*")):
                                raise ValueError("含符号链接的文件夹不能复制")
                            try:
                                shutil.copytree(
                                    source,
                                    destination,
                                    symlinks=True,
                                    ignore=shutil.ignore_patterns(
                                        ".stfolder", ".stversions", ".stignore", ".study-trash"
                                    ),
                                )
                            except Exception:
                                if destination.exists():
                                    shutil.rmtree(destination)
                                raise
                        else:
                            with source.open("rb") as src, destination.open("xb") as dst:
                                shutil.copyfileobj(src, dst)
                elif action == "delete":
                    trash_id = uuid.uuid4().hex
                    trash_root = self.root / ".study-trash"
                    if trash_root.is_symlink():
                        raise ValueError("回收区不能是符号链接")
                    trash_root.mkdir(exist_ok=True)
                    destination = trash_root / trash_id
                    with self.library.connect() as db:
                        docs = self.mappings(db, path)
                        dates = [
                            dict(row)
                            for row in db.execute("SELECT * FROM file_dates")
                            if row["path"] == path or row["path"].startswith(path + "/")
                        ]
                        source.rename(destination)
                        try:
                            db.execute(
                                "INSERT INTO trash VALUES(?,?,?,?,?)",
                                (trash_id, path, time.time(), json.dumps(docs), json.dumps(dates)),
                            )
                        except Exception:
                            destination.rename(source)
                            raise
                    with self.library.connect() as db:
                        for date in dates:
                            db.execute("DELETE FROM file_dates WHERE path=?", (date["path"],))
                    self.library.scan()
                    return {"ok": True, "trash_id": trash_id}
                else:
                    raise ValueError("不支持的文件操作")
            self.library.scan()
            return {"ok": True, "path": target}

    def trash_entries(self):
        with self.library.connect() as db:
            return [
                {"id": row["id"], "path": row["path"], "deleted_at": timestamp(row["deleted_at"])}
                for row in db.execute("SELECT * FROM trash ORDER BY deleted_at DESC")
            ]

    def restore(self, trash_id):
        with self.library.scan_lock, self.library.connect() as db:
            row = db.execute("SELECT * FROM trash WHERE id=?", (trash_id,)).fetchone()
            if row is None:
                raise FileNotFoundError("回收记录不存在")
            target = self.ensure_target(row["path"])
            source = self.root / ".study-trash" / row["id"]
            if source.is_symlink() or source.parent.is_symlink() or not source.exists():
                raise ValueError("回收文件不可用")
            source.rename(target)
            try:
                for doc in json.loads(row["documents"]):
                    db.execute(
                        "INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?,?)",
                        tuple(
                            "" if key == "revision" else doc[key]
                            for key in ("id", "path", "revision", "size", "kind", "error")
                        ),
                    )
                for date in json.loads(row["dates"]):
                    db.execute(
                        "INSERT OR REPLACE INTO file_dates VALUES(?,?,?)",
                        (date["path"], date["created"], date["source"]),
                    )
                db.execute("DELETE FROM trash WHERE id=?", (trash_id,))
            except Exception:
                target.rename(source)
                raise
        self.library.scan()
        return {"ok": True, "path": row["path"]}
