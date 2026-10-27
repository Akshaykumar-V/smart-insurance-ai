"""Supabase REST adapter: validated user token + public key, with RLS as defense in depth."""

import logging
from dataclasses import dataclass, field
from uuid import UUID

import httpx

from app.analysis import Finding, FindingsResponse
from app.config import Settings
from app.diagnostics import Operation, log_upstream_failure, safe_upstream_code
from app.errors import ApiError
from app.models import ExtractedPage, JobError, JobResponse, ParsedPdf, UploadResponse

logger = logging.getLogger(__name__)
BUCKET = "policy-documents"


def public_schema_headers(method: str, path: str) -> dict[str, str]:
    """Select our Data API schema without affecting Auth or Storage requests."""
    if not path.startswith("/rest/v1/"):
        return {}
    profile = (
        "Content-Profile"
        if method.upper() in {"POST", "PATCH", "PUT", "DELETE"}
        else "Accept-Profile"
    )
    return {profile: "public"}


@dataclass(frozen=True)
class Principal:
    user_id: str
    token: str = field(repr=False)


class SupabaseGateway:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    async def request(
        self, method: str, path: str, token: str, *, operation: Operation, **kwargs
    ) -> httpx.Response:
        if not self.settings.supabase_url or not self.settings.supabase_publishable_key:
            log_upstream_failure(operation, failure="not_configured")
            raise ApiError(500, "BACKEND_NOT_CONFIGURED", "Supabase is not configured.")
        headers = httpx.Headers(
            {
                "apikey": self.settings.supabase_publishable_key,
                "Authorization": f"Bearer {token}",
                **kwargs.pop("headers", {}),
            }
        )
        headers.update(public_schema_headers(method, path))
        try:
            response = await self.client.request(
                method,
                self.settings.supabase_url.rstrip("/") + path,
                headers=headers,
                **kwargs,
            )
        except httpx.RequestError:
            log_upstream_failure(operation, failure="transport")
            raise ApiError(
                500, "UPSTREAM_UNAVAILABLE", "Storage or authentication is unavailable."
            ) from None
        if not response.is_success:
            log_upstream_failure(operation, response=response)
        if (
            response.status_code == 404
            and safe_upstream_code(response) == "PT404"
            and (operation, path)
            in {
                (Operation.START_EXTRACTION, "/rest/v1/rpc/start_pdf_extraction"),
                (Operation.FINISH_EXTRACTION, "/rest/v1/rpc/finish_pdf_extraction"),
            }
        ):
            raise ApiError(404, "NOT_FOUND", "Job not found.")
        if response.status_code == 429:
            raise ApiError(429, "RATE_LIMITED", "Too many requests. Try again later.")
        if response.status_code in (401, 403):
            raise ApiError(401, "UNAUTHENTICATED", "A valid access token is required.")
        if not response.is_success:
            # Never propagate upstream bodies, tokens, SQL, or policy content.
            raise ApiError(500, "UPSTREAM_ERROR", "The storage operation could not be completed.")
        return response

    async def authenticate(self, token: str) -> Principal:
        response = await self.request("GET", "/auth/v1/user", token, operation=Operation.AUTH_USER)
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
            operation=Operation.POLICY_LOOKUP,
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
            operation=Operation.STORAGE_UPLOAD,
            content=data,
            headers={"Content-Type": "application/pdf", "x-upsert": "false"},
        )
        try:
            await self.request(
                "POST",
                "/rest/v1/rpc/create_pdf_upload",
                principal.token,
                operation=Operation.CREATE_UPLOAD,
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
                    operation=Operation.STORAGE_CLEANUP,
                    json={"prefixes": [path]},
                )
            except Exception:
                logger.error("upload_cleanup_failed")
            raise

    async def start_job(self, principal: Principal, job_id: str) -> None:
        await self.request(
            "POST",
            "/rest/v1/rpc/start_pdf_extraction",
            principal.token,
            operation=Operation.START_EXTRACTION,
            json={"p_job_id": job_id},
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
            operation=Operation.FINISH_EXTRACTION,
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
            operation=Operation.JOB_LOOKUP,
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

    async def prepare_analysis(self, principal, job_id, parsed):
        await self.request(
            "POST",
            "/rest/v1/rpc/prepare_pdf_analysis",
            principal.token,
            operation=Operation.PREPARE_ANALYSIS,
            json={"p_job_id": job_id, "p_pages": [p.model_dump() for p in parsed.pages]},
        )

    async def begin_analysis(self, principal: Principal, job_id: str):
        response = await self.request(
            "POST",
            "/rest/v1/rpc/get_analysis_document",
            principal.token,
            operation=Operation.BEGIN_ANALYSIS,
            json={"p_job_id": job_id},
        )
        metadata = response.json()
        document_id = metadata["document_id"]
        response = await self.request(
            "GET",
            "/rest/v1/document_pages",
            principal.token,
            operation=Operation.PAGE_LOOKUP,
            params={
                "document_id": f"eq.{document_id}",
                "owner_id": f"eq.{principal.user_id}",
                "select": "page_number,text,extraction_quality,method",
                "order": "page_number.asc",
                "limit": 201,
            },
        )
        pages = [ExtractedPage.model_validate(p) for p in response.json()]
        if not pages or [p.page_number for p in pages] != list(
            range(1, metadata["page_count"] + 1)
        ):
            raise ApiError(500, "AI_PAGE_SEQUENCE", "Stored pages are incomplete.")
        return document_id, pages

    async def finish_analysis(self, principal, job_id, findings, *, code, message):
        await self.request(
            "POST",
            "/rest/v1/rpc/finish_pdf_analysis",
            principal.token,
            operation=Operation.FINISH_ANALYSIS,
            json={
                "p_job_id": job_id,
                "p_findings": [f.model_dump() for f in findings],
                "p_error_code": code,
                "p_message": message,
            },
        )

    async def get_findings(self, principal: Principal, policy_id: str):
        await self.require_policy(principal, policy_id)
        result = []
        # Explicit pagination avoids silently dropping findings at PostgREST's row limit.
        offset = 0
        while True:
            response = await self.request(
                "GET",
                "/rest/v1/findings",
                principal.token,
                operation=Operation.FINDINGS_LOOKUP,
                params={
                    "policy_id": f"eq.{policy_id}",
                    "owner_id": f"eq.{principal.user_id}",
                    "select": "payload",
                    "order": "id.asc",
                    "limit": 100,
                    "offset": offset,
                },
            )
            rows = response.json()
            result.extend(Finding.model_validate(row["payload"]) for row in rows)
            if not rows:
                break
            offset += len(rows)
        return FindingsResponse(policy_id=policy_id, findings=result)
