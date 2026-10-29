# Claim-affecting conditions API proposal (pending Laptop 2 agreement)

This is an additive proposal. `API_CONTRACT.md` v0.1 and its findings endpoint
remain unchanged until both laptops agree on the typed client contract.

All endpoints require the existing bearer token. IDs are UUID strings. A run
selects **one** existing, owner-owned, extracted text document. To analyze both
wording and a schedule, start one run for each document. Every returned clause
retains its own `document_id` and `job_id`; separate documents are not assumed
to have compatible terms.

## Start a run

`POST /api/v1/policies/{policy_id}/condition-extractions`

Request: `{"document_id":"<uuid>"}`. An absent, foreign-owned, wrong-policy,
unextracted or unreadable document is rejected without a provider call. A run
cannot start when the feature flag is disabled. Reuse the existing authenticated
`GET /api/v1/jobs/{job_id}` for status.

202 response:

```json
{"policy_id":"<uuid>","document_id":"<uuid>","job_id":"<uuid>","status":"queued"}
```

Repeated requests for the same owner-owned document return the same `job_id`
and its current status without scheduling another provider run. A new analysis
attempt would require a separately reviewed retry contract.

## Read one run

`GET /api/v1/policies/{policy_id}/conditions?job_id=<uuid>`

`job_id` is required. It selects exactly one owner-owned discovery run; no
"newest job" fallback is allowed. The endpoint returns 404 for a different
owner or policy. A zero-condition run is still returned with its warning.

```json
{
  "policy_id":"<uuid>","document_id":"<uuid>","job_id":"<uuid>",
  "status":"needs_review","analysis_state":"incomplete",
  "warning":"Analysis incomplete; no result establishes the absence of restrictions.",
  "rejected_candidate_count":1,
  "conditions":[{
    "id":"<stable opaque id>","document_id":"<uuid>","job_id":"<uuid>",
    "category":"room_rent","kind":"restriction",
    "title":"Room rent condition","specific_label":null,
    "observed_value_mentions":["INR 5,000"],
    "applicability":"Subject to member schedule",
    "exceptions":["ICU stays are excepted"],
    "dependencies":[{"kind":"policy_schedule","label":null}],
    "evidence":[{
      "passage_id":"<opaque id>","page":1,"start":0,"end":62,
      "quote":"<exact verified quotation>"
    }],
    "source_verified":true,"review_required":true
  }]
}
```

`status` uses the existing job status enum. `analysis_state` is null while
queued or processing, then `complete|incomplete`. Even `complete` means only that planned text passages
were processed, **not** that every policy condition was found. The `warning`
is content-free and non-null for incomplete runs. Titles, categories,
applicability, exceptions and dependencies are model interpretations for human
review. Only evidence spans and literal value mentions are source verified.
There is no financial `rule` field and these conditions cannot enter claim
calculations. Physical PDF pages are 1-indexed; offsets index the canonical
page text in Python characters. No clause is returned without exact evidence.

The frontend should retain `job_id` from the start response (including after
refresh), poll the existing job endpoint, then request this run by `job_id`.
For more than one document, it can show separate run results with document
labels; it should not silently combine clauses into an applicability decision.

## Backend activation checklist

The route implementation is isolated in `app/condition_routes.py` and is
mounted only in tests. After Laptop 2 confirms issue #1, coordinate the shared
contract and frontend types, then review and apply
`patches/feature1_register_routes.patch` to `app/main.py`. This patch merely
registers the proposed routes; the feature flag still defaults to false.

Review `supabase/migrations/202610290001_claim_conditions.sql` before manually
applying it. It creates owner-readable, server-written condition runs and rows,
links each run to exactly one existing analysis job and document, and exposes
three server-only RPCs for atomic job start, progress, and result persistence.
Run `supabase/verify_claim_conditions.sql` afterward; it is read-only. Then
perform a live two-user read isolation check. Neither SQL file has been run.

Backend configuration names: `SUPABASE_SERVICE_ROLE_KEY`,
`CONDITION_EXTRACTION_ENABLED`, `CONDITION_MAX_PROVIDER_REQUESTS`, and the
existing `OPENAI_MODEL` / `OPENAI_API_KEY`. Keep the service role key on the
backend only. The feature flag and a default two-request cap prevent accidental
full-document spending. A real test still needs separate paid-call approval.

Provider requests use one primary passage each and never retry automatically.
A run beyond its configured request cap is explicitly incomplete; the response
does not claim full clause coverage or policy applicability. The existing
`/findings` v0.1 API and claim calculations are unaffected.
