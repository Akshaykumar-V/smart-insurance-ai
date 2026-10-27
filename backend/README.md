# Smart Insurance API backend

Hackathon proof-of-concept, not a production insurance or claim-processing service.
The backend provides authenticated policy reads, PDF ingestion, and bounded AI extraction
of two clause types. It does not calculate claims or make insurer decisions. Embeddings,
hybrid retrieval, OCR, and policy list/detail writes are not implemented.

## Local setup

Requires Python 3.12–3.14 and [uv](https://docs.astral.sh/uv/). From the repository root:

```powershell
cd backend
uv sync --locked
Copy-Item .env.example .env
```

On macOS/Linux, use `cp .env.example .env`. Set `SUPABASE_URL` and
`SUPABASE_PUBLISHABLE_KEY` in `.env`. The latter is the project's public publishable
key or legacy anon key; this backend does not require a service-role key.
Keep `.env` and real documents out of Git. The example contains no credentials.

Before testing authenticated uploads, apply
`../supabase/migrations/202610250001_pdf_ingestion.sql` using the Supabase SQL editor
or your Supabase migration workflow against a **disposable development project**.
Then apply `../supabase/migrations/202610260001_ingestion_security.sql` and run
`../supabase/verify_pdf_ingestion.sql`. Follow [the live setup runbook](SUPABASE_SETUP.md)
for exact configuration, audit expectations, credentials, and the two-user test gate.
The migration creates four tables, three transactional RPCs, RLS policies, and a private
`policy-documents` bucket. It is an initial migration, not an idempotent upgrade script.
No migration is applied automatically by the API. Existing public buckets with this
name cause the migration to fail instead of accepting public document storage.

Create/sign in two fictional test users through Supabase Auth for integration testing.
The frontend supplies its user's access token. No authentication bypass or mock-token
mode is shipped. Health and offline automated tests work without Supabase configuration.

```powershell
uv run --locked uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for the interactive API. The public health response is
a liveness check, not a claim that Supabase is configured or reachable.
For commands in this repository's Codex environment, prepend `rtk proxy` per `RTK.md`.

## Implemented API

| Method and path | Behavior |
| --- | --- |
| `GET /api/v1/health` | Public; `200 {"status":"ok","version":"0.1.0"}` |
| `GET /api/v1/policies` | Authenticated; returns the caller's policy cards and `next_cursor: null` |
| `GET /api/v1/policies/{policy_id}` | Authenticated; returns one owned policy with minimal document metadata; missing/foreign IDs return 404 |
| `POST /api/v1/policies/upload` | Authenticated multipart; returns the exact v0.1 `202` ID envelope |
| `GET /api/v1/jobs/{job_id}` | Authenticated and owner-scoped; returns v0.1 job status/stage/error |
| `GET /api/v1/policies/{policy_id}/findings` | Authenticated and owner-scoped; returns the policy's evidence-backed findings |

### Policy read response contracts

`GET /api/v1/policies` returns only policies owned by the authenticated user. An empty
wallet is `{"items":[],"next_cursor":null}`. The current backend loads all owner rows
internally and returns `next_cursor: null`.

```json
{
  "items": [{
    "id": "pol_demo_001",
    "category": "health",
    "policy_type": "family_floater",
    "insurer": "Fictional Health Insurer",
    "product_name": "Demo Family Cover",
    "sum_insured_paise": 50000000,
    "start_date": null,
    "end_date": null,
    "analysis_status": "needs_review",
    "needs_review": true
  }],
  "next_cursor": null
}
```

`GET /api/v1/policies/{policy_id}` returns this card metadata plus policy details and
minimal document metadata. `needs_review` is true when `analysis_status` is
`needs_review`. The current schema does not store insured-member records, so
`insured_members` is `[]`; unknown schedule fields remain null.

```json
{
  "id": "pol_demo_001",
  "category": "health",
  "policy_type": "family_floater",
  "insurer": "Fictional Health Insurer",
  "product_name": "Demo Family Cover",
  "uin": null,
  "policyholder_name": null,
  "sum_insured_paise": 50000000,
  "start_date": null,
  "end_date": null,
  "insured_members": [],
  "analysis_status": "needs_review",
  "needs_review": true,
  "documents": [{
    "id": "doc_demo_001",
    "type": "policy_wording",
    "name": "demo-wording.pdf",
    "page_count": 2,
    "processing_status": "needs_review"
  }]
}
```

These responses match `PolicyCard`, `PolicyDetails`, and `PolicyDocument` in
`../frontend_api_types.ts`. Monetary values are integer paise; dates are ISO `YYYY-MM-DD`
or null. Document `name` maps to stored `file_name`. Storage paths, checksums, owner
IDs, and extracted page text are not returned. Invalid, missing, and foreign policy IDs
all receive the standard 404 `NOT_FOUND` envelope.

Upload accepts `file`, optional `policy_id`, and optional `document_type_hint`:
`policy_wording`, `policy_schedule`, `cis`, `endorsement`, or `other`.
An absent policy ID creates an owned placeholder. Unknown insurance/schedule fields
remain null; category defaults to `other` and policy type to `unknown`. A document-type
hint is stored as a hint, not as an AI classification result.

Example (set `ACCESS_TOKEN` locally from a Supabase test-user session; do not paste it into Git):

```powershell
curl.exe http://127.0.0.1:8000/api/v1/health
curl.exe -X POST http://127.0.0.1:8000/api/v1/policies/upload `
  -H "Authorization: Bearer $env:ACCESS_TOKEN" `
  -F "file=@fictional-policy.pdf;type=application/pdf" `
  -F "document_type_hint=policy_wording"
curl.exe http://127.0.0.1:8000/api/v1/jobs/JOB_ID_FROM_UPLOAD `
  -H "Authorization: Bearer $env:ACCESS_TOKEN"
```

Upload response:

```json
{"policy_id":"<opaque-id>","document_id":"<opaque-id>","job_id":"<opaque-id>","status":"queued"}
```

The job progresses `queued/uploaded` → `processing/extracting` →
`needs_review/extracting` after text extraction if AI is disabled. With AI enabled after
migration 004, jobs proceed through `processing/analyzing` to `needs_review/verifying`.
Parsing and AI failures return a safe error. No invented progress percentages or claim
decisions are returned.

Extracted text is persisted in `document_pages`, including blank pages. The first
physical PDF page is `page_number=1`, regardless of printed page labels. Text is not
trimmed, summarized, or rewritten. `method=pymupdf` and `extraction_quality` is one of:

- `text_present`: some text was extracted; this does not certify its correctness.
- `no_text`: no non-whitespace text was extracted; the page may be blank or scanned.
- `needs_review`: replacement or NUL characters indicate questionable extraction.

The API has no raw-page-text endpoint or upload text field. Page rows remain available
to subsequent backend stages and owner-scoped database inspection. AI interpretation is
limited to the supported extraction behavior in [AI_EXTRACTION.md](AI_EXTRACTION.md);
no claim calculations are performed.

## Validation, auth, and limits

- Supabase `/auth/v1/user` validates each bearer token. Owners are never supplied by
  form input. Queries explicitly filter the owner and PostgreSQL RLS checks it again.
- Private storage names are `<owner-id>/<policy-id>/<document-id>.pdf`; uploaded
  filenames are metadata only. No public URL is issued. Another owner's policy/job
  appears as `404`, avoiding resource existence disclosure.
- The complete request is bounded before multipart parsing, even without
  `Content-Length`. Default file limit: 20 MiB, plus 1 MiB request-envelope allowance.
- Require a `.pdf` filename, PDF or generic binary MIME, `%PDF-` signature, and a valid
  PyMuPDF document. MIME and extension alone are insufficient.
- Reject empty files, zero-page PDFs, encrypted PDFs (including owner-only encryption),
  damaged/repaired PDFs, more than 200 pages, and unsupported files.
- Inspect and extract in disposable subprocesses with a 20-second timeout per pass;
  terminate timed-out parsers. Extract at most 2,000,000 characters. The timeout and
  size/page/text settings can be reduced in `.env`; hard upper limits remain enforced.
- Empty/scanned pages are retained and flagged for review. Garbled-text detection is
  deliberately limited; arbitrary font encoding/layout errors are not reliably detected.
- Standard errors contain `code`, a safe `message`, and `request_id`; the ID also appears
  in `X-Request-ID`. Invalid upload fields use HTTP 400, files exceeding size limits 413,
  missing/invalid authentication 401, throttling 429, and infrastructure failures 500.
  Upstream error bodies and PDF text are not logged.

## Tests and exit criteria

```powershell
uv run --locked pytest -q
uv run --locked ruff check app tests
uv run --locked ruff format --check app tests
```

Offline tests generate fictional PDFs in memory and exercise the FastAPI application,
real PyMuPDF parsing, isolated parser execution, limits, corruption/encryption/blank
pages, error sanitization, bearer validation, ownership checks, storage failure handling,
and contract response shapes. Memory repositories and mocked HTTP transports exist only
in tests; they do not prove that live Supabase RLS or migrations work.

The two parametrized live cases in `tests/test_supabase_live.py` require explicit
`RUN_SUPABASE_LIVE=1` plus `TEST_SUPABASE_TOKEN_A` and `TEST_SUPABASE_TOKEN_B`, alongside
the configured `.env`. The [setup runbook](SUPABASE_SETUP.md) includes an interactive
runner that obtains fresh tokens without printing them. Both users are tested as the
owner and attacker. Checks cover uploads, attachment, jobs, persisted pages, direct
table read/write isolation, RPCs, private Storage and anonymous denial. Cleanup only
targets the generated fixtures. Without opt-in the cases are **skipped**; opting in
with missing configuration fails rather than silently skipping. To force offline
execution regardless of environment, run `pytest -q -m "not live"`.

Local acceptance: tests/lint/format pass, physical page numbering is preserved, and
responses conform to the implemented v0.1 endpoints. Integration acceptance
additionally requires the live test against the migration. See `MILESTONE_1_STATUS.md`
for tests actually executed in this workspace.

## Known limitations and documentation reconciliation

- `API_CONTRACT.md` remains the shared API source of truth. The existing policy
  list/detail response shapes are implemented; no contract fields or enums changed.
- Limits, extraction-quality labels, database RPCs, and intermediate document statuses
  were unspecified; the choices above are backend implementation details.
- FastAPI background tasks are process-local, not a durable queue. A restart or token
  expiry can leave jobs queued/processing. Failure-state persistence is best effort if
  Supabase is unavailable. There is no retry/resume endpoint in v0.1. Re-upload with a
  refreshed token for this prototype; durable jobs are a later task.
- Storage and PostgreSQL cannot share one transaction. A database-creation failure
  triggers best-effort object deletion; a crash or failed cleanup can leave an orphan.
  Do not use real customer documents. No production data-retention/deletion workflow
  is implemented. Database cascades alone do not delete Storage objects.
- Parser subprocesses isolate crashes and enforce timeouts, but do not provide a full
  hostile-file sandbox or hard per-process memory limit. Restrict this prototype to
  fictional/public PDFs; production needs worker resource and concurrency controls.
- pgvector, hybrid retrieval, policy list/detail writes, evidence PDF access, and
  simulations remain deferred.

Implementation references: [PyMuPDF document checks](https://pymupdf.readthedocs.io/en/latest/document.html),
[page text extraction](https://pymupdf.readthedocs.io/en/latest/page.html),
and [Supabase server-validated users](https://supabase.com/docs/reference/javascript/auth-getuser).
