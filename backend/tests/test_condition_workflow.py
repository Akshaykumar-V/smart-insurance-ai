"""Synthetic, offline tests for review-only claim-affecting clause discovery."""

import json

import pytest
from conftest import make_pdf

from app.condition_workflow import evaluate_mocked_batches, prepare_condition_document
from app.config import Settings
from app.models import ExtractedPage
from app.pdf import parse_isolated

CLAUSES = (
    (
        "room_rent",
        "Room rent is limited to INR 5,000 per day except for ICU stays.",
        "restriction",
    ),
    (
        "deductible",
        "An aggregate deductible of INR 10,000 applies per policy year.",
        "condition",
    ),
    (
        "waiting_period",
        "A waiting period of 24 months applies to listed conditions.",
        "restriction",
    ),
    (
        "exclusion",
        "Cosmetic treatment is excluded unless required after an accident.",
        "restriction",
    ),
    (
        "co_payment",
        "The insured pays a 10% co-payment on admissible expenses.",
        "condition",
    ),
    (
        "sub_limit",
        "Cataract treatment is limited to INR 40,000 per eye per year.",
        "restriction",
    ),
)


def _response(candidates):
    return {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": json.dumps({"candidates": candidates})}
                ],
            }
        ],
    }


def _candidate(passage, text, category, kind, **changes):
    return {
        "title": "Fictional claim condition",
        "category": category,
        "specific_label": None,
        "kind": kind,
        "evidence": [{"passage_id": passage.id, "excerpt": text}],
        "applicability": "Review against the insured member's schedule",
        "exceptions": ["ICU exception"] if category == "room_rent" else [],
        "dependencies": [{"kind": "policy_schedule", "label": None}],
        "review_status": "needs_review",
        **changes,
    }


def _prepared():
    return prepare_condition_document(
        "fictional-document",
        [
            ExtractedPage(page_number=index, text=text, extraction_quality="text_present")
            for index, (_, text, _) in enumerate(CLAUSES, start=1)
        ],
    )


def _responses(prepared, candidates):
    return {batch.id: _response(candidates) for batch in prepared.plan.batches}


def test_six_claim_categories_keep_exact_pages_values_qualifications_and_review_status():
    prepared = _prepared()
    passages = {passage.page_number: passage for passage in prepared.manifest.passages}
    candidates = [
        _candidate(passages[index], text, category, kind)
        for index, (category, text, kind) in enumerate(CLAUSES, start=1)
    ]
    # Assign each candidate to the batch that owns its cited primary passage.
    responses = {
        batch.id: _response(
            [
                candidate
                for candidate in candidates
                if candidate["evidence"][0]["passage_id"]
                in {passage.id for passage in batch.primary_passages}
            ]
        )
        for batch in prepared.plan.batches
    }
    report = evaluate_mocked_batches(prepared, responses)
    assert report.processed_batches == report.planned_batches
    assert not report.incomplete
    assert report.warning is None
    assert len(report.conditions) == 6
    assert {item.clause.category for item in report.conditions} == {item[0] for item in CLAUSES}
    for index, condition in enumerate(report.conditions, start=1):
        evidence = condition.clause.evidence[0]
        assert (evidence.page_number, evidence.passage_id, evidence.start) == (
            index,
            passages[index].id,
            0,
        )
        assert evidence.quote == CLAUSES[index - 1][1]
        assert condition.review_status == "needs_review"
        assert condition.clause.dependencies[0].kind == "policy_schedule"
        assert not hasattr(condition, "rule")
    assert report.conditions[0].clause.exceptions == ("ICU exception",)
    assert report.conditions[0].observed_value_mentions == ("INR 5,000",)
    assert report.conditions[2].observed_value_mentions == ("24 months",)
    assert report.conditions[4].observed_value_mentions == ("10%",)
    assert report.conditions[5].observed_value_mentions == ("INR 40,000",)


@pytest.mark.parametrize(
    ("excerpt", "reason"),
    [
        ("Room rent is limited to INR 6,000 per day except for ICU stays.", "EXCERPT_NOT_FOUND"),
        ("Room rent was limited", "EXCERPT_NOT_FOUND"),
        ("Room rent", "SHORT_EXCERPT"),
    ],
)
def test_altered_partial_or_short_evidence_never_creates_a_condition(excerpt, reason):
    prepared = _prepared()
    passage = prepared.manifest.passages[0]
    candidate = _candidate(passage, excerpt, "room_rent", "restriction")
    report = evaluate_mocked_batches(prepared, _responses(prepared, [candidate]))
    assert report.conditions == ()
    assert report.rejected_by_reason == {reason: 1}
    assert report.incomplete
    assert "1 rejected candidates" in report.warning
    assert excerpt not in report.warning


def test_wrong_passage_and_model_page_are_rejected():
    prepared = _prepared()
    first, second = prepared.manifest.passages[:2]
    wrong = _candidate(second, first.text, "room_rent", "restriction")
    invented_page = _candidate(first, first.text, "room_rent", "restriction", page_number=99)
    report = evaluate_mocked_batches(prepared, _responses(prepared, [wrong, invented_page]))
    assert report.conditions == ()
    assert report.rejected_by_reason == {"EXCERPT_NOT_FOUND": 1, "INVALID_CANDIDATE": 1}


def test_missing_batch_and_zero_results_are_incomplete():
    prepared = _prepared()
    report = evaluate_mocked_batches(prepared, {})
    assert report.processed_batches == 0
    assert report.incomplete
    assert "unprocessed batches" in report.warning
    empty = evaluate_mocked_batches(prepared, _responses(prepared, []))
    assert empty.conditions == ()
    assert empty.incomplete
    assert "absence of limits" in empty.warning


def test_failed_output_does_not_expose_document_text_in_warning():
    prepared = _prepared()
    batch = prepared.plan.batches[0]
    report = evaluate_mocked_batches(prepared, {batch.id: {"status": "incomplete", "output": []}})
    assert report.failed_batches == 1
    assert report.incomplete
    assert CLAUSES[0][1] not in report.warning


def test_duplicate_candidates_are_counted_without_losing_distinct_clauses():
    prepared = _prepared()
    first, second = prepared.manifest.passages[:2]
    one = _candidate(first, first.text, "room_rent", "restriction")
    two = _candidate(second, second.text, "deductible", "condition")
    report = evaluate_mocked_batches(prepared, _responses(prepared, [one, one, two]))
    assert len(report.conditions) == 2
    assert report.duplicate_count == 1


def test_repeated_excerpt_is_ambiguous_and_unreadable_passage_is_reported():
    text = "A fictional waiting period applies."
    prepared = prepare_condition_document(
        "fictional-document",
        [
            ExtractedPage(
                page_number=1, text=text + "\n" + text, extraction_quality="text_present"
            ),
            ExtractedPage(
                page_number=2, text="Unreadable \ufffd", extraction_quality="needs_review"
            ),
        ],
    )
    passage = prepared.manifest.passages[0]
    report = evaluate_mocked_batches(
        prepared,
        _responses(prepared, [_candidate(passage, text, "waiting_period", "restriction")]),
    )
    assert report.conditions == ()
    assert report.rejected_by_reason == {"AMBIGUOUS_EXCERPT": 1}
    assert report.skipped_passages == 1
    assert report.incomplete


def test_unicode_and_cross_page_evidence_preserves_backend_offsets():
    left = "The deductible is ₹10,000 unless the schedule"
    right = "specifies a different amount for this member."
    prepared = prepare_condition_document(
        "fictional-document",
        [
            ExtractedPage(page_number=7, text=left, extraction_quality="text_present"),
            ExtractedPage(page_number=8, text=right, extraction_quality="text_present"),
        ],
    )
    first, second = prepared.manifest.passages
    candidate = _candidate(
        first,
        left,
        "deductible",
        "condition",
        evidence=[
            {"passage_id": first.id, "excerpt": left},
            {"passage_id": second.id, "excerpt": right},
        ],
    )
    report = evaluate_mocked_batches(prepared, _responses(prepared, [candidate]))
    assert len(report.conditions) == 1
    assert report.conditions[0].observed_value_mentions == ("₹10,000",)
    assert [(e.page_number, e.start, e.end) for e in report.conditions[0].clause.evidence] == [
        (7, 0, len(left)),
        (8, 0, len(right)),
    ]
    assert not hasattr(report.conditions[0], "rule")


def test_existing_isolated_pdf_extraction_feeds_offline_condition_workflow():
    source = "A 10% co-payment applies."
    data = make_pdf((source, "INR 40,000 cataract sub-limit applies."))
    settings = Settings(_env_file=None, max_upload_bytes=100_000, max_pdf_pages=10)
    parsed = parse_isolated(data, settings, extract=True)
    prepared = prepare_condition_document("fictional-document", parsed.pages)
    passage = next(item for item in prepared.manifest.passages if item.page_number == 1)
    candidate = _candidate(passage, source, "co_payment", "condition")
    report = evaluate_mocked_batches(prepared, _responses(prepared, [candidate]))
    assert len(report.conditions) == 1
    assert report.conditions[0].clause.evidence[0].page_number == 1
    assert report.conditions[0].observed_value_mentions == ("10%",)
