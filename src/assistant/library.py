import hashlib
import html
import re
import sqlite3
import threading
import zipfile
from contextlib import contextmanager
from pathlib import Path
from xml.etree import ElementTree as ET

SUPPORTED = {".md", ".pdf", ".epub", ".csv", ".txt", ".png", ".jpg", ".jpeg", ".webp"}


def epub_chapters(path):
    """Read EPUB spine order without extracting or executing publisher markup."""
    with zipfile.ZipFile(path) as archive:
        if sum(i.file_size for i in archive.infolist()) > 200_000_000:
            raise ValueError("EPUB 解压大小超出限制")
        container = ET.fromstring(archive.read("META-INF/container.xml"))
        opf_name = next(
            e.attrib["full-path"] for e in container.iter() if e.tag.endswith("rootfile")
        )
        opf = ET.fromstring(archive.read(opf_name))
        manifest = {
            e.attrib["id"]: e.attrib.get("href", "") for e in opf.iter() if e.tag.endswith("}item")
        }
        chapters = []
        for item in opf.iter():
            if not item.tag.endswith("}itemref"):
                continue
            from urllib.parse import unquote

            name = (Path(opf_name).parent / unquote(manifest[item.attrib["idref"]])).as_posix()
            root = ET.fromstring(archive.read(name.split("#")[0]))
            blocks = []
            for element in root.iter():
                tag = element.tag.rsplit("}", 1)[-1]
                if tag in {"h1", "h2", "h3", "p", "li", "pre", "blockquote"}:
                    text = "".join(element.itertext()).strip()
                    if text:
                        blocks.append(text)
            if blocks:
                chapters.append({"title": blocks[0][:100], "text": "\n\n".join(blocks)})
        return chapters


class Library:
    def __init__(self, root, database):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        self.database = str(database)
        self.scan_lock = threading.Lock()
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS documents(
                    id TEXT PRIMARY KEY,path TEXT UNIQUE,revision TEXT,size INTEGER,kind TEXT,error TEXT);
                CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(
                    document_id UNINDEXED, location UNINDEXED, content, tokenize='trigram');
                CREATE TABLE IF NOT EXISTS reading(
                    document_id TEXT PRIMARY KEY,revision TEXT,position INTEGER,
                    version INTEGER NOT NULL DEFAULT 1,updated TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS annotations(
                    id INTEGER PRIMARY KEY,document_id TEXT,revision TEXT,location TEXT,
                    quote TEXT,note TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def resolve(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or any(
            p.startswith(".") for p in Path(relative).parts
        ):
            raise ValueError("路径不允许")
        return path

    def scan(self):
        with self.scan_lock, self.connect() as db:
            seen = set()
            for candidate in self.root.rglob("*"):
                relative = candidate.relative_to(self.root).as_posix()
                if candidate.suffix.lower() not in SUPPORTED or not candidate.is_file():
                    continue
                try:
                    path = self.resolve(relative)
                except ValueError:
                    continue
                seen.add(relative)
                digest = hashlib.sha256()
                try:
                    with path.open("rb") as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(block)
                    revision = digest.hexdigest()
                    old = db.execute("SELECT * FROM documents WHERE path=?", (relative,)).fetchone()
                    if old and old["revision"] == revision:
                        continue
                    doc_id = hashlib.sha256(relative.encode()).hexdigest()[:24]
                    if old is None:
                        matches = db.execute(
                            "SELECT id,path FROM documents WHERE revision=?", (revision,)
                        ).fetchall()
                        moved = [row for row in matches if not (self.root / row["path"]).exists()]
                        if len(moved) == 1:
                            doc_id = moved[0]["id"]
                            db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
                    passages, error = [], ""
                    try:
                        passages = self.extract(path)
                    except Exception as exc:
                        error = str(exc)[:300]
                    db.execute(
                        "INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?,?)",
                        (
                            doc_id,
                            relative,
                            revision,
                            path.stat().st_size,
                            path.suffix.lower(),
                            error,
                        ),
                    )
                    db.execute("DELETE FROM passages WHERE document_id=?", (doc_id,))
                    db.executemany(
                        "INSERT INTO passages VALUES(?,?,?)",
                        [(doc_id, location, text) for location, text in passages],
                    )
                except OSError:
                    continue
            for row in db.execute("SELECT id,path FROM documents").fetchall():
                if row["path"] not in seen:
                    db.execute("DELETE FROM passages WHERE document_id=?", (row["id"],))
                    db.execute("DELETE FROM documents WHERE id=?", (row["id"],))

    def extract(self, path):
        suffix = path.suffix.lower()
        if suffix in {".md", ".txt", ".csv"}:
            if path.stat().st_size > 10_000_000:
                raise ValueError("超过 10MB，仅提供文件下载，不建立文本索引")
            lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
            return [
                (f"行 {i + 1}–{min(i + 30, len(lines))}", "\n".join(lines[i : i + 30]))
                for i in range(0, len(lines), 30)
            ]
        if suffix == ".pdf":
            from pypdf import PdfReader

            return [
                (f"页 {i + 1}", page.extract_text() or "")
                for i, page in enumerate(PdfReader(path).pages)
            ]
        if suffix == ".epub":
            return [
                (f"章 {i + 1}", chapter["text"]) for i, chapter in enumerate(epub_chapters(path))
            ]
        return []

    def documents(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM documents ORDER BY path")]

    def document(self, doc_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if row is None:
            raise KeyError(doc_id)
        return dict(row)

    def search(self, query):
        # LIKE also supports one/two-character Chinese terms, which trigram MATCH cannot.
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    """
                SELECT d.id,d.path,d.revision,p.location,substr(p.content,1,1200) AS excerpt
                FROM passages p JOIN documents d ON d.id=p.document_id
                WHERE p.content LIKE ? ESCAPE '\\' LIMIT 50
            """,
                    ("%" + escaped + "%",),
                )
            ]

    def content(self, doc):
        path = self.resolve(doc["path"])
        if doc["kind"] == ".epub":
            return {"chapters": epub_chapters(path)}
        if doc["kind"] in {".md", ".txt", ".csv"}:
            if path.stat().st_size > 10_000_000:
                raise ValueError("文件过大，请下载查看")
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            if doc["kind"] == ".md":
                from markdown_it import MarkdownIt

                renderer = MarkdownIt("commonmark", {"html": False})
                from urllib.parse import unquote

                def wiki(match):
                    target = match.group(1).split("|", 1)[0]
                    return "![附件](" + target.replace(" ", "%20") + ")"

                text = re.sub(r"!\[\[([^\]]+)\]\]", wiki, text)
                tokens = renderer.parse(text)
                files = {d["path"]: d for d in self.documents()}

                def rewrite(nodes):
                    for node in nodes:
                        if node.type == "image":
                            source = unquote(node.attrGet("src") or "")
                            candidate = (Path(doc["path"]).parent / source).as_posix()
                            candidates = [
                                d for d in files.values() if d["path"] in {candidate, source}
                            ]
                            if not candidates and "/" not in source:
                                candidates = [
                                    d for d in files.values() if Path(d["path"]).name == source
                                ]
                            if len(candidates) == 1 and candidates[0]["kind"] in {
                                ".png",
                                ".jpg",
                                ".jpeg",
                                ".webp",
                            }:
                                node.attrSet(
                                    "src", "/api/documents/" + candidates[0]["id"] + "/file"
                                )
                            else:
                                node.type = "text"
                                node.tag = ""
                                node.content = "[附件未找到或不支持：" + source + "]"
                                node.children = None
                        if node.children:
                            rewrite(node.children)

                rewrite(tokens)
                return {"html": renderer.renderer.render(tokens, renderer.options, {})}
            return {"html": "<pre>" + html.escape(text) + "</pre>"}
        return {}
