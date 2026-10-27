"""FastAPI + real Supabase adapter + parser, with HTTP mocked (not a live RLS test)."""

import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.supabase import SupabaseGateway


def test_authenticated_upload_job_and_second_user_through_http_adapter(pdf_bytes):
    owner_a, owner_b = str(uuid4()), str(uuid4())
    calls, created = [], {}
    settings = Settings(
        _env_file=None,
        supabase_url="https://offline.invalid",
        supabase_publishable_key="public-test-key",
    )

    def handler(request):
        calls.append((request.method, request.url.path))
        token = request.headers["authorization"]
        assert request.headers["apikey"] == "public-test-key"
        if request.url.path.startswith("/rest/v1/"):
            profile = "Accept-Profile" if request.method == "GET" else "Content-Profile"
            assert request.headers[profile] == "public"
        else:
            assert "Accept-Profile" not in request.headers
            assert "Content-Profile" not in request.headers
        assert token in ("Bearer user-a", "Bearer user-b")
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json={"id": owner_a if token.endswith("a") else owner_b})
        if request.method == "GET":
            owner = owner_a if token.endswith("a") else owner_b
            assert request.url.params["owner_id"] == f"eq.{owner}"
            if request.url.path == "/rest/v1/policies":
                assert request.url.params["id"] == f"eq.{created['p_policy_id']}"
                assert owner == owner_b
                return httpx.Response(200, json=[])
            assert request.url.path == "/rest/v1/analysis_jobs"
            assert request.url.params["id"] == f"eq.{created['p_job_id']}"
            return httpx.Response(
                200,
                json=[]
                if owner == owner_b
                else [
                    {
                        "id": created["p_job_id"],
                        "policy_id": created["p_policy_id"],
                        "status": "needs_review",
                        "stage": "extracting",
                        "message": created["p_message"],
                        "error_code": None,
                    }
                ],
            )
        assert token == "Bearer user-a"
        if request.url.path.startswith("/storage/v1/object/policy-documents/"):
            assert request.content == pdf_bytes
            assert request.headers["content-type"] == "application/pdf"
            assert request.headers["x-upsert"] == "false"
            created["storage_path"] = request.url.path.split("policy-documents/", 1)[1]
        else:
            payload = json.loads(request.content)
            if request.url.path == "/rest/v1/rpc/create_pdf_upload":
                assert payload["p_new_policy"] is True
                assert payload["p_hint"] == "policy_wording"
                assert payload["p_path"] == created["storage_path"]
                assert payload["p_path"] == (
                    f"{owner_a}/{payload['p_policy_id']}/{payload['p_document_id']}.pdf"
                )
                assert "owner_id" not in payload
                created.update(payload)
            elif request.url.path == "/rest/v1/rpc/start_pdf_extraction":
                assert payload == {"p_job_id": created["p_job_id"]}
            else:
                assert request.url.path == "/rest/v1/rpc/finish_pdf_extraction"
                assert payload["p_job_id"] == created["p_job_id"]
                assert payload["p_error_code"] is None
                assert [page["page_number"] for page in payload["p_pages"]] == [1, 2]
                assert payload["p_pages"][0]["text"] == "Fictional wording. Printed page 99.\n"
                created.update(payload)
        return httpx.Response(200, json={})

    # MockTransport has no network resources; TestClient owns the async execution.
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = SupabaseGateway(settings, upstream)
    a, b = {"Authorization": "Bearer user-a"}, {"Authorization": "Bearer user-b"}
    with TestClient(create_app(settings, gateway)) as client:
        response = client.post(
            "/api/v1/policies/upload",
            headers=a,
            files={"file": ("fictional.pdf", pdf_bytes, "application/pdf")},
            data={"document_type_hint": "policy_wording", "owner_id": owner_b},
        )
        assert response.status_code == 202
        ids = response.json()
        assert ids["status"] == "queued"
        job = client.get(f"/api/v1/jobs/{ids['job_id']}", headers=a)
        assert job.status_code == 200
        assert job.json()["status"] == "needs_review"
        assert "AI analysis is not implemented" in job.json()["message"]
        before = len([call for call in calls if call[0] == "POST"])
        assert client.get(f"/api/v1/jobs/{ids['job_id']}", headers=b).status_code == 404
        denied = client.post(
            "/api/v1/policies/upload",
            headers=b,
            files={"file": ("fictional.pdf", pdf_bytes, "application/pdf")},
            data={"policy_id": ids["policy_id"]},
        )
        assert denied.status_code == 404
        assert len([call for call in calls if call[0] == "POST"]) == before
    assert [path.rsplit("/", 1)[-1] for method, path in calls if "/rpc/" in path] == [
        "create_pdf_upload",
        "start_pdf_extraction",
        "finish_pdf_extraction",
    ]


@pytest.mark.parametrize("upstream_status", [401, 403])
def test_invalid_or_expired_token_never_reaches_storage(pdf_bytes, upstream_status):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(upstream_status, text="private auth detail")

    settings = Settings(
        _env_file=None, supabase_url="https://offline.invalid", supabase_publishable_key="public"
    )
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with TestClient(create_app(settings, SupabaseGateway(settings, upstream))) as client:
        headers = {"Authorization": "Bearer expired-or-invalid"}
        upload = client.post(
            "/api/v1/policies/upload",
            headers=headers,
            files={"file": ("fictional.pdf", pdf_bytes, "application/pdf")},
        )
        job = client.get(f"/api/v1/jobs/{uuid4()}", headers=headers)
        for response in (upload, job):
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "UNAUTHENTICATED"
            assert "private auth detail" not in response.text
    assert calls == ["/auth/v1/user", "/auth/v1/user"]
