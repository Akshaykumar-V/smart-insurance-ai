"""Offline passage coverage and exact evidence checks; no provider requests."""

import os
from pathlib import Path

import pytest

from app.config import Settings
from app.document_manifest import AnchorError, build_manifest
from app.models import ExtractedPage
from app.pdf import parse_isolated
from scripts.make_ai_demo_pdf import main as make_ai_demo_pdf
from scripts.report_document_manifest import summarize


def page(number: int, text: str, quality: str = "text_present") -> ExtractedPage:
    return ExtractedPage(page_number=number, text=text, extraction_quality=quality)


def assert_exact_coverage(manifest) -> None:
    for source in manifest.pages:
        spans = sorted(
            (item.start, item.end, item.text)
            for item in manifest.passages
            if item.page_number == source.page_number
        )
        assert "".join(text for _, _, text in spans) == source.text
        assert spans == [(start, end, source.text[start:end]) for start, end, _ in spans]
        assert all(end - start <= 2400 for start, end, _ in spans)
        if spans:
            assert [start for start, _, _ in spans] == [0, *(end for _, end, _ in spans[:-1])]
        else:
            assert source.text == ""
    assert manifest.total_characters == manifest.covered_characters
    assert manifest.coverage_percent == 100


def test_fictional_pdf_has_exact_page_and_offset_anchors(capsys):
    make_ai_demo_pdf()
    path = Path(capsys.readouterr().out.strip())
    try:
        parsed = parse_isolated(path.read_bytes(), Settings(_env_file=None), extract=True)
    finally:
        path.unlink(missing_ok=True)
    manifest = build_manifest(parsed.pages)
    assert len(manifest.pages) == 2
    assert_exact_coverage(manifest)
    for physical_page, excerpt in (
        (1, "A co-payment of 20% of admissible expenses"),
        (2, "Cataract treatment is limited to INR 40,000"),
    ):
        passage = next(
            item
            for item in manifest.passages
            if item.page_number == physical_page and excerpt in item.text
        )
        anchor = manifest.anchor(passage.id, excerpt)
        assert (anchor.page_number, anchor.start, anchor.end) == (
            physical_page,
            parsed.pages[physical_page - 1].text.index(excerpt),
            parsed.pages[physical_page - 1].text.index(excerpt) + len(excerpt),
        )
    report = summarize(manifest)
    assert report["total_pages"] == 2
    assert report["evidence_anchors_passed"] == report["evidence_anchors_checked"]
    assert report["altered_excerpts_rejected"] == report["evidence_anchors_checked"]


def test_sections_detect_numbered_and_uppercase_but_preserve_uncertain_headings():
    text = (
        "Introductory notes remain present.\n"
        "1. GENERAL CONDITIONS\n"
        "The wording follows.\n"
        "Possible Schedule Details\n"
        "2.1 Cataract Benefits\n"
        "INR 40,000 per eye.\n"
    )
    manifest = build_manifest([page(4, text)])
    assert [item.heading.strip() for item in manifest.sections if item.heading] == [
        "1. GENERAL CONDITIONS",
        "2.1 Cataract Benefits",
    ]
    assert manifest.sections[0].status == "unclassified"
    assert any(
        item.confidence == "uncertain" and item.text.strip() == "Possible Schedule Details"
        for item in manifest.headings
    )
    assert_exact_coverage(manifest)


def test_no_recognizable_sections_keeps_one_unclassified_section_across_pages():
    manifest = build_manifest(
        [page(2, "lowercase wording.\n"), page(1, "another lowercase line.\n")]
    )
    assert len(manifest.sections) == 1
    assert manifest.sections[0].status == "unclassified"
    assert [item.page_number for item in manifest.pages] == [1, 2]
    assert_exact_coverage(manifest)


def test_roman_heading_requires_punctuation():
    manifest = build_manifest([page(1, "I understand these conditions\nII. ELIGIBILITY\n")])
    assert len(manifest.sections) == 2
    assert manifest.sections[1].heading.strip() == "II. ELIGIBILITY"
    assert any(
        h.text.strip() == "I understand these conditions" and h.confidence == "uncertain"
        for h in manifest.headings
    )


def test_bounded_passages_cover_tables_multiline_unicode_and_malformed_text():
    text = (
        "ITEM | LIMIT\nCataract | ₹40,000\n"
        "Kannada ಮೌಲ್ಯ and Greek α\n" + "Long clause with no section heading. " * 100 + "\ufffd\x00\n"
    )
    manifest = build_manifest(
        [page(1, text, "needs_review"), page(2, " \n", "no_text"), page(3, "", "no_text")],
        max_passage_characters=100,
    )
    assert "".join(p.text for p in manifest.passages if p.page_number == 1) == text
    assert all(len(p.text) <= 100 for p in manifest.passages)
    assert manifest.total_characters == manifest.covered_characters
    assert manifest.coverage_percent == 100
    assert not any(p.page_number == 3 for p in manifest.passages)
    assert not any(h.text.startswith("ITEM | LIMIT") for h in manifest.headings)
    assert_exact_coverage(manifest)


def test_exact_multiline_unicode_quote_and_changed_quote_rejection():
    text = "1. BENEFITS\nCataract treatment\nis limited to ₹40,000 per eye.\n"
    manifest = build_manifest([page(9, text)])
    excerpt = "Cataract treatment\nis limited to ₹40,000 per eye."
    passage = next(item for item in manifest.passages if excerpt in item.text)
    anchor = manifest.anchor(passage.id, excerpt)
    assert text[anchor.start : anchor.end] == excerpt
    assert anchor.page_number == 9
    for changed in (
        excerpt.replace("\n", " "),
        excerpt.replace("₹", "Rs."),
        excerpt.replace("40,000", "50,000"),
    ):
        with pytest.raises(AnchorError, match="EXCERPT_NOT_FOUND"):
            manifest.anchor(passage.id, changed)


def test_repeated_excerpt_requires_unambiguous_passage_and_rejects_wrong_id():
    repeated = "The same exclusion applies."
    manifest = build_manifest([page(1, repeated + "\n" + repeated), page(2, repeated)])
    first, second = manifest.passages
    with pytest.raises(AnchorError, match="AMBIGUOUS_EXCERPT"):
        manifest.anchor(first.id, repeated)
    anchor = manifest.anchor(second.id, repeated)
    assert (anchor.page_number, anchor.start) == (2, 0)
    with pytest.raises(AnchorError, match="UNKNOWN_PASSAGE"):
        manifest.anchor("pass_does_not_exist", repeated)
    with pytest.raises(AnchorError, match="EXCERPT_NOT_FOUND"):
        manifest.anchor(second.id, "An invented exclusion applies.")
    with pytest.raises(AnchorError, match="SHORT_EXCERPT"):
        manifest.anchor(second.id, "exclusion")


def test_cross_page_clause_requires_separate_physical_page_excerpts():
    first = "The co-payment applies only when"
    second = "the policy schedule lists the insured member."
    manifest = build_manifest([page(1, first), page(2, second)])
    left, right = manifest.passages
    assert manifest.anchor(left.id, first).page_number == 1
    assert manifest.anchor(right.id, second).page_number == 2
    with pytest.raises(AnchorError, match="EXCERPT_NOT_FOUND"):
        manifest.anchor(left.id, first + second)
    with pytest.raises(AnchorError, match="EXCERPT_NOT_FOUND"):
        manifest.anchor(right.id, first)


def test_stable_passage_ids_and_duplicate_page_rejection():
    pages = [page(2, "Second page original text."), page(1, "First page original text.")]
    left = build_manifest(pages)
    right = build_manifest(list(reversed(pages)))
    assert [item.id for item in left.passages] == [item.id for item in right.passages]
    assert [item.id for item in left.sections] == [item.id for item in right.sections]
    changed = build_manifest([page(1, "First page changed text."), pages[0]])
    assert changed.passages[0].id != left.passages[0].id
    with pytest.raises(ValueError, match="Duplicate physical page"):
        build_manifest([page(1, "a"), page(1, "b")])


def test_repeated_page_furniture_does_not_become_section_heading():
    pages = [page(number, "POLICY WORDING\ncontent stays.\n") for number in range(1, 5)]
    manifest = build_manifest(pages)
    assert all(section.heading is None for section in manifest.sections)
    assert_exact_coverage(manifest)


def test_dense_uppercase_page_is_uncertain_instead_of_many_invented_sections():
    text = "".join(f"HEADING NUMBER {index}\n" for index in range(9))
    manifest = build_manifest([page(1, text)])
    assert len(manifest.sections) == 1
    assert manifest.sections[0].status == "unclassified"
    assert len([item for item in manifest.headings if item.confidence == "uncertain"]) == 9
    assert_exact_coverage(manifest)


def test_empty_manifest_and_invalid_passage_bound():
    manifest = build_manifest([])
    assert (manifest.coverage_percent, manifest.total_characters) == (100, 0)
    with pytest.raises(ValueError, match="Passage bound"):
        build_manifest([page(1, "text")], max_passage_characters=31)


@pytest.mark.skipif(
    not os.getenv("OFFLINE_POLICY_PDF"), reason="Local public wording PDF not provided"
)
def test_opt_in_69_page_public_wording_offline():
    path = Path(os.environ["OFFLINE_POLICY_PDF"])
    parsed = parse_isolated(path.read_bytes(), Settings(_env_file=None), extract=True)
    assert parsed.page_count == 69
    manifest = build_manifest(parsed.pages)
    assert manifest.total_characters > 120_000
    assert_exact_coverage(manifest)
    report = summarize(manifest)
    assert report["total_pages"] == 69
    assert report["evidence_anchors_passed"] == report["evidence_anchors_checked"]
