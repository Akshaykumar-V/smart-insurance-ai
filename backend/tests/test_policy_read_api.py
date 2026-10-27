"""Owner-scoped policy wallet APIs using mocked Supabase HTTP responses."""

import asyncio
from contextlib import contextmanager
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.supabase import SupabaseGateway

OWNER_A = str(uuid4())
OWNER_B = str(uuid4())
POLICY_ID = str(uuid4())
DOCUMENT_ID = str(uuid4())


@contextmanager
def api_client(handler):
    settings = Settings(
        _env_file=None,
        supabase_url="https://offline.invalid",
        supabase_publishable_key="fixture-public-key",
    )
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with TestClient(create_app(settings, SupabaseGateway(settings, upstream))) as client:
            yield client
    finally:
        asyncio.run(upstream.aclose())


def policy_row(**overrides):
    return {
        "id": POLICY_ID,
        "category": "health",
        "policy_type": "family_floater",
        "insurer": "Fictional Health Insurer",
        "product_name": "Demo Family Cover",
        "uin": "FHI-2026-DEMO",
        "policyholder_name": None,
        "sum_insured_paise": 50000000,
        "start_date": None,
        "end_date": None,
        "analysis_status": "needs_review",
        **overrides,
    }


def test_policy_list_returns_owner_rows_in_contract_shape():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/auth/v1/user":
            assert request.headers["authorization"] == "Bearer user-a"
            return httpx.Response(200, json={"id": OWNER_A})
        assert request.url.path == "/rest/v1/policies"
        assert request.headers["Accept-Profile"] == "public"
        assert request.url.params["owner_id"] == f"eq.{OWNER_A}"
        assert request.url.params["select"] == (
            "id,category,policy_type,insurer,product_name,sum_insured_paise,"
            "start_date,end_date,analysis_status"
        )
        assert request.url.params["order"] == "created_at.desc,id.desc"
        return httpx.Response(200, json=[policy_row()])

    with api_client(handler) as client:
        response = client.get("/api/v1/policies", headers={"Authorization": "Bearer user-a"})

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": POLICY_ID,
                "category": "health",
                "policy_type": "family_floater",
                "insurer": "Fictional Health Insurer",
                "product_name": "Demo Family Cover",
                "sum_insured_paise": 50000000,
                "start_date": None,
                "end_date": None,
                "analysis_status": "needs_review",
                "needs_review": True,
            }
        ],
        "next_cursor": None,
    }
    assert calls == ["/auth/v1/user", "/rest/v1/policies"]


def test_policy_list_returns_empty_items_for_new_user():
    def handler(request):
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json={"id": OWNER_A})
        assert request.url.path == "/rest/v1/policies"
        assert request.url.params["owner_id"] == f"eq.{OWNER_A}"
        return httpx.Response(200, json=[])

    with api_client(handler) as client:
        response = client.get("/api/v1/policies", headers={"Authorization": "Bearer user-a"})

    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


def test_policy_list_reads_all_owner_rows_across_supabase_pages():
    page_ids = [str(uuid4()) for _ in range(101)]
    offsets = []

    def handler(request):
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json={"id": OWNER_A})
        assert request.url.path == "/rest/v1/policies"
        assert request.url.params["owner_id"] == f"eq.{OWNER_A}"
        offset = int(request.url.params["offset"])
        offsets.append(offset)
        start = offset
        return httpx.Response(
            200,
            json=[policy_row(id=policy_id) for policy_id in page_ids[start : start + 100]],
        )

    with api_client(handler) as client:
        response = client.get("/api/v1/policies", headers={"Authorization": "Bearer user-a"})

    assert response.status_code == 200
    assert len(response.json()["items"]) == 101
    assert offsets == [0, 100]


def test_policy_detail_returns_minimal_metadata_and_owner_documents():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json={"id": OWNER_A})
        assert request.headers["Accept-Profile"] == "public"
        assert request.url.params["owner_id"] == f"eq.{OWNER_A}"
        if request.url.path == "/rest/v1/policies":
            assert request.url.params["id"] == f"eq.{POLICY_ID}"
            assert "storage_path" not in request.url.params["select"]
            return httpx.Response(200, json=[policy_row()])
        assert request.url.path == "/rest/v1/documents"
        assert request.url.params["policy_id"] == f"eq.{POLICY_ID}"
        assert request.url.params["select"] == "id,type,file_name,page_count,processing_status"
        assert "storage_path" not in request.url.params["select"]
        assert "sha256" not in request.url.params["select"]
        return httpx.Response(
            200,
            json=[
                {
                    "id": DOCUMENT_ID,
                    "type": "policy_wording",
                    "file_name": "fictional-wording.pdf",
                    "page_count": 2,
                    "processing_status": "needs_review",
                }
            ],
        )

    with api_client(handler) as client:
        response = client.get(
            f"/api/v1/policies/{POLICY_ID}", headers={"Authorization": "Bearer user-a"}
        )

    assert response.status_code == 200
    assert response.json() == {
        "id": POLICY_ID,
        "category": "health",
        "policy_type": "family_floater",
        "insurer": "Fictional Health Insurer",
        "product_name": "Demo Family Cover",
        "uin": "FHI-2026-DEMO",
        "policyholder_name": None,
        "sum_insured_paise": 50000000,
        "start_date": None,
        "end_date": None,
        "insured_members": [],
        "analysis_status": "needs_review",
        "needs_review": True,
        "documents": [
            {
                "id": DOCUMENT_ID,
                "type": "policy_wording",
                "name": "fictional-wording.pdf",
                "page_count": 2,
                "processing_status": "needs_review",
            }
        ],
    }
    assert calls == ["/auth/v1/user", "/rest/v1/policies", "/rest/v1/documents"]


def test_policy_list_and_detail_require_authentication():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(401, json={"message": "invalid token"})

    with api_client(handler) as client:
        no_token = client.get("/api/v1/policies")
        invalid = client.get(
            f"/api/v1/policies/{POLICY_ID}", headers={"Authorization": "Bearer expired"}
        )

    assert no_token.status_code == 401
    assert invalid.status_code == 401
    assert calls == ["/auth/v1/user"]


def test_foreign_policy_detail_returns_404_without_querying_documents():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json={"id": OWNER_B})
        assert request.url.path == "/rest/v1/policies"
        assert request.url.params["owner_id"] == f"eq.{OWNER_B}"
        assert request.url.params["id"] == f"eq.{POLICY_ID}"
        return httpx.Response(200, json=[])

    with api_client(handler) as client:
        response = client.get(
            f"/api/v1/policies/{POLICY_ID}", headers={"Authorization": "Bearer user-b"}
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert response.json()["error"]["message"] == "Policy not found."
    assert calls == ["/auth/v1/user", "/rest/v1/policies"]
