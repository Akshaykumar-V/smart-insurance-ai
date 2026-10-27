import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pymupdf
import pytest
from conftest import MemoryGateway, make_pdf
from fastapi.testclient import TestClient

from app.analysis import Extraction, OpenAIExtractor, verify_findings
from app.config import Settings
from app.errors import ApiError
from app.main import create_app
from app.models import ExtractedPage
from app.supabase import SupabaseGateway
from scripts.make_ai_demo_pdf import main as make_ai_demo_pdf

COPAY = "Health insurance: A co-payment of 20% of admissible expenses applies to age 60 and above."
LIMIT = "Cataract treatment is limited to INR 40,000 per eye per policy year."


def candidate(**changes):
    data = dict(
        condition_type="co_payment",
        page=1,
        quote=COPAY,
        percent=20,
        amount_rupees=None,
        treatment=None,
        basis="admissible expenses",
        applicability="Age 60 and above.",
        explanation="An age-linked co-payment may apply.",
        exceptions=[],
        ambiguous=False,
    )
    return {**data, **changes}


def extraction(*items):
    return Extraction.model_validate({"is_health_policy": True, "findings": list(items)})


def pages():
    return [
        ExtractedPage(page_number=1, text=COPAY, extraction_quality="text_present"),
        ExtractedPage(page_number=2, text=LIMIT, extraction_quality="text_present"),
    ]


def test_demo_pdf_has_exact_quotes_on_physical_pages(capsys):
    make_ai_demo_pdf()
    path = Path(capsys.readouterr().out.strip())
    try:
        with pymupdf.open(path) as document:
            assert len(document) == 2
            assert COPAY in document[0].get_text()
            assert LIMIT in document[1].get_text()
    finally:
        path.unlink(missing_ok=True)


def provider_result(payload):
    return {
        "status": "completed",
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps(payload)}]}
        ],
    }


def test_two_rule_types_preserve_original_evidence_and_paise():
    result = verify_findings(
        extraction(
            candidate(),
            candidate(
                condition_type="sub_limit",
                page=2,
                quote=LIMIT,
                percent=None,
                amount_rupees=40000,
                treatment="Cataract",
                basis="per eye per policy year",
            ),
        ),
        pages(),
        "doc",
    )
    assert result[0].rule == {"percent": 20, "basis": "admissible expenses"}
    assert result[1].rule == {
        "amount_paise": 4000000,
        "treatment": "Cataract",
        "basis": "per eye per policy year",
    }
    assert result[1].source.page == 2
    assert result[1].source.quote == LIMIT
    assert all(f.review_required and f.verification_status == "needs_review" for f in result)


@pytest.mark.parametrize(
    "changes",
    [
        {"page": 99},
        {"quote": "Invented private quote"},
        {"quote": COPAY.lower()},
    ],
)
def test_hallucinated_citation_has_no_source_or_actionable_rule(changes):
    finding = verify_findings(extraction(candidate(**changes)), pages(), "doc")[0]
    assert finding.source is None
    assert finding.rule is None
    assert finding.status == "uncertain"
    assert finding.verification_status == "insufficient_evidence"
    assert "Invented private quote" not in finding.model_dump_json()


@pytest.mark.parametrize(
    "changes",
    [
        {"percent": 30},
        {"percent": 101},
        {"basis": "entire hospital bill"},
        {"ambiguous": True},
        {"percent": None},
    ],
)
def test_uncertain_numeric_or_applicability_conditions_have_no_rule(changes):
    finding = verify_findings(extraction(candidate(**changes)), pages(), "doc")[0]
    assert finding.rule is None
    assert finding.source.quote == COPAY
    assert finding.status == "uncertain"


def test_bad_quality_and_out_of_scope_and_empty_results():
    bad_pages = pages()
    bad_pages[0].extraction_quality = "needs_review"
    assert verify_findings(extraction(candidate()), bad_pages, "doc")[0].rule is None
    out = extraction(candidate())
    out.is_health_policy = False
    assert verify_findings(out, pages(), "doc") == []
    assert verify_findings(extraction(), pages(), "doc") == []
    assert len(verify_findings(extraction(candidate(), candidate()), pages(), "doc")) == 1


@pytest.mark.parametrize(
    "quote,amount",
    [
        ("Cataract INR 2 lakh per eye.", 2),
        ("Cataract INR 25,000 or INR 40,000 per eye.", 25000),
        ("Cataract INR 25,000 per eye.", 40000),
    ],
)
def test_sublimit_units_and_multiple_values_require_review(quote, amount):
    page = ExtractedPage(page_number=1, text=quote, extraction_quality="text_present")
    c = candidate(
        condition_type="sub_limit",
        quote=quote,
        percent=None,
        amount_rupees=amount,
        treatment="Cataract",
        basis="per eye",
    )
    assert verify_findings(extraction(c), [page], "doc")[0].rule is None


def test_openai_structured_request_and_response(caplog):
    def handler(request):
        assert request.url == "https://api.openai.com/v1/responses"
        body = json.loads(request.content)
        assert body["store"] is False
        assert body["text"]["format"]["strict"] is True
        assert "untrusted evidence" in body["instructions"]
        assert json.loads(body["input"])[1]["page_number"] == 2
        assert request.headers["authorization"] == "Bearer fictional-key"
        return httpx.Response(200, json=provider_result(extraction(candidate()).model_dump()))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await OpenAIExtractor(
                Settings(
                    _env_file=None, openai_api_key="fictional-key", openai_model="fixture-model"
                ),
                client,
            ).extract(pages())
            assert result.findings[0].percent == 20

    asyncio.run(run())
    assert COPAY not in caplog.text
    assert "fictional-key" not in caplog.text


@pytest.mark.parametrize(
    "status,body",
    [
        (429, {"secret": "PRIVATE_SENTINEL"}),
        (200, {"status": "incomplete", "output": []}),
        (
            200,
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "refusal", "refusal": "PRIVATE_SENTINEL"}],
                    }
                ],
            },
        ),
        (
            200,
            provider_result(
                {"is_health_policy": True, "findings": [{"quote": "PRIVATE_SENTINEL"}]}
            ),
        ),
        (200, []),
    ],
)
def test_provider_failure_refusal_and_schema_failure_redacted(status, body, caplog):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body))
        ) as client:
            with pytest.raises(ApiError) as error:
                await OpenAIExtractor(
                    Settings(_env_file=None, openai_api_key="fixture", openai_model="fixture"),
                    client,
                ).extract(pages())
            assert "PRIVATE_SENTINEL" not in error.value.message

    asyncio.run(run())
    assert "PRIVATE_SENTINEL" not in caplog.text


@pytest.mark.parametrize("mode", ["missing-key", "too-long", "no-text", "timeout"])
def test_analysis_limits_and_transport_fail_closed(mode):
    async def run():
        def handler(request):
            if mode == "timeout":
                raise httpx.ReadTimeout("PRIVATE_SENTINEL", request=request)
            pytest.fail("Network should not be called")

        settings = Settings(
            _env_file=None,
            openai_api_key="fixture",
            openai_model="fixture",
            ai_max_input_characters=1000,
        )
        sample = pages()
        if mode == "missing-key":
            settings.openai_api_key = type(settings.openai_api_key)("")
        if mode == "too-long":
            sample[0].text = "x" * 1001
        if mode == "no-text":
            sample = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ApiError) as error:
                await OpenAIExtractor(settings, client).extract(sample)
            assert "PRIVATE_SENTINEL" not in error.value.message

    asyncio.run(run())


class AnalysisMemoryGateway(MemoryGateway):
    def __init__(self):
        super().__init__()
        self.results = {}

    async def prepare_analysis(self, principal, job_id, parsed):
        job = await self.get_job(principal, job_id)
        self.pages[self.jobs[job_id]["document_id"]] = parsed.pages
        job.status, job.stage = "processing", "analyzing"

    async def begin_analysis(self, principal, job_id):
        await self.get_job(principal, job_id)
        doc = self.jobs[job_id]["document_id"]
        return doc, self.pages[doc]

    async def finish_analysis(self, principal, job_id, findings, *, code, message):
        job = await self.get_job(principal, job_id)
        self.results[job.policy_id] = findings
        job.status, job.stage, job.message = "needs_review", "verifying", message
        if code:
            from app.models import JobError

            job.error = JobError(code=code, message=message)

    async def get_findings(self, principal, policy_id):
        await self.require_policy(principal, policy_id)
        return {
            "policy_id": policy_id,
            "analysis_version": "v0.1",
            "findings": self.results.get(policy_id, []),
        }


@pytest.mark.parametrize("provider_fails", [False, True])
def test_upload_to_findings_and_cross_user_api(provider_fails, caplog):
    gateway = AnalysisMemoryGateway()

    class MockExtractor:
        async def extract(self, stored_pages):
            assert COPAY in stored_pages[0].text
            if provider_fails:
                raise RuntimeError("PRIVATE_SENTINEL")
            return extraction(candidate())

    settings = Settings(_env_file=None, ai_extraction_enabled=True)
    with TestClient(create_app(settings, gateway, MockExtractor())) as client:
        upload = client.post(
            "/api/v1/policies/upload",
            headers={"Authorization": "Bearer owner-a"},
            files={"file": ("fictional.pdf", make_pdf((COPAY,)), "application/pdf")},
        )
        assert upload.status_code == 202
        ids = upload.json()
        job = client.get(
            "/api/v1/jobs/" + ids["job_id"], headers={"Authorization": "Bearer owner-a"}
        ).json()
        assert job["status"] == "needs_review"
        assert job["stage"] == "verifying"
        assert bool(job["error"]) == provider_fails
        path = "/api/v1/policies/" + ids["policy_id"] + "/findings"
        own = client.get(path, headers={"Authorization": "Bearer owner-a"})
        assert own.status_code == 200
        assert len(own.json()["findings"]) == (0 if provider_fails else 1)
        assert client.get(path).status_code == 401
        denied = client.get(path, headers={"Authorization": "Bearer owner-b"})
        assert denied.status_code == 404
        assert COPAY not in denied.text
        assert "PRIVATE_SENTINEL" not in own.text
    assert "PRIVATE_SENTINEL" not in caplog.text


def test_gateway_findings_requires_owner_and_scopes_query():
    owner, policy = str(uuid4()), str(uuid4())
    calls = []

    def handler(request):
        calls.append(request.url.path)
        assert request.headers["Accept-Profile"] == "public"
        assert request.url.params["owner_id"] == "eq." + owner
        if request.url.path.endswith("/policies"):
            return httpx.Response(200, json=[{"id": policy}])
        assert request.url.params["policy_id"] == "eq." + policy
        return httpx.Response(200, json=[])

    async def run():
        from app.supabase import Principal

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            gateway = SupabaseGateway(
                Settings(
                    _env_file=None,
                    supabase_url="https://offline.invalid",
                    supabase_publishable_key="fixture",
                ),
                client,
            )
            result = await gateway.get_findings(Principal(owner, "fixture"), policy)
            assert result.findings == []

    asyncio.run(run())
    assert calls == ["/rest/v1/policies", "/rest/v1/findings"]


@pytest.mark.parametrize("complete", [True, False])
def test_stored_page_loading_is_owner_scoped_and_rejects_truncation(complete):
    from app.supabase import Principal

    owner, doc, job = str(uuid4()), str(uuid4()), str(uuid4())

    def handler(request):
        assert request.headers["authorization"] == "Bearer fixture"
        if request.method == "POST":
            assert request.headers["Content-Profile"] == "public"
            assert request.url.path == "/rest/v1/rpc/get_analysis_document"
            return httpx.Response(200, json={"document_id": doc, "page_count": 2})
        assert request.url.params["document_id"] == "eq." + doc
        assert request.url.params["owner_id"] == "eq." + owner
        assert request.headers["Accept-Profile"] == "public"
        return httpx.Response(
            200, json=[p.model_dump() for p in (pages() if complete else pages()[:1])]
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            gateway = SupabaseGateway(
                Settings(
                    _env_file=None,
                    supabase_url="https://offline.invalid",
                    supabase_publishable_key="fixture",
                ),
                client,
            )
            if complete:
                actual_doc, actual_pages = await gateway.begin_analysis(
                    Principal(owner, "fixture"), job
                )
                assert actual_doc == doc
                assert len(actual_pages) == 2
            else:
                with pytest.raises(ApiError) as error:
                    await gateway.begin_analysis(Principal(owner, "fixture"), job)
                assert error.value.code == "AI_PAGE_SEQUENCE"

    asyncio.run(run())


def test_findings_lookup_never_queries_private_rows_after_policy_denial():
    from app.supabase import Principal

    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=[])

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            gateway = SupabaseGateway(
                Settings(
                    _env_file=None,
                    supabase_url="https://offline.invalid",
                    supabase_publishable_key="fixture",
                ),
                client,
            )
            with pytest.raises(ApiError) as error:
                await gateway.get_findings(Principal(str(uuid4()), "fixture"), str(uuid4()))
            assert error.value.status == 404

    asyncio.run(run())
    assert calls == ["/rest/v1/policies"]


def test_schema_requires_all_properties_and_rejects_extras():
    from app.analysis import output_schema

    schema = output_schema()
    for obj in [schema, *schema["$defs"].values()]:
        assert set(obj["required"]) == set(obj["properties"])
        assert obj["additionalProperties"] is False


def test_upload_through_real_http_adapters_to_persisted_findings():
    owner = str(uuid4())
    state = {"calls": [], "findings": []}

    def handler(request):
        path = request.url.path
        state["calls"].append(path)
        if request.url.host == "api.openai.com":
            body = json.loads(request.content)
            assert COPAY in json.loads(body["input"])[0]["text"]
            return httpx.Response(200, json=provider_result(extraction(candidate()).model_dump()))
        assert request.headers["authorization"] == "Bearer fixture-user"
        if path == "/auth/v1/user":
            return httpx.Response(200, json={"id": owner})
        if path.startswith("/storage/"):
            return httpx.Response(200, json={})
        if request.method == "POST":
            assert request.headers["Content-Profile"] == "public"
            body = json.loads(request.content)
            if path.endswith("/create_pdf_upload"):
                state.update(
                    doc=body["p_document_id"], job=body["p_job_id"], policy=body["p_policy_id"]
                )
            elif path.endswith("/prepare_pdf_analysis"):
                state["pages"] = body["p_pages"]
            elif path.endswith("/get_analysis_document"):
                return httpx.Response(
                    200,
                    json={
                        "document_id": state["doc"],
                        "page_count": len(state["pages"]),
                    },
                )
            elif path.endswith("/finish_pdf_analysis"):
                assert body["p_error_code"] is None
                state["findings"] = body["p_findings"]
            else:
                assert path.endswith("/start_pdf_extraction")
            return httpx.Response(204)
        assert request.headers["Accept-Profile"] == "public"
        assert request.url.params["owner_id"] == "eq." + owner
        if path.endswith("/document_pages"):
            return httpx.Response(200, json=state["pages"])
        if path.endswith("/policies"):
            return httpx.Response(200, json=[{"id": state["policy"]}])
        assert path.endswith("/findings")
        rows = [{"payload": f} for f in state["findings"]]
        return httpx.Response(200, json=rows if request.url.params["offset"] == "0" else [])

    settings = Settings(
        _env_file=None,
        supabase_url="https://offline.invalid",
        supabase_publishable_key="fixture",
        ai_extraction_enabled=True,
        openai_api_key="fixture-ai",
        openai_model="fixture-model",
    )
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with TestClient(
            create_app(
                settings, SupabaseGateway(settings, upstream), OpenAIExtractor(settings, upstream)
            )
        ) as client:
            uploaded = client.post(
                "/api/v1/policies/upload",
                headers={"Authorization": "Bearer fixture-user"},
                files={"file": ("fictional.pdf", make_pdf((COPAY,)), "application/pdf")},
            )
            assert uploaded.status_code == 202
            response = client.get(
                "/api/v1/policies/" + uploaded.json()["policy_id"] + "/findings",
                headers={"Authorization": "Bearer fixture-user"},
            )
            assert response.status_code == 200
            finding = response.json()["findings"][0]
            assert finding["rule"]["percent"] == 20
            assert finding["source"]["document_id"] == uploaded.json()["document_id"]
            assert finding["source"]["quote"] == COPAY
            assert "/rest/v1/rpc/finish_pdf_extraction" not in state["calls"]
    finally:
        asyncio.run(upstream.aclose())
