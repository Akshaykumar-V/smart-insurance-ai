from typing import Literal

from pydantic import BaseModel, Field

DocumentType = Literal["policy_wording", "policy_schedule", "cis", "endorsement", "other"]


class UploadResponse(BaseModel):
    policy_id: str
    document_id: str
    job_id: str
    status: Literal["queued"] = "queued"


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
