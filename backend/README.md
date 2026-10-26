# PDF ingestion backend — milestone 1

Hackathon proof-of-concept, not a production insurance or claim-processing service.
Only PDF upload, page text extraction, and ingestion job tracking are implemented.
There are no OpenAI calls, AI policy interpretation, embeddings, RAG, claim calculations,
OCR, or insurer decisions in this milestone.

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
| `POST /api/v1/policies/upload` | Authenticated multipart; returns the exact v0.1 `202` ID envelope |
| `GET /api/v1/jobs/{job_id}` | Authenticated and owner-scoped; returns v0.1 job status/stage/error |

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
`needs_review/extracting` after text extraction. Its message explicitly states that AI
analysis is not implemented. Parsing failures end as `failed/extracting` with a safe
error. The frontend can stop polling at either terminal state. No invented progress
percentages, findings, or completed-analysis statuses are returned.

Extracted text is persisted in `document_pages`, including blank pages. The first
physical PDF page is `page_number=1`, regardless of printed page labels. Text is not
trimmed, summarized, or rewritten. `method=pymupdf` and `extraction_quality` is one of:

- `text_present`: some text was extracted; this does not certify its correctness.
- `no_text`: no non-whitespace text was extracted; the page may be blank or scanned.
- `needs_review`: replacement or NUL characters indicate questionable extraction.

The public contract has no raw-page-text endpoint or upload text field, so none was
added. Page rows are available to subsequent backend stages and owner-scoped database
inspection. AI interpretation and calculations are absent.

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
responses conform to the three implemented v0.1 endpoints. Integration acceptance
additionally requires the live test against the migration. See `MILESTONE_1_STATUS.md`
for tests actually executed in this workspace.

## Known limitations and documentation reconciliation

- `START_HERE.md` describes a broader checkpoint ending with a co-payment finding.
  This milestone intentionally stops at text extraction as requested. AI analysis
  normally triggered by upload is deferred; terminal `needs_review` communicates this.
- `API_CONTRACT.md` defines ID/job responses, not a page-text response. No public
  fields, paths, status enums, auth rules, or numbering were changed. Shared docs and
  frontend types were not edited. This is partial implementation of the contract.
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
- OpenAI, pgvector, retrieval, classification, evidence APIs, and simulations are
  deferred. Their packages and tables are not installed prematurely.

Implementation references: [PyMuPDF document checks](https://pymupdf.readthedocs.io/en/latest/document.html),
[page text extraction](https://pymupdf.readthedocs.io/en/latest/page.html),
and [Supabase server-validated users](https://supabase.com/docs/reference/javascript/auth-getuser).
