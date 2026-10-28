"""Validate a Git-ignored local clause benchmark without printing document text.

Run from backend/: python -m scripts.run_clause_benchmark --pdf PDF --benchmark JSON
Add --mock-self-check to exercise the adapter with predictions constructed from gold.
That self-check measures plumbing, not real model accuracy.
"""

import argparse
import json
from pathlib import Path

from app.clause_discovery import plan_batches
from app.config import Settings
from app.document_manifest import build_manifest
from app.pdf import parse_isolated
from benchmarks.offline_clause_benchmark import (
    BenchmarkError,
    evaluate_benchmark,
    load_local_benchmark,
    oracle_mock_predictions,
    validate_gold,
)


def run(pdf_path: Path, benchmark_path: Path, *, mock_self_check: bool) -> dict:
    settings = Settings(_env_file=None)
    if pdf_path.stat().st_size > settings.max_upload_bytes:
        raise BenchmarkError("PDF exceeds the configured upload limit")
    pdf_bytes = pdf_path.read_bytes()
    parsed = parse_isolated(pdf_bytes, settings, extract=True)
    manifest = build_manifest(parsed.pages)
    benchmark = load_local_benchmark(benchmark_path)
    anchors = validate_gold(manifest, benchmark, pdf_bytes=pdf_bytes)
    plan = plan_batches(manifest)
    report = {
        "benchmark_version": benchmark.benchmark_version,
        "targets": [
            {
                "target_id": item.target_id,
                "physical_pages": sorted({source.page_number for source in item.evidence}),
                "passage_ids": [source.passage_id for source in item.evidence],
                "excerpt_characters": sum(len(source.excerpt) for source in item.evidence),
                "category": item.category,
                "kind": item.kind,
                "dependencies": item.dependencies,
                "actionable_rule_supported": item.actionable_rule_supported,
                "manual_review_status": item.manual_review_status,
            }
            for item in benchmark.items
        ],
        "validated_exact_anchors": anchors,
        "manual_review_pending": sum(
            item.manual_review_status == "pending" for item in benchmark.items
        ),
        "batch_count": len(plan.batches),
        "accounted_coverage_percent": plan.accounted_coverage_percent,
        "unprocessed_passages": len(plan.skipped),
    }
    if mock_self_check:
        report["oracle_mock_self_check_not_model_accuracy"] = evaluate_benchmark(
            manifest,
            benchmark,
            oracle_mock_predictions(benchmark),
            pdf_bytes=pdf_bytes,
        ).safe_report()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--mock-self-check", action="store_true")
    args = parser.parse_args()
    try:
        report = run(args.pdf, args.benchmark, mock_self_check=args.mock_self_check)
    except (OSError, BenchmarkError):
        parser.error("Offline benchmark could not be validated")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
