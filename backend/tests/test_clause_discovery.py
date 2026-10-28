"""Mocked, offline clause discovery tests; no provider or database access."""

import os
from pathlib import Path

import pytest

from app.clause_discovery import (
    DiscoveryBatch,
    discover_clauses,
    plan_batches,
)
from app.document_manifest import build_manifest
from app.models import ExtractedPage
from scripts.demo_clause_discovery import real_pdf_probe, synthetic_demo


def page(number: int, text: str, quality: str = "text_present") -> ExtractedPage:
    return ExtractedPage(page_number=number, text=text, extraction_quality=quality)


def mocked_candidate(passage_id: str, excerpt: str, **changes) -> dict:
    return {
        "title": "Fictional policy clause",
        "category": "new_insurance_category",
        "kind": "condition",
        "evidence": [{"passage_id": passage_id, "excerpt": excerpt}],
        **changes,
    }


def test_flexible_definition_and_schedule_dependency_are_review_only():
    text = "Co-payment means an insured person's share, subject to the Policy Schedule."
    manifest = build_manifest([page(4, text)])
    result = discover_clauses(
        manifest,
        [
            mocked_candidate(
                manifest.passages[0].id,
                text,
                kind="definition",
                category="policy_vocabulary",
                specific_label="Co-payment",
                applicability="Subject to a separate schedule",
                exceptions=["An endorsement may differ"],
                dependencies=[{"kind": "policy_schedule"}, {"kind": "endorsement"}],
            )
        ],
    )
    assert result.rejected_count == result.duplicate_count == 0
    clause = result.clauses[0]
    assert (clause.category, clause.kind, clause.review_status) == (
        "policy_vocabulary",
        "definition",
        "needs_review",
    )
    assert {dependency.kind for dependency in clause.dependencies} == {
        "policy_schedule",
        "endorsement",
    }
    assert not hasattr(clause, "rule")
    assert clause.evidence[0].page_number == 4
    assert clause.evidence[0].start == 0
    assert clause.evidence[0].end == len(text)


@pytest.mark.parametrize(
    ("excerpt", "reason"),
    [
        ("Invented policy wording here.", "EXCERPT_NOT_FOUND"),
        ("A co-payment of 30% may apply.", "EXCERPT_NOT_FOUND"),
        ("A co payment of 20% may apply.", "EXCERPT_NOT_FOUND"),
        ("co-payment", "SHORT_EXCERPT"),
    ],
)
def test_rejects_absent_altered_paraphrased_and_short_quotes(excerpt, reason):
    manifest = build_manifest([page(1, "A co-payment of 20% may apply.")])
    result = discover_clauses(manifest, [mocked_candidate(manifest.passages[0].id, excerpt)])
    assert result.clauses == ()
    assert result.rejected_by_reason == {reason: 1}
    assert result.rejected_count == 1


def test_wrong_passage_and_model_supplied_page_are_rejected():
    manifest = build_manifest(
        [
            page(1, "First policy clause has a condition."),
            page(2, "Second policy clause has a benefit."),
        ]
    )
    first, second = manifest.passages
    wrong = mocked_candidate(second.id, first.text)
    invented_page = mocked_candidate(first.id, first.text, page_number=99)
    result = discover_clauses(manifest, [wrong, invented_page])
    assert result.clauses == ()
    assert result.rejected_by_reason == {"EXCERPT_NOT_FOUND": 1, "INVALID_CANDIDATE": 1}


def test_repeated_text_is_ambiguous_within_passage_but_distinct_across_pages():
    excerpt = "The same condition applies."
    manifest = build_manifest([page(1, excerpt + "\n" + excerpt), page(2, excerpt)])
    first, second = manifest.passages
    result = discover_clauses(
        manifest,
        [mocked_candidate(first.id, excerpt), mocked_candidate(second.id, excerpt)],
    )
    assert result.rejected_by_reason == {"AMBIGUOUS_EXCERPT": 1}
    assert len(result.clauses) == 1
    assert result.clauses[0].evidence[0].page_number == 2


def test_unicode_multiline_and_multiple_clauses_in_one_passage_remain_distinct():
    first = "Cataract benefit is limited to ₹40,000 per eye."
    second = "A co-payment of 20%\nmay apply to admissible expenses."
    manifest = build_manifest([page(7, first + "\n" + second)])
    passage = manifest.passages[0]
    candidates = [
        mocked_candidate(passage.id, first, category="treatment_limit", kind="restriction"),
        mocked_candidate(passage.id, second, category="cost_sharing", kind="condition"),
    ]
    result = discover_clauses(manifest, [*candidates, candidates[0]])
    assert len(result.clauses) == 2
    assert result.duplicate_count == 1
    assert result.rejected_count == 0
    assert [clause.evidence[0].start for clause in result.clauses] == [0, len(first) + 1]
    changed = mocked_candidate(passage.id, first.replace("₹", "Rs."))
    assert discover_clauses(manifest, [changed]).rejected_by_reason == {"EXCERPT_NOT_FOUND": 1}


def test_cross_page_clause_requires_every_span_and_deduplicates_reordered_spans():
    first = "The endorsement changes the condition when"
    second = "the separate policy schedule specifies the member."
    manifest = build_manifest([page(1, first), page(2, second)])
    left, right = manifest.passages
    spans = [
        {"passage_id": left.id, "excerpt": first},
        {"passage_id": right.id, "excerpt": second},
    ]
    good = mocked_candidate(left.id, first, evidence=spans, dependencies=[{"kind": "endorsement"}])
    reversed_order = {**good, "evidence": list(reversed(spans))}
    wrong_second = {**good, "evidence": [spans[0], {**spans[1], "excerpt": second + " changed"}]}
    result = discover_clauses(manifest, [good, reversed_order, wrong_second])
    assert len(result.clauses) == 1
    assert [e.page_number for e in result.clauses[0].evidence] == [1, 2]
    assert result.duplicate_count == 1
    assert result.rejected_by_reason == {"EXCERPT_NOT_FOUND": 1}


def test_duplicate_evidence_and_untrusted_review_status_are_rejected():
    text = "A fictional condition appears in the policy wording."
    manifest = build_manifest([page(1, text)])
    span = {"passage_id": manifest.passages[0].id, "excerpt": text}
    duplicated = mocked_candidate(span["passage_id"], text, evidence=[span, span])
    untrusted_status = mocked_candidate(span["passage_id"], text, review_status="verified")
    oversized_exception = mocked_candidate(span["passage_id"], text, exceptions=["x" * 501])
    result = discover_clauses(manifest, [duplicated, untrusted_status, oversized_exception])
    assert result.clauses == ()
    assert result.rejected_by_reason == {"DUPLICATE_EVIDENCE": 1, "INVALID_CANDIDATE": 2}


def test_empty_and_unreadable_passages_are_accounted_for_but_not_discovered():
    readable = "A readable fictional policy clause is present."
    unreadable = "An uncertain extracted clause appears here.\ufffd"
    manifest = build_manifest(
        [page(1, readable), page(2, "  \n", "no_text"), page(3, unreadable, "needs_review")]
    )
    plan = plan_batches(manifest)
    assert plan.accounted_coverage_percent == 100
    assert plan.primary_characters == len(readable)
    assert plan.skipped_characters == len("  \n") + len(unreadable)
    assert {item.reason for item in plan.skipped} == {"no_text", "needs_review"}
    result = discover_clauses(
        manifest,
        [mocked_candidate(manifest.passages[2].id, unreadable)],
    )
    assert result.rejected_by_reason == {"UNREADABLE_PASSAGE": 1}


def test_batch_plan_is_bounded_deterministic_and_covers_sections_once():
    text = "1. GENERAL CONDITIONS\n" + "A fictional clause with several terms.\n" * 24
    manifest = build_manifest(
        [page(1, text), page(2, "2. BENEFITS\n" + text)], max_passage_characters=100
    )
    kwargs = dict(
        max_primary_characters=130,
        max_payload_bytes=850,
        max_primary_passages=2,
        context_radius=1,
    )
    plan = plan_batches(manifest, **kwargs)
    again = plan_batches(manifest, **kwargs)
    assert [batch.id for batch in plan.batches] == [batch.id for batch in again.batches]
    primary_ids = [p.id for batch in plan.batches for p in batch.primary_passages]
    assert primary_ids == [p.id for p in manifest.passages]
    assert len(primary_ids) == len(set(primary_ids))
    assert all(batch.payload_bytes <= 850 for batch in plan.batches)
    assert all(len(batch.primary_passages) <= 2 for batch in plan.batches)
    assert all(sum(len(p.text) for p in batch.primary_passages) <= 130 for batch in plan.batches)
    assert all(
        not ({p.id for p in batch.primary_passages} & {p.id for p in batch.context_passages})
        for batch in plan.batches
    )
    assert plan.accounted_coverage_percent == 100
    assert sum(section.total_characters for section in plan.sections) == manifest.total_characters
    assert {section.section_id for section in plan.sections} == {
        section.id for section in manifest.sections
    }


def test_batch_context_cannot_generate_its_own_clause_or_cite_outside_batch():
    manifest = build_manifest(
        [
            page(1, "Primary fictional clause exists here."),
            page(2, "Context fictional clause exists here."),
            page(3, "Outside fictional clause exists here."),
        ]
    )
    primary, context, outside = manifest.passages
    batch = DiscoveryBatch("mock_batch", (primary,), (context,))
    result = discover_clauses(
        manifest,
        [
            mocked_candidate(context.id, context.text),
            mocked_candidate(outside.id, outside.text),
            mocked_candidate(
                primary.id,
                primary.text,
                evidence=[
                    {"passage_id": primary.id, "excerpt": primary.text},
                    {"passage_id": context.id, "excerpt": context.text},
                ],
            ),
        ],
        batch=batch,
    )
    assert len(result.clauses) == 1
    assert result.rejected_by_reason == {"CONTEXT_ONLY": 1, "OUT_OF_BATCH": 1}


def test_batch_ceiling_fails_without_truncation_and_empty_manifest_is_safe():
    manifest = build_manifest(
        [page(1, "A long fictional sentence about policy eligibility. " * 20)]
    )
    with pytest.raises(ValueError, match="ceiling"):
        plan_batches(manifest, max_primary_characters=10)
    with pytest.raises(ValueError, match="ceiling"):
        plan_batches(manifest, max_payload_bytes=128)
    empty = plan_batches(build_manifest([]))
    assert empty.batches == empty.skipped == empty.sections == ()
    assert empty.accounted_coverage_percent == 100


def test_synthetic_demo_reports_only_counts_and_no_rules():
    report = synthetic_demo()
    assert report["accepted_review_only_clauses"] == 5
    assert report["rejected_by_reason"] == {"EXCERPT_NOT_FOUND": 1}
    assert report["duplicate_candidates"] == 1
    assert report["financial_rules_generated"] == 0
    assert report["accounted_coverage_percent"] == 100


@pytest.mark.skipif(
    not os.getenv("OFFLINE_POLICY_PDF"), reason="Local public wording PDF not provided"
)
def test_real_pdf_probe_is_evidence_only_and_content_free():
    report = real_pdf_probe(Path(os.environ["OFFLINE_POLICY_PDF"]))
    assert report["pages"] == 69
    assert report["semantic_clause_claims"] == 0
    assert report["exact_evidence_probes_accepted"] == 3
    assert report["rejected_by_reason"] == {"EXCERPT_NOT_FOUND": 1}
    assert report["duplicate_candidates"] == 1
    assert report["accounted_coverage_percent"] == 100
