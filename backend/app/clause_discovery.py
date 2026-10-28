"""Offline passage planning and source-backed clause discovery from mocked candidates.

No provider, database, API, interpretation, or financial-rule integration lives here.
Candidate annotations remain review-only, even when their evidence is exact.
"""

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.document_manifest import AnchorError, DocumentManifest, Passage

ClauseKind = Literal[
    "benefit", "restriction", "condition", "definition", "procedural_requirement", "other"
]
DependencyKind = Literal["policy_schedule", "endorsement", "other_clause"]


class CandidateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    passage_id: str = Field(min_length=1, max_length=64)
    excerpt: str = Field(min_length=1, max_length=6000)


class ClauseDependency(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: DependencyKind
    label: str | None = Field(default=None, max_length=160)


class ClauseCandidate(BaseModel):
    """Mocked discovery output. Descriptions are hypotheses, not verified policy rules."""

    model_config = ConfigDict(extra="forbid", strict=True)

    title: str = Field(min_length=1, max_length=160)
    category: str = Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")
    specific_label: str | None = Field(default=None, max_length=160)
    kind: ClauseKind
    evidence: list[CandidateEvidence] = Field(min_length=1, max_length=6)
    applicability: str | None = Field(default=None, max_length=1000)
    exceptions: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list, max_length=10
    )
    dependencies: list[ClauseDependency] = Field(default_factory=list, max_length=10)
    review_status: Literal["needs_review"] = "needs_review"


@dataclass(frozen=True)
class VerifiedEvidence:
    passage_id: str
    page_number: int
    start: int
    end: int
    quote: str


@dataclass(frozen=True)
class DiscoveredClause:
    id: str
    title: str
    category: str
    specific_label: str | None
    kind: ClauseKind
    evidence: tuple[VerifiedEvidence, ...]
    applicability: str | None
    exceptions: tuple[str, ...]
    dependencies: tuple[ClauseDependency, ...]
    review_status: Literal["needs_review"] = "needs_review"


@dataclass(frozen=True)
class DiscoveryResult:
    clauses: tuple[DiscoveredClause, ...]
    rejected_count: int
    rejected_by_reason: dict[str, int]
    duplicate_count: int


def _readable(passage: Passage, quality: str) -> bool:
    return (
        quality == "text_present"
        and bool(passage.text.strip())
        and "\x00" not in passage.text
        and "\ufffd" not in passage.text
        and not any("\ud800" <= char <= "\udfff" for char in passage.text)
    )


def discover_clauses(
    manifest: DocumentManifest,
    candidates: Iterable[ClauseCandidate | dict],
    *,
    batch: "DiscoveryBatch | None" = None,
) -> DiscoveryResult:
    """Accept only exact, unambiguous primary-passage evidence; return counts, not rejected text."""
    passages = {passage.id: passage for passage in manifest.passages}
    qualities = {page.page_number: page.extraction_quality for page in manifest.pages}
    primary_ids = {passage.id for passage in batch.primary_passages} if batch else None
    allowed_ids = (
        primary_ids | {passage.id for passage in batch.context_passages} if batch else None
    )
    accepted: list[DiscoveredClause] = []
    rejected: Counter[str] = Counter()
    seen: set[tuple] = set()
    duplicates = 0
    for raw in candidates:
        try:
            candidate = ClauseCandidate.model_validate(raw)
        except ValidationError:
            rejected["INVALID_CANDIDATE"] += 1
            continue
        evidence_ids = {item.passage_id for item in candidate.evidence}
        if allowed_ids is not None and not evidence_ids <= allowed_ids:
            rejected["OUT_OF_BATCH"] += 1
            continue
        if primary_ids is not None and not evidence_ids & primary_ids:
            rejected["CONTEXT_ONLY"] += 1
            continue
        verified: list[VerifiedEvidence] = []
        try:
            for item in candidate.evidence:
                passage = passages.get(item.passage_id)
                if passage is None:
                    raise AnchorError("UNKNOWN_PASSAGE")
                if not _readable(passage, qualities[passage.page_number]):
                    raise AnchorError("UNREADABLE_PASSAGE")
                anchor = manifest.anchor(item.passage_id, item.excerpt)
                verified.append(
                    VerifiedEvidence(
                        anchor.passage_id,
                        anchor.page_number,
                        anchor.start,
                        anchor.end,
                        anchor.quote,
                    )
                )
        except AnchorError as error:
            rejected[error.code] += 1
            continue
        verified.sort(key=lambda item: (item.page_number, item.start, item.end))
        span_key = tuple((item.passage_id, item.start, item.end) for item in verified)
        if len(set(span_key)) != len(span_key):
            rejected["DUPLICATE_EVIDENCE"] += 1
            continue
        key = (candidate.category, candidate.specific_label, candidate.kind, span_key)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        digest = hashlib.sha256(
            json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:20]
        accepted.append(
            DiscoveredClause(
                id=f"clause_{digest}",
                title=candidate.title,
                category=candidate.category,
                specific_label=candidate.specific_label,
                kind=candidate.kind,
                evidence=tuple(verified),
                applicability=candidate.applicability,
                exceptions=tuple(candidate.exceptions),
                dependencies=tuple(candidate.dependencies),
            )
        )
    return DiscoveryResult(
        tuple(accepted), sum(rejected.values()), dict(sorted(rejected.items())), duplicates
    )


@dataclass(frozen=True)
class DiscoveryBatch:
    id: str
    primary_passages: tuple[Passage, ...]
    context_passages: tuple[Passage, ...]

    def payload(self) -> dict:
        """Separate context from the passages on which discoveries may be based."""

        def item(passage: Passage) -> dict:
            return {
                "passage_id": passage.id,
                "section_id": passage.section_id,
                "page_number": passage.page_number,
                "start": passage.start,
                "end": passage.end,
                "text": passage.text,
            }

        return {
            "primary_passages": [item(passage) for passage in self.primary_passages],
            "context_passages": [item(passage) for passage in self.context_passages],
        }

    @property
    def payload_bytes(self) -> int:
        return len(
            json.dumps(self.payload(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )


@dataclass(frozen=True)
class SkippedPassage:
    passage_id: str
    section_id: str
    characters: int
    reason: Literal["no_text", "needs_review"]


@dataclass(frozen=True)
class SectionCoverage:
    section_id: str
    total_characters: int
    primary_characters: int
    skipped_characters: int


@dataclass(frozen=True)
class BatchPlan:
    batches: tuple[DiscoveryBatch, ...]
    skipped: tuple[SkippedPassage, ...]
    sections: tuple[SectionCoverage, ...]
    source_characters: int
    primary_characters: int
    skipped_characters: int

    @property
    def accounted_coverage_percent(self) -> float:
        if not self.source_characters:
            return 100.0
        return 100 * (self.primary_characters + self.skipped_characters) / self.source_characters


def _batch(primary: tuple[Passage, ...], context: tuple[Passage, ...] = ()) -> DiscoveryBatch:
    ids = [passage.id for passage in primary], [passage.id for passage in context]
    digest = hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode("utf-8")).hexdigest()[:20]
    return DiscoveryBatch(f"batch_{digest}", primary, context)


def plan_batches(
    manifest: DocumentManifest,
    *,
    max_primary_characters: int = 8000,
    max_payload_bytes: int = 12000,
    max_primary_passages: int = 6,
    context_radius: int = 0,
) -> BatchPlan:
    """Plan bounded, deterministic payloads; context never counts as primary coverage."""
    if (
        max_primary_characters < 1
        or max_payload_bytes < 128
        or max_primary_passages < 1
        or not 0 <= context_radius <= 4
    ):
        raise ValueError("Invalid batch size or context setting")
    qualities = {page.page_number: page.extraction_quality for page in manifest.pages}
    all_passages = manifest.passages
    eligible = [p for p in all_passages if _readable(p, qualities[p.page_number])]
    skipped = tuple(
        SkippedPassage(
            p.id,
            p.section_id,
            len(p.text),
            "no_text" if not p.text.strip() else "needs_review",
        )
        for p in all_passages
        if not _readable(p, qualities[p.page_number])
    )
    batches: list[DiscoveryBatch] = []
    index_by_id = {passage.id: index for index, passage in enumerate(all_passages)}
    cursor = 0
    while cursor < len(eligible):
        primary: list[Passage] = []
        primary_characters = 0
        while cursor < len(eligible) and len(primary) < max_primary_passages:
            passage = eligible[cursor]
            proposed = (*primary, passage)
            if (
                primary_characters + len(passage.text) > max_primary_characters
                or _batch(proposed).payload_bytes > max_payload_bytes
            ):
                break
            primary.append(passage)
            primary_characters += len(passage.text)
            cursor += 1
        if not primary:
            raise ValueError("A primary passage exceeds the configured batch ceiling")

        context: list[Passage] = []
        primary_ids = {passage.id for passage in primary}
        neighbors = [
            index_by_id[primary[0].id] - distance for distance in range(1, context_radius + 1)
        ] + [index_by_id[primary[-1].id] + distance for distance in range(1, context_radius + 1)]
        for index in sorted(neighbors):
            if not 0 <= index < len(all_passages):
                continue
            passage = all_passages[index]
            if passage.id in primary_ids or not _readable(passage, qualities[passage.page_number]):
                continue
            boundary_section = (
                primary[0].section_id
                if index < index_by_id[primary[0].id]
                else primary[-1].section_id
            )
            if passage.section_id != boundary_section:
                continue
            proposed_context = tuple(sorted((*context, passage), key=lambda p: index_by_id[p.id]))
            if _batch(tuple(primary), proposed_context).payload_bytes <= max_payload_bytes:
                context = list(proposed_context)
        batches.append(_batch(tuple(primary), tuple(context)))

    primary_ids = [passage.id for batch in batches for passage in batch.primary_passages]
    skipped_ids = [passage.passage_id for passage in skipped]
    if len(set((*primary_ids, *skipped_ids))) != len(all_passages) or set(
        (*primary_ids, *skipped_ids)
    ) != {p.id for p in all_passages}:
        raise AssertionError("Primary passage accounting is incomplete")
    primary_by_section: Counter[str] = Counter()
    skipped_by_section: Counter[str] = Counter()
    for batch in batches:
        for passage in batch.primary_passages:
            primary_by_section[passage.section_id] += len(passage.text)
    for item in skipped:
        skipped_by_section[item.section_id] += item.characters
    sections = tuple(
        SectionCoverage(
            section.id,
            primary_by_section[section.id] + skipped_by_section[section.id],
            primary_by_section[section.id],
            skipped_by_section[section.id],
        )
        for section in manifest.sections
    )
    planned = sum(len(p.text) for batch in batches for p in batch.primary_passages)
    omitted = sum(p.characters for p in skipped)
    if planned + omitted != manifest.total_characters:
        raise AssertionError("Source character accounting is incomplete")
    return BatchPlan(tuple(batches), skipped, sections, manifest.total_characters, planned, omitted)
