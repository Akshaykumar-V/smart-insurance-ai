# API Contract v0.1 — Shared Frontend / Backend Source of Truth

**Status: proposed implementation baseline, agreed here for parallel coding; endpoints are not yet implemented.** Prefix `/api/v1`. All IDs are opaque strings. JSON UTF-8. Monetary figures are integer INR **paise** internally to avoid floating-point errors; displayed amounts convert to rupees. Percentages use numeric `percent` (e.g. `10` means 10%). ISO dates `YYYY-MM-DD`; timestamps UTC ISO 8601. PDF pages are **1-indexed**.

## Authentication and security
- Supabase Auth; frontend sends `Authorization: Bearer <access_token>` for protected APIs.
- FastAPI must verify token and resource ownership on every protected endpoint, including jobs, evidence and PDF access.
- Frontend never receives OpenAI or Supabase service-role credentials.
- Demo mocks are marked as mock and use no real customer files.

## Standard error
`{ "error": {"code": "INVALID_PDF", "message": "Readable user-facing error", "request_id": "..."} }`
HTTP 400 for invalid fields, 401 unauthenticated, 403 forbidden, 404 not found, 413 oversized file, 422 invalid scenario, 429 throttling, 500 transient server error.

## 1. GET /api/v1/health (public)
200: `{ "status":"ok", "version":"0.1.0" }`

## 2. POST /api/v1/policies/upload (authenticated)
`multipart/form-data`: `file` (required PDF), `policy_id` (optional existing policy ID), `document_type_hint` (optional: `policy_wording|policy_schedule|cis|endorsement|other`). If `policy_id` absent, backend creates a new placeholder policy. Upload triggers ingestion + analysis job automatically. Additional uploaded docs can join existing policy. Backend must validate PDF content, size/pages and ownership.
202 response:
```json
{"policy_id":"pol_demo_001","document_id":"doc_demo_001","job_id":"job_demo_001","status":"queued"}
```

## 3. GET /api/v1/jobs/{job_id} (authenticated)
200 response:
```json
{
  "job_id":"job_demo_001", "policy_id":"pol_demo_001",
  "status":"processing", "stage":"extracting",
  "message":"Reading policy pages", "error":null
}
```
`status`: `queued|processing|completed|failed|needs_review`.
`stage`: `uploaded|extracting|classifying|indexing|retrieving|analyzing|verifying|completed`.
Do not invent percent progress. Frontend polls (e.g. every 2s with stop/backoff) until terminal job status, and can manually retry failed job only if a real backend endpoint is later added.

## 4. GET /api/v1/policies (authenticated)
200 response:
```json
{"items":[{"id":"pol_demo_001","category":"health","policy_type":"family_floater","insurer":"Fictional Health Insurer","product_name":"Demo Family Cover","sum_insured_paise":50000000,"start_date":null,"end_date":null,"analysis_status":"ready","needs_review":true}],"next_cursor":null}
```
`category`: `health|life|vehicle|animal|property|other`.
`policy_type`: `individual|family_floater|other|unknown`.
`analysis_status`: `not_started|processing|ready|needs_review|failed|unsupported`.

## 5. GET /api/v1/policies/{policy_id} (authenticated)
200 response:
```json
{
 "id":"pol_demo_001","category":"health","policy_type":"family_floater", "insurer":"Fictional Health Insurer", "product_name":"Demo Family Cover","uin":null,
 "policyholder_name":null,"sum_insured_paise":50000000,"start_date":null,"end_date":null,
 "insured_members":[],"analysis_status":"ready", "needs_review":true,
 "documents":[{"id":"doc_demo_001","type":"policy_wording","name":"demo-wording.pdf","page_count":25,"processing_status":"indexed"}]
}
```
Null means unknown; no guessed age/member/date.

## 6. GET /api/v1/policies/{policy_id}/findings (authenticated)
200 response:
```json
{
 "policy_id":"pol_demo_001","analysis_version":"v0.1",
 "findings":[{
    "id":"finding_demo_001", "condition_type":"co_payment", "status":"found", "verification_status":"needs_review",
    "title":"Age-linked co-payment", "explanation":"A 20% share may apply to eligible insured people aged 60 or over.",
    "rule":{"percent":20,"basis":"admissible_expenses","minimum_age":60},
    "applicability":"Only when an insured member is aged at least 60, subject to exact terms.",
    "exceptions":[], "source":{"document_id":"doc_demo_001","page":12,"quote":"Fictional clause for UI development only."},
    "review_required":true
 }]
}
```
`condition_type`: `co_payment|deductible|sub_limit|room_rent|waiting_period|exclusion`.
`status`: `found|not_found_after_search|uncertain|not_applicable`.
`verification_status`: `verified|needs_review|insufficient_evidence|conflicting`.
`rule` is a typed object varying by condition; support `null` and unknown fields. A result with status `not_found_after_search` must not be rendered as "covered".

## 7. GET /api/v1/documents/{document_id}/access (authenticated)
200: `{ "document_id":"doc_demo_001", "url":"<short-lived-authorized-PDF-URL>","expires_at":"2026-10-25T20:00:00Z" }`
Frontend opens viewer with `#page=12` based on 1-indexed evidence. Only actual backend-confirmed page and quote can be displayed; highlighting coordinates may be added later.

## 8. POST /api/v1/policies/{policy_id}/simulate (authenticated)
Request (fictional):
```json
{"insured_age":65,"estimated_admissible_expenses_paise":10000000,"treatment_label":"Illustrative surgery","room_rent_per_day_paise":null,"room_days":null}
```
200 response:
```json
{
 "policy_id":"pol_demo_001","status":"insufficient_evidence",
 "scenario":{"insured_age":65,"estimated_admissible_expenses_paise":10000000},
 "results":[],
 "missing_information":["The co-payment rule is not yet source-verified."],
 "disclaimer":"Illustrative decision support; not an insurer claim decision."
}
```
`status`: `illustrative|partially_calculable|insufficient_evidence`.
When verified applicability + financial bases are available, `results[]` can contain:
`{"condition_type":"co_payment","customer_share_paise":2000000,"calculation":"20% of ₹1,00,000 admissible expenses","finding_id":"finding_demo_001"}`.
Do **not** display a complete insurer payout without all adjustments. Complex restrictions return an explanation without an arbitrary rupee figure.

## 9. Deleting data (P1)
`DELETE /api/v1/policies/{policy_id}` (authenticated) -> 204. Must remove or schedule deletion of policy-specific private documents, embeddings, and data. Frontend waits for actual confirmation.

## Coordination rule
Changes to paths, status enums, fields, money unit, auth, or page numbering require editing THIS file first, informing both laptops and updating any typed client. If a real backend implementation already exists, reconcile this contract before changing source code.


## 10. Additive claim-affecting condition extraction (Feature 1)

Final backend schema: https://github.com/Akshaykumar-V/smart-insurance-ai/issues/1#issuecomment-6494218395

This addition preserves all v0.1 upload/findings/simulator behavior. Routes remain disabled/unregistered until explicitly enabled by the backend; schema agreement is not permission to make live extraction calls.

- POST `/api/v1/policies/{policy_id}/condition-extractions`, JSON `{ "document_id": "<uuid>" }`, returns HTTP 202 with policy_id, document_id, job_id and JobStatus. A duplicate start returns the existing job's current status, not necessarily queued. Never automatically retry a POST after unknown acceptance.
- GET `/api/v1/jobs/{job_id}` uses the existing authenticated JobResponse and ownership checks.
- GET `/api/v1/policies/{policy_id}/conditions?job_id=<uuid>` returns exactly the selected run, never a latest-run fallback. Missing/foreign runs return 404.
- Run fields: policy_id/document_id/job_id UUIDs, status JobStatus, analysis_state complete|incomplete|null, warning string|null, rejected_candidate_count nonnegative integer, conditions array. Analysis state is null for queued/processing/failed. Failed and incomplete runs require non-empty content-free warnings. Successful zero-condition runs are incomplete with a warning.
- Condition fields: id `condition_` plus 20 lowercase hex characters; document_id/job_id matching the run; category uses the six ConditionType values; kind benefit|restriction|condition|definition|procedural_requirement|other; non-empty title; specific_label/applicability string|null; observed_value_mentions/exceptions string arrays; dependencies objects `{kind: policy_schedule|endorsement|other_clause, label?: string|null}` (omitted label defaults null; unknown dependency keys rejected); evidence array of 1-6 entries; literal source_verified=true and review_required=true.
- Evidence: opaque non-empty passage_id, physical 1-indexed page 1-200, zero-based Unicode-code-point start-inclusive/end-exclusive offsets with end>start, exact anchored quote of at least 12 characters. Frontend must not normalize or re-slice quotations. Backend anchors evidence and literal value mentions; source verification is not insurer certification.
- Complete means planned passages processed, not exhaustive discovery. No financial rule/calculation field is added. Historical job discovery remains separate; explicit known job IDs support retrieval now.

The additive shared TypeScript models are in `frontend_api_types.ts`; frontend boundary and adapter documentation is in `frontend/CONDITION_EXTRACTION_CONTRACT.md`.
