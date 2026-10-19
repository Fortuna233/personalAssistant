import asyncio
from collections import defaultdict

from . import prompts
from .contracts import Analysis, Answer, Outline, normalize, validate_evidence
from .sources import chunks, extract_source, sections
from .store import ReadingStore
from .models import ModelGateway


class CancelledJob(Exception):
    pass


class ReadingService:
    def __init__(self, library, config, gateway=None):
        self.library = library
        self.store = ReadingStore(library, config.get("model", {}))
        self.gateway = gateway or ModelGateway()
        self.on_complete = None
        self.max_requests = min(max(int(config.get("max_requests", 80)), 1), 200)

    def create(self, document_id, topic, purpose=""):
        topic = topic.strip()
        if not topic or len(topic) > 120 or len(purpose) > 2000:
            raise ValueError("请填写不超过 120 字的主题；阅读目的不超过 2000 字")
        readiness = self.gateway.readiness(self.store.settings())
        if not readiness["ready"]:
            raise ValueError("请配置：" + "、".join(readiness["missing"]))
        source = extract_source(self.library, self.library.document(document_id))
        return self.store.enqueue(source, topic, purpose)

    def question(self, job_id, section_id, text):
        job = self.store.get_job(job_id, True)
        if job["status"] != "completed" or job["kind"] != "read":
            raise ValueError("请先完成全文初稿")
        section = next((s for s in job["result"]["sections"] if s["id"] == section_id), None)
        if not section or not text.strip() or len(text) > 4000:
            raise ValueError("请选择章节并填写不超过 4000 字的问题")
        source = {**job["source"], "blocks": section["blocks"]}
        readiness = self.gateway.readiness(self.store.settings())
        if not readiness["ready"]:
            raise ValueError("请配置：" + "、".join(readiness["missing"]))
        return self.store.enqueue(
            source,
            job["topic"],
            text.strip(),
            "question",
            {"parent_job_id": job_id, "section_id": section_id, "title": section["title"]},
        )

    def call(self, job, key, instruction, payload, contract, validate=None):
        status = self.store.get_job(job["id"])["status"]
        if status != "running":
            raise CancelledJob()
        saved = self.store.step(job["id"], key)
        if saved is not None:
            return contract.model_validate(saved)
        with self.library.connect() as db:
            count = db.execute(
                "SELECT COUNT(*) FROM literature_steps WHERE job_id=?", (job["id"],)
            ).fetchone()[0]
        if count >= self.max_requests:
            raise ValueError("已达到本任务请求上限；已完成步骤保留，未声称全文完成")
        self.store.update(job["id"], progress=payload.get("stage", key))
        instruction = job["capability"]["stages"][key.split(":", 1)[0]]
        instructions = (
            job["capability"]["instructions"]
            + "\n用户阅读偏好：\n"
            + job["capability"]["rules"]
            + "\n"
            + instruction
        )
        result, usage = self.gateway.generate(job["settings"], instructions, payload, contract)
        if validate:
            validate(result)
        self.store.save_step(job["id"], key, result.model_dump(), usage)
        return result

    def execute(self, job):
        if job["capability"].get("workflow_version") != "1":
            raise ValueError("此任务的流程版本不受当前程序支持，未自动切换版本")
        source = job["source"]
        if job["kind"] == "question":
            answers = []
            for i, part in enumerate(chunks(source["blocks"])):
                answer = self.call(
                    job,
                    f"question:{i}",
                    prompts.QUESTION,
                    {
                        "stage": f"回答分段 {i + 1}",
                        "question": job["purpose"],
                        "section": source["question_context"]["title"],
                        "source_blocks": part,
                    },
                    Answer,
                    lambda a: validate_evidence(a, part),
                )
                answers.append(answer.model_dump())
            return {"answers": answers, "context": source["question_context"], "status": "待核对"}
        metadata = {**source["metadata"]}
        headings = list(source["headings"])
        limitations = list(source["warnings"])
        for i, part in enumerate(chunks(source["blocks"])):

            def validate_outline(outline):
                mapping = {b["id"]: b for b in part}
                for h in outline.headings:
                    if h.block_id not in mapping or normalize(h.title) not in normalize(
                        mapping[h.block_id]["text"]
                    ):
                        raise ValueError("模型小标题无法在原文对应位置验证，请重试或检查文字提取")

            outline = self.call(
                job,
                f"outline:{i}",
                prompts.OUTLINE,
                {"stage": f"识别原文小标题 {i + 1}", "first_chunk": i == 0, "source_blocks": part},
                Outline,
                validate_outline,
            )
            if i == 0:
                for key, value in outline.metadata.model_dump().items():
                    if value:
                        metadata[key] = value
            headings.extend(h.model_dump() for h in outline.headings)
            limitations.extend(outline.limitations)
        headings = [
            heading
            for heading in headings
            if normalize(heading["title"]) != normalize(metadata["title"])
        ]
        grouped = sections(source, headings)
        total = len(grouped)
        for index, section in enumerate(grouped):
            analyses = []
            for j, part in enumerate(chunks(section["blocks"])):
                analysis = self.call(
                    job,
                    f"analysis:{section['id']}:{j}",
                    prompts.ANALYZE,
                    {
                        "stage": f"精读 {index + 1}/{total}：{section['title']}",
                        "purpose": job["purpose"],
                        "section_title": section["title"],
                        "part": j + 1,
                        "source_blocks": part,
                    },
                    Analysis,
                    lambda a: validate_evidence(a, part),
                )
                analyses.append(analysis.model_dump())
            merged = defaultdict(list)
            for analysis in analyses:
                for key, value in analysis.items():
                    merged[key].extend(value)
            section["analysis"] = dict(merged)
        with self.library.connect() as db:
            usage = [
                dict(r)
                for r in db.execute(
                    "SELECT step_key,usage FROM literature_steps WHERE job_id=?", (job["id"],)
                )
            ]
        return {
            "metadata": metadata,
            "sections": grouped,
            "limitations": list(dict.fromkeys(limitations)),
            "status": "待核对",
            "user_ideas": "",
            "revision": source["revision"],
            "source_path": source["path"],
            "document_id": source["document_id"],
            "capability": job["capability"],
            "usage": usage,
        }

    def run_next(self):
        job = self.store.claim()
        if job is None:
            return False
        try:
            result = self.execute(job)
            if self.store.get_job(job["id"])["status"] == "running":
                self.store.update(
                    job["id"],
                    status="completed",
                    progress="初稿已生成，待核对",
                    result=result,
                    error="",
                )
                if self.on_complete and job["kind"] == "read":
                    try:
                        result["export"] = self.on_complete(self.store.get_job(job["id"]))
                    except (ValueError, OSError) as exc:
                        result["export"] = {"saved": False, "error": str(exc)[:500]}
                    self.store.update(job["id"], result=result)
        except CancelledJob:
            pass
        except Exception as exc:
            if self.store.get_job(job["id"])["status"] == "running":
                # Model response/transport errors are sanitized in the gateway.
                message = (
                    str(exc)
                    if isinstance(exc, ValueError)
                    else "处理失败，已保存步骤保留；请检查服务日志或重试"
                )
                self.store.update(
                    job["id"],
                    status="failed",
                    error=message[:600],
                    progress="处理失败，可从已保存步骤重试",
                )
        return True

    async def worker(self):
        while True:
            worked = await asyncio.to_thread(self.run_next)
            if not worked:
                await asyncio.sleep(1)
