import hashlib
import logging
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import uuid4

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from app.analysis import FindingsResponse, OpenAIExtractor, analyze_job
from app.config import Settings
from app.diagnostics import request_id_context
from app.errors import ApiError
from app.models import DocumentType, JobResponse, UploadResponse
from app.pdf import parse_isolated
from app.supabase import Principal, SupabaseGateway

logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)


def error_response(status: int, code: str, message: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {"code": code, "message": message, "request_id": request_id},
        },
    )


class RequestBoundary:
    """Bound the complete multipart body before FastAPI spools uploaded files."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = str(uuid4())
        context_token = request_id_context.set(request_id)
        scope.setdefault("state", {})["request_id"] = request_id
        started = False

        async def send_with_id(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message["headers"] = [*message["headers"], (b"x-request-id", request_id.encode())]
            await send(message)

        try:
            # Enforce both declared and streamed lengths (including chunked requests).
            headers = dict(scope["headers"])
            if b"content-length" in headers:
                try:
                    length = int(headers[b"content-length"])
                except ValueError:
                    raise ApiError(400, "INVALID_REQUEST", "Invalid request length.") from None
                if length < 0:
                    raise ApiError(400, "INVALID_REQUEST", "Invalid request length.")
                if length > self.max_bytes:
                    raise ApiError(413, "FILE_TOO_LARGE", "The upload exceeds the size limit.")
            body = bytearray()
            while True:
                event = await receive()
                if event["type"] == "http.disconnect":
                    return
                body.extend(event.get("body", b""))
                if len(body) > self.max_bytes:
                    raise ApiError(413, "FILE_TOO_LARGE", "The upload exceeds the size limit.")
                if not event.get("more_body", False):
                    break
            consumed = False

            async def bounded_receive():
                nonlocal consumed
                if consumed:
                    return await receive()
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            await self.app(scope, bounded_receive, send_with_id)
        except ApiError as exc:
            if not started:
                await error_response(exc.status, exc.code, exc.message, request_id)(
                    scope,
                    receive,
                    send_with_id,
                )
        except Exception:
            logger.error("request_failed request_id=%s", request_id)
            if not started:
                await error_response(
                    500, "INTERNAL_ERROR", "The request could not be completed.", request_id
                )(scope, receive, send_with_id)
        finally:
            request_id_context.reset(context_token)


async def current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    if credentials is None:
        raise ApiError(401, "UNAUTHENTICATED", "A valid bearer access token is required.")
    return await request.app.state.gateway.authenticate(credentials.credentials)


async def extract_job(
    gateway, principal, job_id: str, data: bytes, settings: Settings, extractor=None
):
    try:
        await gateway.start_job(principal, job_id)
        parsed = await run_in_threadpool(parse_isolated, data, settings, extract=True)
        unreadable = any(page.extraction_quality != "text_present" for page in parsed.pages)
        message = "PDF text extracted. AI analysis is not implemented in this milestone."
        if unreadable:
            message = (
                "Some pages have no readable text or require review. OCR is not implemented. "
                "AI analysis is not implemented in this milestone."
            )
        if settings.ai_extraction_enabled:
            await gateway.prepare_analysis(principal, job_id, parsed)
        else:
            await gateway.finish_job(principal, job_id, parsed, code=None, message=message)
    except Exception as exc:
        code = exc.code if isinstance(exc, ApiError) else "EXTRACTION_FAILED"
        message = exc.message if isinstance(exc, ApiError) else "PDF extraction could not complete."
        try:
            await gateway.finish_job(principal, job_id, None, code=code, message=message)
        except Exception:
            # Do not log exception bodies or tracebacks that could include private text/tokens.
            logger.error("job_failure_persistence_failed job_id=%s", job_id)

        return
    if settings.ai_extraction_enabled:
        await analyze_job(gateway, extractor, principal, job_id)


def create_app(settings: Settings | None = None, gateway=None, extractor=None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            app.state.gateway = gateway or SupabaseGateway(settings, client)
            app.state.extractor = extractor or OpenAIExtractor(settings, client)
            yield

    app = FastAPI(
        title="Smart Insurance — hackathon proof-of-concept", version="0.1.0", lifespan=lifespan
    )
    app.add_middleware(RequestBoundary, max_bytes=settings.max_upload_bytes + 1024 * 1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError):
        return error_response(exc.status, exc.code, exc.message, request.state.request_id)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError):
        return error_response(
            400,
            "INVALID_FIELDS",
            "Check the required file and form fields.",
            request.state.request_id,
        )

    @app.exception_handler(HTTPException)
    async def handle_http_error(request: Request, exc: HTTPException):
        return error_response(
            exc.status_code,
            "INVALID_REQUEST",
            "The request could not be handled.",
            request.state.request_id,
        )

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.post("/api/v1/policies/upload", status_code=202, response_model=UploadResponse)
    async def upload(
        request: Request,
        background_tasks: BackgroundTasks,
        principal: Annotated[Principal, Depends(current_user)],
        file: Annotated[UploadFile, File()],
        policy_id: Annotated[str | None, Form(max_length=200)] = None,
        document_type_hint: Annotated[DocumentType | None, Form()] = None,
    ):
        try:
            name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
            if not name.lower().endswith(".pdf") or file.content_type not in (
                "application/pdf",
                "application/octet-stream",
            ):
                raise ApiError(400, "UNSUPPORTED_FILE", "Upload a PDF file.")
            if len(name) > 255 or any(ord(char) < 32 for char in name):
                raise ApiError(400, "INVALID_FIELDS", "The file name is invalid.")
            data = await file.read(settings.max_upload_bytes + 1)
            if len(data) > settings.max_upload_bytes:
                raise ApiError(413, "FILE_TOO_LARGE", "The PDF exceeds the upload size limit.")
            if policy_id is not None:
                await request.app.state.gateway.require_policy(principal, policy_id)
            inspected = await run_in_threadpool(parse_isolated, data, settings, extract=False)
            ids = UploadResponse(
                policy_id=policy_id or str(uuid4()), document_id=str(uuid4()), job_id=str(uuid4())
            )
            await request.app.state.gateway.create_upload(
                principal,
                ids,
                data,
                new_policy=policy_id is None,
                name=name,
                hint=document_type_hint or "other",
                sha256=hashlib.sha256(data).hexdigest(),
                page_count=inspected.page_count,
            )
            background_tasks.add_task(
                extract_job,
                request.app.state.gateway,
                principal,
                ids.job_id,
                data,
                settings,
                request.app.state.extractor,
            )
            return ids
        finally:
            await file.close()

    @app.get("/api/v1/jobs/{job_id}", response_model=JobResponse)
    async def job(
        request: Request, job_id: str, principal: Annotated[Principal, Depends(current_user)]
    ):
        return await request.app.state.gateway.get_job(principal, job_id)

    @app.get("/api/v1/policies/{policy_id}/findings", response_model=FindingsResponse)
    async def findings(
        request: Request, policy_id: str, principal: Annotated[Principal, Depends(current_user)]
    ):
        return await request.app.state.gateway.get_findings(principal, policy_id)

    def contract_openapi():
        if app.openapi_schema is None:
            schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
            # FastAPI otherwise advertises its default 422 field-validation response,
            # although the agreed upload/job contract uses our 400 error envelope.
            for path in schema["paths"].values():
                for operation in path.values():
                    if isinstance(operation, dict) and "422" in operation.get("responses", {}):
                        del operation["responses"]["422"]
                        operation["responses"]["400"] = {"description": "Invalid request fields"}
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = contract_openapi
    return app


app = create_app()
