"""Create an explicitly synthetic UI example. Never calls a cloud model or reads personal notes."""

import json
import subprocess
import tempfile
from pathlib import Path

from assistant.library import Library
from assistant.literature.contracts import Analysis, Evidence, Heading, Metadata, Outline
from assistant.literature.notes import NoteExporter
from assistant.literature.service import ReadingService

PROJECT = Path(__file__).resolve().parents[1]
DEMO = PROJECT / "runtime/demo"
DEMO.mkdir(parents=True, exist_ok=True)
config_path = DEMO / "config.json"
if not config_path.exists():
    raise SystemExit("先创建本地 runtime/demo/config.json；此脚本不接受个人配置路径")
config = json.loads(config_path.read_text())
root = Path(config["library"]).resolve()
if not root.is_relative_to(DEMO.resolve()):
    raise SystemExit("演示脚本只能操作 runtime/demo 内的合成资料库")
records = Path(tempfile.gettempdir()) / "shenqingti-demo-records"
if not (records / ".git").exists():
    records.mkdir(parents=True, exist_ok=True)
    if any(records.iterdir()):
        raise SystemExit("演示记录目录已有非 Git 数据，未覆盖")
    subprocess.run(["git", "init", "-b", "main", str(records)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(records), "config", "user.name", "Demo User"], check=True)
    subprocess.run(
        ["git", "-C", str(records), "config", "user.email", "demo@example.invalid"], check=True
    )
config.setdefault("literature", {})["records_root"] = str(records)
config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2))
source = root / "Books/合成文献阅读示例.md"
source.parent.mkdir(parents=True, exist_ok=True)
source.write_text(
    """# 合成示例：文献阅读流程（非真实论文）

此文件仅用于测试，不代表真实研究结论。

## 1. Background

本示例研究如何将一篇文献整理为可追溯的阅读笔记。

## 2. Methods

将原文分节，保留来源位置，对每一节分别提炼方法、结果与讨论。

## 3. Results

测试流程生成五列主题表和逐节笔记，个人想法保留在独立区域。

## 4. Discussion

示例不能证明真实论文的分析质量，图片、公式和真实模型效果仍需核验。
""",
    encoding="utf-8",
)


class SyntheticGateway:
    def readiness(self, settings):
        return {"ready": True, "missing": []}

    def generate(self, settings, instructions, payload, contract):
        blocks = payload["source_blocks"]
        if contract is Outline:
            headings = [
                Heading(title=b["text"].lstrip("# "), block_id=b["id"])
                for b in blocks
                if b["text"].startswith("## ")
            ]
            return Outline(
                metadata=Metadata(
                    title="合成示例：文献阅读流程（非真实论文）",
                    authors=["本地测试适配器"],
                    venue="合成演示",
                ),
                headings=headings,
                limitations=["此条由本地测试适配器生成，未调用云端模型，不是真实论文分析。"],
            ), {}
        quoted = next((b for b in blocks if not b["text"].startswith("#")), blocks[0])
        title = payload["section_title"]
        values = {"evidence": [Evidence(block_id=quoted["id"], quote=quoted["text"])]}
        if "Background" in title:
            values["background"] = ["用合成资料演示按原文小标题组织阅读笔记。"]
        elif "Methods" in title:
            values["methods"] = ["提取来源块，按小标题分组；引用必须能回到输入原文。"]
        elif "Results" in title:
            values["results"] = ["演示产物包括五列主题总表和详细 Markdown 笔记。"]
        elif "Discussion" in title:
            values["author_discussion"] = ["合成示例不构成科学证据。"]
            values["assistant_analysis"] = ["真实文献仍需人工核对图像、公式及推论。"]
            values["suggested_questions"] = ["这份笔记是否清楚地区分了来源、解释与个人想法？"]
        return Analysis(**values), {}


library = Library(root, config["database"])
library.scan()
service = ReadingService(library, config.get("literature", {}), SyntheticGateway())
original = service.store.settings()
try:
    service.store.save_settings(
        {"provider": "openai", "model": "synthetic-fixture-not-a-cloud-model"}
    )
    document = next(
        d for d in library.documents() if d["path"] == source.relative_to(root).as_posix()
    )
    job = service.create(document["id"], "功能演示（合成数据）")
    if job["status"] != "completed":
        service.run_next()
    job = service.store.get_job(job["id"])
    if job["status"] != "completed":
        raise SystemExit("演示任务失败：" + job["error"])
    saved = NoteExporter(service.store, records).save(job)
    print("已创建明确标识的合成演示；未调用云端模型、未读取或修改真实个人笔记。")
    print("演示笔记仓库：", records)
    print("Git 保存：", not saved["version_pending"])
finally:
    service.store.save_settings(original)
