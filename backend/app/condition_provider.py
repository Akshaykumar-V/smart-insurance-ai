"""Opt-in, bounded passage extraction; no retries or financial rule generation."""

import copy
import json

import httpx

from app.condition_workflow import (
    ConditionDiscoveryReport,
    PreparedConditionDocument,
    evaluate_mocked_batches,
    prepare_condition_document,
)
from app.config import Settings
from app.errors import ApiError
from app.models import ExtractedPage
from benchmarks.pilot_preflight import (
    MAX_OUTPUT_TOKENS_PER_REQUEST,
    PILOT_INSTRUCTIONS,
    PILOT_MODEL,
    PILOT_SCHEMA,
    PreparedPilotRequest,
    require_offline_token_budget,
)


def prepare_provider_document(
    document_id: str, pages: list[ExtractedPage]
) -> PreparedConditionDocument:
    """One primary passage per bounded request for the existing token gate."""
    return prepare_condition_document(
        document_id, pages, max_primary_passages=1, max_payload_bytes=2600
    )


class OpenAIConditionExtractor:
    """Reuse the configured Responses client; fail before sending if preflight fails."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    def _request_for(self, batch):
        # The existing offline preflight validates one primary, no context.
        if len(batch.primary_passages) != 1 or batch.context_passages:
            raise ApiError(500, "CONDITION_PREFLIGHT", "Condition extraction is unavailable.")
        passage = batch.primary_passages[0]
        body = {
            "model": self.settings.openai_model,
            "store": False,
            "instructions": PILOT_INSTRUCTIONS,
            "input": json.dumps(batch.payload(), ensure_ascii=False, separators=(",", ":")),
            "max_output_tokens": MAX_OUTPUT_TOKENS_PER_REQUEST,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "offline_clause_pilot",
                    "strict": True,
                    "schema": copy.deepcopy(PILOT_SCHEMA),
                }
            },
        }
        request = PreparedPilotRequest(batch.id, passage.id, passage.page_number, body)
        # This offline gate includes instructions, passage, schema, formatting
        # reserve and reserved output. It never claims an authoritative count.
        require_offline_token_budget((request,))
        return body

    async def extract(self, prepared: PreparedConditionDocument) -> ConditionDiscoveryReport:
        if not self.settings.condition_extraction_enabled:
            raise ApiError(404, "FEATURE_DISABLED", "Condition extraction is unavailable.")
        if (
            self.settings.openai_model != PILOT_MODEL
            or not self.settings.openai_api_key.get_secret_value()
        ):
            raise ApiError(500, "BACKEND_NOT_CONFIGURED", "Condition extraction is unavailable.")
        selected = prepared.plan.batches[: self.settings.condition_max_provider_requests]
        try:
            requests = [(batch, self._request_for(batch)) for batch in selected]
        except Exception:
            raise ApiError(
                500, "CONDITION_PREFLIGHT", "Condition extraction is unavailable."
            ) from None
        responses: dict[str, dict] = {}
        for batch, body in requests:
            try:
                response = await self.client.post(
                    "https://api.openai.com/v1/responses",
                    headers={
                        "Authorization": f"Bearer {self.settings.openai_api_key.get_secret_value()}"
                    },
                    json=body,
                    timeout=self.settings.ai_timeout_seconds,
                )
                if not response.is_success or len(response.content) > 1_000_000:
                    raise ValueError
                responses[batch.id] = response.json()
            except (httpx.RequestError, ValueError):
                # Stop on the first provider error. No paid retry or leaked body.
                responses[batch.id] = {"status": "failed", "output": []}
                break
        return evaluate_mocked_batches(prepared, responses)
