"""Offline evaluation of exact clause evidence against a local reviewable benchmark.

Real excerpts belong only in a Git-ignored local benchmark file. Reports contain
counts and identifiers, never quotes or document text. This is not a live model path.
"""

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.clause_discovery import ClauseCandidate, ClauseKind, discover_clauses, plan_batches
from app.document_manifest import AnchorError, DocumentManifest


class BenchmarkError(ValueError):
    """Content-free benchmark validation failure."""


class GoldEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    passage_id: str
    page_number: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    excerpt: str = Field(min_length=12, max_length=6000)


class GoldClause(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    target_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    title: str = Field(min_length=1, max_length=160)
    category: str = Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")
    kind: ClauseKind
    evidence: list[GoldEvidence] = Field(min_length=1, max_length=6)
    dependencies: list[Literal["policy_schedule", "endorsement", "other_clause"]] = Field(
        default_factory=list, max_length=10
    )
    qualifications: str = Field(max_length=1000)
    actionable_rule_supported: bool
    manual_review_status: Literal["pending", "approved", "rejected"]


class LocalBenchmark(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    benchmark_version: str
    source_pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    physical_page_count: int = Field(ge=1)
    canonical_text_characters: int = Field(ge=0)
    manual_review_required: bool
    items: list[GoldClause] = Field(min_length=1)


@dataclass(frozen=True)
class BenchmarkPrediction:
    candidate: dict
    target_id: str | None = None
    expected_supported: bool = True


@dataclass(frozen=True)
class BenchmarkMetrics:
    gold_targets: int
    validated_gold_anchors: int
    pending_manual_review: int
    approved_targets: int
    provisional_recalled_targets: int
    approved_recalled_targets: int | None
    predictions: int
    exact_evidence_accepted: int
    correct_passage_associations: int
    targeted_predictions: int
    rejected_candidates: int
    rejected_by_reason: dict[str, int]
    unsupported_candidates_rejected: int
    unsupported_candidates_total: int
    duplicate_candidates: int
    unsafe_rule_attempts: int
    incorrect_actionable_rules_retained: int
    missing_primary_passages: int
    unprocessed_passages: int
    unprocessed_characters: int
    incomplete_sections: int
    accounted_coverage_percent: float

    def safe_report(self) -> dict:
        return asdict(self)


def load_local_benchmark(path: Path) -> LocalBenchmark:
    """Hide schema-validation details because they may contain real excerpts."""
    try:
        return LocalBenchmark.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError):
        raise BenchmarkError("Local benchmark could not be read or validated") from None


def validate_gold(
    manifest: DocumentManifest, benchmark: LocalBenchmark, *, pdf_bytes: bytes | None = None
) -> int:
    if (
        pdf_bytes is not None
        and hashlib.sha256(pdf_bytes).hexdigest() != benchmark.source_pdf_sha256
    ):
        raise BenchmarkError("Benchmark PDF fingerprint differs")
    if (
        len(manifest.pages) != benchmark.physical_page_count
        or manifest.total_characters != benchmark.canonical_text_characters
    ):
        raise BenchmarkError("Benchmark extraction metadata differs")
    if len({item.target_id for item in benchmark.items}) != len(benchmark.items):
        raise BenchmarkError("Benchmark target IDs are duplicated")
    anchors = 0
    for item in benchmark.items:
        for source in item.evidence:
            try:
                anchor = manifest.anchor(source.passage_id, source.excerpt)
            except AnchorError:
                raise BenchmarkError("A benchmark evidence anchor failed") from None
            if (anchor.page_number, anchor.start, anchor.end) != (
                source.page_number,
                source.start,
                source.end,
            ):
                raise BenchmarkError("A benchmark page or offset differs")
            anchors += 1
    return anchors


def _gold_key(item: GoldClause) -> tuple:
    return tuple(sorted((e.passage_id, e.start, e.end) for e in item.evidence))


def _clause_key(clause) -> tuple:
    return tuple(sorted((e.passage_id, e.start, e.end) for e in clause.evidence))


def evaluate_benchmark(
    manifest: DocumentManifest,
    benchmark: LocalBenchmark,
    predictions: list[BenchmarkPrediction],
    *,
    pdf_bytes: bytes | None = None,
) -> BenchmarkMetrics:
    anchors = validate_gold(manifest, benchmark, pdf_bytes=pdf_bytes)
    plan = plan_batches(manifest)
    result = discover_clauses(manifest, [prediction.candidate for prediction in predictions])
    gold_by_id = {item.target_id: item for item in benchmark.items}
    supported_rejected = 0
    evidence_accepted = 0
    associated = 0
    targeted = 0
    unsupported_total = 0
    unsafe_rule_attempts = 0
    for prediction in predictions:
        candidate = prediction.candidate
        if candidate.get("rule") is not None or candidate.get("actionable_rule") is not None:
            unsafe_rule_attempts += 1
        single = discover_clauses(manifest, [candidate])
        evidence_accepted += bool(single.clauses)
        if not prediction.expected_supported:
            unsupported_total += 1
            supported_rejected += not bool(single.clauses)
        if prediction.target_id in gold_by_id:
            targeted += 1
            try:
                parsed = ClauseCandidate.model_validate(candidate)
            except ValidationError:
                continue
            expected = {source.passage_id for source in gold_by_id[prediction.target_id].evidence}
            associated += {source.passage_id for source in parsed.evidence} == expected

    recalled = {
        item.target_id
        for item in benchmark.items
        if item.manual_review_status != "rejected"
        and any(
            clause.category == item.category
            and clause.kind == item.kind
            and _clause_key(clause) == _gold_key(item)
            for clause in result.clauses
        )
    }
    approved = {
        item.target_id for item in benchmark.items if item.manual_review_status == "approved"
    }
    primary_ids = {p.id for batch in plan.batches for p in batch.primary_passages}
    skipped_ids = {p.passage_id for p in plan.skipped}
    missing_ids = {p.id for p in manifest.passages} - primary_ids - skipped_ids
    incomplete_sections = sum(
        section.total_characters != section.primary_characters + section.skipped_characters
        for section in plan.sections
    )
    incorrect_rules = sum(
        getattr(clause, "rule", None) is not None
        and not any(
            item.actionable_rule_supported and _clause_key(clause) == _gold_key(item)
            for item in benchmark.items
        )
        for clause in result.clauses
    )
    return BenchmarkMetrics(
        gold_targets=len(benchmark.items),
        validated_gold_anchors=anchors,
        pending_manual_review=sum(i.manual_review_status == "pending" for i in benchmark.items),
        approved_targets=len(approved),
        provisional_recalled_targets=len(recalled),
        approved_recalled_targets=len(recalled & approved) if approved else None,
        predictions=len(predictions),
        exact_evidence_accepted=evidence_accepted,
        correct_passage_associations=associated,
        targeted_predictions=targeted,
        rejected_candidates=result.rejected_count,
        rejected_by_reason=result.rejected_by_reason,
        unsupported_candidates_rejected=supported_rejected,
        unsupported_candidates_total=unsupported_total,
        duplicate_candidates=result.duplicate_count,
        unsafe_rule_attempts=unsafe_rule_attempts,
        incorrect_actionable_rules_retained=incorrect_rules,
        missing_primary_passages=len(missing_ids),
        unprocessed_passages=len(plan.skipped),
        unprocessed_characters=plan.skipped_characters,
        incomplete_sections=incomplete_sections,
        accounted_coverage_percent=plan.accounted_coverage_percent,
    )


def oracle_mock_predictions(benchmark: LocalBenchmark) -> list[BenchmarkPrediction]:
    """Plumbing self-check only: built from gold, so recall is not model accuracy."""
    predictions = [
        BenchmarkPrediction(
            target_id=item.target_id,
            candidate={
                "title": item.title,
                "category": item.category,
                "kind": item.kind,
                "evidence": [
                    {"passage_id": source.passage_id, "excerpt": source.excerpt}
                    for source in item.evidence
                ],
                "dependencies": [{"kind": kind} for kind in item.dependencies],
            },
        )
        for item in benchmark.items
    ]
    first = predictions[0]
    predictions.append(first)
    altered = {
        **first.candidate,
        "evidence": [
            {
                **first.candidate["evidence"][0],
                "excerpt": first.candidate["evidence"][0]["excerpt"] + "\x00",
            }
        ],
    }
    predictions.append(BenchmarkPrediction(altered, expected_supported=False))
    predictions.append(
        BenchmarkPrediction(
            {**first.candidate, "rule": {"amount_paise": 1}}, expected_supported=False
        )
    )
    other_passage = next(
        (
            item.evidence[0].passage_id
            for item in benchmark.items[1:]
            if item.evidence[0].passage_id != benchmark.items[0].evidence[0].passage_id
        ),
        None,
    )
    if other_passage is not None:
        wrong = {
            **first.candidate,
            "evidence": [{**first.candidate["evidence"][0], "passage_id": other_passage}],
        }
        predictions.append(
            BenchmarkPrediction(wrong, target_id=first.target_id, expected_supported=False)
        )
    return predictions
