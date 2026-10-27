"""Gateway regressions; DB enforcement itself is verified by the opt-in live cases."""

import asyncio
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.diagnostics import Operation, safe_upstream_code
from app.errors import ApiError
from app.main import create_app
from app.models import ExtractedPage, ParsedPdf
from app.supabase import Principal, SupabaseGateway


@pytest.mark.parametrize("action", ["start", "finish"])
@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (204, None, None),
        (404, "PT404", (404, "NOT_FOUND")),
        (404, "PGRST202", (500, "UPSTREAM_ERROR")),
        (500, "P0002", (500, "UPSTREAM_ERROR")),
        (500, "XX000", (500, "UPSTREAM_ERROR")),
        (500, "PT404", (500, "UPSTREAM_ERROR")),
    ],
)
def test_job_rpc_errors_are_narrowly_mapped(action, status, code, expected, caplog):
    job_id, owner_id = str(uuid4()), str(uuid4())
    secret = "PRIVATE-TOKEN-AND-ERROR-BODY"
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path == f"/rest/v1/rpc/{action}_pdf_extraction"
        assert request.headers["Authorization"] == f"Bearer {secret}"
        assert request.headers["Content-Profile"] == "public"
        if status == 204:
            return httpx.Response(204)
        return httpx.Response(status, json={"code": code, "message": secret, "details": secret})

    async def run():
        settings = Settings(
            _env_file=None,
            supabase_url="https://offline.invalid",
            supabase_publishable_key="public-key",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
            gateway = SupabaseGateway(settings, upstream)
            principal = Principal(owner_id, secret)
            if action == "start":
                operation = gateway.start_job(principal, job_id)
            else:
                parsed = ParsedPdf(
                    page_count=1,
                    pages=[
                        ExtractedPage(
                            page_number=1, text="Fictional", extraction_quality="text_present"
                        )
                    ],
                )
                operation = gateway.finish_job(principal, job_id, parsed, code=None, message="Done")
            if expected is None:
                await operation
            else:
                with pytest.raises(ApiError) as error:
                    await operation
                assert (error.value.status, error.value.code) == expected
                assert secret not in error.value.message
                if expected[0] == 404:
                    assert error.value.message == "Job not found."

    asyncio.run(run())
    assert len(calls) == 1
    assert secret not in caplog.text
    if status != 204:
        assert f"operation={action}_pdf_extraction upstream_status={status}" in caplog.text
    if code == "P0002":
        assert "upstream_code=P0002" in caplog.text


def test_pt404_on_unrelated_rpc_is_not_mapped_to_job_not_found():
    async def run():
        settings = Settings(
            _env_file=None,
            supabase_url="https://offline.invalid",
            supabase_publishable_key="public-key",
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(404, json={"code": "PT404"})
            )
        ) as upstream:
            with pytest.raises(ApiError) as error:
                await SupabaseGateway(settings, upstream).request(
                    "POST",
                    "/rest/v1/rpc/create_pdf_upload",
                    "token",
                    operation=Operation.CREATE_UPLOAD,
                )
            assert error.value.status == 500
            assert error.value.code == "UPSTREAM_ERROR"

    asyncio.run(run())


@pytest.mark.parametrize(("status", "code"), [(500, "P0002"), (404, "PT404")])
def test_direct_rpc_denial_diagnostics_are_safe(status, code, caplog):
    from test_supabase_live import assert_hidden_job

    response = httpx.Response(status, json={"code": code, "message": "PRIVATE BODY"})
    if status == 500:
        with pytest.raises(AssertionError):
            assert_hidden_job(response, Operation.START_EXTRACTION)
    else:
        assert_hidden_job(response, Operation.START_EXTRACTION)
    assert f"upstream_status={status} upstream_code={code}" in caplog.text
    assert "PRIVATE BODY" not in caplog.text
    assert safe_upstream_code(response) == code


@pytest.mark.parametrize(
    ("case", "status"),
    [
        ("owner", 200),
        ("cross-user", 404),
        ("missing", 404),
        ("database-failure", 500),
    ],
)
def test_public_job_access_error_envelope(case, status, caplog):
    """Actual API handler and gateway; HTTP doubles do not prove deployed RLS."""
    owner, outsider, job_id, policy_id = (str(uuid4()) for _ in range(4))
    caller = outsider if case == "cross-user" else owner
    private_detail = "PRIVATE-DATABASE-DETAIL"
    settings = Settings(
        _env_file=None,
        supabase_url="https://offline.invalid",
        supabase_publishable_key="public-key",
    )

    def handler(request):
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json={"id": caller})
        assert request.url.path == "/rest/v1/analysis_jobs"
        assert request.url.params["owner_id"] == f"eq.{caller}"
        assert request.url.params["id"] == f"eq.{job_id}"
        assert request.headers["Accept-Profile"] == "public"
        if case == "database-failure":
            return httpx.Response(500, json={"code": "P0002", "message": private_detail})
        rows = (
            []
            if case != "owner"
            else [
                {
                    "id": job_id,
                    "policy_id": policy_id,
                    "status": "processing",
                    "stage": "extracting",
                    "message": "Reading policy pages",
                    "error_code": None,
                }
            ]
        )
        return httpx.Response(200, json=rows)

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with TestClient(create_app(settings, SupabaseGateway(settings, upstream))) as client:
            response = client.get(
                f"/api/v1/jobs/{job_id}", headers={"Authorization": "Bearer fixture-token"}
            )
    finally:
        asyncio.run(upstream.aclose())
    assert response.status_code == status
    if status == 200:
        assert response.json()["job_id"] == job_id
        assert response.json()["status"] == "processing"
    else:
        error = response.json()["error"]
        assert set(error) == {"code", "message", "request_id"}
        assert error["request_id"] == response.headers["x-request-id"]
        assert error["code"] == ("NOT_FOUND" if status == 404 else "UPSTREAM_ERROR")
        if status == 404:
            assert error["message"] == "Job not found."
        assert job_id not in response.text
        assert owner not in response.text
    assert private_detail not in response.text + caplog.text


@pytest.mark.parametrize(
    ("operation", "path"),
    [
        (Operation.START_EXTRACTION, "/rest/v1/rpc/create_pdf_upload"),
        (Operation.CREATE_UPLOAD, "/rest/v1/rpc/start_pdf_extraction"),
    ],
)
def test_job_not_found_requires_matching_operation_and_path(operation, path):
    async def run():
        settings = Settings(
            _env_file=None,
            supabase_url="https://offline.invalid",
            supabase_publishable_key="public-key",
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(404, json={"code": "PT404"})
            )
        ) as upstream:
            with pytest.raises(ApiError) as error:
                await SupabaseGateway(settings, upstream).request(
                    "POST",
                    path,
                    "token",
                    operation=operation,
                )
            assert error.value.status == 500
            assert error.value.code == "UPSTREAM_ERROR"

    asyncio.run(run())
