import os

import pytest
from fastapi.testclient import TestClient

from assistant.app import create_app
from assistant.files import FileConflict, FileManager
from assistant.library import Library


@pytest.fixture
def manager(tmp_path):
    return FileManager(Library(tmp_path / "library", tmp_path / "state.db"))


def get_entry(manager, path):
    return next(entry for entry in manager.entries() if entry["path"] == path)


def act(manager, action, path="", target="", content=""):
    version = get_entry(manager, path)["version"] if path else ""
    return manager.operate(action, path, target, version, content)


def test_entries_include_directories_types_and_dates(manager):
    act(manager, "create_folder", target="Notes")
    act(manager, "create_file", target="Notes/test.md", content="hello")
    item = get_entry(manager, "Notes/test.md")
    assert item["parent"] == "Notes"
    assert item["kind"] == ".md"
    assert item["size"] == 5
    assert item["created_at"] and item["modified_at"]
    assert item["created_source"] in {"filesystem", "first_seen"}
    assert item["document_id"]
    assert get_entry(manager, "Notes")["is_dir"] is True
    assert get_entry(manager, "Notes")["parent"] == ""
    with manager.library.connect() as db:
        db.execute('UPDATE file_dates SET created=1,source="first_seen" WHERE path="Notes/test.md"')
    assert get_entry(manager, "Notes/test.md")["created_at"].startswith("1970-01-01")


def test_folder_move_preserves_document_ids_and_reading(manager):
    act(manager, "create_folder", target="Notes")
    act(manager, "create_file", target="Notes/test.md", content="unique text")
    doc_id = get_entry(manager, "Notes/test.md")["document_id"]
    with manager.library.connect() as db:
        db.execute(
            "INSERT INTO reading(document_id,revision,position,version) VALUES(?,?,?,?)",
            (doc_id, "revision", 8, 1),
        )
    act(manager, "move", "Notes", "Renamed")
    assert get_entry(manager, "Renamed/test.md")["document_id"] == doc_id
    assert manager.library.search("unique")[0]["path"] == "Renamed/test.md"
    # Reusing the old path must not steal the moved file's ID or reading history.
    act(manager, "create_folder", target="Notes")
    act(manager, "create_file", target="Notes/test.md", content="new note")
    assert get_entry(manager, "Notes/test.md")["document_id"] != doc_id
    with manager.library.connect() as db:
        assert (
            db.execute("SELECT position FROM reading WHERE document_id=?", (doc_id,)).fetchone()[0]
            == 8
        )


def test_copy_gets_independent_identity_and_does_not_overwrite(manager):
    act(manager, "create_folder", target="Notes")
    act(manager, "create_file", target="Notes/a.md", content="hello")
    act(manager, "copy", "Notes", "Copied")
    assert (manager.root / "Copied/a.md").read_text() == "hello"
    assert (
        get_entry(manager, "Copied/a.md")["document_id"]
        != get_entry(manager, "Notes/a.md")["document_id"]
    )
    with pytest.raises(FileConflict):
        act(manager, "copy", "Notes/a.md", "Copied/a.md")
    with pytest.raises(ValueError):
        act(manager, "move", "Notes", "Notes/Nested")
    with pytest.raises(FileConflict):
        act(manager, "create_file", target="Notes/A.md")


def test_delete_restore_recovers_search_and_annotation_identity(manager):
    act(manager, "create_folder", target="Notes")
    act(manager, "create_file", target="Notes/a.md", content="searchable record")
    doc_id = get_entry(manager, "Notes/a.md")["document_id"]
    result = act(manager, "delete", "Notes")
    assert manager.entries() == []
    assert manager.library.search("searchable") == []
    assert manager.trash_entries()[0]["id"] == result["trash_id"]
    manager.restore(result["trash_id"])
    assert get_entry(manager, "Notes/a.md")["document_id"] == doc_id
    assert manager.library.search("searchable")[0]["id"] == doc_id
    assert manager.trash_entries() == []


def test_restore_conflict_does_not_overwrite_new_file(manager):
    act(manager, "create_file", target="a.md", content="original")
    deleted = act(manager, "delete", "a.md")
    act(manager, "create_file", target="a.md", content="new")
    with pytest.raises(FileConflict):
        manager.restore(deleted["trash_id"])
    assert (manager.root / "a.md").read_text() == "new"
    assert manager.trash_entries()


@pytest.mark.parametrize(
    "path",
    [
        "../outside.md",
        "/tmp/outside.md",
        ".obsidian/x.md",
        "dir/../outside.md",
        "C:\\test.md",
        "a//b.md",
        "NUL.txt",
        "folder/COM1",
        "trailing.",
    ],
)
def test_paths_are_portable_and_confined(manager, path):
    with pytest.raises(ValueError):
        manager.operate("create_file", target=path)


def test_stale_version_cannot_delete_changed_file(manager):
    act(manager, "create_file", target="a.md", content="before")
    old = get_entry(manager, "a.md")
    (manager.root / "a.md").write_text("changed by another device")
    with pytest.raises(FileConflict):
        manager.operate("delete", "a.md", expected_version=old["version"])
    assert (manager.root / "a.md").exists()


def test_symlinks_are_never_followed(manager, tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    (external / "secret.md").write_text("private")
    try:
        (manager.root / "link").symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink privilege unavailable")
    assert manager.entries() == []
    with pytest.raises(ValueError):
        manager.operate("create_file", target="link/leak.md")
    assert not (external / "leak.md").exists()


def test_file_api_requires_auth_and_reindexes_mutations(tmp_path):
    config = {
        "library": str(tmp_path / "library"),
        "database": str(tmp_path / "state.db"),
        "token": "x" * 32,
    }
    app = create_app(config, scan_on_start=False)
    with TestClient(app) as client:
        assert client.get("/api/files").status_code == 401
        assert (
            client.post(
                "/api/files/operations", json={"action": "create_folder", "target": "Notes"}
            ).status_code
            == 401
        )
        client.headers["Authorization"] = "Bearer " + config["token"]
        response = client.post(
            "/api/files/operations",
            json={"action": "create_file", "target": "new.md", "content": "test record"},
        )
        assert response.status_code == 200
        entry = client.get("/api/files").json()[0]
        assert entry["document_id"]
        assert client.get("/api/search?q=record").json()
        assert client.get("/api/files/download?path=new.md").content == b"test record"
        assert (
            client.post(
                "/api/files/operations",
                json={"action": "delete", "path": "new.md", "expected_version": "wrong"},
            ).status_code
            == 409
        )
        deleted = client.post(
            "/api/files/operations",
            json={"action": "delete", "path": "new.md", "expected_version": entry["version"]},
        ).json()
        assert client.get("/api/files").json() == []
        assert (
            client.post("/api/files/trash/" + deleted["trash_id"] + "/restore").status_code == 200
        )
        assert client.get("/api/search?q=record").json()
        assert client.get("/api/files/download?path=../state.db").status_code == 400


def test_dates_update_without_content_change(manager):
    act(manager, "create_file", target="a.md", content="same")
    first = get_entry(manager, "a.md")
    path = manager.root / "a.md"
    os.utime(path, (1_000_000, 1_000_000))
    second = get_entry(manager, "a.md")
    assert second["modified_at"] != first["modified_at"]
    assert second["created_at"] == first["created_at"]


def test_syncthing_collection_root_cannot_be_renamed_or_deleted(manager):
    act(manager, "create_folder", target="Notes")
    (manager.root / "Notes/.stfolder").mkdir()
    for action, target in [("move", "Renamed"), ("delete", "")]:
        with pytest.raises(ValueError, match="同步根目录"):
            act(manager, action, "Notes", target)
    act(manager, "copy", "Notes", "Copy")
    assert not (manager.root / "Copy/.stfolder").exists()
