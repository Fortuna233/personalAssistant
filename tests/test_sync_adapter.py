import importlib.util
import io
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "sync_adapter", Path(__file__).resolve().parents[1] / "scripts/configure_sync.py"
)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


@pytest.mark.parametrize("payload,expected", [(b"", None), (b'{"ok":true}', {"ok": True})])
def test_syncthing_empty_success_response(monkeypatch, payload, expected):
    # Syncthing mutation endpoints may return an empty HTTP 200, not only 204.
    monkeypatch.setattr(
        adapter.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(payload)
    )
    assert (
        adapter.request("http://127.0.0.1:8384", "test-key", "config/devices", {}, "POST")
        == expected
    )
