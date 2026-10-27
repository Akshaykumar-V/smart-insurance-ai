"""Schema selection is explicit, method-aware and confined to the Data API."""

import asyncio

import httpx
import pytest

from app.config import Settings
from app.diagnostics import Operation
from app.supabase import SupabaseGateway


@pytest.mark.parametrize(
    ("method", "path", "profile"),
    [
        ("GET", "/rest/v1/policies", "Accept-Profile"),
        ("HEAD", "/rest/v1/policies", "Accept-Profile"),
        ("POST", "/rest/v1/rpc/create_pdf_upload", "Content-Profile"),
        ("PATCH", "/rest/v1/policies", "Content-Profile"),
        ("DELETE", "/rest/v1/policies", "Content-Profile"),
        ("PUT", "/rest/v1/policies", "Content-Profile"),
        ("post", "/rest/v1/rpc/create_pdf_upload", "Content-Profile"),
        ("GET", "/auth/v1/user", None),
        ("POST", "/storage/v1/object/policy-documents/fixture.pdf", None),
        ("GET", "/storage/v1/object/authenticated/policy-documents/fixture.pdf", None),
        ("DELETE", "/storage/v1/object/policy-documents", None),
    ],
)
def test_gateway_schema_profile_headers(method, path, profile):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer fixture-user-token"
        assert request.headers["apikey"] == "fixture-public-key"
        assert request.headers["Content-Type"] == "application/pdf"
        assert request.headers["x-upsert"] == "false"
        actual = {
            name: request.headers[name]
            for name in ("Accept-Profile", "Content-Profile")
            if name in request.headers
        }
        assert actual == ({profile: "public"} if profile else {})
        return httpx.Response(200, json={})

    async def run():
        settings = Settings(
            _env_file=None,
            supabase_url="https://offline.invalid",
            supabase_publishable_key="fixture-public-key",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await SupabaseGateway(settings, client).request(
                method,
                path,
                "fixture-user-token",
                operation=Operation.CREATE_UPLOAD,
                headers={"Content-Type": "application/pdf", "x-upsert": "false"},
            )

    asyncio.run(run())
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("method", "profile"),
    [
        ("GET", "accept-profile"),
        ("POST", "content-profile"),
    ],
)
def test_profile_cannot_be_overridden_by_mixed_case_extra_header(method, profile):
    def handler(request):
        assert request.headers.get_list(profile) == ["public"]
        return httpx.Response(200, json={})

    async def run():
        settings = Settings(
            _env_file=None,
            supabase_url="https://offline.invalid",
            supabase_publishable_key="fixture-public-key",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await SupabaseGateway(settings, client).request(
                method,
                "/rest/v1/policies",
                "token",
                operation=Operation.POLICY_LOOKUP,
                headers={profile: "graphql_public"},
            )

    asyncio.run(run())
