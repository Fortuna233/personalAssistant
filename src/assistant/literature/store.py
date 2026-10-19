import json
import time
import uuid

from .models import fingerprint, model_settings
from . import prompts

CAPABILITY_ID = "literature.full-reading"


class ReadingStore:
    def __init__(self, library, defaults=None):
        self.library = library
        self.defaults = defaults or {}
        with library.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS literature_settings(id INTEGER PRIMARY KEY,body TEXT);
                CREATE TABLE IF NOT EXISTS reading_capabilities(
                    version INTEGER PRIMARY KEY,instructions TEXT,digest TEXT,active INTEGER,
                    created REAL);
                CREATE TABLE IF NOT EXISTS literature_jobs(
                    id TEXT PRIMARY KEY,cache_key TEXT UNIQUE,kind TEXT,document_id TEXT,
                    revision TEXT,topic TEXT,purpose TEXT,settings TEXT,capability TEXT,source TEXT,
                    status TEXT,progress TEXT,result TEXT,error TEXT,created REAL,updated REAL);
                CREATE TABLE IF NOT EXISTS literature_steps(
                    job_id TEXT,step_key TEXT,result TEXT,usage TEXT,
                    PRIMARY KEY(job_id,step_key));
                CREATE TABLE IF NOT EXISTS literature_exports(
                    path TEXT PRIMARY KEY,managed_digest TEXT);
                CREATE TABLE IF NOT EXISTS literature_saved(
                    paper_key TEXT,topic TEXT,job_id TEXT,result TEXT,note_path TEXT,
                    PRIMARY KEY(paper_key,topic));
            """)
            if not db.execute("SELECT 1 FROM reading_capabilities").fetchone():
                db.execute(
                    "INSERT INTO reading_capabilities VALUES(1,?,?,1,?)",
                    ("", fingerprint({"base": prompts.BASE, "rules": ""}), time.time()),
                )

    def settings(self):
        with self.library.connect() as db:
            row = db.execute("SELECT body FROM literature_settings WHERE id=1").fetchone()
        return model_settings(json.loads(row["body"]) if row else self.defaults)

    def save_settings(self, value):
        settings = model_settings(value)
        with self.library.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO literature_settings VALUES(1,?)", (json.dumps(settings),)
            )
        return settings

    def capability(self):
        with self.library.connect() as db:
            row = db.execute("SELECT * FROM reading_capabilities WHERE active=1").fetchone()
        # Include code-defined constraints in the snapshot and digest; old jobs retain theirs.
        return {
            "id": CAPABILITY_ID,
            "version": row["version"],
            "rules": row["instructions"],
            "instructions": prompts.BASE,
            "stages": {
                "outline": prompts.OUTLINE,
                "analysis": prompts.ANALYZE,
                "question": prompts.QUESTION,
            },
            "workflow_version": "1",
            "digest": fingerprint(
                {
                    "base": prompts.BASE,
                    "rules": row["instructions"],
                    "stages": [prompts.OUTLINE, prompts.ANALYZE, prompts.QUESTION],
                    "workflow_version": "1",
                }
            ),
        }

    def save_rules(self, text, expected_version):
        if len(text) > 10000:
            raise ValueError("规则超过 10000 字符")
        with self.library.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM reading_capabilities WHERE active=1").fetchone()
            if row["version"] != expected_version:
                raise ValueError("规则已被其他设备更新，请刷新后再保存")
            if text.strip() == row["instructions"]:
                return self.capability()
            version = db.execute("SELECT MAX(version)+1 FROM reading_capabilities").fetchone()[0]
            db.execute("UPDATE reading_capabilities SET active=0")
            db.execute(
                "INSERT INTO reading_capabilities VALUES(?,?,?,1,?)",
                (
                    version,
                    text.strip(),
                    fingerprint({"base": prompts.BASE, "rules": text.strip()}),
                    time.time(),
                ),
            )
        return self.capability()

    def get_job(self, job_id, include_source=False):
        with self.library.connect() as db:
            row = db.execute("SELECT * FROM literature_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError("任务不存在")
        result = dict(row)
        for key in ("settings", "capability", "source", "result"):
            result[key] = json.loads(result[key]) if result[key] else None
        if result["kind"] == "question":
            result["question_context"] = result["source"].get("question_context", {})
        if not include_source:
            result.pop("source")
        return result

    def jobs(self):
        with self.library.connect() as db:
            ids = [
                row["id"]
                for row in db.execute(
                    "SELECT id FROM literature_jobs ORDER BY created DESC LIMIT 200"
                )
            ]
        return [self.get_job(job_id) for job_id in ids]

    def enqueue(self, source, topic, purpose, kind="read", extra=None):
        settings, capability = self.settings(), self.capability()
        key = fingerprint(
            {
                "revision": source["revision"],
                "topic": topic,
                "purpose": purpose,
                "settings": settings,
                "capability": capability,
                "kind": kind,
                "extra": extra,
            }
        )
        with self.library.connect() as db:
            existing = db.execute(
                "SELECT id FROM literature_jobs WHERE cache_key=?", (key,)
            ).fetchone()
            if existing:
                return self.get_job(existing["id"])
            job_id = uuid.uuid4().hex
            if extra:
                source = {**source, "question_context": extra}
            now = time.time()
            db.execute(
                "INSERT INTO literature_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    key,
                    kind,
                    source["document_id"],
                    source["revision"],
                    topic,
                    purpose,
                    json.dumps(settings),
                    json.dumps(capability, ensure_ascii=False),
                    json.dumps(source, ensure_ascii=False),
                    "queued",
                    "等待执行",
                    None,
                    "",
                    now,
                    now,
                ),
            )
        return self.get_job(job_id)

    def update(self, job_id, **changes):
        allowed = {"status", "progress", "result", "error"}
        if not changes or set(changes) - allowed:
            raise ValueError("无效任务更新")
        if "result" in changes:
            changes["result"] = json.dumps(changes["result"], ensure_ascii=False)
        changes["updated"] = time.time()
        with self.library.connect() as db:
            db.execute(
                "UPDATE literature_jobs SET "
                + ",".join(key + "=?" for key in changes)
                + " WHERE id=?",
                (*changes.values(), job_id),
            )

    def step(self, job_id, key):
        with self.library.connect() as db:
            row = db.execute(
                "SELECT result FROM literature_steps WHERE job_id=? AND step_key=?", (job_id, key)
            ).fetchone()
        return json.loads(row["result"]) if row else None

    def save_step(self, job_id, key, result, usage):
        with self.library.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO literature_steps VALUES(?,?,?,?)",
                (job_id, key, json.dumps(result, ensure_ascii=False), json.dumps(usage)),
            )

    def claim(self):
        with self.library.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute('SELECT 1 FROM literature_jobs WHERE status="running"').fetchone():
                return None
            row = db.execute(
                'SELECT id FROM literature_jobs WHERE status="queued" ORDER BY created LIMIT 1'
            ).fetchone()
            if row:
                db.execute(
                    'UPDATE literature_jobs SET status="running",updated=? WHERE id=?',
                    (time.time(), row["id"]),
                )
        return self.get_job(row["id"], True) if row else None

    def recover(self):
        with self.library.connect() as db:
            db.execute(
                'UPDATE literature_jobs SET status="queued",progress="恢复已保存步骤" WHERE status="running"'
            )

    def change_status(self, job_id, action):
        job = self.get_job(job_id)
        if action == "cancel" and job["status"] in {"running", "queued"}:
            self.update(job_id, status="cancelled", progress="已取消；当前模型请求可能仍会计费")
        elif action == "retry" and job["status"] in {"failed", "cancelled"}:
            self.update(job_id, status="queued", error="", progress="等待从已保存步骤继续")
        else:
            raise ValueError("当前状态不能执行该操作")
        return self.get_job(job_id)
