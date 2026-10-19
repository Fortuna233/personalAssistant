"""Local-device selective reception. Never delete files or distribute Git internals."""

import os
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field


START = "# assistant-selective:start"
END = "# assistant-selective:end"


def merge_ignores(existing, excluded):
    if existing.count(START) != existing.count(END) or existing.count(START) > 1:
        raise ValueError("已有选择性同步标记损坏，请人工检查")
    rules = list(existing)
    if START in rules:
        start, end = rules.index(START), rules.index(END)
        if start > end:
            raise ValueError("已有选择性同步标记顺序错误")
        del rules[start : end + 1]
    # Put managed exclusions first; earlier user negations must not override the selection.
    return [START, *["/" + path for path in sorted(set(excluded))], END, *rules]


def candidates(library):
    # Only leaves are optional: selecting a whole directory could suppress new unseen files.
    return sorted(doc["path"] for doc in library.documents() if doc["kind"] in {".pdf", ".epub"})


class SyncSelection:
    def __init__(self, library, config=None, transport=None):
        self.library = library
        self.config = dict(config or {})
        self.config.setdefault("excluded_file", str(library.database) + ".sync-selection")
        self.transport = transport

    def status(self):
        excluded = []
        if self.config.get("excluded_file"):
            path = Path(self.config["excluded_file"])
            if path.is_file():
                excluded = path.read_text(encoding="utf-8").splitlines()
        return {
            "candidates": candidates(self.library),
            "excluded": excluded,
            "available": bool(os.environ.get("SYNCTHING_API_KEY")),
        }

    def apply(self, excluded):
        allowed = set(candidates(self.library))
        for path in excluded:
            if path not in allowed or any(c in path for c in "*?[]{}!#\n\r\\"):
                raise ValueError("只能选择资料库中路径不含通配符的 PDF、EPUB 文件")
            self.library.resolve(path)
        key = os.environ.get("SYNCTHING_API_KEY")
        if not key:
            raise ValueError(
                "请在本机设置 SYNCTHING_API_KEY 后使用；手机可在 Syncthing 中配置忽略规则"
            )
        folder_id = self.config.get("media_folder_id", "study-media")
        if not folder_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError("同步集合 ID 不合法")
        with httpx.Client(transport=self.transport, timeout=20) as client:
            base = "http://127.0.0.1:8384/rest"
            headers = {"X-API-Key": key}
            folder = client.get(f"{base}/config/folders/{folder_id}", headers=headers)
            folder.raise_for_status()
            if Path(folder.json()["path"]).resolve() != self.library.root:
                raise ValueError("本机 Syncthing 资料目录与助手不一致，未修改")
            response = client.get(
                f"{base}/db/ignores", params={"folder": folder_id}, headers=headers
            )
            response.raise_for_status()
            rules = merge_ignores(response.json().get("ignore", []), excluded)
            response = client.post(
                f"{base}/db/ignores",
                params={"folder": folder_id},
                headers=headers,
                json={"ignore": rules},
            )
            response.raise_for_status()
        path = Path(
            self.config.get("excluded_file", str(self.library.database) + ".sync-selection")
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(excluded), encoding="utf-8")
        self.config["excluded_file"] = str(path)
        return {"message": "已应用到本机；未删除现有文件。其他设备需各自设置。"}


class ZoteroSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    kind: str = "users"
    library_id: str = "0"


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    excluded: list[str] = Field(default_factory=list, max_length=20000)


def create_sync_router(library, records_root, config, auth, bridge):
    router = APIRouter(prefix="/api/sync", dependencies=[Depends(auth)])
    selection = SyncSelection(library, config.get("sync", {}))

    @router.get("/storage")
    def storage():
        return {
            "records_root": str(records_root or "尚未配置"),
            "media_root": str(library.root),
            "git_sync": False,
            "selection": selection.status(),
        }

    @router.post("/selection")
    def choose(body: Selection):
        try:
            return selection.apply(body.excluded)
        except (ValueError, OSError, httpx.HTTPError) as exc:
            raise HTTPException(
                422,
                "Syncthing 本机 API 不可用，请确认程序与管理密钥。"
                if isinstance(exc, httpx.HTTPError)
                else str(exc)[:300],
            ) from None

    @router.get("/zotero")
    def status():
        return bridge.status()

    @router.put("/zotero")
    def settings(body: ZoteroSettings):
        try:
            return bridge.configure(body.model_dump())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.post("/zotero/run")
    def sync():
        try:
            value = bridge.sync()
            library.scan()
            return value
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    return router
