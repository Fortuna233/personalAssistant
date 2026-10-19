import json
import subprocess

import httpx
import pytest
from fastapi.testclient import TestClient

from assistant.app import create_app
from assistant.library import Library
from assistant.literature.contracts import Analysis, Answer, Evidence, Heading, Metadata, Outline
from assistant.literature.models import ModelGateway, model_settings
from assistant.literature.notes import NoteConflict, NoteExporter, TABLE_HEADERS
from assistant.literature.service import ReadingService
from assistant.literature.sources import SourceChanged, extract_source
from assistant.literature.worker import WorkerLease


class FakeModel:
    def __init__(self):
        self.calls = []
        self.fail_title = None
        self.failed = False
        self.bad_quote = False
        self.bad_heading = False

    def readiness(self, settings):
        return {"ready": True, "missing": []}

    def generate(self, settings, instructions, payload, contract):
        self.calls.append((settings, instructions, payload))
        blocks = payload["source_blocks"]
        if contract is Outline:
            headings = [
                Heading(title=b["text"].lstrip("# "), block_id=b["id"])
                for b in blocks
                if b["text"].startswith("#")
            ]
            if self.bad_heading:
                headings = [Heading(title="Invented heading", block_id=blocks[0]["id"])]
            return Outline(
                metadata=Metadata(title="Synthetic paper", authors=["Test Author"]),
                headings=headings,
            ), {"input_tokens": 100, "output_tokens": 100}
        quoted = next((b for b in blocks if not b["text"].startswith("#")), blocks[0])
        evidence = Evidence(
            block_id=quoted["id"], quote="fabricated" if self.bad_quote else quoted["text"][:100]
        )
        if contract is Answer:
            return Answer(answer="基于本节的测试回答。", evidence=[evidence]), {}
        if payload["section_title"] == self.fail_title and not self.failed:
            self.failed = True
            raise ValueError("Temporary test failure")
        return Analysis(
            background=["测试背景"],
            methods=["测试方法与对照"],
            results=["测试结果"],
            author_discussion=["作者讨论"],
            assistant_analysis=["助手推测，待核对"],
            suggested_questions=["你的判断是什么？"],
            evidence=[evidence],
        ), {}


@pytest.fixture
def reading(tmp_path):
    library = Library(tmp_path / "library", tmp_path / "state.db")
    (library.root / "paper.md").write_text(
        "# Synthetic paper\n\nPaper front matter.\n\n## Background\n\nBackground evidence.\n\n## Methods\n\nControl and experiment.\n\n## Results\n\nObserved result.\n",
        encoding="utf-8",
    )
    library.scan()
    fake = FakeModel()
    service = ReadingService(library, {"model": {"provider": "openai", "model": "test-only"}}, fake)
    doc = library.documents()[0]
    return service, fake, doc, tmp_path


def completed(reading):
    service, fake, doc, _ = reading
    job = service.create(doc["id"], "Test topic")
    assert service.run_next()
    result = service.store.get_job(job["id"])
    assert result["status"] == "completed", result["error"]
    return result


def test_import_metadata_does_not_call_cloud_and_source_snapshot_is_complete(reading):
    service, fake, doc, _ = reading
    source = extract_source(service.library, doc)
    assert fake.calls == []
    assert "Observed result." in "\n".join(b["text"] for b in source["blocks"])
    assert any(h["title"] == "Methods" for h in source["headings"])
    (service.library.root / "paper.md").write_text("changed")
    with pytest.raises(SourceChanged):
        extract_source(service.library, doc)


def test_full_read_preserves_original_headings_validates_evidence_and_reuses_cache(reading):
    service, fake, doc, _ = reading
    job = completed(reading)
    titles = [s["title"] for s in job["result"]["sections"]]
    assert titles[1:] == ["Background", "Methods", "Results"]
    assert job["result"]["status"] == "待核对"
    assert job["result"]["user_ideas"] == ""
    count = len(fake.calls)
    same = service.create(doc["id"], "Test topic")
    assert same["id"] == job["id"]
    assert not service.run_next()
    assert len(fake.calls) == count
    assert all("source_blocks" in call[2] for call in fake.calls)


def test_failed_step_resumes_without_repeating_successful_model_calls(reading):
    service, fake, doc, _ = reading
    fake.fail_title = "Methods"
    job = service.create(doc["id"], "Test topic")
    service.run_next()
    assert service.store.get_job(job["id"])["status"] == "failed"
    before_outline = sum("识别" in call[2]["stage"] for call in fake.calls)
    before_background = sum(call[2].get("section_title") == "Background" for call in fake.calls)
    service.store.change_status(job["id"], "retry")
    service.run_next()
    assert service.store.get_job(job["id"])["status"] == "completed"
    assert sum("识别" in call[2]["stage"] for call in fake.calls) == before_outline
    assert (
        sum(call[2].get("section_title") == "Background" for call in fake.calls)
        == before_background
    )


@pytest.mark.parametrize("mode", ["bad_quote", "bad_heading"])
def test_unverifiable_model_output_cannot_become_a_completed_draft(reading, mode):
    service, fake, doc, _ = reading
    setattr(fake, mode, True)
    job = service.create(doc["id"], "topic")
    service.run_next()
    result = service.store.get_job(job["id"])
    assert result["status"] == "failed"
    assert result["result"] is None


def test_new_sessions_load_rules_but_running_job_keeps_its_snapshot(reading):
    service, fake, doc, _ = reading
    first = service.create(doc["id"], "topic")
    capability = service.store.capability()
    changed = service.store.save_rules("单独检查样本量。", capability["version"])
    restarted = ReadingService(service.library, {}, fake)
    second = restarted.create(doc["id"], "topic")
    assert second["id"] != first["id"]
    assert second["capability"]["version"] == changed["version"]
    assert first["capability"]["rules"] == ""
    assert second["capability"]["rules"] == "单独检查样本量。"
    with pytest.raises(ValueError, match="其他设备"):
        service.store.save_rules("stale update", capability["version"])
    claimed = service.store.claim()
    assert claimed["id"] == first["id"]
    restarted.store.recover()
    assert restarted.store.get_job(first["id"])["status"] == "queued"
    restarted.run_next()
    assert all("单独检查样本量。" not in call[1] for call in fake.calls)


def test_section_question_is_persistent_and_only_uses_selected_section(reading):
    service, fake, _, _ = reading
    parent = completed(reading)
    section = next(s for s in parent["result"]["sections"] if s["title"] == "Methods")
    question = service.question(parent["id"], section["id"], "What was the control?")
    assert question["question_context"]["parent_job_id"] == parent["id"]
    service.run_next()
    value = service.store.get_job(question["id"])
    assert value["status"] == "completed"
    assert value["result"]["answers"][0]["evidence"]
    ids = {b["id"] for b in section["blocks"]}
    assert all(b["id"] in ids for b in fake.calls[-1][2]["source_blocks"])


def personal_repo(tmp_path):
    root = tmp_path / "personal-records"
    root.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
    for name, value in [("user.name", "Test User"), ("user.email", "test@example.invalid")]:
        subprocess.run(["git", "-C", str(root), "config", name, value], check=True)
    return root


def test_export_creates_five_column_table_and_limited_git_commit(reading):
    service, _, _, tmp_path = reading
    job = completed(reading)
    root = personal_repo(tmp_path)
    unrelated = root / "unrelated.md"
    unrelated.write_text("do not commit me")
    exporter = NoteExporter(service.store, root)
    preview = exporter.preview(job)
    saved = exporter.save(
        job, ideas="My own thought.", expected_notes_revision=preview["notes_revision"]
    )
    assert not saved["version_pending"]
    table = (root / saved["table_path"]).read_text()
    assert "| " + " | ".join(TABLE_HEADERS) + " |" in table
    assert "My own thought." in table
    detail = (root / saved["note_path"]).read_text()
    assert "## Methods" in detail
    assert "### 作者讨论" in detail and "### 助手分析" in detail
    assert "## 我的想法" in detail and "My own thought." in detail
    tracked = subprocess.check_output(["git", "-C", str(root), "ls-files"], text=True)
    assert "unrelated.md" not in tracked
    assert len(saved["commit"]) == 40
    again = exporter.save(job)
    assert again["commit"] == saved["commit"]


def test_export_preserves_handwritten_text_and_rejects_changed_managed_region(reading):
    service, _, _, tmp_path = reading
    job = completed(reading)
    root = personal_repo(tmp_path)
    exporter = NoteExporter(service.store, root)
    saved = exporter.save(job)
    path = root / saved["note_path"]
    path.write_text(path.read_text() + "\n## Handwritten\nDo not overwrite.\n")
    exporter.save(job)
    assert "Do not overwrite." in path.read_text()
    original = path.read_text()
    path.write_text(original.replace("测试方法与对照", "user changed AI area"))
    with pytest.raises(NoteConflict, match="外部修改"):
        exporter.save(job)
    assert "user changed AI area" in path.read_text()


def test_stale_personal_ideas_and_unrelated_staged_changes_are_not_overwritten(reading):
    service, _, _, tmp_path = reading
    job = completed(reading)
    root = personal_repo(tmp_path)
    exporter = NoteExporter(service.store, root)
    preview = exporter.preview(job)
    saved = exporter.save(job)
    with pytest.raises(NoteConflict, match="其他设备"):
        exporter.save(job, "stale thoughts", preview["notes_revision"])
    unrelated = root / "private.md"
    unrelated.write_text("keep staged")
    subprocess.run(["git", "-C", str(root), "add", "private.md"], check=True)
    before = (root / saved["note_path"]).read_bytes()
    with pytest.raises(NoteConflict, match="暂存"):
        exporter.save(job)
    assert (root / saved["note_path"]).read_bytes() == before


def test_export_failure_leaves_files_and_reports_pending_git(reading, monkeypatch):
    service, _, _, tmp_path = reading
    job = completed(reading)
    root = personal_repo(tmp_path)
    exporter = NoteExporter(service.store, root)
    original = exporter.git

    def fail_commit(*args):
        if args[0] == "commit":
            raise ValueError("test commit failure")
        return original(*args)

    monkeypatch.setattr(exporter, "git", fail_commit)
    saved = exporter.save(job)
    assert saved["version_pending"]
    assert (root / saved["note_path"]).exists()


def test_model_adapters_use_expected_routes_and_never_expose_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-a-real-credential")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-not-a-real-credential")
    monkeypatch.setenv("MOONSHOT_API_KEY", "test-key-not-a-real-credential")
    calls = []

    def respond(request):
        calls.append((str(request.url), json.loads(request.content)))
        value = {"answer": "unknown", "evidence": [], "limitations": ["Not in source"]}
        if request.url.path.endswith("/responses"):
            body = {
                "status": "completed",
                "output": [{"content": [{"type": "output_text", "text": json.dumps(value)}]}],
            }
        else:
            body = {
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(value)}}]
            }
        return httpx.Response(200, json=body)

    gateway = ModelGateway(httpx.MockTransport(respond))
    gateway.generate(
        model_settings({"provider": "openai", "model": "configured-test-model"}), "JSON", {}, Answer
    )
    gateway.generate(
        model_settings({"provider": "deepseek", "model": "configured-test-model"}),
        "JSON",
        {},
        Answer,
    )
    gateway.generate(
        model_settings({"provider": "kimi", "model": "configured-test-model"}), "JSON", {}, Answer
    )
    assert calls[2][0] == "https://api.moonshot.cn/v1/chat/completions"
    assert calls[0][0] == "https://api.openai.com/v1/responses"
    assert calls[0][1]["store"] is False
    assert calls[1][0] == "https://api.deepseek.com/chat/completions"
    assert "test-key-not-a-real-credential" not in json.dumps(calls)
    bad = ModelGateway(
        httpx.MockTransport(lambda request: httpx.Response(401, text="sensitive echoed body"))
    )
    with pytest.raises(ValueError, match="HTTP 401") as caught:
        bad.generate(model_settings({"provider": "openai", "model": "test"}), "JSON", {}, Answer)
    assert "sensitive" not in str(caught.value)


def test_no_configuration_is_honest_and_key_is_never_saved(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = {
        "library": str(tmp_path / "library"),
        "database": str(tmp_path / "state.db"),
        "token": "x" * 32,
    }
    app = create_app(config, scan_on_start=False, start_worker=False)
    with TestClient(app) as client:
        assert client.get("/api/literature/settings").status_code == 401
        client.headers["Authorization"] = "Bearer " + config["token"]
        settings = client.get("/api/literature/settings").json()
        assert not settings["model_status"]["ready"]
        assert not settings["records"]["ready"]
        assert client.get("/api/literature/jobs").json() == []
        body = {"provider": "openai", "model": "test", "api_key": "do-not-store"}
        assert client.put("/api/literature/settings", json=body).status_code == 422


def test_api_metadata_start_poll_question_export_and_automatic_notes(tmp_path):
    root = personal_repo(tmp_path)
    fake = FakeModel()
    config = {
        "library": str(tmp_path / "library"),
        "database": str(tmp_path / "state.db"),
        "token": "x" * 32,
        "literature": {"records_root": str(root), "model": {"provider": "openai", "model": "test"}},
    }
    app = create_app(config, scan_on_start=False, start_worker=False, model_gateway=fake)
    (app.state.library.root / "paper.md").write_text(
        "# Synthetic paper\n\n## Methods\n\nSome evidence."
    )
    app.state.library.scan()
    doc = app.state.library.documents()[0]
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + config["token"]
        assert client.get("/api/literature/metadata/" + doc["id"]).status_code == 200
        assert not fake.calls
        response = client.post(
            "/api/literature/jobs", json={"document_id": doc["id"], "topic": "Biology"}
        )
        assert response.status_code == 200, response.text
        job_id = response.json()["id"]
        app.state.literature.run_next()
        value = client.get("/api/literature/jobs/" + job_id).json()
        assert value["status"] == "completed", value["error"]
        assert value["result"]["export"]["saved"]
        assert client.get("/api/literature/jobs/" + job_id + "/notes/download").status_code == 200
        assert client.get("/api/literature/jobs/" + job_id + "/notes").json()["ready"]
        listed = client.get("/api/literature/jobs").json()[0]
        assert "blocks" not in listed["result"]["sections"][0]
        question = client.post(
            "/api/literature/jobs/" + job_id + "/questions/new",
            json={"section_id": value["result"]["sections"][0]["id"], "text": "Why?"},
        )
        assert question.status_code == 200, question.text
        app.state.literature.run_next()
        assert (
            client.get("/api/literature/jobs/" + question.json()["id"]).json()["status"]
            == "completed"
        )


def test_worker_lease_prevents_two_owners(tmp_path):
    first = WorkerLease(tmp_path / "test.db")
    second = WorkerLease(tmp_path / "test.db")
    assert first.acquire()
    try:
        assert not second.acquire()
    finally:
        first.close()
    assert second.acquire()
    second.close()


def test_long_source_chunking_never_silently_omits_text(reading):
    from assistant.literature.sources import chunks

    service, _, doc, _ = reading
    source = extract_source(service.library, doc)
    parts = chunks(source["blocks"], max_chars=150)
    assert [block for part in parts for block in part] == source["blocks"]


def test_cancelled_job_is_not_claimed_and_budget_failure_keeps_checkpoints(reading):
    service, fake, doc, _ = reading
    job = service.create(doc["id"], "cancelled")
    service.store.change_status(job["id"], "cancel")
    assert service.run_next() is False
    assert fake.calls == []
    limited = service.create(doc["id"], "limited")
    service.max_requests = 1
    service.run_next()
    assert service.store.get_job(limited["id"])["status"] == "failed"
    assert service.store.step(limited["id"], "outline:0") is not None


def test_empty_scanned_pdf_is_not_called_full_text(reading):
    from pypdf import PdfWriter

    service, fake, _, _ = reading
    path = service.library.root / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    with path.open("wb") as stream:
        writer.write(stream)
    service.library.scan()
    doc = next(d for d in service.library.documents() if d["path"] == "scan.pdf")
    with pytest.raises(ValueError, match="可读文本"):
        service.create(doc["id"], "topic")
    assert not fake.calls


def test_personal_repository_must_not_be_inside_code_tree(reading):
    service, _, _, tmp_path = reading
    code = tmp_path / "code"
    code.mkdir()
    exporter = NoteExporter(service.store, code / "private-records", code_root=code)
    assert not exporter.readiness()["ready"]
    assert "不能位于" in exporter.readiness()["reason"]


def test_followup_question_pins_only_same_section_history(reading):
    service, fake, _, _ = reading
    parent = completed(reading)
    methods = next(s for s in parent["result"]["sections"] if s["title"] == "Methods")
    other = next(s for s in parent["result"]["sections"] if s["title"] == "Results")
    service.question(parent["id"], methods["id"], "What was the control?")
    service.run_next()
    service.question(parent["id"], other["id"], "Unrelated question")
    service.run_next()
    followup = service.question(parent["id"], methods["id"], "Why that control?")
    service.run_next()
    history = fake.calls[-1][2]["conversation_history"]
    assert len(history) == 1
    assert history[0]["question"] == "What was the control?"
    assert followup["question_context"]["history"] == history
