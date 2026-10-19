import json

import httpx
import pytest
from fastapi.testclient import TestClient

from assistant.app import create_app
from assistant.cli import Client, handle_command, load_config, main, run_chat
from assistant.conversation import ConversationService, Message, Reply
from assistant.library import Library
from assistant.literature.service import ReadingService


class Gateway:
    def __init__(self):
        self.calls = []
        self.result = Reply(text="我们可以一起整理思路。")
        self.ready = True

    def readiness(self, settings):
        return {"ready": self.ready, "missing": [] if self.ready else ["模型名称"]}

    def generate(self, settings, instructions, payload, contract):
        self.calls.append(payload)
        return self.result, {}


@pytest.fixture
def conversation(tmp_path):
    library = Library(tmp_path / "Media", tmp_path / "state.db")
    (library.root / "test.md").write_text("# Paper\n\nEvidence", encoding="utf-8")
    library.scan()
    gateway = Gateway()
    reading = ReadingService(library, {}, gateway)
    return ConversationService(reading), gateway


def test_explicit_workspace_navigation_needs_no_model_and_negation_is_not_navigation(conversation):
    service, gateway = conversation
    gateway.ready = False
    session = service.create()["id"]
    for index, text in enumerate(["我要进行文献阅读", "打开文件", "/tasks"]):
        reply = service.send(session, Message(text=text, request_id=str(index)))
        assert reply["workspace"] != "none"
    reply = service.send(session, Message(text="不要打开文献阅读", request_id="negative"))
    assert reply["workspace"] == "none"
    assert gateway.calls == []


def test_conversation_survives_service_restart_and_repeated_request_does_not_call_model(
    conversation,
):
    service, gateway = conversation
    session = service.create()["id"]
    message = Message(text="帮我梳理问题", request_id="request")
    first = service.send(session, message)
    assert service.send(session, message) == first
    assert len(gateway.calls) == 1
    restored = ConversationService(service.reading)
    assert len(restored.get(session)["messages"]) == 2
    with pytest.raises(ValueError, match="不一致"):
        restored.send(session, Message(text="different", request_id="request"))
    restored.send(session, Message(text="继续", request_id="followup"))
    assert gateway.calls[-1]["history"][0]["text"] == "帮我梳理问题"


def test_model_workspace_and_document_are_validated(conversation):
    service, gateway = conversation
    session = service.create()["id"]
    doc = service.library.documents()[0]
    gateway.result = Reply(text="打开这篇文献", workspace="literature", document_id=doc["id"])
    assert (
        service.send(session, Message(text="帮我处理 test", request_id="one"))["document_id"]
        == doc["id"]
    )
    gateway.result = Reply(text="unknown", workspace="literature", document_id="missing")
    result = service.send(session, Message(text="another", request_id="two"))
    assert result["error"] and result["workspace"] == "none"
    with pytest.raises(ValueError):
        Reply(text="execute", workspace="shell")


def test_question_reply_tracks_persistent_job_and_evidence(conversation, monkeypatch):
    service, _ = conversation
    session = service.create()["id"]
    job = {"id": "question", "status": "queued", "progress": "waiting", "error": "", "result": None}
    monkeypatch.setattr(service.reading, "question", lambda *args: job)
    monkeypatch.setattr(service.reading.store, "get_job", lambda *args: job)
    service.send(
        session,
        Message(
            text="什么对照？",
            request_id="ask",
            context={"job_id": "parent", "section_id": "methods"},
        ),
    )
    assert service.get(session)["messages"][-1]["task_status"] == "queued"
    job.update(
        status="completed",
        result={
            "answers": [
                {"answer": "基于原文回答", "evidence": [{"block_id": "B1", "quote": "Evidence"}]}
            ]
        },
    )
    answer = service.get(session)["messages"][-1]
    assert answer["text"] == "基于原文回答"
    assert answer["evidence"][0]["block_id"] == "B1"


def test_conversation_routes_require_auth_and_share_web_and_terminal_history(tmp_path):
    app = create_app(
        {
            "token": "x" * 32,
            "library": str(tmp_path / "Media"),
            "database": str(tmp_path / "state.db"),
        },
        scan_on_start=False,
        start_worker=False,
    )
    with TestClient(app) as client:
        assert client.get("/api/conversations").status_code == 401
        headers = {"Authorization": "Bearer " + "x" * 32}
        session = client.post("/api/conversations", headers=headers).json()["id"]
        result = client.post(
            f"/api/conversations/{session}/messages",
            headers=headers,
            json={"text": "我要进行文献阅读", "request_id": "terminal"},
        )
        assert result.json()["workspace"] == "literature"
        assert (
            len(client.get(f"/api/conversations/{session}", headers=headers).json()["messages"])
            == 2
        )
        assert client.get("/api/conversations/missing", headers=headers).status_code == 404


def test_terminal_read_resolves_path_and_rejects_ambiguous_name():
    calls = []
    docs = [{"id": "a", "path": "one/paper.pdf"}, {"id": "b", "path": "two/paper.pdf"}]

    def handler(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer test"
        if request.url.path.endswith("/documents"):
            return httpx.Response(200, json=docs)
        payload = json.loads(request.content)
        return httpx.Response(200, json={"id": "job", "document_id": payload["document_id"]})

    client = Client("http://localhost:8765", "test", httpx.MockTransport(handler))
    try:
        with pytest.raises(ValueError, match="重名"):
            client.read("paper.pdf", "topic")
        assert client.read("one/paper.pdf", "topic")["document_id"] == "a"
        assert client.read("b", "topic")["document_id"] == "b"
    finally:
        client.close()


def test_terminal_stays_connected_only_for_requests_and_does_not_start_worker():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"text": "已打开", "workspace": "literature"})
        return httpx.Response(200, json={"id": "session", "messages": []})

    client = Client("http://localhost:8765", "test", httpx.MockTransport(handler))
    output = []
    lines = iter(["我要进行文献阅读", "/web files", "/quit"])
    try:
        run_chat(client, read=lambda prompt: next(lines), write=output.append)
    finally:
        client.close()
    assert len(calls) == 2
    assert any("/#literature" in line for line in output)
    assert any("/#files" in line for line in output)


def test_cli_config_keeps_legacy_serve_paths_and_errors_without_secret(
    tmp_path, monkeypatch, capsys
):
    config = tmp_path / "config" / "local.json"
    config.parent.mkdir()
    config.write_text(
        json.dumps(
            {
                "library": "Media",
                "database": "runtime/state.db",
                "literature": {"records_root": "Records"},
            }
        )
    )
    value = load_config(config)
    assert value["library"] == str(tmp_path / "Media")
    assert value["literature"]["records_root"] == str(tmp_path / "Records")
    monkeypatch.delenv("ASSISTANT_TOKEN", raising=False)
    assert main(["chat", "--config", str(tmp_path / "missing")]) == 1
    assert "ASSISTANT_TOKEN" in capsys.readouterr().err


def test_cli_auth_is_not_forwarded_on_redirect():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://other.example"})

    client = Client("http://localhost:8765", "test", httpx.MockTransport(handler))
    try:
        with pytest.raises(ValueError, match="重定向"):
            client.request("documents")
    finally:
        client.close()
    assert len(requests) == 1


def test_cli_notes_prints_version_pending_honestly():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "note_path": "paper.md",
                "version_pending": True,
                "error": "Git identity missing",
            },
        )

    client = Client("http://localhost", "test", httpx.MockTransport(handler))
    output = []
    try:
        handle_command(client, "/notes job", "session", output.append)
    finally:
        client.close()
    assert output == ["已保存：paper.md", "Git 待处理：Git identity missing"]


def test_cli_model_settings_and_rules_use_existing_validated_apis():
    calls = []
    settings = {
        "providers": {"deepseek": {"base_url": "https://api.deepseek.com", "api_mode": "chat"}},
        "settings": {"provider": "deepseek", "model": "model", "max_output_tokens": 6000},
        "model_status": {"ready": True, "missing": []},
        "capability": {"rules": "保留原文小标题", "version": 2},
    }

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/rules"):
            value = json.loads(request.content)
            assert value["expected_version"] == 2
            assert value["text"] == "保留原文小标题\n区分作者结论和推测"
            return httpx.Response(200, json={"version": 3, "rules": value["text"]})
        if request.method == "PUT":
            value = json.loads(request.content)
            assert value["provider"] == "deepseek" and value["model"] == "selected-model"
            assert value["api_mode"] == "chat"
        return httpx.Response(200, json=settings)

    client = Client("http://localhost", "test", httpx.MockTransport(handler))
    output = []
    try:
        handle_command(client, "/model deepseek selected-model", "session", output.append)
        handle_command(client, "/rule 区分作者结论和推测", "session", output.append)
    finally:
        client.close()
    assert any("阅读规则 v3" in line for line in output)
    assert len(calls) == 4
