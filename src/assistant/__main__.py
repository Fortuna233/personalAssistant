import argparse
import json
from pathlib import Path

import uvicorn

from .app import create_app

parser = argparse.ArgumentParser(description="沈轻媞")
parser.add_argument("--config", default="config/local.json")
args = parser.parse_args()
config_path = Path(args.config).resolve()
config = json.loads(config_path.read_text(encoding="utf-8-sig"))
for field in ("library", "database"):
    path = Path(config[field])
    if not path.is_absolute():
        config[field] = str(config_path.parent.parent / path)
records_root = config.get("literature", {}).get("records_root")
if records_root and not Path(records_root).is_absolute():
    config["literature"]["records_root"] = str(config_path.parent.parent / records_root)
uvicorn.run(create_app(config), host=config.get("host", "127.0.0.1"), port=config.get("port", 8765))
