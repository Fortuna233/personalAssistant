"""Take a consistent SQLite backup and a dated file snapshot OUTSIDE the sync tree."""

import argparse
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--config", default="config/local.json")
parser.add_argument("--destination", required=True)
args = parser.parse_args()
config_path = Path(args.config).resolve()
config = json.loads(config_path.read_text(encoding="utf-8-sig"))
base = config_path.parent.parent
library = (base / config["library"]).resolve()
database = (base / config["database"]).resolve()
destination = Path(args.destination).resolve()
if destination == library or destination.is_relative_to(library):
    raise SystemExit("备份目录必须在同步资料库之外")
snapshot = destination / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
snapshot.mkdir(parents=True)
with (
    sqlite3.connect(str(database)) as source,
    sqlite3.connect(str(snapshot / "assistant.db")) as target,
):
    source.backup(target)
shutil.copytree(library, snapshot / "library", ignore=shutil.ignore_patterns(".stversions", ".git"))
print(snapshot)
