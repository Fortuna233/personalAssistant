from typing import List

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Metadata(Contract):
    title: str = ""
    authors: List[str] = Field(default_factory=list)
    affiliations: List[str] = Field(default_factory=list)
    published_date: str = ""
    venue: str = ""
    doi: str = ""


class Heading(Contract):
    title: str
    block_id: str


class Outline(Contract):
    metadata: Metadata = Field(default_factory=Metadata)
    headings: List[Heading] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class Evidence(Contract):
    block_id: str
    quote: str = Field(min_length=1, max_length=600)


class Analysis(Contract):
    background: List[str] = Field(default_factory=list)
    methods: List[str] = Field(default_factory=list)
    results: List[str] = Field(default_factory=list)
    author_discussion: List[str] = Field(default_factory=list)
    assistant_analysis: List[str] = Field(default_factory=list)
    suggested_questions: List[str] = Field(default_factory=list)
    evidence: List[Evidence] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class Answer(Contract):
    answer: str
    evidence: List[Evidence] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


def normalize(text):
    return "".join(text.split()).casefold()


def validate_evidence(result, blocks):
    source = {block["id"]: block for block in blocks}
    for item in result.evidence:
        if item.block_id not in source or normalize(item.quote) not in normalize(
            source[item.block_id]["text"]
        ):
            raise ValueError("模型引用无法在原文中定位，本步骤未通过验证，可重试")
    if isinstance(result, Analysis):
        claims = result.background + result.methods + result.results + result.author_discussion
        if claims and not result.evidence:
            raise ValueError("模型给出了原文结论但未提供证据，本步骤未通过验证")
    return result
