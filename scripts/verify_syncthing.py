import argparse
import importlib.util
import socket
import sys
import os
from pathlib import Path
import subprocess
import tempfile
import time
from xml.etree import ElementTree as ET

parser = argparse.ArgumentParser(
    description="Verify real Syncthing with two disposable local instances; no personal files are read."
)
parser.add_argument("--binary", required=True)
binary = str(Path(parser.parse_args().binary).resolve())
project = Path(__file__).resolve().parents[1]
for port in (18384, 18385, 22000, 22001):
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            raise SystemExit(f"Test port {port} occupied; stop temporary services before testing.")
spec = importlib.util.spec_from_file_location("sync_adapter", project / "scripts/configure_sync.py")
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
root = Path(tempfile.mkdtemp(prefix="study-sync-integration-"))
processes = []
try:
    nodes = []
    for index in range(2):
        home = root / f"node{index}"
        subprocess.run(
            [binary, "generate", "--home", str(home)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        tree = ET.parse(home / "config.xml")
        xml = tree.getroot()
        for folder in xml.findall("folder"):
            xml.remove(folder)
        options = xml.find("options")
        for name, value in {
            "globalAnnounceEnabled": "false",
            "localAnnounceEnabled": "false",
            "relaysEnabled": "false",
            "natEnabled": "false",
            "startBrowser": "false",
            "autoUpgradeIntervalH": "0",
            "urAccepted": "-1",
            "crashReportingEnabled": "false",
        }.items():
            element = options.find(name)
            if element is not None:
                element.text = value
        for element in options.findall("listenAddress"):
            options.remove(element)
        ET.SubElement(options, "listenAddress").text = f"tcp://127.0.0.1:{22000 + index}"
        xml.find("gui/address").text = f"127.0.0.1:{18384 + index}"
        key = xml.find("gui/apikey").text
        tree.write(home / "config.xml", encoding="utf-8", xml_declaration=True)
        log = (root / f"node{index}.log").open("w")
        process = subprocess.Popen(
            [binary, "serve", "--home", str(home), "--no-browser", "--no-restart"],
            env={**os.environ, "STNOUPGRADE": "1"},
            stdout=log,
            stderr=log,
        )
        processes.append(process)
        base = f"http://127.0.0.1:{18384 + index}"
        for attempt in range(100):
            try:
                status = adapter.request(base, key, "system/status")
                break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError("Temporary Syncthing did not start")
        nodes.append((base, key, status["myID"]))
    a, b = nodes
    # Configure twice and verify no duplicated folders; all data lives in temporary directories.
    command = [
        sys.executable,
        str(project / "scripts/configure_sync.py"),
        "--root",
        str(root / "library"),
        "--url",
        a[0],
        "--device",
        b[2] + "=TestPeer=127.0.0.1",
    ]
    env = {**os.environ, "SYNCTHING_API_KEY": a[1]}
    subprocess.run(command, env=env, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(command, env=env, check=True, stdout=subprocess.DEVNULL)
    config = adapter.request(a[0], a[1], "config")
    assert len(config["folders"]) == 3
    assert not config["options"]["globalAnnounceEnabled"]
    assert not config["options"]["relaysEnabled"]
    assert all(f["versioning"]["type"] == "staggered" for f in config["folders"])
    assert ".obsidian" in adapter.request(a[0], a[1], "db/ignores?folder=study-notes")["ignore"]
    adapter.request(
        a[0], a[1], "config/devices/" + b[2], {"addresses": ["tcp://127.0.0.1:22001"]}, "PATCH"
    )
    peer = adapter.request(b[0], b[1], "config/defaults/device")
    peer.update({"deviceID": a[2], "name": "TestHub", "addresses": ["tcp://127.0.0.1:22000"]})
    adapter.request(b[0], b[1], "config/devices", peer, "POST")
    folder = adapter.request(b[0], b[1], "config/defaults/folder")
    folder.update(
        {
            "id": "study-notes",
            "label": "Notes",
            "path": str(root / "peer-notes"),
            "type": "sendreceive",
            "devices": [{"deviceID": a[2]}, {"deviceID": b[2]}],
            "rescanIntervalS": 1,
        }
    )
    adapter.request(b[0], b[1], "config/folders", folder, "POST")
    source = root / "library/Notes/实验同步.md"
    source.write_text("Mac-like edit", encoding="utf-8")
    adapter.request(a[0], a[1], "db/scan?folder=study-notes", {}, "POST")
    target = root / "peer-notes/实验同步.md"
    for attempt in range(200):
        if target.exists() and target.read_text() == "Mac-like edit":
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("Forward sync timeout")
    target.write_text("Android-like edit", encoding="utf-8")
    adapter.request(b[0], b[1], "db/scan?folder=study-notes", {}, "POST")
    for attempt in range(200):
        if source.read_text() == "Android-like edit":
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("Reverse sync timeout")
    print(
        "PASS: real Syncthing; repeat-safe configuration, LAN-only options, versioning, ignores, bidirectional file transfer"
    )
finally:
    for process in processes:
        process.terminate()
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
