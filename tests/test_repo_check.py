import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "repo_check", Path(__file__).resolve().parents[1] / "scripts/repo_check.py"
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def test_private_runtime_and_secrets_are_rejected():
    for path in ["config/local.json", "runtime/state.db", ".env", "data/Notes/note.md"]:
        assert guard.problems(path, b"harmless content")
    assert guard.problems("accidental.txt", b"-----BEGIN " + b"PRIVATE KEY-----")


def test_examples_and_normal_source_are_allowed():
    assert guard.problems("config/example.json", b'{"token":"REPLACE_WITH_RANDOM_SECRET"}') == []
    assert guard.problems(".env.example", b"TOKEN=placeholder") == []
    assert guard.problems("src/assistant/app.py", b'print("hello")') == []
