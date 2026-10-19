import httpx
import pytest
from fastapi.testclient import TestClient

from assistant.app import create_app
from assistant.library import Library
from assistant.synchronization import SyncSelection, merge_ignores
from assistant.zotero import ZoteroBridge


@pytest.fixture
def bridge(tmp_path):
    library = Library(tmp_path / "Media", tmp_path / "state.db")
    storage = tmp_path / "Zotero" / "storage"
    storage.mkdir(parents=True)
    source = storage / "ATTACH01" / "test.pdf"
    source.parent.mkdir()
    source.write_bytes(b"%PDF-1.4 synthetic fixture")
    items = [
        {"key": "PARENT01", "data": {"itemType": "journalArticle", "title": "Test paper"}},
        {
            "key": "ATTACH01",
            "data": {
                "itemType": "attachment",
                "parentItem": "PARENT01",
                "title": "Test PDF",
                "filename": "test.pdf",
                "linkMode": "imported_file",
            },
        },
    ]
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"  # Metadata is exclusively owned by Zotero.
        if request.url.path.endswith("/file/view/url"):
            return (
                httpx.Response(200, text=source.as_uri())
                if source.exists()
                else httpx.Response(404)
            )
        return httpx.Response(200, json=items, headers={"Last-Modified-Version": "1"})

    adapter = ZoteroBridge(
        library,
        {"allowed_roots": [str(storage)], "storage_root": str(storage)},
        httpx.MockTransport(handler),
    )
    return adapter, source, items, calls


def canonical(adapter):
    return adapter.library.root / "Papers/Zotero/users-0/ATTACH01/document.pdf"


def test_new_items_and_attachments_are_bridged_idempotently(bridge):
    adapter, source, items, calls = bridge
    result = adapter.sync()
    assert result["message"] == "同步完成"
    assert canonical(adapter).read_bytes() == source.read_bytes()
    modified = canonical(adapter).stat().st_mtime_ns
    assert adapter.sync()["items"][1]["state"] == "available"
    assert canonical(adapter).stat().st_mtime_ns == modified
    items.append({"key": "PARENT02", "data": {"itemType": "book", "title": "New book"}})
    assert len(adapter.sync()["items"]) == 3
    # Trashed remote items disappear from listing, but their local files are retained.
    items.pop(1)
    adapter.sync()
    assert canonical(adapter).exists()


def test_single_side_updates_propagate_and_dual_edits_are_preserved(bridge):
    adapter, source, _, _ = bridge
    adapter.sync()
    source.write_bytes(b"local revision 2")
    adapter.sync()
    assert canonical(adapter).read_bytes() == b"local revision 2"
    canonical(adapter).write_bytes(b"remote revision 3")
    adapter.sync()
    assert source.read_bytes() == b"remote revision 3"
    source.write_bytes(b"local conflict")
    canonical(adapter).write_bytes(b"remote conflict")
    result = adapter.sync()
    assert result["items"][1]["state"] == "error"
    assert source.read_bytes() == b"local conflict"
    assert canonical(adapter).read_bytes() == b"remote conflict"


def test_missing_stored_file_restores_from_received_attachment(bridge):
    adapter, source, _, _ = bridge
    adapter.sync()
    expected = source.read_bytes()
    source.unlink()
    result = adapter.sync()
    assert source.read_bytes() == expected
    assert "补齐" in result["items"][1]["message"]


def test_unknown_existing_copy_is_not_overwritten(bridge):
    adapter, source, _, _ = bridge
    path = canonical(adapter)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"already received")
    assert adapter.sync()["items"][1]["state"] == "error"
    assert path.read_bytes() == b"already received"
    assert source.exists()


def test_attachment_roots_and_symlinks_prevent_escape(bridge, tmp_path):
    adapter, source, _, _ = bridge
    adapter.config["allowed_roots"] = []
    assert adapter.sync()["items"][1]["state"] == "error"
    assert not canonical(adapter).exists()
    with pytest.raises(ValueError):
        adapter.safe_under(adapter.library.root, "../escape.pdf")
    try:
        (adapter.library.root / "Papers").symlink_to(tmp_path / "Zotero", target_is_directory=True)
    except OSError:
        pytest.skip("此 Windows 账户没有创建符号链接权限")
    adapter.config["allowed_roots"] = [str(source.parent)]
    assert adapter.sync()["items"][1]["state"] == "error"


def test_offline_keeps_metadata_and_does_not_delete_files(bridge):
    adapter, _, _, _ = bridge
    adapter.sync()

    def offline(request):
        raise httpx.ConnectError("unavailable", request=request)

    adapter.transport = httpx.MockTransport(offline)
    result = adapter.sync()
    assert len(result["items"]) == 2
    assert "不可用" in result["message"]
    assert canonical(adapter).exists()


def test_version_change_during_pagination_does_not_publish_partial_catalog(bridge):
    adapter, _, _, _ = bridge
    adapter.sync()
    row = {"key": "PARENT01", "data": {"itemType": "book"}}

    def pages(request):
        start = request.url.params.get("start")
        return httpx.Response(
            200, json=[row] * 100, headers={"Last-Modified-Version": "1" if start == "0" else "2"}
        )

    adapter.transport = httpx.MockTransport(pages)
    result = adapter.sync()
    assert len(result["items"]) == 2
    assert "分页期间更新" in result["message"]


def test_file_limit_is_enforced_before_copy(bridge):
    adapter, _, _, _ = bridge
    adapter.config["max_attachment_bytes"] = 2
    assert adapter.sync()["items"][1]["state"] == "error"
    assert not canonical(adapter).exists()


def test_selection_keeps_user_rules_and_replaces_only_managed_region():
    previous = [
        ".git",
        START := "# assistant-selective:start",
        "/old.pdf",
        "# assistant-selective:end",
        "Thumbs.db",
    ]
    rules = merge_ignores(previous, ["Books/new.epub"])
    assert rules == [START, "/Books/new.epub", "# assistant-selective:end", ".git", "Thumbs.db"]
    with pytest.raises(ValueError):
        merge_ignores([START], [])


def test_selection_targets_only_matching_local_folder(bridge, monkeypatch, tmp_path):
    adapter, _, _, _ = bridge
    (adapter.library.root / "book.epub").write_bytes(b"book")
    adapter.library.scan()
    monkeypatch.setenv("SYNCTHING_API_KEY", "test-key")
    posted = []

    def syncthing(request):
        if request.url.path.endswith("study-media"):
            return httpx.Response(200, json={"path": str(adapter.library.root)})
        if request.method == "GET":
            return httpx.Response(200, json={"ignore": [".git"]})
        posted.append(request.content)
        return httpx.Response(200)

    selection = SyncSelection(adapter.library, transport=httpx.MockTransport(syncthing))
    assert "未删除" in selection.apply(["book.epub"])["message"]
    assert posted and (adapter.library.root / "book.epub").exists()
    assert SyncSelection(adapter.library).status()["excluded"] == ["book.epub"]
    with pytest.raises(ValueError):
        selection.apply(["../escape.pdf"])
    assert len(posted) == 1

    def mismatch(request):
        return httpx.Response(200, json={"path": str(tmp_path / "other")})

    selection.transport = httpx.MockTransport(mismatch)
    with pytest.raises(ValueError, match="不一致"):
        selection.apply([])


def test_connection_api_is_authenticated_and_read_only_metadata(bridge):
    adapter, _, _, _ = bridge
    app = create_app(
        {
            "token": "x" * 32,
            "library": str(adapter.library.root),
            "database": adapter.library.database,
        },
        scan_on_start=False,
        start_worker=False,
    )
    with TestClient(app) as client:
        assert client.get("/api/sync/zotero").status_code == 401
        headers = {"Authorization": "Bearer " + "x" * 32}
        assert client.get("/api/sync/storage", headers=headers).status_code == 200
        response = client.put(
            "/api/sync/zotero",
            headers=headers,
            json={"enabled": True, "kind": "users", "library_id": "0"},
        )
        assert response.json()["settings"]["enabled"]
        assert (
            client.put(
                "/api/sync/zotero",
                headers=headers,
                json={"enabled": True, "kind": "users", "library_id": "../"},
            ).status_code
            == 422
        )
