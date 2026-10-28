import subprocess

import pymupdf
import pytest
from conftest import make_pdf

from app.config import Settings
from app.errors import ApiError
from app.pdf import parse_isolated
from app.pdf_worker import parse_pdf


@pytest.mark.parametrize("user_password", ["secret", ""])
def test_password_and_owner_only_encryption_are_rejected(user_password):
    data = make_pdf(
        encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner-secret", user_pw=user_password
    )
    with pytest.raises(ApiError) as error:
        parse_pdf(data, 200, 2_000_000, True)
    assert error.value.code == "ENCRYPTED_PDF"


def test_repaired_pdf_is_rejected(pdf_bytes):
    data = pdf_bytes[: pdf_bytes.rfind(b"xref")]
    with pytest.raises(ApiError) as error:
        parse_pdf(data, 200, 2_000_000, True)
    assert error.value.code == "INVALID_PDF"


def test_zero_page_pdf():
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n",
    ]
    data = b"%PDF-1.4\n"
    offsets = []
    for obj in objects:
        offsets.append(len(data))
        data += obj
    xref = len(data)
    data += b"xref\n0 3\n0000000000 65535 f \n"
    for offset in offsets:
        data += f"{offset:010d} 00000 n \n".encode()
    data += f"trailer\n<< /Size 3 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    with pytest.raises(ApiError) as error:
        parse_pdf(data, 200, 2_000_000, True)
    assert error.value.code == "EMPTY_PDF"


def test_character_limit(pdf_bytes):
    with pytest.raises(ApiError) as error:
        parse_pdf(pdf_bytes, 200, 5, True)
    assert error.value.code == "TEXT_LIMIT_EXCEEDED"


def test_process_roundtrip_preserves_pages(pdf_bytes, settings):
    result = parse_isolated(pdf_bytes, settings, extract=True)
    assert result.page_count == 2
    assert [p.page_number for p in result.pages] == [1, 2]
    assert result.pages[0].text == "Fictional wording. Printed page 99.\n"


def test_process_roundtrip_preserves_non_cp1252_text(monkeypatch):
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_htmlbox(
            pymupdf.Rect(50, 50, 550, 200),
            "<p>Fictional clause: &#8377;40,000 limit and Greek &#945;.</p>",
        )
        data = document.tobytes()
    settings = Settings(_env_file=None, max_upload_bytes=1_000_000)
    expected = parse_pdf(data, settings.max_pdf_pages, settings.max_extracted_characters, True)
    assert "\u20b9" in expected.pages[0].text
    assert "\u03b1" in expected.pages[0].text

    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    actual = parse_isolated(data, settings, extract=True)
    assert actual.page_count == 1
    assert actual.pages[0].text == expected.pages[0].text


@pytest.mark.parametrize(("returncode", "output"), [(1, b""), (0, b"invalid json"), (0, b"{}")])
def test_parser_crash_or_invalid_output(settings, monkeypatch, returncode, output):
    monkeypatch.setattr(
        "app.pdf.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(a, returncode, stdout=output),
    )
    with pytest.raises(ApiError) as error:
        parse_isolated(b"%PDF-", settings, extract=True)
    assert error.value.code == "INVALID_PDF"
