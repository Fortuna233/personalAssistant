"""Configure an already installed Syncthing through its LOCAL authenticated API.

Only explicitly named new folders are created; existing folders are never overwritten.
"""

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def request(base, key, route, body=None, method=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        base + "/rest/" + route,
        data=data,
        method=method,
        headers={"X-API-Key": key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        payload = response.read()
        return json.loads(payload) if payload else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="非 Git 资料目录（Media）")
    parser.add_argument("--records-root", required=True, help="独立个人 Git 仓库根目录")
    parser.add_argument(
        "--device", action="append", default=[], help="DEVICE-ID=NAME=IP; may repeat"
    )
    parser.add_argument("--url", default="http://127.0.0.1:8384")
    args = parser.parse_args()
    parsed = urllib.parse.urlparse(args.url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("管理 API 只允许本机访问")
    key = os.environ.get("SYNCTHING_API_KEY")
    if not key:
        parser.error("请在本机设置 SYNCTHING_API_KEY 环境变量；不要写入 Git")
    base = args.url.rstrip("/")
    config = request(base, key, "config")
    requested = []
    existing_ids = {d["deviceID"] for d in config["devices"]}
    for specification in args.device:
        device_id, name, address = specification.split("=", 2)
        requested.append({"deviceID": device_id})
        if device_id not in existing_ids:
            request(
                base,
                key,
                "config/devices",
                {
                    "deviceID": device_id,
                    "name": name,
                    "addresses": ["tcp://" + address + ":22000"],
                    "autoAcceptFolders": False,
                },
                "POST",
            )
    root = Path(args.root).resolve()
    existing_folders = {f["id"] for f in config["folders"]}
    occupied_paths = {str(Path(f["path"]).resolve()) for f in config["folders"]}
    records = Path(args.records_root).resolve()
    if records == root or records.is_relative_to(root) or root.is_relative_to(records):
        parser.error("记录仓库与资料目录必须互不嵌套")
    for folder_id, name, path in [
        ("study-notes", "Records", records),
        ("study-media", "Media", root),
    ]:
        if folder_id in existing_folders:
            existing = next(f for f in config["folders"] if f["id"] == folder_id)
            if Path(existing["path"]).resolve() != path:
                raise SystemExit("已有同步集合路径与新目录不同，请按迁移文档检查：" + folder_id)
            shared = {d["deviceID"] for d in existing["devices"]}
            additions = [d for d in requested if d["deviceID"] not in shared]
            if additions:
                request(
                    base,
                    key,
                    "config/folders/" + folder_id,
                    {"devices": existing["devices"] + additions},
                    "PATCH",
                )
            print("保留已有配置：", folder_id)
            continue
        if any(
            path == Path(p) or path.is_relative_to(Path(p)) or Path(p).is_relative_to(path)
            for p in occupied_paths
        ):
            raise SystemExit("目录已由其他同步集合管理，请先人工检查：" + str(path))
        path.mkdir(parents=True, exist_ok=True)
        devices = [{"deviceID": request(base, key, "system/status")["myID"]}] + requested
        folder = request(base, key, "config/defaults/folder")
        folder.update(
            {
                "id": folder_id,
                "label": name,
                "path": str(path),
                "type": "sendreceive",
                "devices": devices,
                "rescanIntervalS": 60,
                "fsWatcherEnabled": True,
                "versioning": {"type": "staggered", "params": {"maxAge": "31536000"}},
            }
        )
        request(base, key, "config/folders", folder, "POST")
        rules = [".DS_Store", "Thumbs.db", ".git", ".obsidian", ".trash", ".study-trash"]
        request(base, key, "db/ignores?folder=" + folder_id, {"ignore": rules}, "POST")
        print("创建同步集合：", folder_id, path)
    options = config["options"]
    options.update(
        {
            "globalAnnounceEnabled": False,
            "localAnnounceEnabled": True,
            "relaysEnabled": False,
            "natEnabled": False,
            "listenAddresses": ["tcp://0.0.0.0:22000"],
        }
    )
    request(base, key, "config/options", options, "PATCH")
    print("已禁用公网发现、中继与 NAT 映射；请在其他设备按文档配置相同选项。")
    print("需要重启：", request(base, key, "config/restart-required"))


if __name__ == "__main__":
    main()
