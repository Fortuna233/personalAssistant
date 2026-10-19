"""Read Zotero's local API; bridge attachment files without syncing its database.

Zotero itself owns metadata synchronisation. This adapter never writes to its API.
"""

import hashlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import httpx

from .library import SUPPORTED
from .literature.worker import WorkerLease


class ZoteroBridge:
    def __init__(self, library, config=None, transport=None):
        self.library = library
        self.config = config or {}
        self.transport = transport
        self.lock = threading.Lock()
        self.base = "http://127.0.0.1:23119/api"
        with library.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS zotero_config(id INTEGER PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS zotero_cache(scope TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS zotero_files(
                    scope TEXT, key TEXT, digest TEXT, PRIMARY KEY(scope,key));
            """)

    def settings(self):
        with self.library.connect() as db:
            row = db.execute("SELECT value FROM zotero_config WHERE id=1").fetchone()
        return (
            json.loads(row[0])
            if row
            else {
                "enabled": bool(self.config.get("enabled", False)),
                "kind": self.config.get("kind", "users"),
                "library_id": str(self.config.get("library_id", "0")),
            }
        )

    def configure(self, value):
        if value["kind"] not in {"users", "groups"} or not re.fullmatch(
            r"[0-9]{1,20}", value["library_id"]
        ):
            raise ValueError("资料库类型或 ID 不合法")
        with self.library.connect() as db:
            db.execute("INSERT OR REPLACE INTO zotero_config VALUES(1,?)", (json.dumps(value),))
        return self.status()

    def status(self):
        settings = self.settings()
        scope = settings["kind"] + "-" + settings["library_id"]
        with self.library.connect() as db:
            row = db.execute("SELECT value FROM zotero_cache WHERE scope=?", (scope,)).fetchone()
        return {
            "settings": settings,
            "local_api": self.base,
            "allowed_roots_configured": bool(self.config.get("allowed_roots")),
            "storage_restore_configured": bool(self.config.get("storage_root")),
            **(json.loads(row[0]) if row else {"items": [], "message": "尚未同步"}),
        }

    @staticmethod
    def fingerprint(path):
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(block)
        return h.hexdigest()

    @staticmethod
    def safe_under(root, relative):
        root = Path(root).resolve()
        path = root / relative
        current = root
        for part in Path(relative).parts:
            if part in {".", ".."} or part.startswith("."):
                raise ValueError("附件路径不合法")
            current /= part
            if current.is_symlink():
                raise ValueError("附件路径不能经过符号链接")
        if not path.resolve().is_relative_to(root):
            raise ValueError("附件路径越界")
        return path

    def local_file(self, client, prefix, item):
        response = client.get(f"{self.base}/{prefix}/items/{item['key']}/file/view/url")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        # Local API returns the file URL as plain text, not a redirect to an arbitrary host.
        uri = urlparse(response.text.strip())
        if uri.scheme != "file" or uri.netloc not in {"", "localhost"}:
            raise ValueError("Zotero 未返回本机 file URL")
        path = Path(url2pathname(uri.path)).resolve()
        roots = [Path(p).resolve() for p in self.config.get("allowed_roots", [])]
        if not any(path.is_relative_to(root) for root in roots):
            raise ValueError("请先在主机配置 zotero.allowed_roots，允许读取该附件目录")
        return path if path.is_file() else None

    def copy_atomic(self, source, target, expected, target_digest=None):
        limit = int(self.config.get("max_attachment_bytes", 2_000_000_000))
        if source.stat().st_size > limit:
            raise ValueError("附件超过本机配置的大小限制")
        if (self.fingerprint(target) if target.exists() else None) != target_digest:
            raise ValueError("目标附件已发生修改，未覆盖")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".zotero-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as output, source.open("rb") as stream:
                size = 0
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    size += len(block)
                    if size > limit:
                        raise ValueError("附件超过大小限制")
                    output.write(block)
            if self.fingerprint(Path(temp)) != expected or self.fingerprint(source) != expected:
                raise ValueError("附件复制时发生修改，请下次重试")
            if (self.fingerprint(target) if target.exists() else None) != target_digest:
                raise ValueError("复制期间目标附件发生修改，未覆盖")
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def bridge_file(self, client, prefix, scope, item):
        data = item["data"]
        filename = (
            data.get("filename") or str(data.get("path", "")).replace("\\", "/").rsplit("/", 1)[-1]
        )
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED or suffix == ".md":
            return {"state": "unsupported", "message": "仅桥接 PDF、EPUB、CSV、图片和文本附件"}
        if data.get("linkMode") not in {"imported_file", "imported_url", "linked_file"}:
            return {"state": "unsupported", "message": "此附件没有本机文件"}
        canonical = self.safe_under(
            self.library.root, f"Papers/Zotero/{scope}/{item['key']}/document{suffix}"
        )
        relative = canonical.relative_to(self.library.root).as_posix()
        source = self.local_file(client, prefix, item)
        with self.library.connect() as db:
            row = db.execute(
                "SELECT digest FROM zotero_files WHERE scope=? AND key=?", (scope, item["key"])
            ).fetchone()
        baseline = row[0] if row else None
        if source:
            local_hash = self.fingerprint(source)
            remote_hash = self.fingerprint(canonical) if canonical.exists() else None
            if local_hash != remote_hash:
                if remote_hash and local_hash == baseline:
                    self.copy_atomic(canonical, source, remote_hash, local_hash)
                    local_hash = remote_hash
                elif remote_hash and remote_hash != baseline:
                    raise ValueError("同步副本与本机附件不一致；保留双方文件，请人工核对")
                else:
                    self.copy_atomic(source, canonical, local_hash, remote_hash)
            with self.library.connect() as db:
                db.execute(
                    "INSERT OR REPLACE INTO zotero_files VALUES(?,?,?)",
                    (scope, item["key"], local_hash),
                )
            return {"state": "available", "path": relative, "message": "已桥接到同步目录"}
        if canonical.exists():
            # Restore missing STORED attachments only. Never invent a linked-file path.
            storage_root = self.config.get("storage_root")
            if storage_root and data.get("linkMode") in {"imported_file", "imported_url"}:
                if not filename or Path(filename).name != filename or "\\" in filename:
                    raise ValueError("附件文件名不合法")
                target = self.safe_under(storage_root, item["key"] + "/" + filename)
                if not target.exists():
                    self.copy_atomic(canonical, target, self.fingerprint(canonical))
                    return {"state": "available", "path": relative, "message": "已补齐本机缺失附件"}
            return {
                "state": "available",
                "path": relative,
                "message": "主机副本可读；本机 Zotero 未关联",
            }
        return {"state": "waiting", "message": "等待来源电脑将附件同步到主机"}

    def sync(self):
        if not self.lock.acquire(blocking=False):
            raise ValueError("Zotero 同步正在执行")
        lease = WorkerLease(str(self.library.database) + ".zotero")
        try:
            if not lease.acquire():
                raise ValueError("另一个进程正在桥接本机 Zotero")
            return self._sync()
        finally:
            lease.close()
            self.lock.release()

    def _sync(self):
        from datetime import datetime, timezone

        settings = self.settings()
        prefix = settings["kind"] + "/" + settings["library_id"]
        scope = prefix.replace("/", "-")
        items = []
        try:
            with httpx.Client(
                transport=self.transport, timeout=30, follow_redirects=False
            ) as client:
                version = None
                for page in range(1000):
                    response = client.get(
                        f"{self.base}/{prefix}/items",
                        headers={"Zotero-API-Version": "3"},
                        params={"start": page * 100, "limit": 100, "format": "json"},
                    )
                    response.raise_for_status()
                    server_id = response.headers.get("Zotero-Server-ID")
                    if server_id:
                        client.headers["Zotero-Server-ID"] = server_id
                    current = response.headers.get("Last-Modified-Version")
                    if version is not None and current != version:
                        raise ValueError("Zotero 资料库在分页期间更新，下次重新同步")
                    version = current
                    batch = response.json()
                    if not isinstance(batch, list):
                        raise ValueError("Zotero 返回的资料格式不正确")
                    items.extend(batch)
                    if len(batch) < 100:
                        break
                else:
                    raise ValueError("资料库过大，请分库接入")
                rows = []
                for item in items:
                    key = item.get("key", "")
                    if not re.fullmatch(r"[A-Z0-9]{8}", key):
                        raise ValueError("Zotero 条目 key 不合法")
                    data = item["data"]
                    row = {
                        "key": key,
                        "title": data.get("title", ""),
                        "type": data.get("itemType", ""),
                        "data": data,
                    }
                    if row["type"] == "attachment":
                        try:
                            row.update(self.bridge_file(client, prefix, scope, item))
                        except (ValueError, OSError, httpx.HTTPError) as exc:
                            row.update(state="error", message=self.error(exc))
                    rows.append(row)
            state = {
                "items": rows,
                "version": version,
                "message": "同步完成",
                "last_sync": datetime.now(timezone.utc).isoformat(),
            }
        except (ValueError, OSError, httpx.HTTPError) as exc:
            state = {
                key: value
                for key, value in self.status().items()
                if key in {"items", "version", "last_sync"}
            }
            state["message"] = self.error(exc)
        with self.library.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO zotero_cache VALUES(?,?)",
                (scope, json.dumps(state, ensure_ascii=False)),
            )
        return self.status()

    @staticmethod
    def error(exc):
        if isinstance(exc, httpx.HTTPError):
            return "Zotero 本机 API 不可用：请打开 Zotero 并启用本机 API；缺失附件需在来源电脑运行桥接。"
        return str(exc)[:300]
