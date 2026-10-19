from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from .models import PROVIDERS
from .notes import NoteConflict, detail_markdown
from .sources import SourceChanged, extract_source


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartReading(Input):
    document_id: str
    topic: str = Field(min_length=1, max_length=120)
    purpose: str = Field(default="", max_length=2000)


class Settings(Input):
    provider: str
    model: str = Field(max_length=200)
    base_url: str = Field(default="", max_length=1000)
    api_mode: str = "responses"
    json_mode: bool = True
    max_output_tokens: int = 6000


class RuleUpdate(Input):
    text: str = Field(max_length=10000)
    expected_version: int


class Question(Input):
    section_id: str
    text: str = Field(min_length=1, max_length=4000)


class ExportNotes(Input):
    ideas: Optional[str] = Field(default=None, max_length=50000)
    notes_revision: Optional[str] = None


def create_router(service, exporter, auth):
    router = APIRouter(prefix="/api/literature", dependencies=[Depends(auth)])

    def fail(exc):
        status = (
            409
            if isinstance(exc, (SourceChanged, NoteConflict))
            else 404
            if isinstance(exc, KeyError)
            else 422
        )
        raise HTTPException(status, str(exc))

    def read_job(job_id):
        job = service.store.get_job(job_id)
        if job["kind"] != "read" or job["status"] != "completed":
            raise ValueError("全文初稿尚未完成")
        return job

    @router.get("/settings")
    def settings():
        value = service.store.settings()
        return {
            "settings": value,
            "model_status": service.gateway.readiness(value),
            "providers": PROVIDERS,
            "records": exporter.readiness(),
            "capability": service.store.capability(),
        }

    @router.put("/settings")
    def save_settings(body: Settings):
        try:
            service.store.save_settings(body.model_dump())
            return settings()
        except ValueError as exc:
            fail(exc)

    @router.put("/rules")
    def rules(body: RuleUpdate):
        try:
            return service.store.save_rules(body.text, body.expected_version)
        except ValueError as exc:
            fail(exc)

    @router.get("/metadata/{document_id}")
    def metadata(document_id: str):
        try:
            source = extract_source(service.library, service.library.document(document_id))
            return {
                "metadata": source["metadata"],
                "revision": source["revision"],
                "warnings": source["warnings"],
                "blocks": len(source["blocks"]),
            }
        except (ValueError, KeyError, OSError) as exc:
            fail(exc)

    @router.get("/jobs")
    def jobs():
        rows = service.store.jobs()
        for job in rows:
            if job["result"] and job["kind"] == "read":
                job["personal_ideas"] = ""
                if exporter.root and not exporter.root.is_relative_to(exporter.code_root):
                    try:
                        note_path = exporter.safe(exporter.paths(job)[0])
                        if note_path.is_file():
                            job["personal_ideas"] = exporter.ideas(
                                note_path.read_text(encoding="utf-8")
                            )
                    except (OSError, ValueError):
                        pass
                job["result"] = {
                    **job["result"],
                    "sections": [
                        {key: value for key, value in section.items() if key != "blocks"}
                        for section in job["result"]["sections"]
                    ],
                }
        return rows

    @router.post("/jobs")
    def create(body: StartReading):
        try:
            return service.create(body.document_id, body.topic, body.purpose)
        except (ValueError, KeyError, OSError) as exc:
            fail(exc)

    @router.get("/jobs/{job_id}")
    def job(job_id: str):
        try:
            return service.store.get_job(job_id)
        except KeyError as exc:
            fail(exc)

    @router.post("/jobs/{job_id}/{action}")
    def action(job_id: str, action: str):
        if action not in {"retry", "cancel"}:
            raise HTTPException(404, "操作不存在")
        try:
            return service.store.change_status(job_id, action)
        except (ValueError, KeyError) as exc:
            fail(exc)

    @router.post("/jobs/{job_id}/questions/new")
    def question(job_id: str, body: Question):
        try:
            return service.question(job_id, body.section_id, body.text)
        except (ValueError, KeyError) as exc:
            fail(exc)

    @router.get("/jobs/{job_id}/notes")
    def preview(job_id: str):
        try:
            return exporter.preview(read_job(job_id))
        except (ValueError, KeyError, OSError) as exc:
            fail(exc)

    @router.post("/jobs/{job_id}/notes/save")
    def save(job_id: str, body: ExportNotes):
        try:
            return exporter.save(read_job(job_id), body.ideas, body.notes_revision)
        except (ValueError, KeyError, OSError) as exc:
            fail(exc)

    @router.get("/jobs/{job_id}/notes/download")
    def download(job_id: str):
        try:
            value = detail_markdown(read_job(job_id))
            return Response(
                value,
                media_type="text/markdown",
                headers={"Content-Disposition": f'attachment; filename="reading-{job_id[:12]}.md"'},
            )
        except (ValueError, KeyError) as exc:
            fail(exc)

    return router
