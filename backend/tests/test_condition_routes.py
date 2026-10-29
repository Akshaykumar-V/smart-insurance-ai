"""Provisional routes mounted only in tests; no network or paid provider calls."""

import json
from uuid import uuid4

import pytest
from conftest import MemoryGateway
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.condition_contract import (
    ConditionItem,
    ConditionRunResponse,
    ConditionStartResponse,
    items_from_report,
)
from app.condition_routes import create_condition_router
from app.condition_workflow import evaluate_mocked_batches
from app.config import Settings
from app.errors import ApiError
from app.main import create_app, current_user
from app.models import ExtractedPage, JobError, JobResponse

POLICY_ID = str(uuid4())
DOCUMENT_ID = str(uuid4())
OTHER_DOCUMENT_ID = str(uuid4())
CLAUSES = (
    ("co_payment", "condition", "A co-payment of 10% applies to eligible expenses."),
    ("deductible", "condition", "An aggregate deductible of INR 10,000 applies."),
    ("room_rent", "restriction", "Room rent is limited to INR 5,000 except for ICU."),
    ("waiting_period", "restriction", "A waiting period of 24 months applies."),
    ("exclusion", "restriction", "Cosmetic treatment is excluded except after an accident."),
    ("sub_limit", "restriction", "Cataract treatment is limited to INR 40,000 per eye."),
)
PAGE_TEXTS = (
    "\n".join(item[2] for item in CLAUSES[:3]),
    "\n".join(item[2] for item in CLAUSES[3:]),
)


def provider_response(candidates):
    return {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": json.dumps({"candidates": candidates})}
                ],
            }
        ],
    }


class MockConditionExtractor:
    def __init__(self, mode="six"):
        self.mode = mode
        self.calls = 0

    async def extract(self, prepared):
        self.calls += 1
        if self.mode == "failure":
            raise ApiError(500, "CONDITION_PREFLIGHT", "Condition extraction unavailable.")
        responses = {}
        for batch in prepared.plan.batches:
            candidates = []
            if self.mode == "six":
                for passage in batch.primary_passages:
                    for category, kind, quote in CLAUSES:
                        if quote in passage.text:
                            candidates.append(
                                {
                                    "title": "Synthetic claim condition",
                                    "category": category,
                                    "specific_label": None,
                                    "kind": kind,
                                    "evidence": [{"passage_id": passage.id, "excerpt": quote}],
                                    "applicability": "Schedule requires review",
                                    "exceptions": ["ICU exception"]
                                    if category == "room_rent"
                                    else [],
                                    "dependencies": [{"kind": "policy_schedule", "label": None}],
                                    "review_status": "needs_review",
                                }
                            )
            responses[batch.id] = provider_response(candidates)
        return evaluate_mocked_batches(prepared, responses)


class MemoryConditionStore:
    def __init__(self, gateway):
        self.gateway = gateway
        self.runs = {}
        self.pages_data = [
            ExtractedPage(page_number=i, text=text, extraction_quality="text_present")
            for i, text in enumerate(PAGE_TEXTS, 1)
        ]

    def require_scope(self, principal, policy_id, document_id):
        if (
            principal.user_id != self.gateway.users["owner-a"]
            or policy_id != POLICY_ID
            or document_id != DOCUMENT_ID
        ):
            raise ApiError(404, "NOT_FOUND", "Document not found.")

    async def start_run(self, principal, policy_id, document_id):
        self.require_scope(principal, policy_id, document_id)
        if self.runs:
            job_id = next(iter(self.runs))
            return (
                ConditionStartResponse(
                    policy_id=policy_id,
                    document_id=document_id,
                    job_id=job_id,
                    status=self.gateway.jobs[job_id]["response"].status,
                ),
                False,
            )
        job_id = str(uuid4())
        self.gateway.jobs[job_id] = {
            "owner": principal.user_id,
            "document_id": document_id,
            "response": JobResponse(
                job_id=job_id,
                policy_id=policy_id,
                status="queued",
                stage="uploaded",
                message="Queued",
                error=None,
            ),
        }
        self.runs[job_id] = {
            "owner": principal.user_id,
            "policy_id": policy_id,
            "document_id": document_id,
            "state": None,
            "warning": None,
            "rejected": 0,
            "items": [],
        }
        return (
            ConditionStartResponse(
                policy_id=policy_id, document_id=document_id, job_id=job_id, status="queued"
            ),
            True,
        )

    async def mark_processing(self, principal, job_id):
        job = await self.gateway.get_job(principal, job_id)
        job.status = "processing"
        job.stage = "analyzing"

    async def pages(self, principal, policy_id, document_id):
        self.require_scope(principal, policy_id, document_id)
        return self.pages_data

    async def finish(self, principal, job_id, report):
        run = self.runs[job_id]
        run["items"] = items_from_report(report, job_id)
        run["state"] = "incomplete" if report.incomplete else "complete"
        run["warning"] = report.warning
        run["rejected"] = report.rejected_count
        job = await self.gateway.get_job(principal, job_id)
        job.status = "needs_review"
        job.stage = "verifying"

    async def finish_error(self, principal, job_id, code):
        run = self.runs[job_id]
        run["state"] = "incomplete"
        run["warning"] = "Analysis incomplete."
        job = await self.gateway.get_job(principal, job_id)
        job.status = "failed"
        job.error = JobError(code=code, message="Condition extraction did not complete.")

    async def get_run(self, principal, policy_id, job_id):
        run = self.runs.get(job_id)
        if not run or run["owner"] != principal.user_id or run["policy_id"] != policy_id:
            raise ApiError(404, "NOT_FOUND", "Condition run not found.")
        job = await self.gateway.get_job(principal, job_id)
        return ConditionRunResponse(
            policy_id=policy_id,
            document_id=run["document_id"],
            job_id=job_id,
            status=job.status,
            analysis_state=run["state"],
            warning=run["warning"],
            rejected_candidate_count=run["rejected"],
            conditions=run["items"],
        )


@pytest.fixture
def mounted_app():
    gateway = MemoryGateway()
    settings = Settings(_env_file=None, condition_extraction_enabled=True)
    app = create_app(settings, gateway)
    app.include_router(create_condition_router(current_user, settings))
    store = MemoryConditionStore(gateway)
    extractor = MockConditionExtractor()
    app.state.condition_store = store
    app.state.condition_extractor = extractor
    with TestClient(app) as client:
        yield client, store, extractor


def start(client, token="owner-a", document_id=DOCUMENT_ID, policy_id=POLICY_ID):
    return client.post(
        f"/api/v1/policies/{policy_id}/condition-extractions",
        headers={"Authorization": f"Bearer {token}"},
        json={"document_id": document_id},
    )


def read(client, job_id, token="owner-a", policy_id=POLICY_ID):
    return client.get(
        f"/api/v1/policies/{policy_id}/conditions",
        params={"job_id": job_id},
        headers={"Authorization": f"Bearer {token}"},
    )


def test_success_six_categories_and_existing_job_poll(mounted_app):
    client, _, extractor = mounted_app
    accepted = start(client)
    assert accepted.status_code == 202
    body = accepted.json()
    assert body["status"] == "queued"
    assert body["document_id"] == DOCUMENT_ID
    job_id = body["job_id"]
    assert extractor.calls == 1
    job = client.get(f"/api/v1/jobs/{job_id}", headers={"Authorization": "Bearer owner-a"})
    assert job.status_code == 200
    assert job.json()["status"] == "needs_review"
    result = read(client, job_id)
    assert result.status_code == 200
    data = result.json()
    assert data["analysis_state"] == "complete"
    assert data["rejected_candidate_count"] == 0
    assert len(data["conditions"]) == 6
    assert {item["category"] for item in data["conditions"]} == {row[0] for row in CLAUSES}
    for item in data["conditions"]:
        assert item["job_id"] == job_id
        assert item["document_id"] == DOCUMENT_ID
        assert item["source_verified"] and item["review_required"]
        assert item["evidence"][0]["quote"] in PAGE_TEXTS[item["evidence"][0]["page"] - 1]
        assert "rule" not in item
    assert next(i for i in data["conditions"] if i["category"] == "room_rent")["exceptions"] == [
        "ICU exception"
    ]
    missing_verification = dict(data["conditions"][0])
    missing_verification.pop("source_verified")
    with pytest.raises(ValidationError):
        ConditionItem.model_validate(missing_verification)


def test_invalid_document_and_foreign_owner_never_start(mounted_app):
    client, _, extractor = mounted_app
    assert start(client, document_id=OTHER_DOCUMENT_ID).status_code == 404
    assert start(client, token="owner-b").status_code == 404
    assert start(client, policy_id=str(uuid4())).status_code == 404
    assert extractor.calls == 0


def test_duplicate_post_returns_same_job_without_second_provider_call(mounted_app):
    client, _, extractor = mounted_app
    first = start(client).json()
    second = start(client).json()
    assert second["job_id"] == first["job_id"]
    assert second["status"] == "needs_review"
    assert extractor.calls == 1


def test_missing_job_and_foreign_owner_read_are_404(mounted_app):
    client, _, _ = mounted_app
    job_id = start(client).json()["job_id"]
    assert read(client, str(uuid4())).status_code == 404
    assert read(client, job_id, token="owner-b").status_code == 404
    assert read(client, job_id, policy_id=str(uuid4())).status_code == 404


@pytest.mark.parametrize("mode,status", [("empty", "needs_review"), ("failure", "failed")])
def test_incomplete_or_provider_failure_cannot_imply_no_restrictions(mounted_app, mode, status):
    client, _, extractor = mounted_app
    extractor.mode = mode
    job_id = start(client).json()["job_id"]
    data = read(client, job_id).json()
    assert data["status"] == status
    assert data["analysis_state"] == "incomplete"
    assert data["conditions"] == []
    assert data["warning"]
    assert extractor.calls == 1
