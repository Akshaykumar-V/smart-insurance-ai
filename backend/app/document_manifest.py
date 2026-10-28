"""Offline, exact-text section and passage index for extracted PDF pages.

This module does not classify insurance terms or change the live analysis path.
All offsets are Python character offsets into the original ExtractedPage.text.
"""

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, replace
from typing import Literal

from app.models import ExtractedPage

HeadingConfidence = Literal["likely", "uncertain"]


@dataclass(frozen=True)
class HeadingCandidate:
    page_number: int
    start: int
    end: int
    text: str
    confidence: HeadingConfidence


@dataclass(frozen=True)
class Section:
    id: str
    heading: str | None
    status: Literal["likely", "unclassified"]
    start_page: int
    start_offset: int
    end_page: int
    end_offset: int


@dataclass(frozen=True)
class Passage:
    id: str
    section_id: str
    page_number: int
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class EvidenceAnchor:
    passage_id: str
    page_number: int
    start: int
    end: int
    quote: str


class AnchorError(ValueError):
    """A content-free reason for rejecting an excerpt."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class DocumentManifest:
    pages: tuple[ExtractedPage, ...]
    headings: tuple[HeadingCandidate, ...]
    sections: tuple[Section, ...]
    passages: tuple[Passage, ...]

    @property
    def total_characters(self) -> int:
        return sum(len(page.text) for page in self.pages)

    @property
    def covered_characters(self) -> int:
        return sum(passage.end - passage.start for passage in self.passages)

    @property
    def coverage_percent(self) -> float:
        return (
            100 * self.covered_characters / self.total_characters
            if self.total_characters
            else 100.0
        )

    def anchor(self, passage_id: str, excerpt: str) -> EvidenceAnchor:
        passage = next((item for item in self.passages if item.id == passage_id), None)
        if passage is None:
            raise AnchorError("UNKNOWN_PASSAGE")
        if not isinstance(excerpt, str) or len(excerpt.strip()) < 12:
            raise AnchorError("SHORT_EXCERPT")
        first = passage.text.find(excerpt)
        if first < 0:
            raise AnchorError("EXCERPT_NOT_FOUND")
        if passage.text.find(excerpt, first + 1) >= 0:
            raise AnchorError("AMBIGUOUS_EXCERPT")
        start = passage.start + first
        end = start + len(excerpt)
        page = next(item for item in self.pages if item.page_number == passage.page_number)
        if page.text[start:end] != excerpt:
            raise AnchorError("EXCERPT_NOT_FOUND")
        return EvidenceAnchor(passage.id, passage.page_number, start, end, excerpt)


_NUMBERED = re.compile(r"(?:\d+(?:\.\d+){0,3}[.)]?|[IVX]{1,6}[.)])\s+(.+)", re.I)


def _heading_confidence(line: str, *, repeated: bool) -> HeadingConfidence | None:
    text = line.strip()
    if (
        repeated
        or "|" in text
        or "\t" in line
        or not 4 <= len(text) <= 100
        or text.endswith((".", ";", "?", "!"))
    ):
        return None
    letters = [char for char in text if char.isalpha()]
    if len(letters) < 4:
        return None
    match = _NUMBERED.fullmatch(text)
    if (
        match
        and len(match.group(1).split()) <= 12
        and not re.search(r"\d\s*%|\b(?:INR|Rs\.?|₹)\s*\d", text, re.I)
    ):
        return "likely"
    if len(text.split()) >= 2 and all(char.isupper() for char in letters):
        return "likely"
    if 2 <= len(text.split()) <= 10 and text[0].isupper() and not re.search(r"[,:%]", text):
        return "uncertain"
    return None


def _id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256("\x1f".join(map(str, parts)).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _passage_end(text: str, start: int, limit: int, max_characters: int) -> int:
    hard_end = min(start + max_characters, limit)
    if hard_end == limit:
        return limit
    preferred_start = start + max_characters * 3 // 5
    newline = text.rfind("\n", preferred_start, hard_end)
    if newline >= 0:
        return newline + 1
    whitespace = max((text.rfind(char, preferred_start, hard_end) for char in " \t"), default=-1)
    return whitespace + 1 if whitespace >= 0 else hard_end


def build_manifest(
    pages: list[ExtractedPage], *, max_passage_characters: int = 2400
) -> DocumentManifest:
    if max_passage_characters < 32:
        raise ValueError("Passage bound must be at least 32 characters")
    ordered = tuple(sorted(pages, key=lambda page: page.page_number))
    if len({page.page_number for page in ordered}) != len(ordered):
        raise ValueError("Duplicate physical page number")
    if not ordered:
        return DocumentManifest((), (), (), ())

    # Repeated lines are page furniture candidates, not reliable section identities.
    line_pages: dict[str, set[int]] = {}
    for page in ordered:
        for line in page.text.splitlines():
            key = line.strip().casefold()
            if key:
                line_pages.setdefault(key, set()).add(page.page_number)

    headings: list[HeadingCandidate] = []
    for page in ordered:
        offset = 0
        for line in page.text.splitlines(keepends=True):
            key = line.strip().casefold()
            confidence = _heading_confidence(line, repeated=len(line_pages.get(key, ())) >= 3)
            if confidence:
                headings.append(
                    HeadingCandidate(page.page_number, offset, offset + len(line), line, confidence)
                )
            offset += len(line)

    # Dense lists and tables can look like dozens of uppercase section titles.
    # Keep the candidates, but do not turn that page into invented sections.
    likely_per_page = Counter(h.page_number for h in headings if h.confidence == "likely")
    headings = [
        replace(h, confidence="uncertain")
        if h.confidence == "likely" and likely_per_page[h.page_number] > 8
        else h
        for h in headings
    ]

    section_starts: dict[tuple[int, int], HeadingCandidate | None] = {
        (ordered[0].page_number, 0): None
    }
    for item in headings:
        if item.confidence == "likely":
            section_starts[(item.page_number, item.start)] = item
    # A heading at the first character replaces the unclassified preamble.
    starts = [
        (page, offset, section_starts[(page, offset)]) for page, offset in sorted(section_starts)
    ]
    sections = []
    for index, (page_number, offset, heading) in enumerate(starts):
        end_page, end_offset = (
            starts[index + 1][:2]
            if index + 1 < len(starts)
            else (ordered[-1].page_number, len(ordered[-1].text))
        )
        sections.append(
            Section(
                id=_id("sec", page_number, offset, heading.text if heading else "unclassified"),
                heading=heading.text if heading else None,
                status="likely" if heading else "unclassified",
                start_page=page_number,
                start_offset=offset,
                end_page=end_page,
                end_offset=end_offset,
            )
        )

    passages: list[Passage] = []
    for page in ordered:
        boundaries = sorted(
            {
                0,
                len(page.text),
                *(
                    h.start
                    for h in headings
                    if h.page_number == page.page_number and h.confidence == "likely"
                ),
            }
        )
        for left, right in zip(boundaries, boundaries[1:]):
            section = max(
                (
                    item
                    for item in sections
                    if (item.start_page, item.start_offset) <= (page.page_number, left)
                ),
                key=lambda item: (item.start_page, item.start_offset),
            )
            start = left
            while start < right:
                end = _passage_end(page.text, start, right, max_passage_characters)
                chunk = page.text[start:end]
                passages.append(
                    Passage(
                        _id("pass", page.page_number, start, end, chunk),
                        section.id,
                        page.page_number,
                        start,
                        end,
                        chunk,
                    )
                )
                start = end
    manifest = DocumentManifest(ordered, tuple(headings), tuple(sections), tuple(passages))
    for page in ordered:
        cursor = 0
        for passage in (item for item in passages if item.page_number == page.page_number):
            if (
                passage.start != cursor
                or passage.end > len(page.text)
                or passage.text != page.text[passage.start : passage.end]
            ):
                raise AssertionError("Passage coverage is incomplete")
            cursor = passage.end
        if cursor != len(page.text):
            raise AssertionError("Passage coverage is incomplete")
    return manifest
