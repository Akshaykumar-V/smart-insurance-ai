"""Read-only, content-free diagnostics for a local PDF's offline manifest.

Run from backend/: python -m scripts.report_document_manifest PATH_TO_LOCAL_PDF
No document text, headings, excerpts, or path are printed.
"""

import argparse
import json
from pathlib import Path

from app.config import Settings
from app.document_manifest import AnchorError, DocumentManifest, build_manifest
from app.pdf import parse_isolated


def summarize(manifest: DocumentManifest) -> dict[str, int | float]:
    eligible = [passage for passage in manifest.passages if len(passage.text.strip()) >= 12]
    anchored = 0
    altered_rejected = 0
    for passage in eligible:
        anchor = manifest.anchor(passage.id, passage.text)
        anchored += anchor.start == passage.start and anchor.end == passage.end
        try:
            manifest.anchor(passage.id, passage.text + "\x00")
        except AnchorError as error:
            altered_rejected += error.code == "EXCERPT_NOT_FOUND"
    return {
        "total_pages": len(manifest.pages),
        "total_sections": len(manifest.sections),
        "total_passages": len(manifest.passages),
        "total_source_characters": manifest.total_characters,
        "total_characters_covered": manifest.covered_characters,
        "coverage_percentage": manifest.coverage_percent,
        "unclassified_sections": sum(s.status == "unclassified" for s in manifest.sections),
        "uncertain_heading_candidates": sum(h.confidence == "uncertain" for h in manifest.headings),
        "evidence_anchors_checked": len(eligible),
        "evidence_anchors_passed": anchored,
        "altered_excerpts_rejected": altered_rejected,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()
    settings = Settings(_env_file=None)
    if args.pdf.stat().st_size > settings.max_upload_bytes:
        parser.error("PDF exceeds the configured upload size limit")
    parsed = parse_isolated(args.pdf.read_bytes(), settings, extract=True)
    print(json.dumps(summarize(build_manifest(parsed.pages)), sort_keys=True))


if __name__ == "__main__":
    main()
