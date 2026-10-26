"""Supabase REST adapter: validated user token + public key, with RLS as defense in depth."""

import logging
from dataclasses import dataclass, field
from uuid import UUID

import httpx

from app.config import Settings
from app.errors import ApiError
from app.models import JobError, JobResponse, ParsedPdf, UploadResponse

logger = logging.getLogger(__name__)
BUCKET = "policy-documents"


@dataclass(frozen=True)
class Principal:
    user_id: str
    token: str = field(repr=False)


class SupabaseGateway:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    async def request(self, method: str, path: str, token: str, **kwargs) -> httpx.Response:
        if not self.settings.supabase_url or not self.settings.supabase_publishable_key:
            raise ApiError(500, "BACKEND_NOT_CONFIGURED", "Supabase is not configured.")
        headers = {
            "apikey": self.settings.supabase_publishable_key,
            "Authorization": f"Bearer {token}",
            **kwargs.pop("headers", {}),
        }
        try:
            response = await self.client.request(
                method,
                self.settings.supabase_url.rstrip("/") + path,
                headers=headers,
                **kwargs,
            )
        except httpx.RequestError:
            raise ApiError(
                500, "UPSTREAM_UNAVAILABLE", "Storage or authentication is unavailable."
            ) from None
        if response.status_code == 429:
            raise ApiError(429, "RATE_LIMITED", "Too many requests. Try again later.")
        if response.status_code in (401, 403):
            raise ApiError(401, "UNAUTHENTICATED", "A valid access token is required.")
        if response.is_error:
            # Never propagate upstream bodies, tokens, SQL, or policy content.
            raise ApiError(500, "UPSTREAM_ERROR", "The storage operation could not be completed.")
        return response

    async def authenticate(self, token: str) -> Principal:
        response = await self.request("GET", "/auth/v1/user", token)
        try:
            user_id = str(UUID(response.json()["id"]))
        except (ValueError, TypeError, KeyError):
            raise ApiError(401, "UNAUTHENTICATED", "A valid access token is required.") from None
        return Principal(user_id=user_id, token=token)

    async def require_policy(self, principal: Principal, policy_id: str) -> None:
        try:
            UUID(policy_id)
        except ValueError:
            raise ApiError(404, "NOT_FOUND", "Policy not found.") from None
        response = await self.request(
            "GET",
            "/rest/v1/policies",
            principal.token,
            params={
                "id": f"eq.{policy_id}",
                "owner_id": f"eq.{principal.user_id}",
                "select": "id",
            },
        )
        if not response.json():
            raise ApiError(404, "NOT_FOUND", "Policy not found.")

    async def create_upload(
        self,
        principal: Principal,
        ids: UploadResponse,
        data: bytes,
        *,
        new_policy: bool,
        name: str,
        hint: str,
        sha256: str,
        page_count: int,
    ) -> None:
        path = f"{principal.user_id}/{ids.policy_id}/{ids.document_id}.pdf"
        await self.request(
            "POST",
            f"/storage/v1/object/{BUCKET}/{path}",
            principal.token,
            content=data,
            headers={"Content-Type": "application/pdf", "x-upsert": "false"},
        )
        try:
            await self.request(
                "POST",
                "/rest/v1/rpc/create_pdf_upload",
                principal.token,
                json={
                    "p_policy_id": ids.policy_id,
                    "p_document_id": ids.document_id,
                    "p_job_id": ids.job_id,
                    "p_new_policy": new_policy,
                    "p_name": name,
                    "p_hint": hint,
                    "p_path": path,
                    "p_sha256": sha256,
                    "p_page_count": page_count,
                },
            )
        except Exception:
            try:
                await self.request(
                    "DELETE",
                    f"/storage/v1/object/{BUCKET}",
                    principal.token,
                    json={"prefixes": [path]},
                )
            except Exception:
                logger.error("upload_cleanup_failed")
            raise

    async def start_job(self, principal: Principal, job_id: str) -> None:
        await self.request(
            "POST", "/rest/v1/rpc/start_pdf_extraction", principal.token, json={"p_job_id": job_id}
        )

    async def finish_job(
        self,
        principal: Principal,
        job_id: str,
        parsed: ParsedPdf | None,
        *,
        code: str | None,
        message: str,
    ) -> None:
        await self.request(
            "POST",
            "/rest/v1/rpc/finish_pdf_extraction",
            principal.token,
            json={
                "p_job_id": job_id,
                "p_pages": [page.model_dump() for page in parsed.pages] if parsed else None,
                "p_error_code": code,
                "p_message": message,
            },
        )

    async def get_job(self, principal: Principal, job_id: str) -> JobResponse:
        try:
            UUID(job_id)
        except ValueError:
            raise ApiError(404, "NOT_FOUND", "Job not found.") from None
        response = await self.request(
            "GET",
            "/rest/v1/analysis_jobs",
            principal.token,
            params={
                "id": f"eq.{job_id}",
                "owner_id": f"eq.{principal.user_id}",
                "select": "id,policy_id,status,stage,message,error_code",
            },
        )
        rows = response.json()
        if not rows:
            raise ApiError(404, "NOT_FOUND", "Job not found.")
        row = rows[0]
        return JobResponse(
            job_id=row["id"],
            policy_id=row["policy_id"],
            status=row["status"],
            stage=row["stage"],
            message=row["message"],
            error=JobError(code=row["error_code"], message=row["message"])
            if row["error_code"]
            else None,
        )
