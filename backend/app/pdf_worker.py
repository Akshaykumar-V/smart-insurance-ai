"""Disposable parser process. Never print PDF content or parser diagnostics to logs."""

import json
import sys

import pymupdf

from app.errors import ApiError
from app.models import ExtractedPage, ParsedPdf


def parse_pdf(data: bytes, max_pages: int, max_characters: int, extract: bool) -> ParsedPdf:
    if not data:
        raise ApiError(400, "EMPTY_FILE", "The uploaded file is empty.")
    if not data.startswith(b"%PDF-"):
        raise ApiError(400, "INVALID_PDF", "Upload a valid PDF document.")
    try:
        with pymupdf.open(stream=data, filetype="pdf") as document:
            if document.needs_pass or (document.metadata or {}).get("encryption"):
                raise ApiError(400, "ENCRYPTED_PDF", "Upload an unencrypted copy of the PDF.")
            if document.is_repaired:
                raise ApiError(400, "INVALID_PDF", "The PDF is damaged. Export a new copy.")
            if document.page_count == 0:
                raise ApiError(400, "EMPTY_PDF", "The PDF has no pages.")
            if document.page_count > max_pages:
                raise ApiError(400, "TOO_MANY_PAGES", "The PDF exceeds the page limit.")
            pages = []
            total = 0
            if extract:
                for index, page in enumerate(document):
                    # Keep the actual extracted text, including whitespace and blank pages.
                    text = page.get_text("text", sort=False)
                    total += len(text)
                    if total > max_characters:
                        raise ApiError(
                            400, "TEXT_LIMIT_EXCEEDED", "The PDF text exceeds the limit."
                        )
                    quality = "text_present"
                    if not text.strip():
                        quality = "no_text"
                    elif "\ufffd" in text or "\x00" in text:
                        quality = "needs_review"
                    pages.append(
                        ExtractedPage(
                            page_number=index + 1,
                            text=text,
                            extraction_quality=quality,
                        )
                    )
            return ParsedPdf(page_count=document.page_count, pages=pages)
    except ApiError:
        raise
    except Exception:
        raise ApiError(400, "INVALID_PDF", "The PDF could not be read safely.") from None


if __name__ == "__main__":
    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    try:
        result = parse_pdf(
            sys.stdin.buffer.read(int(sys.argv[4]) + 1),
            int(sys.argv[1]),
            int(sys.argv[2]),
            sys.argv[3] == "extract",
        )
        sys.stdout.buffer.write(result.model_dump_json().encode("utf-8") + b"\n")
    except ApiError as exc:
        print(
            json.dumps({"error": {"status": exc.status, "code": exc.code, "message": exc.message}})
        )
