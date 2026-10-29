"""Owner-scoped reads and server-only writes for proposed condition routes."""

from uuid import UUID

import httpx

from app.condition_contract import (
    ConditionItem,
    ConditionRunResponse,
    ConditionStartResponse,
    items_from_report,
)
from app.condition_workflow import ConditionDiscoveryReport
from app.config import Settings
from app.diagnostics import Operation
from app.errors import ApiError
from app.models import ExtractedPage
from app.supabase import Principal, SupabaseGateway


def _uuid(value: str, noun: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError):
        raise ApiError(404, "NOT_FOUND", f"{noun} not found.") from None


class ConditionStore:
    """The service key is used only for controlled job/result writes."""

    def __init__(self, settings: Settings, gateway: SupabaseGateway):
        self.settings = settings
        self.gateway = gateway

    async def _service_rpc(self, name: str, payload: dict):
        key = self.settings.supabase_service_role_key.get_secret_value()
        if not key or not self.settings.supabase_url:
            raise ApiError(500, "BACKEND_NOT_CONFIGURED", "Condition storage is unavailable.")
        try:
            response = await self.gateway.client.post(
                self.settings.supabase_url.rstrip("/") + f"/rest/v1/rpc/{name}",
                headers={
                    "apikey": key,
                    "Authorization": f"Bearer {key}",
                    "Content-Profile": "public",
                },
                json=payload,
                timeout=20,
            )
        except httpx.RequestError:
            raise ApiError(
                500, "UPSTREAM_UNAVAILABLE", "Condition storage is unavailable."
            ) from None
        if not response.is_success:
            # Never propagate SQL diagnostics, source text, keys, or upstream bodies.
            raise ApiError(500, "UPSTREAM_ERROR", "Condition storage is unavailable.")
        return response

    async def require_document(self, principal: Principal, policy_id: str, document_id: str) -> int:
        policy_id = _uuid(policy_id, "Policy")
        document_id = _uuid(document_id, "Document")
        await self.gateway.require_policy(principal, policy_id)
        response = await self.gateway.request(
            "GET",
            "/rest/v1/documents",
            principal.token,
            operation=Operation.CONDITION_DOCUMENT,
            params={
                "id": f"eq.{document_id}",
                "policy_id": f"eq.{policy_id}",
                "owner_id": f"eq.{principal.user_id}",
                "select": "id,processing_status,page_count",
                "limit": 1,
            },
        )
        rows = response.json()
        if not rows:
            raise ApiError(404, "NOT_FOUND", "Document not found.")
        if rows[0]["processing_status"] != "extracted":
            raise ApiError(409, "DOCUMENT_NOT_READY", "Document text is not ready for analysis.")
        return int(rows[0]["page_count"])

    async def start_run(
        self, principal: Principal, policy_id: str, document_id: str
    ) -> tuple[ConditionStartResponse, bool]:
        await self.require_document(principal, policy_id, document_id)
        response = await self._service_rpc(
            "start_condition_discovery",
            {
                "p_owner_id": principal.user_id,
                "p_policy_id": policy_id,
                "p_document_id": document_id,
            },
        )
        try:
            data = response.json()
            job_id = str(UUID(data["job_id"]))
            created = data["created"]
            if type(created) is not bool:
                raise ValueError
            return (
                ConditionStartResponse(
                    policy_id=policy_id,
                    document_id=document_id,
                    job_id=job_id,
                    status=data["status"],
                ),
                created,
            )
        except (KeyError, TypeError, ValueError):
            raise ApiError(500, "UPSTREAM_ERROR", "Condition storage is unavailable.") from None

    async def pages(
        self, principal: Principal, policy_id: str, document_id: str
    ) -> list[ExtractedPage]:
        count = await self.require_document(principal, policy_id, document_id)
        response = await self.gateway.request(
            "GET",
            "/rest/v1/document_pages",
            principal.token,
            operation=Operation.CONDITION_PAGES,
            params={
                "document_id": f"eq.{document_id}",
                "owner_id": f"eq.{principal.user_id}",
                "select": "page_number,text,extraction_quality,method",
                "order": "page_number.asc",
                "limit": 201,
            },
        )
        try:
            pages = [ExtractedPage.model_validate(row) for row in response.json()]
        except (TypeError, ValueError):
            raise ApiError(500, "INVALID_PAGES", "Extracted pages need review.") from None
        if len(pages) != count or [p.page_number for p in pages] != list(range(1, count + 1)):
            raise ApiError(500, "INVALID_PAGES", "Extracted pages need review.")
        return pages

    async def mark_processing(self, principal: Principal, job_id: str) -> None:
        await self._service_rpc(
            "mark_condition_processing",
            {"p_job_id": job_id, "p_owner_id": principal.user_id},
        )

    async def finish(
        self, principal: Principal, job_id: str, report: ConditionDiscoveryReport
    ) -> None:
        items = items_from_report(report, job_id)
        await self._service_rpc(
            "finish_condition_discovery",
            {
                "p_job_id": job_id,
                "p_owner_id": principal.user_id,
                "p_items": [item.model_dump(mode="json") for item in items],
                "p_incomplete": report.incomplete,
                "p_warning": report.warning,
                "p_rejected_count": report.rejected_count,
                "p_error_code": None,
            },
        )

    async def finish_error(self, principal: Principal, job_id: str, code: str) -> None:
        if code not in {"CONDITION_PREFLIGHT", "CONDITION_EXTRACTION_FAILED", "INVALID_PAGES"}:
            code = "CONDITION_EXTRACTION_FAILED"
        await self._service_rpc(
            "finish_condition_discovery",
            {
                "p_job_id": job_id,
                "p_owner_id": principal.user_id,
                "p_items": [],
                "p_incomplete": True,
                "p_warning": "Analysis incomplete. No absence of restrictions can be inferred.",
                "p_rejected_count": 0,
                "p_error_code": code,
            },
        )

    async def get_run(
        self, principal: Principal, policy_id: str, job_id: str
    ) -> ConditionRunResponse:
        policy_id = _uuid(policy_id, "Policy")
        job_id = _uuid(job_id, "Job")
        await self.gateway.require_policy(principal, policy_id)
        response = await self.gateway.request(
            "GET",
            "/rest/v1/claim_condition_runs",
            principal.token,
            operation=Operation.CONDITION_RUN,
            params={
                "job_id": f"eq.{job_id}",
                "policy_id": f"eq.{policy_id}",
                "owner_id": f"eq.{principal.user_id}",
                "select": "job_id,document_id,analysis_state,warning,rejected_candidate_count",
                "limit": 1,
            },
        )
        rows = response.json()
        if not rows:
            raise ApiError(404, "NOT_FOUND", "Condition run not found.")
        row = rows[0]
        job = await self.gateway.get_job(principal, job_id)
        if job.policy_id != policy_id:
            raise ApiError(404, "NOT_FOUND", "Condition run not found.")
        result: list[ConditionItem] = []
        offset = 0
        while True:
            items_response = await self.gateway.request(
                "GET",
                "/rest/v1/claim_conditions",
                principal.token,
                operation=Operation.CONDITION_RESULTS,
                params={
                    "job_id": f"eq.{job_id}",
                    "policy_id": f"eq.{policy_id}",
                    "document_id": f"eq.{row['document_id']}",
                    "owner_id": f"eq.{principal.user_id}",
                    "select": "payload",
                    "order": "id.asc",
                    "limit": 100,
                    "offset": offset,
                },
            )
            items = items_response.json()
            result.extend(ConditionItem.model_validate(item["payload"]) for item in items)
            if len(items) < 100:
                break
            offset += 100
        if any(item.job_id != job_id or item.document_id != row["document_id"] for item in result):
            raise ApiError(500, "INVALID_RESULTS", "Condition results need review.")
        return ConditionRunResponse(
            policy_id=policy_id,
            document_id=row["document_id"],
            job_id=job_id,
            status=job.status,
            analysis_state=row["analysis_state"],
            warning=row["warning"],
            rejected_candidate_count=row["rejected_candidate_count"],
            conditions=result,
        )
