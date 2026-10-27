"""Diagnostics contain fixed labels and codes only; never raw upstream data."""

import logging
from contextvars import ContextVar
from enum import StrEnum

import httpx

request_id_context: ContextVar[str] = ContextVar("request_id", default="none")
logger = logging.getLogger("app.supabase")


class Operation(StrEnum):
    AUTH_USER = "auth_user"
    POLICY_LOOKUP = "policy_lookup"
    STORAGE_UPLOAD = "storage_upload"
    CREATE_UPLOAD = "create_pdf_upload"
    STORAGE_CLEANUP = "storage_cleanup"
    START_EXTRACTION = "start_pdf_extraction"
    FINISH_EXTRACTION = "finish_pdf_extraction"
    JOB_LOOKUP = "job_lookup"
    BEGIN_ANALYSIS = "get_analysis_document"
    PREPARE_ANALYSIS = "prepare_pdf_analysis"
    FINISH_ANALYSIS = "finish_pdf_analysis"
    PAGE_LOOKUP = "page_lookup"
    FINDINGS_LOOKUP = "findings_lookup"


# Exact membership, not a regex: arbitrary upstream strings must never reach logs.
SAFE_CODES = frozenset(
    {
        "PGRST202",
        "PGRST203",
        "PGRST204",
        "PGRST301",
        "PGRST302",
        "PGRST303",
        "23502",
        "23503",
        "23505",
        "23514",
        "22P02",
        "42501",
        "42P01",
        "42883",
        "P0001",
        "P0002",
        "PT404",
        "AccessDenied",
        "NoSuchBucket",
        "NoSuchKey",
        "InvalidBucketName",
        "InvalidMimeType",
        "EntityTooLarge",
        "KeyAlreadyExists",
        "ResourceAlreadyExists",
        "InvalidJWT",
        "InvalidSignature",
        "DatabaseError",
        "InternalError",
    }
)


def safe_upstream_code(response: httpx.Response) -> str:
    # Do not retain/serialize messages, details, hints, URLs or nested originalError.
    if len(response.content) > 65536:
        return "unknown"
    try:
        payload = response.json()
    except (ValueError, UnicodeError, RecursionError):
        return "unknown"
    if isinstance(payload, dict):
        code = payload.get("code")
        if isinstance(code, str) and code in SAFE_CODES:
            return code
    return "unknown"


def log_upstream_failure(
    operation: Operation,
    *,
    response: httpx.Response | None = None,
    failure: str = "http",
) -> None:
    # All callers supply enum values and fixed failure labels, never exception text.
    logger.warning(
        "supabase_request_failed operation=%s upstream_status=%s upstream_code=%s "
        "failure=%s request_id=%s",
        operation.value,
        response.status_code if response is not None else "none",
        safe_upstream_code(response) if response is not None else "none",
        failure,
        request_id_context.get(),
    )
