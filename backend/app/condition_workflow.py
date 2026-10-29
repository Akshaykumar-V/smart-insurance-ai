"""Offline, review-only passage discovery workflow for mocked Responses output.

This module has no provider client, persistence, or API route. It does not change
the live v0.1 extractor or turn a discovered clause into a claim calculation.
"""

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.clause_discovery import BatchPlan, DiscoveredClause, discover_clauses
from app.clause_discovery import plan_batches as build_batch_plan
from app.document_manifest import DocumentManifest, build_manifest
from app.models import ExtractedPage

MAX_RESPONSE_BYTES = 1_000_000
MAX_CANDIDATES_PER_BATCH = 32

# These are exact substrings of verified evidence, not interpreted policy limits.
_VALUE_MENTION = re.compile(
    r"(?<![\w.])\d+(?:\.\d+)?\s*%"
    r"|\b(?:INR|Rs\.?)\s*[\d,]+(?:\.\d+)?"
    r"|₹\s*[\d,]+(?:\.\d+)?"
    r"|\b\d+(?:\.\d+)?\s*(?:days?|months?|years?)\b",
    re.I,
)


class InvalidDiscoveryOutput(ValueError):
    """Content-free failure for malformed or incomplete mocked provider output."""


@dataclass(frozen=True)
class PreparedConditionDocument:
    document_id: str
    manifest: DocumentManifest
    plan: BatchPlan


@dataclass(frozen=True)
class ReviewCondition:
    id: str
    document_id: str
    clause: DiscoveredClause
    observed_value_mentions: tuple[str, ...]

    @property
    def review_status(self) -> str:
        return "needs_review"


@dataclass(frozen=True)
class ConditionDiscoveryReport:
    conditions: tuple[ReviewCondition, ...]
    rejected_count: int
    rejected_by_reason: dict[str, int]
    duplicate_count: int
    processed_batches: int
    planned_batches: int
    failed_batches: int
    skipped_passages: int
    incomplete: bool
    warning: str | None


def prepare_condition_document(
    document_id: str, pages: list[ExtractedPage], **batch_limits: int
) -> PreparedConditionDocument:
    """Index the original extracted pages without changing their canonical text."""
    if not document_id:
        raise ValueError("Document ID is required")
    manifest = build_manifest(pages)
    return PreparedConditionDocument(
        document_id, manifest, build_batch_plan(manifest, **batch_limits)
    )


def _mocked_candidates(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Read the same completed structured-output envelope as the current provider."""
    try:
        if len(json.dumps(body, ensure_ascii=False).encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise ValueError
        if body["status"] != "completed":
            raise ValueError
        blocks = [
            block
            for item in body["output"]
            if item.get("type") == "message"
            for block in item.get("content", [])
        ]
        if any(block.get("type") == "refusal" for block in blocks):
            raise ValueError
        texts = [block["text"] for block in blocks if block.get("type") == "output_text"]
        if len(texts) != 1:
            raise ValueError
        payload = json.loads(texts[0])
        if (
            not isinstance(payload, dict)
            or set(payload) != {"candidates"}
            or not isinstance(payload["candidates"], list)
            or len(payload["candidates"]) > MAX_CANDIDATES_PER_BATCH
            or any(not isinstance(item, dict) for item in payload["candidates"])
        ):
            raise ValueError
        return payload["candidates"]
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
        raise InvalidDiscoveryOutput("Mocked discovery output is invalid") from None


def evaluate_mocked_batches(
    prepared: PreparedConditionDocument, responses_by_batch: dict[str, dict[str, Any]]
) -> ConditionDiscoveryReport:
    """Verify exact evidence in every supplied batch; missing batches remain incomplete."""
    known_ids = {batch.id for batch in prepared.plan.batches}
    if set(responses_by_batch) - known_ids:
        raise ValueError("Unknown discovery batch")
    conditions: list[ReviewCondition] = []
    reasons: Counter[str] = Counter()
    seen: set[str] = set()
    processed = failed = duplicates = 0
    for batch in prepared.plan.batches:
        if batch.id not in responses_by_batch:
            continue
        try:
            candidates = _mocked_candidates(responses_by_batch[batch.id])
        except InvalidDiscoveryOutput:
            failed += 1
            continue
        processed += 1
        result = discover_clauses(prepared.manifest, candidates, batch=batch)
        reasons.update(result.rejected_by_reason)
        duplicates += result.duplicate_count
        for clause in result.clauses:
            condition_id = hashlib.sha256(
                f"{prepared.document_id}\x1f{clause.id}".encode("utf-8")
            ).hexdigest()[:20]
            if condition_id in seen:
                duplicates += 1
                continue
            seen.add(condition_id)
            # Values are copied only from backend-verified source spans.
            mentions = tuple(
                match.group()
                for evidence in clause.evidence
                for match in _VALUE_MENTION.finditer(evidence.quote)
            )
            conditions.append(
                ReviewCondition(f"condition_{condition_id}", prepared.document_id, clause, mentions)
            )
    incomplete = (
        processed != len(prepared.plan.batches)
        or failed > 0
        or bool(prepared.plan.skipped)
        or bool(reasons)
        or not conditions
    )
    warning = None
    if incomplete:
        warning = (
            f"Analysis incomplete: {sum(reasons.values())} rejected candidates, "
            f"{failed} failed batches, "
            f"{len(prepared.plan.batches) - processed - failed} unprocessed batches, "
            f"{len(prepared.plan.skipped)} unreadable passages. "
            "No result establishes the absence of limits, exclusions, or restrictions."
        )
    return ConditionDiscoveryReport(
        tuple(conditions),
        sum(reasons.values()),
        dict(sorted(reasons.items())),
        duplicates,
        processed,
        len(prepared.plan.batches),
        failed,
        len(prepared.plan.skipped),
        incomplete,
        warning,
    )
