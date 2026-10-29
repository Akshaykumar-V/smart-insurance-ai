"""Proposed authenticated routes; register only after shared contract approval."""

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.condition_contract import (
    ConditionRunResponse,
    ConditionStartRequest,
    ConditionStartResponse,
)
from app.condition_provider import OpenAIConditionExtractor, prepare_provider_document
from app.condition_store import ConditionStore
from app.config import Settings
from app.errors import ApiError
from app.supabase import Principal

logger = logging.getLogger(__name__)


async def run_condition_job(
    store, extractor, principal: Principal, policy_id: str, document_id: str, job_id: str
) -> None:
    try:
        await store.mark_processing(principal, job_id)
        pages = await store.pages(principal, policy_id, document_id)
        prepared = prepare_provider_document(document_id, pages)
        report = await extractor.extract(prepared)
        await store.finish(principal, job_id, report)
    except Exception as error:
        code = error.code if isinstance(error, ApiError) else "CONDITION_EXTRACTION_FAILED"
        try:
            await store.finish_error(principal, job_id, code)
        except Exception:
            # Never log exception text, provider bodies, credentials or document content.
            logger.error("condition_failure_persistence_failed")


def create_condition_router(current_user, settings: Settings) -> APIRouter:
    """The app registration is intentionally held in a separate approval patch."""
    router = APIRouter()

    def store(request: Request):
        return getattr(request.app.state, "condition_store", None) or ConditionStore(
            settings, request.app.state.gateway
        )

    def extractor(request: Request):
        return getattr(request.app.state, "condition_extractor", None) or OpenAIConditionExtractor(
            settings, request.app.state.gateway.client
        )

    @router.post(
        "/api/v1/policies/{policy_id}/condition-extractions",
        status_code=202,
        response_model=ConditionStartResponse,
    )
    async def start(
        request: Request,
        background_tasks: BackgroundTasks,
        policy_id: str,
        body: ConditionStartRequest,
        principal: Annotated[Principal, Depends(current_user)],
    ):
        if not settings.condition_extraction_enabled:
            raise ApiError(404, "FEATURE_DISABLED", "Condition extraction is unavailable.")
        result, created = await store(request).start_run(
            principal, policy_id, str(body.document_id)
        )
        if created:
            background_tasks.add_task(
                run_condition_job,
                store(request),
                extractor(request),
                principal,
                policy_id,
                str(body.document_id),
                result.job_id,
            )
        return result

    @router.get("/api/v1/policies/{policy_id}/conditions", response_model=ConditionRunResponse)
    async def conditions(
        request: Request,
        policy_id: str,
        job_id: str,
        principal: Annotated[Principal, Depends(current_user)],
    ):
        return await store(request).get_run(principal, policy_id, job_id)

    return router
