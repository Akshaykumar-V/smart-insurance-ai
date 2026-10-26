# Disposable Supabase integration gate

This is a hackathon proof-of-concept. Use only fictional documents and test identities.
Local tests and a source review do **not** establish that deployed RLS or Storage work.
No live project was configured or contacted by the integration suite during this task.

## 1. Create and configure the project manually

1. Create a **new disposable development project** in the Supabase Dashboard. Verify
   its project reference before running SQL. Do not use an existing customer project.
2. Wait for provisioning. Enable the Data API with the `public` schema exposed. The
   backend uses `/rest/v1` and `/storage/v1`; it does not need a database connection URL.
3. In SQL Editor, run these complete files in order, as the project administrator:
   - `supabase/migrations/202610250001_pdf_ingestion.sql`
   - `supabase/migrations/202610260001_ingestion_security.sql`
   Each file has its own transaction. Neither is an idempotent script. If the first
   migration is already applied, apply only the second; do not replay the first.
   If either fails, stop and retain the sanitized error. Do not disable RLS to proceed.
4. Run `supabase/verify_pdf_ingestion.sql` in SQL Editor. It is read-only and rolls back.
   It must finish without an exception. Review the returned policies and constraints:
   - Four tables: `policies`, `documents`, `document_pages`, `analysis_jobs`, all with RLS.
   - Exactly one authenticated `ALL` policy per table; both `USING` and `WITH CHECK`
     compare `auth.uid()` with `owner_id`. No anonymous table access.
   - Authenticated grants are only SELECT/INSERT/UPDATE/DELETE, not TRUNCATE or TRIGGER.
   - Three RPCs are `SECURITY INVOKER`, executable by authenticated users, not `anon`.
   - Owner-consistent composite foreign keys link policy, document, page and job rows.
     `documents_storage_scope` requires `<owner>/<policy>/<document>.pdf` exactly.
   - `UNIQUE(document_id, page_number)` and positive page bounds preserve physical
     page numbering. Money is BIGINT paise; absent schedule values remain nullable.
   - Three Storage policies allow authenticated INSERT/SELECT/DELETE only when bucket
     is `policy-documents` and the first path component is the current user's UUID.
     No UPDATE policy is expected. Extra policies require review because permissive
     policies can combine to widen access. The audit deliberately rejects extra
     Storage policies in this fresh project; do not delete unrelated policies blindly.
5. In Storage, confirm bucket `policy-documents` is **private**, with file-size limit
   **20 MiB / 20,971,520 bytes**, and MIME allowlist **application/pdf only**. The second
   migration rejects missing/different settings instead of silently changing a bucket.
   If an empty, pre-created disposable bucket has mismatched settings, correct them in
   the Dashboard and rerun only the failed migration. Never make this bucket public.
6. Under Authentication, enable email/password sign-in. Create **two different** test
   users with disposable emails/passwords and confirmed email status (or complete the
   email confirmation flow). Keep anonymous sign-ins disabled for this gate. A project
   API key is not a user access token. Do not use real patient accounts or PDFs.

The SQL audit's assertions plus returned definitions are configuration checks. The
two-user HTTP tests below are required before claiming runtime isolation. SQL Editor
queries run with administrator privileges and alone cannot demonstrate user RLS.

## 2. Configure environment variables locally

From `backend/`, copy `.env.example` to `.env` **only if `.env` does not already exist**.
Use the project's Connect dialog / Settings > API Keys to copy its URL and public key.
Do not paste keys, passwords, tokens, refresh tokens, or signed URLs into chat or Git.
Do not print `.env` or enable verbose HTTP logging during live checks.

| Variable | Required | Source / purpose |
| --- | --- | --- |
| `SUPABASE_URL` | Yes | Disposable project HTTPS URL, such as `https://<ref>.supabase.co` |
| `SUPABASE_PUBLISHABLE_KEY` | Yes | `sb_publishable_...` key, or legacy **anon** key from the same project |
| `CORS_ORIGINS` | Default supplied | JSON list; default `["http://localhost:3000"]` |
| `MAX_UPLOAD_BYTES` | Default supplied | 20971520 maximum; can reduce |
| `MAX_PDF_PAGES` | Default supplied | 200 maximum; can reduce |
| `MAX_EXTRACTED_CHARACTERS` | Default supplied | 2000000 maximum; can reduce |
| `PDF_TIMEOUT_SECONDS` | Default supplied | 20 seconds; allowed up to 60 |
| `RUN_SUPABASE_LIVE` | Live tests only | Must equal `1` to allow external integration requests |
| `TEST_SUPABASE_TOKEN_A`, `TEST_SUPABASE_TOKEN_B` | Live tests only | Fresh access tokens for two distinct confirmed users; process environment only |

No service-role key, `sb_secret_...` key, database password, JWT signing secret,
OpenAI key, or AI model setting is required. The public key goes in `apikey`; the
user's access JWT goes in `Authorization: Bearer ...`. Secrets/service-role keys bypass
RLS and would invalidate this integration gate. Keep test tokens out of `.env`: pytest's
live gate reads them from the process environment; the runner below supplies them.

## 3. Run the local checks, then the explicit live gate

Commands below run from `backend/` in the existing Python environment. A clean checkout
can first install locked dependencies with `rtk proxy uv sync --locked`.

```powershell
rtk proxy .venv/Scripts/python.exe -m pytest -q -m "not live"
rtk proxy .venv/Scripts/python.exe -m ruff check app tests scripts
rtk proxy .venv/Scripts/python.exe -m ruff format --check app tests scripts
```

**Stop here until steps 1 and 2 are complete.** Then run this yourself locally:

```powershell
rtk proxy .venv/Scripts/python.exe -m scripts.run_supabase_live
```

The interactive runner displays the target hostname and asks you to type it to confirm
this is the disposable project. It prompts for both emails and hides password input.
It signs in via `/auth/v1/token?grant_type=password`, verifies distinct user IDs, and
passes fresh access tokens only in the pytest child process environment. It does not
print or save passwords/tokens. It runs `pytest -q -m live --tb=short --no-showlocals`;
do not add `--showlocals`, HTTP debug logs, or dump responses containing signed URLs.
Run in an interactive terminal so hidden password input works.

Alternatively, securely inject both access tokens into the current process environment,
set `RUN_SUPABASE_LIVE=1`, and execute that pytest command directly. Merely having tokens
present no longer starts live tests. With opt-in off, both live cases skip; with opt-in
on but missing configuration, they fail. No running uvicorn server is needed: TestClient
executes the real FastAPI app against live Auth, PostgREST and Storage. This does not
test a deployed server, browser CORS, or network/proxy behavior in front of uvicorn.

Expected live acceptance, **not an observed result yet**:

- Both users upload fictional PDFs and attach a schedule to their own policy (`202`).
- Job polling returns `needs_review` / `extracting`, explicitly saying AI is absent.
- Physical pages persist as 1 and 2; blank page text remains empty; schedule data is null.
- The other user gets `404` for API jobs/attachments, empty direct table reads, and no
  affected records on cross-user UPDATE/DELETE. Forged relationships and RPCs fail.
- The owner can download a private PDF and request a short-lived signed URL. Another
  user cannot read, sign, list, delete or upload into that owner's document folder.
- Public URLs cannot read the PDF. Anonymous database/RPC/private-file access fails.
- Both parametrized live cases pass. Record actual output; skipped is not passed.

The signed-URL probe tests Supabase Storage directly; the contract's backend
`GET /documents/{document_id}/access` endpoint is still unimplemented. Signed URLs are
bearer capabilities until expiry: someone who receives an authorized URL can use it.
The test must not claim that sharing an already signed URL preserves per-user isolation.

## 4. Cleanup and troubleshooting

The live tests delete their generated objects through the Storage API first, then
their policy rows (which cascade to documents, pages and jobs). They never wipe tables
or delete users. If an assertion fails, cleanup is still attempted. Expired credentials,
outages, or an upload that fails before returning IDs can leave fixtures/orphans.
Inspect the two test users' folders and rows in this disposable project after a failed
run. Remove objects through Storage, not SQL against `storage.objects`; then remove
fixture policy rows. Deleting database rows alone does not remove stored bytes.
Delete the disposable project manually when finished if it is no longer needed.

- **401:** ensure both users are confirmed and obtain fresh access tokens from the same
  project as the configured public key. Never substitute the public key for a JWT.
- **403 / hidden rows for owner:** verify the audit and migration grants. Do not use a
  service-role key or relax policies to make a failing test pass.
- **RPC/table not found:** check migration execution and Data API schema exposure;
  after successful migration, allow the schema cache to refresh and retry.
- **Private bucket / size / MIME assertion:** fix only the disposable bucket's settings;
  run the failed migration and audit again.
- **Jobs remain queued/processing:** process-local tasks and expired tokens are known
  limitations. Restarting does not resume jobs; use a fresh session and re-upload.
- **A live test fails:** retain only sanitized error/status and fixture IDs for review.
  Do not claim live acceptance or proceed to AI extraction.

## Security review and remaining boundaries

Source review found remote token validation via `/auth/v1/user`, owner IDs derived
from that validated response, explicit owner-filtered lookups, user JWT forwarding,
RLS on every implemented private table, and composite ownership foreign keys. No
service-role or local unsigned-JWT fallback exists. Upstream bodies are sanitized.

The follow-up migration removes potentially inherited anonymous RPC execution and
excess table privileges (including TRUNCATE, which RLS does not protect), checks bucket
restrictions, and enforces document path scope even for direct table writes. These
are reviewed changes, **not yet proven against a running PostgreSQL/Supabase project**.

Remaining issues before production or trusted AI evidence:

- Authenticated owners have CRUD on their own tables and can invoke ingestion RPCs.
  They can bypass FastAPI PDF validation, fabricate their own extracted page text or
  job states, and upload arbitrary bytes labeled PDF through Storage. RLS isolates
  users; it does not attest that page content came from the parser. A future evidence
  milestone must establish trusted worker writes before treating stored results as
  source-verified. No AI/evidence trust claim is made here.
- Storage policies validate the owner folder, not policy existence or complete filename
  shape. The adapter and document constraint enforce canonical registered paths;
  users can still create orphan objects within their own prefix. Quotas/rate limiting,
  lifecycle cleanup, and a durable worker are not implemented.
- Process restarts/token expiry can strand jobs. Storage/DB changes are not one atomic
  transaction. Cleanup is best effort. No production retention/deletion workflow exists.
- `document_chunks`, `findings`, pgvector/retrieval, and scenarios are deferred. This
  migration covers only Milestone 1; full future-schema acceptance is not claimed.

References: [Supabase API keys](https://supabase.com/docs/guides/getting-started/api-keys),
[API grants and defaults](https://supabase.com/docs/guides/api/securing-your-api),
[function permissions](https://supabase.com/docs/guides/database/functions),
[private buckets](https://supabase.com/docs/guides/storage/buckets/fundamentals),
[authenticated downloads and signed URLs](https://supabase.com/docs/guides/storage/serving/downloads).
