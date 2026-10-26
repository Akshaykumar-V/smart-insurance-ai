import subprocess

import pymupdf
import pytest
from conftest import make_pdf
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import ApiError
from app.main import create_app


def upload(client, headers, pdf_data, **kwargs):
    return client.post(
        "/api/v1/policies/upload",
        headers=headers,
        files={"file": ("wording.pdf", pdf_data, "application/pdf")},
        **kwargs,
    )


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert set(error) == {"code", "message", "request_id"}
    assert error["code"] == code
    assert error["request_id"] == response.headers["x-request-id"]


def test_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


def test_openapi_matches_upload_validation_status(client):
    schema = client.get("/openapi.json").json()
    responses = schema["paths"]["/api/v1/policies/upload"]["post"]["responses"]
    assert "202" in responses
    assert "400" in responses
    assert "422" not in responses


@pytest.mark.parametrize("user_password", ["secret", ""])
def test_encrypted_upload_rejected_before_storage(client, headers, gateway, user_password):
    data = make_pdf(
        encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner-secret", user_pw=user_password
    )
    assert_error(upload(client, headers, data), 400, "ENCRYPTED_PDF")
    assert gateway.documents == {}


def test_image_only_scan_preserves_page_and_requests_review(client, headers, gateway):
    with pymupdf.open() as document:
        page = document.new_page()
        pixels = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 10, 10), False)
        pixels.clear_with(200)
        page.insert_image(page.rect, pixmap=pixels)
        data = document.tobytes()
    response = upload(client, headers, data)
    assert response.status_code == 202
    extracted = gateway.pages[response.json()["document_id"]]
    assert len(extracted) == 1
    assert extracted[0].page_number == 1
    assert extracted[0].text == ""
    assert extracted[0].extraction_quality == "no_text"


def test_upload_contract_pages_and_job(client, headers, gateway):
    response = upload(client, headers, make_pdf(("Printed page 99", "", "Printed page 1")))
    assert response.status_code == 202
    ids = response.json()
    assert set(ids) == {"policy_id", "document_id", "job_id", "status"}
    assert ids["status"] == "queued"
    assert gateway.transitions == ["queued", "processing", "needs_review"]
    pages = gateway.pages[ids["document_id"]]
    assert [p.page_number for p in pages] == [1, 2, 3]
    assert pages[0].text == "Printed page 99\n"
    assert pages[1].text == ""
    assert pages[1].extraction_quality == "no_text"
    assert pages[2].text == "Printed page 1\n"
    job = client.get(f"/api/v1/jobs/{ids['job_id']}", headers=headers)
    assert job.status_code == 200
    assert set(job.json()) == {"job_id", "policy_id", "status", "stage", "message", "error"}
    assert job.json()["status"] == "needs_review"
    assert job.json()["stage"] == "extracting"
    assert job.json()["error"] is None
    assert "OCR is not implemented" in job.json()["message"]


def test_readable_pdf_never_claims_ai_analysis(client, headers, pdf_bytes):
    ids = upload(client, headers, pdf_bytes).json()
    job = client.get(f"/api/v1/jobs/{ids['job_id']}", headers=headers).json()
    assert job["status"] == "needs_review"
    assert "AI analysis is not implemented" in job["message"]


def test_attach_to_owned_policy(client, headers, pdf_bytes, gateway):
    first = upload(client, headers, pdf_bytes).json()
    second = upload(
        client,
        headers,
        pdf_bytes,
        data={"policy_id": first["policy_id"], "document_type_hint": "policy_schedule"},
    )
    assert second.status_code == 202
    assert second.json()["policy_id"] == first["policy_id"]
    assert second.json()["document_id"] != first["document_id"]
    assert len(gateway.policies) == 1
    assert gateway.documents[second.json()["document_id"]]["hint"] == "policy_schedule"


def test_second_user_cannot_read_job_or_attach_document(client, headers, pdf_bytes, gateway):
    ids = upload(client, headers, pdf_bytes).json()
    second_user = {"Authorization": "Bearer owner-b"}
    assert_error(client.get(f"/api/v1/jobs/{ids['job_id']}", headers=second_user), 404, "NOT_FOUND")
    assert_error(
        upload(client, second_user, pdf_bytes, data={"policy_id": ids["policy_id"]}),
        404,
        "NOT_FOUND",
    )
    assert len(gateway.documents) == 1


@pytest.mark.parametrize(
    "auth", [{}, {"Authorization": "Bearer invalid"}, {"Authorization": "Basic owner-a"}]
)
def test_authentication_required(client, pdf_bytes, auth):
    assert_error(upload(client, auth, pdf_bytes), 401, "UNAUTHENTICATED")
    assert_error(client.get("/api/v1/jobs/unknown", headers=auth), 401, "UNAUTHENTICATED")


@pytest.mark.parametrize(
    ("data", "code"),
    [(b"", "EMPTY_FILE"), (b"not a pdf", "INVALID_PDF"), (b"%PDF-1.7\ncorrupted", "INVALID_PDF")],
)
def test_invalid_pdf_creates_no_records(client, headers, gateway, data, code):
    assert_error(upload(client, headers, data), 400, code)
    assert gateway.documents == {}
    assert gateway.jobs == {}


@pytest.mark.parametrize(
    ("name", "mime"),
    [("photo.png", "image/png"), ("fake.pdf", "text/plain"), ("file.txt", "application/pdf")],
)
def test_unsupported_file(client, headers, pdf_bytes, name, mime):
    response = client.post(
        "/api/v1/policies/upload", headers=headers, files={"file": (name, pdf_bytes, mime)}
    )
    assert_error(response, 400, "UNSUPPORTED_FILE")


def test_binary_mime_accepted_only_for_pdf(client, headers, pdf_bytes, gateway):
    response = client.post(
        "/api/v1/policies/upload",
        headers=headers,
        files={"file": ("../wording.PDF", pdf_bytes, "application/octet-stream")},
    )
    assert response.status_code == 202
    assert gateway.documents[response.json()["document_id"]]["name"] == "wording.PDF"


def test_invalid_form_fields(client, headers, pdf_bytes):
    assert_error(
        upload(client, headers, pdf_bytes, data={"document_type_hint": "invented"}),
        400,
        "INVALID_FIELDS",
    )
    assert_error(client.post("/api/v1/policies/upload", headers=headers), 400, "INVALID_FIELDS")


def test_oversized_file(client, headers, settings):
    assert_error(
        upload(client, headers, b"x" * (settings.max_upload_bytes + 1)), 413, "FILE_TOO_LARGE"
    )


def test_whole_request_limit(client, headers, settings):
    response = client.post(
        "/api/v1/policies/upload",
        headers=headers,
        content=b"x" * (settings.max_upload_bytes + 1024 * 1024 + 1),
    )
    assert_error(response, 413, "FILE_TOO_LARGE")


def test_page_limit(client, headers, settings):
    assert_error(
        upload(client, headers, make_pdf([""] * (settings.max_pdf_pages + 1))),
        400,
        "TOO_MANY_PAGES",
    )


def test_blank_pdf_needs_review_without_fabricating_text(client, headers, gateway):
    ids = upload(client, headers, make_pdf(("",))).json()
    assert gateway.pages[ids["document_id"]][0].text == ""
    assert gateway.jobs[ids["job_id"]]["response"].status == "needs_review"


def test_background_failure_is_pollable(client, headers, pdf_bytes, monkeypatch):
    from app import main

    real_parse = main.parse_isolated

    def failing_extraction(data, settings, *, extract):
        if extract:
            raise ApiError(400, "PDF_TIMEOUT", "The PDF took too long to read safely.")
        return real_parse(data, settings, extract=False)

    monkeypatch.setattr(main, "parse_isolated", failing_extraction)
    ids = upload(client, headers, pdf_bytes).json()
    job = client.get(f"/api/v1/jobs/{ids['job_id']}", headers=headers).json()
    assert job["status"] == "failed"
    assert job["error"]["code"] == "PDF_TIMEOUT"


def test_upstream_error_is_sanitized(client, headers, pdf_bytes, gateway, monkeypatch, caplog):
    async def broken(*args, **kwargs):
        raise RuntimeError("PRIVATE PDF TEXT AND SECRET TOKEN")

    monkeypatch.setattr(gateway, "create_upload", broken)
    response = upload(client, headers, pdf_bytes)
    assert_error(response, 500, "INTERNAL_ERROR")
    assert "PRIVATE" not in response.text + caplog.text


def test_health_without_supabase_and_upload_fails_closed(pdf_bytes):
    with TestClient(create_app(Settings(_env_file=None))) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert_error(
            upload(client, {"Authorization": "Bearer anything"}, pdf_bytes),
            500,
            "BACKEND_NOT_CONFIGURED",
        )


def test_unknown_job(client, headers):
    assert_error(client.get("/api/v1/jobs/unknown", headers=headers), 404, "NOT_FOUND")


def test_parser_timeout_is_safe(client, headers, pdf_bytes, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("parser", 20)

    monkeypatch.setattr("app.pdf.subprocess.run", timeout)
    assert_error(upload(client, headers, pdf_bytes), 400, "PDF_TIMEOUT")
