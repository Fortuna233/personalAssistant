import asyncio
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .library import Library
from .zotero import ZoteroBridge
from .synchronization import create_sync_router
from .files import FileManager, FileConflict
from .literature.service import ReadingService
from .literature.notes import NoteExporter
from .literature.api import create_router
from .literature.worker import run_worker


class Login(BaseModel):
    token: str


class Progress(BaseModel):
    revision: str
    position: int = Field(ge=1)
    version: int = Field(ge=0)


class Annotation(BaseModel):
    revision: str
    location: str = Field(max_length=200)
    quote: str = Field(default="", max_length=10000)
    note: str = Field(min_length=1, max_length=20000)


class FileOperation(BaseModel):
    action: str
    path: str = Field(default="", max_length=2000)
    target: str = Field(default="", max_length=2000)
    expected_version: str = Field(default="", max_length=100)
    content: str = Field(default="", max_length=1000000)


def create_app(config, scan_on_start=True, model_gateway=None, start_worker=True):
    token = config["token"]
    if len(token) < 24 or token.startswith("REPLACE_"):
        raise ValueError("请先生成至少 24 字符的访问密钥")
    library = Library(config["library"], config["database"])
    files = FileManager(library)
    zotero = ZoteroBridge(library, config.get("zotero", {}))
    literature_config = config.get("literature", {})
    literature = ReadingService(library, literature_config, model_gateway)
    note_exporter = NoteExporter(literature.store, literature_config.get("records_root"))
    literature.on_complete = note_exporter.save
    scan_status = {"running": False, "error": None, "completed": None}

    async def scan():
        if scan_status["running"]:
            return
        scan_status["running"] = True
        try:
            await asyncio.to_thread(library.scan)
            from datetime import datetime, timezone

            scan_status["completed"] = datetime.now(timezone.utc).isoformat()
            scan_status["error"] = None
        except Exception as exc:
            scan_status["error"] = str(exc)[:300]
        finally:
            scan_status["running"] = False

    async def loop():
        while True:
            await scan()
            await asyncio.sleep(max(10, config.get("scan_seconds", 60)))

    async def zotero_loop():
        while True:
            if zotero.settings()["enabled"]:
                step = asyncio.create_task(asyncio.to_thread(zotero.sync))
                try:
                    await asyncio.shield(step)
                    await scan()
                except ValueError:
                    pass  # A manual sync can already hold the bridge lock.
                except asyncio.CancelledError:
                    await step
                    raise
            await asyncio.sleep(max(30, config.get("zotero", {}).get("interval_seconds", 60)))

    @asynccontextmanager
    async def lifespan(app):
        tasks = []
        if scan_on_start:
            tasks.append(asyncio.create_task(loop()))
        if start_worker:
            tasks.append(asyncio.create_task(run_worker(literature)))
            tasks.append(asyncio.create_task(zotero_loop()))
        yield
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

    app = FastAPI(title="沈轻媞", lifespan=lifespan)
    app.state.library = library
    app.state.literature = literature
    sessions = set()

    def auth(request: Request):
        authorization = request.headers.get("authorization", "")
        bearer = authorization.removeprefix("Bearer ")
        if request.cookies.get("study_session") not in sessions and not secrets.compare_digest(
            bearer, token
        ):
            raise HTTPException(401, "请登录")
        # Browsers must send same-origin custom header for every mutation.
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("x-study-client") != "web" and not authorization:
                raise HTTPException(403, "缺少请求校验")

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; frame-src 'self' blob:; object-src 'self'; "
            "connect-src 'self'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.post("/api/login")
    def login(body: Login, response: Response, request: Request):
        if request.headers.get("x-study-client") != "web":
            raise HTTPException(403, "缺少请求校验")
        if not secrets.compare_digest(body.token, token):
            raise HTTPException(401, "密钥错误")
        session = secrets.token_urlsafe(32)
        sessions.add(session)
        response.set_cookie(
            "study_session",
            session,
            httponly=True,
            samesite="strict",
            secure=config.get("secure_cookie", False),
        )
        return {"ok": True}

    @app.post("/api/logout", dependencies=[Depends(auth)])
    def logout(request: Request, response: Response):
        sessions.discard(request.cookies.get("study_session"))
        response.delete_cookie("study_session")
        return {"ok": True}

    def document(doc_id):
        try:
            return library.document(doc_id)
        except KeyError:
            raise HTTPException(404, "资料不存在")

    @app.get("/api/documents", dependencies=[Depends(auth)])
    def documents():
        return library.documents()

    def file_error(exc):
        status = (
            409
            if isinstance(exc, FileConflict)
            else 404
            if isinstance(exc, FileNotFoundError)
            else 400
        )
        raise HTTPException(status, str(exc))

    @app.get("/api/files", dependencies=[Depends(auth)])
    def entries():
        return files.entries()

    @app.post("/api/files/operations", dependencies=[Depends(auth)])
    def operate(body: FileOperation):
        try:
            return files.operate(**body.model_dump())
        except (ValueError, OSError) as exc:
            file_error(exc)

    @app.get("/api/files/trash", dependencies=[Depends(auth)])
    def trash():
        return files.trash_entries()

    @app.post("/api/files/trash/{trash_id}/restore", dependencies=[Depends(auth)])
    def restore(trash_id: str):
        try:
            return files.restore(trash_id)
        except (ValueError, OSError) as exc:
            file_error(exc)

    @app.get("/api/files/download", dependencies=[Depends(auth)])
    def download(path: str):
        try:
            source = files.path(path)
            if not source.is_file():
                raise FileNotFoundError("文件不存在")
            return FileResponse(source, filename=source.name, content_disposition_type="attachment")
        except (ValueError, OSError) as exc:
            file_error(exc)

    @app.get("/api/status", dependencies=[Depends(auth)])
    def status():
        return {
            "index": scan_status,
            "documents": len(library.documents()),
            "sync": "文件同步由 Syncthing 管理；这里显示索引状态，不代表设备已同步",
        }

    @app.post("/api/scan", dependencies=[Depends(auth)])
    async def rescan():
        await scan()
        return scan_status

    @app.get("/api/search", dependencies=[Depends(auth)])
    def search(q: str = ""):
        return library.search(q[:300]) if q.strip() else []

    @app.get("/api/documents/{doc_id}/content", dependencies=[Depends(auth)])
    def content(doc_id: str):
        try:
            return library.content(document(doc_id))
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc))

    @app.api_route(
        "/api/documents/{doc_id}/file", methods=["GET", "HEAD"], dependencies=[Depends(auth)]
    )
    def file(doc_id: str):
        doc = document(doc_id)
        try:
            path = library.resolve(doc["path"])
        except ValueError:
            raise HTTPException(403, "文件路径不允许")
        if not path.is_file():
            raise HTTPException(404, "文件已移除，请更新索引")
        return FileResponse(path, filename=path.name, content_disposition_type="inline")

    @app.get("/api/documents/{doc_id}/reading", dependencies=[Depends(auth)])
    def reading(doc_id: str):
        doc = document(doc_id)
        with library.connect() as db:
            progress = db.execute("SELECT * FROM reading WHERE document_id=?", (doc_id,)).fetchone()
            notes = db.execute(
                "SELECT * FROM annotations WHERE document_id=? ORDER BY id DESC", (doc_id,)
            ).fetchall()
        return {
            "progress": dict(progress)
            if progress
            else {"position": 1, "version": 0, "revision": doc["revision"]},
            "annotations": [dict(note) for note in notes],
        }

    @app.put("/api/documents/{doc_id}/reading", dependencies=[Depends(auth)])
    def progress(doc_id: str, body: Progress):
        doc = document(doc_id)
        if body.revision != doc["revision"]:
            raise HTTPException(409, "原文已更新，请重新打开资料")
        with library.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT version FROM reading WHERE document_id=?", (doc_id,)
            ).fetchone()
            if (row["version"] if row else 0) != body.version:
                raise HTTPException(409, "另一设备已更新进度，请重新打开资料后再保存")
            version = body.version + 1
            db.execute(
                """INSERT INTO reading(document_id,revision,position,version) VALUES(?,?,?,?)
                ON CONFLICT(document_id) DO UPDATE SET revision=excluded.revision,
                position=excluded.position,version=excluded.version,updated=CURRENT_TIMESTAMP""",
                (doc_id, body.revision, body.position, version),
            )
        return {"version": version}

    @app.post("/api/documents/{doc_id}/annotations", dependencies=[Depends(auth)])
    def annotate(doc_id: str, body: Annotation):
        doc = document(doc_id)
        if body.revision != doc["revision"]:
            raise HTTPException(409, "原文已更新，请重新打开资料")
        with library.connect() as db:
            cursor = db.execute(
                "INSERT INTO annotations(document_id,revision,location,quote,note) VALUES(?,?,?,?,?)",
                (doc_id, body.revision, body.location, body.quote, body.note),
            )
        return {"id": cursor.lastrowid}

    @app.get("/api/annotations/export", dependencies=[Depends(auth)])
    def export():
        with library.connect() as db:
            rows = db.execute("""SELECT a.*,d.path FROM annotations a LEFT JOIN documents d
                ON a.document_id=d.id ORDER BY a.id""").fetchall()
        return Response(
            json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="annotations.json"'},
        )

    app.include_router(create_router(literature, note_exporter, auth))
    app.include_router(create_sync_router(library, note_exporter.root, config, auth, zotero))

    static = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=static, html=True), name="web")
    return app
