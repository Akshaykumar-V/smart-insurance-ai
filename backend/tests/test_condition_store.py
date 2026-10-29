"""MockTransport checks owner-scoped reads and service-only writes offline."""

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.condition_store import ConditionStore
from app.condition_workflow import evaluate_mocked_batches, prepare_condition_document
from app.config import Settings
from app.errors import ApiError
from app.models import ExtractedPage
from app.supabase import Principal, SupabaseGateway

OWNER_A = str(uuid4())
OWNER_B = str(uuid4())
POLICY = str(uuid4())
DOCUMENT = str(uuid4())
JOB = str(uuid4())


def _client(handler):
    settings = Settings(
        _env_file=None,
        supabase_url="https://example.invalid",
        supabase_publishable_key="synthetic-public-key",
        supabase_service_role_key=SecretStr("synthetic-service-key"),
    )
    return settings, httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _scope(request):
    query = request.url.params
    return query.get("owner_id") == f"eq.{OWNER_A}" and query.get("policy_id") == f"eq.{POLICY}"


def _policy_scope(request):
    query = request.url.params
    return query.get("owner_id") == f"eq.{OWNER_A}" and query.get("id") == f"eq.{POLICY}"


def test_start_checks_policy_document_and_owner_before_service_write():
    service_calls = []

    def handler(request):
        path = request.url.path
        if path == "/rest/v1/policies":
            return httpx.Response(200, json=[{"id": POLICY}] if _policy_scope(request) else [])
        if path == "/rest/v1/documents":
            rows = (
                [{"id": DOCUMENT, "processing_status": "extracted", "page_count": 2}]
                if _scope(request) and request.url.params.get("id") == f"eq.{DOCUMENT}"
                else []
            )
            return httpx.Response(200, json=rows)
        if path == "/rest/v1/rpc/start_condition_discovery":
            service_calls.append(request)
            assert request.headers["apikey"] == "synthetic-service-key"
            assert json.loads(request.content)["p_owner_id"] == OWNER_A
            return httpx.Response(200, json={"job_id": JOB, "created": True, "status": "queued"})
        raise AssertionError("Unexpected request path")

    async def run():
        settings, client = _client(handler)
        async with client:
            gateway = SupabaseGateway(settings, client)
            store = ConditionStore(settings, gateway)
            response, created = await store.start_run(
                Principal(OWNER_A, "token-a"), POLICY, DOCUMENT
            )
            assert (response.job_id, created) == (JOB, True)
            with pytest.raises(ApiError) as foreign:
                await store.start_run(Principal(OWNER_B, "token-b"), POLICY, DOCUMENT)
            assert foreign.value.status == 404
            with pytest.raises(ApiError) as missing:
                await store.start_run(Principal(OWNER_A, "token-a"), POLICY, str(uuid4()))
            assert missing.value.status == 404

    asyncio.run(run())
    assert len(service_calls) == 1


def test_read_requires_matching_owner_policy_job_and_scopes_condition_query():
    condition_queries = []

    def handler(request):
        path = request.url.path
        if path == "/rest/v1/policies":
            return httpx.Response(200, json=[{"id": POLICY}] if _policy_scope(request) else [])
        if path == "/rest/v1/claim_condition_runs":
            rows = (
                [
                    {
                        "job_id": JOB,
                        "document_id": DOCUMENT,
                        "analysis_state": "incomplete",
                        "warning": "Analysis incomplete.",
                        "rejected_candidate_count": 2,
                    }
                ]
                if _scope(request) and request.url.params.get("job_id") == f"eq.{JOB}"
                else []
            )
            return httpx.Response(200, json=rows)
        if path == "/rest/v1/analysis_jobs":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": JOB,
                        "policy_id": POLICY,
                        "status": "needs_review",
                        "stage": "verifying",
                        "message": "Analysis incomplete.",
                        "error_code": None,
                    }
                ],
            )
        if path == "/rest/v1/claim_conditions":
            condition_queries.append(request.url.params)
            return httpx.Response(200, json=[])
        raise AssertionError("Unexpected request path")

    async def run():
        settings, client = _client(handler)
        async with client:
            gateway = SupabaseGateway(settings, client)
            store = ConditionStore(settings, gateway)
            result = await store.get_run(Principal(OWNER_A, "token-a"), POLICY, JOB)
            assert result.analysis_state == "incomplete"
            assert result.rejected_candidate_count == 2
            assert result.conditions == []
            with pytest.raises(ApiError) as foreign:
                await store.get_run(Principal(OWNER_B, "token-b"), POLICY, JOB)
            assert foreign.value.status == 404
            with pytest.raises(ApiError) as missing:
                await store.get_run(Principal(OWNER_A, "token-a"), POLICY, str(uuid4()))
            assert missing.value.status == 404

    asyncio.run(run())
    assert len(condition_queries) == 1
    query = condition_queries[0]
    assert query["owner_id"] == f"eq.{OWNER_A}"
    assert query["policy_id"] == f"eq.{POLICY}"
    assert query["document_id"] == f"eq.{DOCUMENT}"
    assert query["job_id"] == f"eq.{JOB}"


def test_finish_uses_service_key_and_only_backend_verified_condition_payload():
    quote = "A co-payment of 10% applies to eligible expenses."
    prepared = prepare_condition_document(
        DOCUMENT, [ExtractedPage(page_number=1, text=quote, extraction_quality="text_present")]
    )
    passage = prepared.manifest.passages[0]
    candidate = {
        "title": "Synthetic co-payment",
        "category": "co_payment",
        "kind": "condition",
        "evidence": [{"passage_id": passage.id, "excerpt": quote}],
    }
    response = {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": json.dumps({"candidates": [candidate]})}
                ],
            }
        ],
    }
    report = evaluate_mocked_batches(prepared, {prepared.plan.batches[0].id: response})
    writes = []

    def handler(request):
        assert request.url.path == "/rest/v1/rpc/finish_condition_discovery"
        assert request.headers["apikey"] == "synthetic-service-key"
        assert request.headers["authorization"] == "Bearer synthetic-service-key"
        writes.append(json.loads(request.content))
        return httpx.Response(204)

    async def run():
        settings, client = _client(handler)
        async with client:
            await ConditionStore(settings, SupabaseGateway(settings, client)).finish(
                Principal(OWNER_A, "token-a"), JOB, report
            )

    asyncio.run(run())
    assert len(writes) == 1
    item = writes[0]["p_items"][0]
    assert item["evidence"][0]["quote"] == quote
    assert item["evidence"][0]["page"] == 1
    assert item["source_verified"] and item["review_required"]
    assert "rule" not in item
    assert writes[0]["p_owner_id"] == OWNER_A
