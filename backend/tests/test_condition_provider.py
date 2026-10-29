"""No network or paid calls: all provider responses use MockTransport."""

import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from app.condition_provider import OpenAIConditionExtractor, prepare_provider_document
from app.config import Settings
from app.errors import ApiError
from app.models import ExtractedPage
from benchmarks.pilot_preflight import OfflineTokenBudgetUnavailable


def _prepared(*texts):
    return prepare_provider_document(
        "fictional-document",
        [
            ExtractedPage(page_number=index, text=text, extraction_quality="text_present")
            for index, text in enumerate(texts, start=1)
        ],
    )


def _settings(**changes):
    return Settings(
        _env_file=None,
        condition_extraction_enabled=True,
        openai_model="gpt-4.1-mini",
        openai_api_key=SecretStr("synthetic-test-only"),
        **changes,
    )


def _response(candidates):
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


def _candidate(passage):
    return {
        "title": "Fictional room condition",
        "category": "room_rent",
        "specific_label": None,
        "kind": "restriction",
        "evidence": [{"passage_id": passage.id, "excerpt": passage.text}],
        "applicability": None,
        "exceptions": [],
        "dependencies": [],
        "review_status": "needs_review",
    }


def test_disabled_feature_cannot_invoke_provider():
    prepared = _prepared("Room rent is limited to INR 5,000 per day.")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=_response([]))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            extractor = OpenAIConditionExtractor(
                Settings(_env_file=None, condition_extraction_enabled=False), client
            )
            with pytest.raises(ApiError) as error:
                await extractor.extract(prepared)
            assert error.value.code == "FEATURE_DISABLED"

    asyncio.run(run())
    assert calls == []


def test_preflight_failure_blocks_all_requests(monkeypatch):
    prepared = _prepared("Room rent is limited to INR 5,000 per day.")
    calls = []

    def fail(_):
        raise OfflineTokenBudgetUnavailable("Unavailable")

    monkeypatch.setattr("app.condition_provider.require_offline_token_budget", fail)

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=_response([]))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ApiError) as error:
                await OpenAIConditionExtractor(_settings(), client).extract(prepared)
            assert error.value.code == "CONDITION_PREFLIGHT"

    asyncio.run(run())
    assert calls == []


def test_real_offline_preflight_accepts_small_synthetic_request_without_sending():
    prepared = _prepared("Room rent is limited to INR 5,000 per day.")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=_response([]))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            extractor = OpenAIConditionExtractor(_settings(), client)
            return extractor._request_for(prepared.plan.batches[0])

    body = asyncio.run(run())
    assert body["max_output_tokens"] == 800
    assert calls == []


def test_wrong_model_cannot_send_even_with_a_mock_transport():
    prepared = _prepared("Room rent is limited to INR 5,000 per day.")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=_response([]))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            settings = _settings()
            settings.openai_model = "unsupported-model"
            with pytest.raises(ApiError) as error:
                await OpenAIConditionExtractor(settings, client).extract(prepared)
            assert error.value.code == "BACKEND_NOT_CONFIGURED"

    asyncio.run(run())
    assert calls == []


def test_mocked_provider_accepts_exact_evidence_with_no_rule(monkeypatch):
    prepared = _prepared("Room rent is limited to INR 5,000 per day.")
    calls = []
    monkeypatch.setattr("app.condition_provider.require_offline_token_budget", lambda _: ())

    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        assert body["store"] is False
        assert body["max_output_tokens"] == 800
        assert len(json.loads(body["input"])["primary_passages"]) == 1
        return httpx.Response(200, json=_response([_candidate(prepared.manifest.passages[0])]))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await OpenAIConditionExtractor(_settings(), client).extract(prepared)

    report = asyncio.run(run())
    assert len(calls) == 1
    assert len(report.conditions) == 1
    assert report.conditions[0].clause.evidence[0].page_number == 1
    assert report.conditions[0].observed_value_mentions == ("INR 5,000",)
    assert not hasattr(report.conditions[0], "rule")


def test_provider_error_stops_without_retry_and_marks_incomplete(monkeypatch):
    prepared = _prepared(
        "Room rent is limited to INR 5,000 per day.",
        "The waiting period is 24 months for listed conditions.",
    )
    calls = []
    monkeypatch.setattr("app.condition_provider.require_offline_token_budget", lambda _: ())

    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={"message": "do not expose"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await OpenAIConditionExtractor(_settings(), client).extract(prepared)

    report = asyncio.run(run())
    assert len(calls) == 1
    assert report.failed_batches == 1
    assert report.incomplete
    assert "do not expose" not in report.warning


def test_request_cap_preserves_unprocessed_warning(monkeypatch):
    prepared = _prepared(
        "Room rent is limited to INR 5,000 per day.",
        "The waiting period is 24 months for listed conditions.",
    )
    calls = []
    monkeypatch.setattr("app.condition_provider.require_offline_token_budget", lambda _: ())

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=_response([]))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await OpenAIConditionExtractor(
                _settings(condition_max_provider_requests=1), client
            ).extract(prepared)

    report = asyncio.run(run())
    assert len(calls) == 1
    assert report.planned_batches == 2
    assert report.processed_batches == 1
    assert "1 unprocessed batches" in report.warning
