"""Synthetic-only tests for the offline benchmark; real-PDF test is local opt-in."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from app.document_manifest import build_manifest
from app.models import ExtractedPage
from benchmarks.offline_clause_benchmark import (
    BenchmarkError,
    LocalBenchmark,
    evaluate_benchmark,
    load_local_benchmark,
    oracle_mock_predictions,
    validate_gold,
)
from scripts.run_clause_benchmark import run


def synthetic_benchmark(*, pending: bool = False, unreadable: bool = False):
    pages = [
        ExtractedPage(
            page_number=1,
            text="A fictional co-payment definition describes cost sharing.\n",
            extraction_quality="text_present",
        ),
        ExtractedPage(
            page_number=2,
            text="A fictional pre-hospitalization benefit needs an admissible stay.\n",
            extraction_quality="text_present",
        ),
    ]
    if unreadable:
        pages.append(
            ExtractedPage(
                page_number=3,
                text="Unreadable source text has a replacement character.\ufffd",
                extraction_quality="needs_review",
            )
        )
    manifest = build_manifest(pages)
    items = []
    for target_id, passage, category, kind in (
        ("co_payment_definition", manifest.passages[0], "cost_sharing", "definition"),
        ("pre_hospitalization", manifest.passages[1], "hospitalization_benefits", "benefit"),
    ):
        anchor = manifest.anchor(passage.id, passage.text)
        items.append(
            {
                "target_id": target_id,
                "title": "Fictional benchmark clause",
                "category": category,
                "kind": kind,
                "evidence": [
                    {
                        "passage_id": anchor.passage_id,
                        "page_number": anchor.page_number,
                        "start": anchor.start,
                        "end": anchor.end,
                        "excerpt": anchor.quote,
                    }
                ],
                "dependencies": ["policy_schedule"],
                "qualifications": "Review required.",
                "actionable_rule_supported": False,
                "manual_review_status": "pending" if pending else "approved",
            }
        )
    benchmark = LocalBenchmark.model_validate(
        {
            "benchmark_version": "synthetic-v1",
            "source_pdf_sha256": hashlib.sha256(b"fictional-pdf").hexdigest(),
            "physical_page_count": len(pages),
            "canonical_text_characters": manifest.total_characters,
            "manual_review_required": True,
            "items": items,
        }
    )
    return manifest, benchmark


def test_oracle_mock_is_plumbing_check_with_exact_rejections_and_duplicate_accounting():
    manifest, benchmark = synthetic_benchmark()
    predictions = oracle_mock_predictions(benchmark)
    metrics = evaluate_benchmark(manifest, benchmark, predictions)
    assert metrics.gold_targets == metrics.validated_gold_anchors == 2
    assert metrics.provisional_recalled_targets == metrics.approved_recalled_targets == 2
    assert metrics.predictions == 6
    assert metrics.exact_evidence_accepted == 3
    assert metrics.correct_passage_associations == 3
    assert metrics.targeted_predictions == 4
    assert metrics.rejected_candidates == 3
    assert metrics.rejected_by_reason == {"EXCERPT_NOT_FOUND": 2, "INVALID_CANDIDATE": 1}
    assert (metrics.unsupported_candidates_rejected, metrics.unsupported_candidates_total) == (3, 3)
    assert metrics.duplicate_candidates == 1
    assert metrics.unsafe_rule_attempts == 1
    assert metrics.incorrect_actionable_rules_retained == 0
    assert metrics.missing_primary_passages == metrics.unprocessed_passages == 0
    assert metrics.incomplete_sections == 0
    assert metrics.accounted_coverage_percent == 100
    assert "excerpt" not in str(metrics.safe_report())


def test_pending_review_is_not_reported_as_approved_accuracy():
    manifest, benchmark = synthetic_benchmark(pending=True)
    metrics = evaluate_benchmark(manifest, benchmark, oracle_mock_predictions(benchmark))
    assert metrics.pending_manual_review == 2
    assert metrics.provisional_recalled_targets == 2
    assert metrics.approved_targets == 0
    assert metrics.approved_recalled_targets is None


def test_skipped_text_is_accounted_without_becoming_a_discovery_target():
    manifest, benchmark = synthetic_benchmark(unreadable=True)
    metrics = evaluate_benchmark(manifest, benchmark, oracle_mock_predictions(benchmark))
    assert metrics.unprocessed_passages == 1
    assert metrics.unprocessed_characters > 0
    assert metrics.missing_primary_passages == 0
    assert metrics.accounted_coverage_percent == 100


def test_tampered_page_offset_and_pdf_fingerprint_fail_content_free():
    manifest, benchmark = synthetic_benchmark()
    changed = benchmark.model_copy(deep=True)
    changed.items[0].evidence[0].page_number = 99
    with pytest.raises(BenchmarkError, match="page or offset") as error:
        validate_gold(manifest, changed)
    assert "fictional" not in str(error.value)
    with pytest.raises(BenchmarkError, match="fingerprint"):
        validate_gold(manifest, benchmark, pdf_bytes=b"wrong-pdf")


def test_duplicate_target_ids_and_malformed_json_are_rejected(tmp_path):
    manifest, benchmark = synthetic_benchmark()
    changed = benchmark.model_copy(deep=True)
    changed.items[1].target_id = changed.items[0].target_id
    with pytest.raises(BenchmarkError, match="duplicated"):
        validate_gold(manifest, changed)
    path = tmp_path / "invalid-benchmark.json"
    path.write_text('{"excerpt":"fictional sensitive content"}', encoding="utf-8")
    with pytest.raises(BenchmarkError) as error:
        load_local_benchmark(path)
    assert "fictional sensitive content" not in str(error.value)


@pytest.mark.skipif(
    not (os.getenv("OFFLINE_POLICY_PDF") and os.getenv("OFFLINE_CLAUSE_BENCHMARK")),
    reason="Local public PDF and ignored benchmark file not provided",
)
def test_local_six_target_benchmark_exact_anchors_and_pending_review():
    benchmark_path = Path(os.environ["OFFLINE_CLAUSE_BENCHMARK"])
    report = run(
        Path(os.environ["OFFLINE_POLICY_PDF"]),
        benchmark_path,
        mock_self_check=True,
    )
    assert report["validated_exact_anchors"] == report["manual_review_pending"] == 6
    assert [target["physical_pages"] for target in report["targets"]] == [
        [3],
        [10],
        [11],
        [12],
        [13],
        [19],
    ]
    assert all(not target["actionable_rule_supported"] for target in report["targets"])
    metrics = report["oracle_mock_self_check_not_model_accuracy"]
    assert metrics["provisional_recalled_targets"] == 6
    assert metrics["approved_recalled_targets"] is None
    assert metrics["unsupported_candidates_rejected"] == 3
    assert metrics["duplicate_candidates"] == 1
    assert metrics["incorrect_actionable_rules_retained"] == 0
    assert metrics["missing_primary_passages"] == 0
    printed = json.dumps(report)
    assert all(
        source.excerpt not in printed
        for item in load_local_benchmark(benchmark_path).items
        for source in item.evidence
    )
