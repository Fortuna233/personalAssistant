import hashlib
import io
import re

from .contracts import Metadata
from ..library import epub_chapters


class SourceChanged(ValueError):
    pass


def extract_source(library, document):
    path = library.resolve(document["path"])
    if path.stat().st_size > 80_000_000:
        raise ValueError("文件超过 80MB，请先拆分；不会静默截断全文")
    raw = path.read_bytes()
    revision = hashlib.sha256(raw).hexdigest()
    if revision != document["revision"]:
        raise SourceChanged("原文已修改，请刷新索引后重试")
    metadata = Metadata(title=path.stem)
    blocks, headings, warnings = [], [], []

    def add(text, location):
        # Every nonempty extracted line is retained, with stable source-local IDs.
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            # Overlong extracted lines are split without losing text.
            for start in range(0, len(line), 3000):
                blocks.append(
                    {
                        "id": f"B{len(blocks) + 1:05d}",
                        "text": line[start : start + 3000],
                        "location": location,
                    }
                )

    kind = document["kind"]
    if kind == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise ValueError("加密 PDF 需先在本机解密")
        meta = reader.metadata or {}
        metadata.title = str(meta.get("/Title") or path.stem)
        if meta.get("/Author"):
            metadata.authors = [str(meta["/Author"])]
        empty = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if not text.strip():
                empty.append(i + 1)
            add(text, f"页 {i + 1}")
        warnings.append(
            "当前分析覆盖 PDF 可提取文本；图像、版式和公式未经视觉核验，补充材料只在另行提供后处理。"
        )
        if empty:
            warnings.append("未提取到文字的页：" + "、".join(map(str, empty)) + "；可能需要 OCR。")
    elif kind in {".md", ".txt"}:
        for i, line in enumerate(raw.decode("utf-8-sig", errors="replace").splitlines()):
            start = len(blocks)
            add(line, f"行 {i + 1}")
            if kind == ".md" and re.match(r"^#{1,6}\s+", line) and len(blocks) > start:
                headings.append(
                    {
                        "title": re.sub(r"^#{1,6}\s+", "", line).strip(),
                        "block_id": blocks[start]["id"],
                    }
                )
    elif kind == ".epub":
        # Read the same file snapshot: reject changes during parser access.
        for i, chapter in enumerate(epub_chapters(path)):
            before = len(blocks)
            add(chapter["text"], f"章 {i + 1}")
            if len(blocks) > before:
                headings.append({"title": chapter["title"], "block_id": blocks[before]["id"]})
        if hashlib.sha256(path.read_bytes()).hexdigest() != revision:
            raise SourceChanged("原文在解析期间变化，请重试")
        warnings.append("EPUB 当前只分析提取正文，不含插图和原始版式。")
    else:
        raise ValueError("文献阅读支持 PDF、EPUB、Markdown 和 TXT")
    if not blocks:
        raise ValueError("未提取到可读文本，不能将空文件或扫描件标记为全文已读")
    if sum(len(b["text"]) for b in blocks) > 500_000:
        raise ValueError("全文超过当前 50 万字符处理上限，请拆分；未截断或发往模型")
    doi = re.search(r"10\.\d{4,9}/[^\s<>\"]+", " ".join(b["text"] for b in blocks[:80]))
    if doi:
        metadata.doi = doi.group(0).rstrip(".,;)")
    return {
        "document_id": document["id"],
        "path": document["path"],
        "revision": revision,
        "metadata": metadata.model_dump(),
        "blocks": blocks,
        "headings": headings,
        "warnings": warnings,
    }


def chunks(blocks, max_chars=14000):
    output, current, size = [], [], 0
    for block in blocks:
        cost = len(block["text"]) + 100
        if current and size + cost > max_chars:
            output.append(current)
            current, size = [], 0
        current.append(block)
        size += cost
    if current:
        output.append(current)
    return output


def sections(source, headings):
    blocks = source["blocks"]
    positions = {b["id"]: i for i, b in enumerate(blocks)}
    ordered = sorted(headings, key=lambda h: positions[h["block_id"]])
    unique = {h["block_id"]: h for h in ordered}
    ordered = list(unique.values())
    if not ordered or positions[ordered[0]["block_id"]] != 0:
        ordered.insert(
            0, {"title": "题录与开篇（未识别到原文小标题）", "block_id": blocks[0]["id"]}
        )
    result = []
    for i, heading in enumerate(ordered):
        start = positions[heading["block_id"]]
        stop = positions[ordered[i + 1]["block_id"]] if i + 1 < len(ordered) else len(blocks)
        result.append(
            {"id": f"S{i + 1:03d}", "title": heading["title"], "blocks": blocks[start:stop]}
        )
    return result
