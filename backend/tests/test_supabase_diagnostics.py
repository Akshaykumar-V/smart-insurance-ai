"""Demonstrate error masking safely using mocked upstream responses only."""

import asyncio
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.diagnostics import Operation, request_id_context, safe_upstream_code
from app.errors import ApiError
from app.main import create_app
from app.supabase import SupabaseGateway


@pytest.mark.parametrize(
    ("stage", "status", "code", "cleanup_fails", "api_status"),
    [
        ("storage_upload", 400, "AccessDenied", False, 500),
        ("create_pdf_upload", 404, "PGRST202", False, 500),
        ("create_pdf_upload", 400, "23514", True, 500),
        ("create_pdf_upload", 403, "42501", False, 401),
        ("create_pdf_upload", 300, "PGRST203", False, 500),
    ],
)
def test_upload_diagnostics_and_compensation(
    pdf_bytes, caplog, stage, status, code, cleanup_fails, api_status
):
    owner = str(uuid4())
    calls = []
    secret = "PRIVATE-CREDENTIAL-DOCUMENT-AND-SIGNED-URL"
    settings = Settings(
        _env_file=None,
        supabase_url="https://offline.invalid",
        supabase_publishable_key=secret,
    )

    def handler(request):
        calls.append(request)
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json={"id": owner})
        if request.method == "DELETE":
            return httpx.Response(503 if cleanup_fails else 200, text=secret)
        if stage == "storage_upload" or request.url.path == "/rest/v1/rpc/create_pdf_upload":
            return httpx.Response(
                status,
                json={
                    "code": code,
                    "message": secret,
                    "details": secret,
                    "hint": secret,
                    "originalError": {"message": secret},
                },
                headers={"Location": "https://offline.invalid/?token=" + secret},
            )
        return httpx.Response(200, json={})

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with TestClient(create_app(settings, SupabaseGateway(settings, upstream))) as client:
            response = client.post(
                "/api/v1/policies/upload",
                headers={
                    "Authorization": "Bearer " + secret,
                    "X-Request-ID": secret,
                },
                files={"file": (secret + ".pdf", pdf_bytes, "application/pdf")},
            )
    finally:
        asyncio.run(upstream.aclose())
    assert response.status_code == api_status
    error = response.json()["error"]
    assert set(error) == {"code", "message", "request_id"}
    assert error["code"] == ("UNAUTHENTICATED" if api_status == 401 else "UPSTREAM_ERROR")
    request_id = response.headers["x-request-id"]
    assert str(UUID(request_id)) == error["request_id"]
    records = [record for record in caplog.records if record.name == "app.supabase"]
    diagnostics = [
        record.getMessage()
        for record in records
        if record.getMessage().startswith("supabase_request_failed")
    ]
    assert diagnostics[0] == (
        f"supabase_request_failed operation={stage} upstream_status={status} "
        f"upstream_code={code} failure=http request_id={request_id}"
    )
    assert len(diagnostics) == (2 if cleanup_fails else 1)
    if cleanup_fails:
        assert "operation=storage_cleanup upstream_status=503" in diagnostics[1]
        assert diagnostics[1].endswith("request_id=" + request_id)
    # A secondary cleanup failure must not overwrite the primary RPC error.
    assert [req.method for req in calls] == (
        ["GET", "POST"] if stage == "storage_upload" else ["GET", "POST", "POST", "DELETE"]
    )
    assert secret not in caplog.text + response.text
    assert owner not in caplog.text
    assert "offline.invalid" not in caplog.text
    assert all(record.exc_info is None for record in records)
    assert request_id_context.get() == "none"


@pytest.mark.parametrize(
    "payload",
    [
        {"code": "untrusted-secret-code", "message": "secret"},
        {"code": ["PGRST202"]},
        {"code": {"secret": "value"}},
        {"message": "PGRST202"},
        ["PGRST202"],
        None,
    ],
)
def test_only_exact_allowlisted_top_level_codes_are_logged(payload):
    assert safe_upstream_code(httpx.Response(400, json=payload)) == "unknown"


@pytest.mark.parametrize(
    "body",
    [b"<html>secret</html>", b"x" * 65537, b"[" * 2000 + b"]" * 2000],
    ids=["invalid-json", "oversized-body", "deeply-nested-body"],
)
def test_non_json_and_large_error_bodies_are_not_logged(body):
    assert safe_upstream_code(httpx.Response(500, content=body)) == "unknown"


@pytest.mark.parametrize("status", [300, 302])
def test_rpc_non_success_is_not_mistaken_for_success(status, caplog):
    async def run():
        settings = Settings(
            _env_file=None,
            supabase_url="https://offline.invalid",
            supabase_publishable_key="public-key",
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status, json={"code": "PGRST203"})
            )
        ) as upstream:
            gateway = SupabaseGateway(settings, upstream)
            with pytest.raises(ApiError) as error:
                await gateway.request(
                    "POST",
                    "/rest/v1/rpc/create_pdf_upload",
                    "private-token",
                    operation=Operation.CREATE_UPLOAD,
                )
            assert error.value.code == "UPSTREAM_ERROR"

    asyncio.run(run())
    assert f"upstream_status={status}" in caplog.text


def test_transport_failure_has_no_invented_http_status(caplog):
    def handler(request):
        raise httpx.ConnectError("SECRET exception and URL", request=request)

    async def run():
        settings = Settings(
            _env_file=None,
            supabase_url="https://offline.invalid",
            supabase_publishable_key="public-key",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
            gateway = SupabaseGateway(settings, upstream)
            with pytest.raises(ApiError) as error:
                await gateway.authenticate("PRIVATE-TOKEN")
            assert error.value.code == "UPSTREAM_UNAVAILABLE"

    asyncio.run(run())
    assert (
        "operation=auth_user upstream_status=none upstream_code=none failure=transport"
        in caplog.text
    )
    assert "SECRET" not in caplog.text
    assert "PRIVATE-TOKEN" not in caplog.text


def test_missing_configuration_is_distinct_from_http_failure(caplog, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_PUBLISHABLE_KEY", raising=False)

    async def run():
        async with httpx.AsyncClient() as upstream:
            with pytest.raises(ApiError) as error:
                await SupabaseGateway(Settings(_env_file=None), upstream).authenticate("token")
            assert error.value.code == "BACKEND_NOT_CONFIGURED"

    asyncio.run(run())
    assert "upstream_status=none upstream_code=none failure=not_configured" in caplog.text
