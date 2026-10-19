import zipfile

import pytest
from fastapi.testclient import TestClient

from assistant.app import create_app
from assistant.library import Library, epub_chapters


@pytest.fixture
def library(tmp_path):
    return Library(tmp_path / "library", tmp_path / "state.db")


def test_index_updates_and_removes_deleted_files(library):
    path = library.root / "实验.md"
    path.write_text("实验结果：正确\n第二行", encoding="utf-8")
    library.scan()
    hit = library.search("实验")[0]
    assert hit["location"] == "行 1–2"
    assert len(hit["revision"]) == 64
    path.write_text("更新后的记录", encoding="utf-8")
    library.scan()
    assert library.search("实验") == []
    assert library.search("更新")[0]["revision"] != hit["revision"]
    path.unlink()
    library.scan()
    assert library.documents() == []
    assert library.search("更新") == []


def test_private_hidden_paths_and_symlinks_are_excluded(library, tmp_path):
    secret = tmp_path / "secret.md"
    secret.write_text("private")
    (library.root / "escape.md").symlink_to(secret)
    hidden = library.root / ".obsidian"
    hidden.mkdir()
    (hidden / "secret.md").write_text("private")
    library.scan()
    assert library.documents() == []
    with pytest.raises(ValueError):
        library.resolve("../secret.md")


def test_markdown_does_not_execute_html(library):
    (library.root / "x.md").write_text("<script>alert(1)</script>\n![x](https://tracker.invalid/x)")
    library.scan()
    result = library.content(library.documents()[0])["html"]
    assert "<script>" not in result
    assert "<img" not in result


def test_epub_uses_spine_and_drops_script(tmp_path):
    path = tmp_path / "book.epub"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="OEBPS/book.opf"/></rootfiles></container>',
        )
        z.writestr(
            "OEBPS/book.opf",
            '<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="a" href="a.xhtml"/><item id="b" href="b.xhtml"/></manifest><spine><itemref idref="b"/><itemref idref="a"/></spine></package>',
        )
        z.writestr("OEBPS/a.xhtml", "<html><body><p>A</p></body></html>")
        z.writestr(
            "OEBPS/b.xhtml", "<html><body><h1>B</h1><p>正文</p><script>evil</script></body></html>"
        )
    chapters = epub_chapters(path)
    assert chapters[0]["title"] == "B"
    assert chapters[1]["title"] == "A"
    assert "evil" not in chapters[0]["text"]


def test_reading_conflicts_auth_and_durable_annotations(tmp_path):
    config = {
        "library": str(tmp_path / "library"),
        "database": str(tmp_path / "state.db"),
        "token": "x" * 32,
    }
    app = create_app(config, scan_on_start=False)
    (app.state.library.root / "note.md").write_text("hello")
    app.state.library.scan()
    with TestClient(app) as client:
        assert client.get("/api/documents").status_code == 401
        assert client.post("/api/login", json={"token": "x" * 32}).status_code == 403
        assert (
            client.post(
                "/api/login", json={"token": "x" * 32}, headers={"X-Study-Client": "web"}
            ).status_code
            == 200
        )
        doc = client.get("/api/documents").json()[0]
        route = "/api/documents/" + doc["id"]
        headers = {"X-Study-Client": "web"}
        body = {"revision": doc["revision"], "position": 3, "version": 0}
        assert client.put(route + "/reading", json=body, headers=headers).status_code == 200
        assert client.put(route + "/reading", json=body, headers=headers).status_code == 409
        note = {"revision": doc["revision"], "location": "页 3", "note": "一个理解"}
        assert client.post(route + "/annotations", json=note, headers=headers).status_code == 200
        assert client.get(route + "/reading").json()["annotations"][0]["note"] == "一个理解"
        assert client.get("/api/annotations/export").status_code == 200
    # New process/app sees the same database, not an in-memory conversation.
    with TestClient(create_app(config, scan_on_start=False)) as client:
        client.headers["Authorization"] = "Bearer " + config["token"]
        state = client.get(route + "/reading").json()
        assert state["progress"]["position"] == 3
        assert state["annotations"][0]["note"] == "一个理解"
        wrong = {**body, "revision": "outdated", "version": 1}
        assert client.put(route + "/reading", json=wrong).status_code == 409


def test_rename_preserves_identity_and_search_source(library):
    source = library.root / "before.md"
    source.write_text("a unique note")
    library.scan()
    before = library.documents()[0]
    source.rename(library.root / "after.md")
    library.scan()
    after = library.documents()[0]
    assert before["id"] == after["id"]
    assert library.search("unique")[0]["path"] == "after.md"


def test_wiki_and_relative_images_use_authenticated_files(library):
    (library.root / "image.png").write_bytes(b"fake-image-for-index")
    (library.root / "note.md").write_text("![[image.png]]\n\n![local](image.png)")
    library.scan()
    doc = next(d for d in library.documents() if d["kind"] == ".md")
    rendered = library.content(doc)["html"]
    assert rendered.count("/api/documents/") == 2
    assert rendered.count("<img") == 2


def test_pdf_range_and_missing_file_are_handled(tmp_path):
    from pypdf import PdfWriter

    config = {
        "library": str(tmp_path / "library"),
        "database": str(tmp_path / "state.db"),
        "token": "x" * 32,
    }
    app = create_app(config, scan_on_start=False)
    path = app.state.library.root / "test.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    with path.open("wb") as stream:
        writer.write(stream)
    app.state.library.scan()
    doc = app.state.library.documents()[0]
    with TestClient(app) as client:
        route = "/api/documents/" + doc["id"] + "/file"
        assert client.get(route).status_code == 401
        client.headers["Authorization"] = "Bearer " + config["token"]
        response = client.get(route, headers={"Range": "bytes=0-9"})
        assert response.status_code == 206
        assert len(response.content) == 10
        assert response.content.startswith(b"%PDF")
        path.unlink()
        assert client.get(route).status_code == 404


def test_backup_is_restorable_and_outside_library(tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path

    project = tmp_path / "project"
    (project / "config").mkdir(parents=True)
    lib = Library(project / "library", project / "runtime/state.db")
    (lib.root / "note.md").write_text("keep me")
    lib.scan()
    config = project / "config/local.json"
    config.write_text(json.dumps({"library": "library", "database": "runtime/state.db"}))
    script = Path(__file__).resolve().parents[1] / "scripts/backup.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--config",
            str(config),
            "--destination",
            str(tmp_path / "backups"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    snapshot = Path(result.stdout.strip())
    restored = Library(snapshot / "library", snapshot / "assistant.db")
    assert restored.search("keep")[0]["path"] == "note.md"
    rejected = subprocess.run(
        [
            sys.executable,
            str(script),
            "--config",
            str(config),
            "--destination",
            str(lib.root / "backup"),
        ],
        capture_output=True,
    )
    assert rejected.returncode != 0
