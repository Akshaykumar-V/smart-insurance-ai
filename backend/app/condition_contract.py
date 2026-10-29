"""Provisional, additive condition contract; not wired into the live app."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.clause_discovery import ClauseDependency, ClauseKind
from app.condition_workflow import ConditionDiscoveryReport


class ConditionStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID


class ConditionStartResponse(BaseModel):
    policy_id: str
    document_id: str
    job_id: str
    status: Literal["queued", "processing", "completed", "failed", "needs_review"]


class ConditionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passage_id: str = Field(min_length=1)
    page: int = Field(ge=1, le=200)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=12)


class ConditionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    document_id: str
    job_id: str
    category: str
    kind: ClauseKind
    title: str
    specific_label: str | None
    observed_value_mentions: list[str]
    applicability: str | None
    exceptions: list[str]
    dependencies: list[ClauseDependency]
    evidence: list[ConditionEvidence] = Field(min_length=1, max_length=6)
    source_verified: Literal[True]
    review_required: Literal[True]


class ConditionRunResponse(BaseModel):
    policy_id: str
    document_id: str
    job_id: str
    status: Literal["queued", "processing", "completed", "failed", "needs_review"]
    analysis_state: Literal["complete", "incomplete"] | None
    warning: str | None
    rejected_candidate_count: int = Field(ge=0)
    conditions: list[ConditionItem]


def items_from_report(report: ConditionDiscoveryReport, job_id: str) -> list[ConditionItem]:
    """Only backend-anchored evidence enters the persistence payload."""
    return [
        ConditionItem(
            id=condition.id,
            document_id=condition.document_id,
            job_id=job_id,
            category=condition.clause.category,
            kind=condition.clause.kind,
            title=condition.clause.title,
            specific_label=condition.clause.specific_label,
            observed_value_mentions=list(condition.observed_value_mentions),
            applicability=condition.clause.applicability,
            exceptions=list(condition.clause.exceptions),
            dependencies=list(condition.clause.dependencies),
            evidence=[
                ConditionEvidence(
                    passage_id=evidence.passage_id,
                    page=evidence.page_number,
                    start=evidence.start,
                    end=evidence.end,
                    quote=evidence.quote,
                )
                for evidence in condition.clause.evidence
            ],
            source_verified=True,
            review_required=True,
        )
        for condition in report.conditions
    ]
