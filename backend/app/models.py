from typing import Literal

from pydantic import BaseModel, Field

DocumentType = Literal["policy_wording", "policy_schedule", "cis", "endorsement", "other"]
InsuranceCategory = Literal["health", "life", "vehicle", "animal", "property", "other"]
PolicyType = Literal["individual", "family_floater", "other", "unknown"]
AnalysisStatus = Literal[
    "not_started", "processing", "ready", "needs_review", "failed", "unsupported"
]


class UploadResponse(BaseModel):
    policy_id: str
    document_id: str
    job_id: str
    status: Literal["queued"] = "queued"


class PolicyCard(BaseModel):
    id: str
    category: InsuranceCategory
    policy_type: PolicyType
    insurer: str | None
    product_name: str | None
    sum_insured_paise: int | None
    start_date: str | None
    end_date: str | None
    analysis_status: AnalysisStatus
    needs_review: bool


class PolicyListResponse(BaseModel):
    items: list[PolicyCard]
    next_cursor: str | None = None


class PolicyDocument(BaseModel):
    id: str
    type: DocumentType
    name: str
    page_count: int | None
    processing_status: Literal["uploaded", "extracting", "extracted", "needs_review", "failed"]


class PolicyMember(BaseModel):
    name: str | None
    age: int | None


class PolicyDetails(PolicyCard):
    uin: str | None
    policyholder_name: str | None
    insured_members: list[PolicyMember]
    documents: list[PolicyDocument]


class JobError(BaseModel):
    code: str
    message: str


class JobResponse(BaseModel):
    job_id: str
    policy_id: str
    status: Literal["queued", "processing", "completed", "failed", "needs_review"]
    stage: Literal[
        "uploaded",
        "extracting",
        "classifying",
        "indexing",
        "retrieving",
        "analyzing",
        "verifying",
        "completed",
    ]
    message: str | None
    error: JobError | None


class ExtractedPage(BaseModel):
    page_number: int = Field(ge=1)
    text: str
    extraction_quality: Literal["text_present", "no_text", "needs_review"]
    method: Literal["pymupdf"] = "pymupdf"


class ParsedPdf(BaseModel):
    page_count: int = Field(ge=1)
    pages: list[ExtractedPage] = []
