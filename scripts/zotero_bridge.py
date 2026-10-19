"""Run on a desktop that creates Zotero attachments, without keeping a chat open."""

import argparse
import json
import time
from pathlib import Path

from assistant.library import Library
from assistant.zotero import ZoteroBridge


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
    # Paths must be explicit so the daemon cannot accidentally mirror the wrong directory.
    if not all(Path(config[key]).is_absolute() for key in ("library", "database")):
        parser.error("桥接配置 library、database 必须使用本机绝对路径")
    library = Library(config["library"], config["database"])
    bridge = ZoteroBridge(library, config.get("zotero", {}))
    while True:
        result = bridge.sync()
        print(result["message"], flush=True)
        for item in result["items"]:
            if item.get("state") in {"error", "waiting"}:
                print(item["key"], item["message"], flush=True)
        if not args.watch:
            break
        time.sleep(max(30, config.get("zotero", {}).get("interval_seconds", 60)))


if __name__ == "__main__":
    main()
