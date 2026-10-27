# Milestone 3A: bounded health-clause extraction

Hackathon proof-of-concept, not a claims adjudicator. No claim calculations, embeddings,
hybrid RAG, OCR, or frontend changes. Existing API v0.1 and shared TypeScript shapes
remain unchanged. This implements the already-contracted findings endpoint and upload
job integration; no new public analysis/retry endpoint is introduced.

## Flow and limits

AI_EXTRACTION_ENABLED defaults to false. With it enabled, upload still returns 202.
After PDF parsing, prepare_pdf_analysis atomically persists pages using the existing
ingestion function and keeps the job processing/analyzing. Original page text is then
read from Supabase with the owner's JWT and explicit owner/document filters.
The backend sends all pages, as untrusted evidence, to OpenAI's Responses API with
strict JSON-schema output and store=false. This is not a zero-retention guarantee;
only use public wording and fictional data for the demo.

Default input limit: 120,000 characters, maximum 200 physical pages from ingestion;
no silent truncation or retrieval shortcut. The response permits at most 32 candidates
and 8,000 output tokens. Large inputs, truncated/refused/invalid responses, missing
configuration and timeouts are explicit job errors. No automatic retries/cost loops.
Jobs use the existing in-process BackgroundTasks mechanism: server restarts or token
expiry can interrupt work. A queue, durable retries and rate limiting are deferred.

Supported candidates: percentage co-payments and explicit integer INR treatment
sub-limits. INR rupees are converted to integer paise for storage, not used to calculate
payments. Lakh/crore, amounts in words, multiple competing amounts, unclear basis,
and percentages of sum insured require review rather than inferred numeric rules.
Each document is analyzed independently. Policy-level results collect findings across
documents without reconciling schedule/endorsement conflicts.

Exact, case-sensitive contiguous quote matching against the referenced physical page
is mandatory. No fuzzy matching or invented citations. Matched numeric tokens and
basis/treatment text are checked before a rule is retained. Incorrect quotes/pages
produce uncertain/insufficient_evidence with source=null and rule=null; invented
quotes are not returned as evidence. Matching quotes with ambiguous/unsupported rules
retain the source, but rule=null and status=uncertain.

Every finding is review_required=true. Even a source-matched numeric rule remains
needs_review: quote presence does not verify applicability, completeness, model health
classification, exceptions or insurer decisions. Explanation/applicability/exception
text is AI interpretation, not independently verified source text. An empty list is
not a coverage guarantee. Findings are marked found only when the local numeric checks
pass; otherwise uncertain. The terminal job is needs_review/verifying, with a safe
error object if AI failed. Parsed pages remain available if the provider fails.

## Database migration

Apply supabase/migrations/202610260004_ai_extraction.sql after the first four migrations
in the disposable project. The user reports that this migration has been applied. It creates public.findings
and three SECURITY INVOKER RPCs:

- prepare_pdf_analysis(uuid,jsonb): atomic PDF completion and analysis transition.
- get_analysis_document(uuid): owner-scoped active job/document metadata.
- finish_pdf_analysis(uuid,jsonb,text,text): atomic findings replacement for that
  document and terminal job status. Rechecks source document, physical page, and exact
  quote in SQL before accepting evidence.

All new functions revoke PUBLIC/anon execution and grant authenticated execution.
The findings table uses owner-only RLS and owner-consistent composite foreign keys
to documents/policies; policy/document deletion cascades to findings. Authenticated
CRUD matches the existing SECURITY INVOKER model. Never use a service-role key.

Schema implementation detail relative to DATABASE_SCHEMA.md: for this smallest MVP,
the v0.1 finding fields (condition, rule, applicability, exceptions, source, etc.) are
stored together in a payload JSONB column; id, owner_id, policy_id, document_id,
analysis_version and created_at remain relational. This keeps the API shape intact,
with no shared contract changes. No queryable per-rule indexes are introduced.
Owner-writable records are not tamper-proof audit evidence.

Run supabase/verify_ai_extraction.sql read-only after application. It checks RLS and
effective grants and displays predicates/constraints. Static/offline tests do not prove
the new SQL executes correctly or deployed isolation works; verify with two test users.
Existing migration files and Storage policies are unchanged.

## API response

GET /api/v1/policies/{policy_id}/findings requires the caller's Supabase bearer token.
Missing/foreign policy returns the existing 404 NOT_FOUND envelope before reading
findings. Owner policies with no saved findings return an empty findings list; consult
GET /api/v1/jobs/{job_id} to distinguish pending, failed or no supported clauses.

Fictional response example (IDs are illustrative):

    {
      "policy_id": "policy-id",
      "analysis_version": "v0.1",
      "findings": [{
        "id": "finding-id",
        "condition_type": "co_payment",
        "status": "found",
        "verification_status": "needs_review",
        "title": "Percentage co-payment",
        "explanation": "An age-linked co-payment may apply. Applicability and exceptions require review.",
        "rule": {"percent": 20, "basis": "admissible expenses"},
        "applicability": "Age 60 and above.",
        "exceptions": [],
        "source": {
          "document_id": "document-id",
          "page": 1,
          "quote": "Health insurance: A co-payment of 20% of admissible expenses applies to age 60 and above."
        },
        "review_required": true
      }]
    }

A supported sub_limit rule has exactly amount_paise (integer), treatment (string),
and basis (string). Example: amount_paise=4000000, treatment=Cataract,
basis=per eye per policy year. Unsupported rules and unverifiable sources are null,
as allowed by the shared TypeScript Finding type. No simulator output is produced.

## Backend configuration

Keep these only in the ignored backend/.env:

- Existing SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY.
- AI_EXTRACTION_ENABLED=true to opt in after migration; false preserves ingestion.
- OPENAI_API_KEY: backend-only secret, never shared with the browser or committed.
- OPENAI_MODEL: an available model ID supporting Responses strict structured outputs.
  It is required explicitly; no model is silently selected.
- AI_MAX_INPUT_CHARACTERS=120000 (bounded 1000 through 200000).
- AI_TIMEOUT_SECONDS=90 (maximum 180).

The HTTP adapter uses the existing httpx dependency. No SDK/framework dependency
or lockfile change is needed. OpenAI reference:
https://developers.openai.com/api/docs/guides/structured-outputs

## One real extraction

1. Apply the new migration and run the read-only audit on the disposable project.
2. Configure the values above locally. Do not send keys or JWTs in chat.
3. Generate a fictional PDF from backend/:

       rtk proxy .venv/Scripts/python.exe -m scripts.make_ai_demo_pdf

   This prints the path to a newly generated PDF in the OS temp directory.
4. Start the backend from backend/:

       rtk proxy .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

5. Open http://127.0.0.1:8000/docs. Use Authorize with a fresh access token from your
   signed-in Supabase test user's session. Keep it local; never use a service-role key.
   POST /api/v1/policies/upload with that fictional PDF and policy_wording hint.
6. Poll GET /api/v1/jobs/{job_id} from the 202 response until needs_review or failed.
   Inspect the safe error code if AI failed. Then call
   GET /api/v1/policies/{policy_id}/findings and compare every quote/page to the PDF.
   For this two-page fictional fixture, expect a 20% co-payment cited to physical PDF
   page 1 and a Cataract sub-limit of 4000000 paise (INR 40,000) cited to page 2.
   Both quotes must match contiguous extracted page text exactly; do not interpret
   uncertain/null rules as numeric findings. Repeat the GET with the second test
   user's token: expect 404 with no findings.
7. Delete only generated fixtures through the established Storage-first cleanup
   procedure. Delete the local temporary demo PDF when done.

Do not enable debug HTTP logging or paste findings containing real customer content.
Use a new upload for another attempt; there is no public retry endpoint in v0.1.
The existing scripts.run_supabase_live explicitly disables AI to preserve the original
ingestion security gate. Its passing result does not validate this new AI migration.

## Offline validation

tests/test_analysis.py uses fictional clauses and mocked OpenAI HTTP responses.
It covers both rule types, numeric/source mismatches, ambiguity, bad page quality,
out-of-scope/empty results, refusal, malformed output, timeout, input limits,
upload-to-findings API behavior, cross-user denial, owner filters and incomplete pages.
No paid OpenAI request or new live SQL execution is claimed.


## Verification record

### User-reported live extraction

On 2026-10-27, the user reported one authenticated fictional-PDF upload accepted with
HTTP 202, a terminal `needs_review` job, and findings for the 20% co-payment on physical
page 1 and the INR 40,000 cataract sub-limit on physical page 2. The user confirmed
matching source quotations, document attribution, and `needs_review` on both findings.
The user also reported that a second test user received HTTP 404 for the first user's
findings. These are user-reported live results; they were not independently rerun here.

### Offline checks rerun during commit preparation

- `tests/test_analysis.py`: 32 passed; one existing Starlette deprecation warning.
- Full offline suite (`-m "not live"`): 189 passed, 2 live cases deselected; one existing
  Starlette deprecation warning.
- Ruff lint passed; formatting check passed with 25 files already formatted.
- No paid OpenAI request or live Supabase test was made during commit preparation.

Commands (from backend/):

    rtk proxy .venv/Scripts/python.exe -m pytest -q tests/test_analysis.py --tb=short
    rtk proxy .venv/Scripts/python.exe -m pytest -q -m "not live" --tb=short
    rtk proxy .venv/Scripts/python.exe -m ruff check app tests scripts
    rtk proxy .venv/Scripts/python.exe -m ruff format --check app tests scripts

Milestone files added: app/analysis.py, tests/test_analysis.py,
scripts/make_ai_demo_pdf.py, this guide, ../supabase/verify_ai_extraction.sql,
../supabase/migrations/202610260004_ai_extraction.sql.
Existing files updated: app/config.py, app/main.py, app/supabase.py,
app/diagnostics.py, scripts/run_supabase_live.py, tests/test_live_runner.py,
.env.example, SUPABASE_SETUP.md. Earlier staged Supabase work was preserved;
Milestone 3A changes were left unstaged. No commit, push or merge performed.
