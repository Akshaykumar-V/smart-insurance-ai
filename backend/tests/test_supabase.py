import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from app.config import Settings
from app.errors import ApiError
from app.models import UploadResponse
from app.supabase import Principal, SupabaseGateway


def run_with_gateway(handler, operation):
    async def run():
        settings = Settings(
            _env_file=None,
            supabase_url="https://test.supabase.co",
            supabase_publishable_key="public-test-key",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await operation(SupabaseGateway(settings, client))

    return asyncio.run(run())


def test_auth_token_is_validated_remotely():
    owner = str(uuid4())

    def handler(request):
        assert request.url.path == "/auth/v1/user"
        assert request.headers["authorization"] == "Bearer supplied-token"
        assert request.headers["apikey"] == "public-test-key"
        return httpx.Response(200, json={"id": owner})

    result = run_with_gateway(handler, lambda gateway: gateway.authenticate("supplied-token"))
    assert result.user_id == owner
    assert "supplied-token" not in repr(result)


@pytest.mark.parametrize(("status", "expected"), [(401, 401), (403, 401), (429, 429), (500, 500)])
def test_auth_failure_never_exposes_upstream_body(status, expected):
    with pytest.raises(ApiError) as error:
        run_with_gateway(
            lambda request: httpx.Response(status, text="secret upstream detail"),
            lambda gateway: gateway.authenticate("token"),
        )
    assert error.value.status == expected
    assert "secret" not in error.value.message


def test_auth_rejects_invalid_user_response():
    with pytest.raises(ApiError) as error:
        run_with_gateway(
            lambda request: httpx.Response(200, json={"id": "bad-id"}),
            lambda gateway: gateway.authenticate("token"),
        )
    assert error.value.status == 401


def test_network_failure_is_sanitized():
    def handler(request):
        raise httpx.ConnectError("secret", request=request)

    with pytest.raises(ApiError) as error:
        run_with_gateway(handler, lambda gateway: gateway.authenticate("token"))
    assert error.value.code == "UPSTREAM_UNAVAILABLE"


def test_policy_lookup_filters_owner_and_hides_absent_resources():
    principal = Principal(str(uuid4()), "token")
    policy_id = str(uuid4())

    def handler(request):
        assert request.url.params["owner_id"] == f"eq.{principal.user_id}"
        assert request.url.params["id"] == f"eq.{policy_id}"
        return httpx.Response(200, json=[])

    with pytest.raises(ApiError) as error:
        run_with_gateway(handler, lambda gateway: gateway.require_policy(principal, policy_id))
    assert error.value.status == 404


def test_job_lookup_filters_owner_and_maps_error():
    principal = Principal(str(uuid4()), "token")
    job_id, policy_id = str(uuid4()), str(uuid4())

    def handler(request):
        assert request.url.params["owner_id"] == f"eq.{principal.user_id}"
        assert request.url.params["id"] == f"eq.{job_id}"
        return httpx.Response(
            200,
            json=[
                {
                    "id": job_id,
                    "policy_id": policy_id,
                    "status": "failed",
                    "stage": "extracting",
                    "message": "The PDF could not be read safely.",
                    "error_code": "INVALID_PDF",
                }
            ],
        )

    job = run_with_gateway(handler, lambda gateway: gateway.get_job(principal, job_id))
    assert job.job_id == job_id
    assert job.error.code == "INVALID_PDF"


def test_storage_upload_is_private_owner_scoped_and_database_failure_cleans_up():
    principal = Principal(str(uuid4()), "token")
    ids = UploadResponse(policy_id=str(uuid4()), document_id=str(uuid4()), job_id=str(uuid4()))
    path = f"{principal.user_id}/{ids.policy_id}/{ids.document_id}.pdf"
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer token"
        if len(requests) == 1:
            assert request.method == "POST"
            assert request.url.path == f"/storage/v1/object/policy-documents/{path}"
            assert request.content == b"pdf-bytes"
            assert request.headers["x-upsert"] == "false"
            return httpx.Response(200, json={})
        if len(requests) == 2:
            assert request.url.path == "/rest/v1/rpc/create_pdf_upload"
            body = json.loads(request.content)
            assert body["p_path"] == path
            assert "owner_id" not in body  # SQL derives owner from auth.uid().
            return httpx.Response(500, text="private SQL detail")
        assert request.method == "DELETE"
        assert json.loads(request.content) == {"prefixes": [path]}
        return httpx.Response(200, json={})

    with pytest.raises(ApiError):
        run_with_gateway(
            handler,
            lambda gateway: gateway.create_upload(
                principal,
                ids,
                b"pdf-bytes",
                new_policy=True,
                name="fictional.pdf",
                hint="other",
                sha256="0" * 64,
                page_count=1,
            ),
        )
    assert len(requests) == 3


def test_storage_failure_never_creates_database_records():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500)

    with pytest.raises(ApiError):
        run_with_gateway(
            handler,
            lambda gateway: gateway.create_upload(
                Principal(str(uuid4()), "token"),
                UploadResponse(
                    policy_id=str(uuid4()), document_id=str(uuid4()), job_id=str(uuid4())
                ),
                b"pdf",
                new_policy=True,
                name="fictional.pdf",
                hint="other",
                sha256="0" * 64,
                page_count=1,
            ),
        )
    assert len(calls) == 1
