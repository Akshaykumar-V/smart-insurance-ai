"""Content-free offline demo of mocked clause discovery and optional real-PDF anchoring.

Run from backend/: python -m scripts.demo_clause_discovery [--pdf LOCAL_PUBLIC_PDF]
The synthetic wording is fictional. Real-PDF probes make no semantic clause claims.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from app.clause_discovery import discover_clauses, plan_batches
from app.config import Settings
from app.document_manifest import build_manifest
from app.models import ExtractedPage
from app.pdf import parse_isolated

COPAY = "A 20% co-payment of admissible expenses may apply where the Policy Schedule specifies it."
LIMIT = (
    "Cataract treatment has an illustrative INR 40,000 per-eye limit, "
    "subject to the Policy Schedule."
)


def _candidate(manifest, excerpt: str, *, title: str, category: str, kind: str, **extra) -> dict:
    passage = next(passage for passage in manifest.passages if excerpt in passage.text)
    return {
        "title": title,
        "category": category,
        "kind": kind,
        "evidence": [{"passage_id": passage.id, "excerpt": excerpt}],
        **extra,
    }


def synthetic_demo() -> dict:
    pages = [
        ExtractedPage(
            page_number=1,
            text=(
                "1. ILLUSTRATIVE COST SHARING\n"
                + COPAY
                + "\nCo-payment means the portion of an admissible claim payable by the insured.\n"
                + "An endorsement may change the limits listed\n"
            ),
            extraction_quality="text_present",
        ),
        ExtractedPage(
            page_number=2,
            text=(
                "in the Policy Schedule for the insured member.\n"
                "2. ILLUSTRATIVE TREATMENT LIMITS\n"
                + LIMIT
                + "\nTo request review, submit the claim form and supporting bills.\n"
            ),
            extraction_quality="text_present",
        ),
    ]
    manifest = build_manifest(pages)
    condition = _candidate(
        manifest,
        COPAY,
        title="Illustrative co-payment condition",
        category="cost_sharing",
        kind="condition",
        dependencies=[{"kind": "policy_schedule"}],
    )
    definition = _candidate(
        manifest,
        "Co-payment means the portion of an admissible claim payable by the insured.",
        title="Illustrative co-payment definition",
        category="definitions",
        kind="definition",
    )
    restriction = _candidate(
        manifest,
        LIMIT,
        title="Illustrative treatment limit",
        category="treatment_limits",
        kind="restriction",
        dependencies=[{"kind": "policy_schedule"}],
    )
    procedure = _candidate(
        manifest,
        "To request review, submit the claim form and supporting bills.",
        title="Illustrative documentation requirement",
        category="claims_process",
        kind="procedural_requirement",
    )
    first = "An endorsement may change the limits listed"
    second = "in the Policy Schedule for the insured member."
    cross_page = {
        **_candidate(
            manifest,
            first,
            title="Illustrative cross-page dependency",
            category="endorsements",
            kind="condition",
            dependencies=[{"kind": "endorsement"}, {"kind": "policy_schedule"}],
        ),
        "evidence": [
            {
                "passage_id": next(p.id for p in manifest.passages if first in p.text),
                "excerpt": first,
            },
            {
                "passage_id": next(p.id for p in manifest.passages if second in p.text),
                "excerpt": second,
            },
        ],
    }
    altered = {
        **condition,
        "evidence": [
            {
                **condition["evidence"][0],
                "excerpt": condition["evidence"][0]["excerpt"].replace("20%", "30%"),
            }
        ],
    }
    result = discover_clauses(
        manifest, [condition, definition, restriction, procedure, cross_page, altered, condition]
    )
    plan = plan_batches(manifest, context_radius=1)
    return {
        "fixture": "fictional_hdfc_style_wording",
        "pages": len(manifest.pages),
        "sections": len(manifest.sections),
        "passages": len(manifest.passages),
        "batches": len(plan.batches),
        "accounted_coverage_percent": plan.accounted_coverage_percent,
        "accepted_review_only_clauses": len(result.clauses),
        "kinds": dict(sorted(Counter(clause.kind for clause in result.clauses).items())),
        "rejected_candidates": result.rejected_count,
        "rejected_by_reason": result.rejected_by_reason,
        "duplicate_candidates": result.duplicate_count,
        "financial_rules_generated": 0,
    }


def real_pdf_probe(path: Path) -> dict:
    settings = Settings(_env_file=None)
    if path.stat().st_size > settings.max_upload_bytes:
        raise ValueError("PDF exceeds configured upload limit")
    parsed = parse_isolated(path.read_bytes(), settings, extract=True)
    manifest = build_manifest(parsed.pages)
    plan = plan_batches(manifest)
    eligible = [
        passage
        for batch in plan.batches
        for passage in batch.primary_passages
        if len(passage.text.strip()) >= 12
    ]
    probes = [
        {
            "title": "Offline evidence probe",
            "category": "document_text",
            "kind": "other",
            "evidence": [{"passage_id": passage.id, "excerpt": passage.text}],
        }
        for passage in eligible[:3]
    ]
    if probes:
        altered = {
            **probes[0],
            "evidence": [
                {
                    **probes[0]["evidence"][0],
                    "excerpt": probes[0]["evidence"][0]["excerpt"] + "\x00",
                }
            ],
        }
        probes.extend([altered, probes[0]])
    result = discover_clauses(manifest, probes)
    return {
        "semantic_clause_claims": 0,
        "pages": len(manifest.pages),
        "sections": len(manifest.sections),
        "passages": len(manifest.passages),
        "batches": len(plan.batches),
        "primary_characters": plan.primary_characters,
        "skipped_characters": plan.skipped_characters,
        "accounted_coverage_percent": plan.accounted_coverage_percent,
        "exact_evidence_probes_accepted": len(result.clauses),
        "rejected_candidates": result.rejected_count,
        "rejected_by_reason": result.rejected_by_reason,
        "duplicate_candidates": result.duplicate_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pdf", type=Path, help="Optional local public PDF for evidence-only probes"
    )
    args = parser.parse_args()
    report = {"synthetic_demo": synthetic_demo()}
    if args.pdf:
        report["real_pdf_evidence_probe"] = real_pdf_probe(args.pdf)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
