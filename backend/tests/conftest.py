from uuid import uuid4

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import ApiError
from app.main import create_app
from app.models import JobError, JobResponse
from app.supabase import Principal


def make_pdf(
    texts=("Fictional wording. Printed page 99.", "Second physical page."), **save_options
):
    with pymupdf.open() as document:
        for text in texts:
            page = document.new_page()
            if text:
                page.insert_text((72, 72), text)
        return document.tobytes(**save_options)


class MemoryGateway:
    """Test double only; the application never falls back to memory or mock auth."""

    def __init__(self):
        self.users = {"owner-a": str(uuid4()), "owner-b": str(uuid4())}
        self.policies = {}
        self.documents = {}
        self.jobs = {}
        self.pages = {}
        self.transitions = []

    async def authenticate(self, token):
        if token not in self.users:
            raise ApiError(401, "UNAUTHENTICATED", "A valid access token is required.")
        return Principal(self.users[token], token)

    async def require_policy(self, principal, policy_id):
        if self.policies.get(policy_id) != principal.user_id:
            raise ApiError(404, "NOT_FOUND", "Policy not found.")

    async def create_upload(self, principal, ids, data, **metadata):
        self.policies[ids.policy_id] = principal.user_id
        self.documents[ids.document_id] = {"data": data, **metadata}
        self.jobs[ids.job_id] = {
            "owner": principal.user_id,
            "document_id": ids.document_id,
            "response": JobResponse(
                job_id=ids.job_id,
                policy_id=ids.policy_id,
                status="queued",
                stage="uploaded",
                message="Waiting",
                error=None,
            ),
        }
        self.transitions.append("queued")

    async def start_job(self, principal, job_id):
        job = await self.get_job(principal, job_id)
        job.status = "processing"
        job.stage = "extracting"
        self.transitions.append("processing")

    async def finish_job(self, principal, job_id, parsed, *, code, message):
        job = await self.get_job(principal, job_id)
        job.status = "failed" if code else "needs_review"
        job.message = message
        job.error = JobError(code=code, message=message) if code else None
        if parsed:
            self.pages[self.jobs[job_id]["document_id"]] = parsed.pages
        self.transitions.append(job.status)

    async def get_job(self, principal, job_id):
        row = self.jobs.get(job_id)
        if not row or row["owner"] != principal.user_id:
            raise ApiError(404, "NOT_FOUND", "Job not found.")
        return row["response"]


@pytest.fixture
def gateway():
    return MemoryGateway()


@pytest.fixture
def settings():
    return Settings(_env_file=None, max_upload_bytes=100_000, max_pdf_pages=10)


@pytest.fixture
def client(gateway, settings):
    with TestClient(create_app(settings, gateway)) as client:
        yield client


@pytest.fixture
def pdf_bytes():
    return make_pdf()


@pytest.fixture
def headers():
    return {"Authorization": "Bearer owner-a"}
