"""Report the disabled-provider two-request pilot plan without printing PDF text.

Run from backend/: python -m scripts.run_pilot_preflight --pdf PDF --benchmark JSON
This script never sends a provider request and always reports exact tokens unavailable.
"""

import argparse
import json
from pathlib import Path

from app.config import Settings
from app.document_manifest import build_manifest
from app.pdf import parse_isolated
from benchmarks.offline_clause_benchmark import BenchmarkError, load_local_benchmark
from benchmarks.pilot_preflight import (
    ExactTokenCountUnavailable,
    PilotPreflightError,
    prepare_pilot_requests,
    require_exact_token_budget,
)


def run(pdf_path: Path, benchmark_path: Path, *, settings: Settings) -> dict:
    if pdf_path.stat().st_size > settings.max_upload_bytes:
        raise PilotPreflightError("PDF exceeds the configured upload limit")
    pdf_bytes = pdf_path.read_bytes()
    manifest = build_manifest(parse_isolated(pdf_bytes, settings, extract=True).pages)
    benchmark = load_local_benchmark(benchmark_path)
    requests = prepare_pilot_requests(
        manifest, benchmark, model=settings.openai_model, pdf_bytes=pdf_bytes
    )
    try:
        require_exact_token_budget(requests, count_input_tokens=None)
    except ExactTokenCountUnavailable:
        status = "blocked_exact_token_counter_unavailable"
    else:
        raise AssertionError("Offline preflight must never enable provider requests")
    return {
        "status": status,
        "provider_requests_sent": 0,
        "model": settings.openai_model,
        "physical_pages": len(manifest.pages),
        "planned_requests": len(requests),
        "manual_review_pending": sum(
            item.manual_review_status == "pending" for item in benchmark.items
        ),
        "requests": [request.safe_summary() for request in requests],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run(args.pdf, args.benchmark, settings=Settings())
    except (OSError, BenchmarkError, PilotPreflightError, ValueError):
        parser.error("Offline pilot preflight could not be completed")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
