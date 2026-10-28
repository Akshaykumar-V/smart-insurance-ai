"""Offline request-shape and complete-budget tests; no provider client is used."""

import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.document_manifest import build_manifest
from app.models import ExtractedPage
from benchmarks.offline_clause_benchmark import BenchmarkError, LocalBenchmark, load_local_benchmark
from benchmarks.pilot_preflight import (
    MAX_INPUT_TOKENS_PER_REQUEST,
    MAX_OUTPUT_TOKENS_PER_REQUEST,
    ExactTokenCountUnavailable,
    PilotPreflightError,
    prepare_pilot_requests,
    require_exact_token_budget,
)


def synthetic_plan():
    pages = [
        ExtractedPage(
            page_number=1,
            text="Co-payment means cost sharing: 20% with ₹ and सीमा.\n",
            extraction_quality="text_present",
        ),
        ExtractedPage(
            page_number=2,
            text="Proportionate deduction applies only where the schedule specifies a limit.\n",
            extraction_quality="text_present",
        ),
    ]
    manifest = build_manifest(pages)
    items = []
    for target_id, passage in zip(
        ("co_payment_definition", "proportionate_room_rent_deduction"),
        manifest.passages,
        strict=True,
    ):
        anchor = manifest.anchor(passage.id, passage.text)
        items.append(
            {
                "target_id": target_id,
                "title": "Synthetic clause",
                "category": "cost_sharing",
                "kind": "definition",
                "evidence": [
                    {
                        "passage_id": passage.id,
                        "page_number": anchor.page_number,
                        "start": anchor.start,
                        "end": anchor.end,
                        "excerpt": anchor.quote,
                    }
                ],
                "dependencies": [],
                "qualifications": "Review required",
                "actionable_rule_supported": False,
                "manual_review_status": "pending",
            }
        )
    benchmark = LocalBenchmark.model_validate(
        {
            "benchmark_version": "synthetic-preflight",
            "source_pdf_sha256": hashlib.sha256(b"synthetic").hexdigest(),
            "physical_page_count": 2,
            "canonical_text_characters": manifest.total_characters,
            "manual_review_required": True,
            "items": items,
        }
    )
    return manifest, benchmark


def test_under_budget_accounts_for_complete_input_and_reserved_output():
    manifest, benchmark = synthetic_plan()
    requests = prepare_pilot_requests(manifest, benchmark, model="configured-model")
    seen = []

    def exact_counter(payload):
        seen.append(payload)
        return MAX_INPUT_TOKENS_PER_REQUEST

    counted = require_exact_token_budget(requests, count_input_tokens=exact_counter)
    assert len(counted) == len(seen) == 2
    assert all(item.reserved_total_tokens == 6800 for item in counted)
    assert all(
        item.request.body["max_output_tokens"] == MAX_OUTPUT_TOKENS_PER_REQUEST for item in counted
    )
    assert all(set(payload) == {"model", "instructions", "input", "text"} for payload in seen)
    assert all(payload["text"]["format"]["schema"] for payload in seen)
    assert all(payload["instructions"] for payload in seen)
    assert all(len(json.loads(payload["input"])["primary_passages"]) == 1 for payload in seen)
    assert all(json.loads(payload["input"])["context_passages"] == [] for payload in seen)
    assert all(request.body["store"] is False for request in requests)


def test_oversized_request_fails_before_any_provider_work():
    manifest, benchmark = synthetic_plan()
    requests = prepare_pilot_requests(manifest, benchmark, model="configured-model")
    with patch("httpx.Client.request") as provider_request:
        with pytest.raises(PilotPreflightError, match="token ceiling"):
            require_exact_token_budget(
                requests, count_input_tokens=lambda payload: MAX_INPUT_TOKENS_PER_REQUEST + 1
            )
        provider_request.assert_not_called()


def test_no_exact_counter_fails_closed():
    manifest, benchmark = synthetic_plan()
    requests = prepare_pilot_requests(manifest, benchmark, model="configured-model")
    with pytest.raises(ExactTokenCountUnavailable, match="complete-request"):
        require_exact_token_budget(requests, count_input_tokens=None)


def test_counter_failure_fails_closed_without_leaking_source():
    manifest, benchmark = synthetic_plan()
    requests = prepare_pilot_requests(manifest, benchmark, model="configured-model")

    def unavailable(payload):
        raise RuntimeError(payload["input"])

    with pytest.raises(PilotPreflightError, match="counting failed") as error:
        require_exact_token_budget(requests, count_input_tokens=unavailable)
    assert "₹" not in str(error.value)


@pytest.mark.parametrize("bad_count", [0, -1, None, 5000.0, True, "5000"])
def test_unreliable_count_values_fail_closed(bad_count):
    manifest, benchmark = synthetic_plan()
    requests = prepare_pilot_requests(manifest, benchmark, model="configured-model")
    with pytest.raises(PilotPreflightError, match="count is invalid"):
        require_exact_token_budget(requests, count_input_tokens=lambda payload: bad_count)


def test_unicode_is_preserved_and_counted_payload_contains_it():
    manifest, benchmark = synthetic_plan()
    request = prepare_pilot_requests(manifest, benchmark, model="configured-model")[0]
    payload = request.count_payload()
    assert "₹ and सीमा" in payload["input"]
    assert request.serialized_complete_request_bytes >= request.serialized_count_payload_bytes
    assert request.safe_summary()["exact_input_tokens"] is None
    assert "₹" not in str(request.safe_summary())


def test_altered_exact_evidence_blocks_request_construction():
    manifest, benchmark = synthetic_plan()
    changed = benchmark.model_copy(deep=True)
    changed.items[0].evidence[0].excerpt += "changed"
    with pytest.raises(BenchmarkError, match="anchor failed"):
        prepare_pilot_requests(manifest, changed, model="configured-model")


def test_request_count_and_output_reserve_are_hard_caps():
    manifest, benchmark = synthetic_plan()
    with pytest.raises(PilotPreflightError, match="selection is invalid"):
        prepare_pilot_requests(
            manifest,
            benchmark,
            model="configured-model",
            target_ids=("co_payment_definition",) * 3,
        )
    requests = prepare_pilot_requests(manifest, benchmark, model="configured-model")
    requests[0].body["max_output_tokens"] = MAX_OUTPUT_TOKENS_PER_REQUEST + 1
    with pytest.raises(PilotPreflightError, match="output token reserve"):
        require_exact_token_budget(requests, count_input_tokens=lambda payload: 100)


@pytest.mark.skipif(
    not (os.getenv("OFFLINE_POLICY_PDF") and os.getenv("OFFLINE_CLAUSE_BENCHMARK")),
    reason="Local PDF and ignored benchmark file not provided",
)
def test_local_real_pdf_plan_is_two_passages_and_still_blocked():
    from app.config import Settings
    from app.pdf import parse_isolated

    pdf_bytes = Path(os.environ["OFFLINE_POLICY_PDF"]).read_bytes()
    manifest = build_manifest(
        parse_isolated(pdf_bytes, Settings(_env_file=None), extract=True).pages
    )
    benchmark = load_local_benchmark(Path(os.environ["OFFLINE_CLAUSE_BENCHMARK"]))
    requests = prepare_pilot_requests(
        manifest, benchmark, model="configured-model", pdf_bytes=pdf_bytes
    )
    assert len(requests) == 2
    assert [item.page_number for item in requests] == [3, 12]
    assert all(item.manual_review_status == "pending" for item in benchmark.items)
    icu_item = next(
        item for item in benchmark.items if item.target_id == "proportionate_room_rent_deduction"
    )
    assert "ICU" in icu_item.evidence[0].excerpt
    assert "ICCU" in icu_item.evidence[0].excerpt
    assert "not associated medical expenses" in icu_item.qualifications
    with pytest.raises(ExactTokenCountUnavailable):
        require_exact_token_budget(requests, count_input_tokens=None)
