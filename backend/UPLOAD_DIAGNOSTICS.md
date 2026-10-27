# Live upload failure investigation

Branch: `feature/ai-backend`. Repository: `C:\Projects\smart-insurance-ai`.
Working tree was clean at investigation start. This remains a hackathon proof-of-concept.

## What is established

The user reports that both test users sign in, then both uploads return 500. The original
adapter discarded the failing operation, upstream status and error code. That information
cannot be recovered from a generic `UPSTREAM_ERROR` alone. No live failure was reproduced
in this session, and no deployed database definitions were read here. **The exact failing
live operation and its root cause are not yet established.**

Two code-level issues were established and addressed:

1. Storage and RPC errors were indistinguishable in backend diagnostics. Operation,
   actual HTTP status, a strictly allowlisted error code, and API request ID are now
   logged at WARNING level. Public API response fields and existing status/code mapping
   stay unchanged. In particular, an upstream 403 still maps to the existing API 401,
   but the diagnostic records 403 so permissions are not mistaken for expired login.
2. `response.is_error` does not reject HTTP 3xx. In particular PostgREST can return
   HTTP 300 / `PGRST203` for ambiguous RPC overloads, which the adapter previously
   accepted as success. The adapter now accepts only 2xx. Regression tests cover this
   and compensating Storage deletion. This defect is **not proven to explain the
   reported 500**; do not assume an overload exists in the deployed project.

## Trace and payload review

FastAPI authenticates via `/auth/v1/user`, validates the multipart PDF, optionally
checks policy ownership, and inspects the PDF in a subprocess. It then calls:

1. `POST /storage/v1/object/policy-documents/<owner>/<policy>/<document>.pdf`, with
   PDF bytes, `Content-Type: application/pdf`, `x-upsert: false`, the project public
   key in `apikey`, and the user's JWT in Authorization.
2. `POST /rest/v1/rpc/create_pdf_upload` with JSON below. HTTPX supplies JSON content type.
   No client-provided owner ID is included; SQL uses `auth.uid()`.
3. If step 2 fails, DELETE the just-uploaded Storage object (best effort). The primary
   error is preserved even if cleanup also fails. If both succeed, return 202 and
   schedule existing page-text extraction using `start_pdf_extraction` and
   `finish_pdf_extraction`. These background calls do not implement AI extraction.

| JSON argument | Migration parameter type | Value supplied |
| --- | --- | --- |
| `p_policy_id` | uuid | Existing policy ID or generated UUID |
| `p_document_id` | uuid | Generated UUID |
| `p_job_id` | uuid | Generated UUID |
| `p_new_policy` | boolean | Whether policy_id was absent |
| `p_name` | text | Validated base filename, at most 255 characters |
| `p_hint` | text | Allowed document hint, otherwise `other` |
| `p_path` | text | Canonical owner/policy/document PDF path |
| `p_sha256` | text | 64 lowercase hexadecimal characters |
| `p_page_count` | integer | Validated physical count, 1 through 200 |

All nine names/types match the checked-in function signature. UUID-generated paths
match `documents_storage_scope`; checksums, hints and page counts satisfy the declared
checks. Composite foreign keys preserve the same owner across policy/document/job.
The RPC uses SECURITY INVOKER and the follow-up migration grants authenticated CRUD and
RPC EXECUTE. The Storage INSERT policy checks the owner prefix and does not require the
policy row to exist before upload. No mismatch was found in these checked-in definitions.

Actual deployed grants, schema exposure/cache, bucket settings, custom triggers,
constraints, signatures/overloads and policies still need verification. Source review
cannot show whether the migrations were applied to the project being tested.

## Safe live rerun

Do not reapply existing migrations blindly. No corrective migration was added: there
is no demonstrated schema defect yet. Do not disable RLS, broaden policies, or switch
to a service-role/secret key. Keep the current migrations unchanged.

From an interactive PowerShell terminal:

```powershell
Set-Location C:\Projects\smart-insurance-ai\backend
rtk proxy .venv/Scripts/python.exe -m scripts.run_supabase_live
```

Confirm the displayed disposable-project hostname. Enter the two confirmed test-user
emails and passwords at the prompts. Passwords are hidden and fresh tokens go only
to the pytest child environment. This uses the existing ignored `.env` URL/public key.
Do not paste tokens into commands or chat. The runner enables WARNING diagnostics,
disables HTTPX/HTTPCore logging, keeps short tracebacks and disables local-variable
dumps. Do not turn on debug HTTP logs or `--showlocals`.

The suite contains deliberate invalid-token requests; `operation=auth_user` / 401
warnings from these are expected. Find the **first storage_upload or create_pdf_upload
failure** for the upload that failed its 202 assertion. A diagnostic looks like this
illustrative example (not an observed live result):

```text
supabase_request_failed operation=create_pdf_upload upstream_status=404 upstream_code=PGRST202 failure=http request_id=<generated-uuid>
```

Share only those `supabase_request_failed` lines, test case names, API error code and
the matching `request_id`/`X-Request-ID`. Do not share full upstream responses, emails,
headers, passwords, JWTs, `.env`, object paths, document text or signed URLs. Unknown,
malformed, nested and oversized error bodies produce `upstream_code=unknown`; this
is intentional. Transport failures have `upstream_status=none`, not a guessed HTTP code.

The tests create fictional fixtures and attempt cleanup. An upload failure before IDs
are returned or a cleanup failure can leave an orphan. Inspect the test users' folders
in the disposable project's Storage dashboard after failed runs; remove only generated
fixtures through Storage, not SQL deletion of `storage.objects`. Do not delete unrelated
objects. The runner is not a deployed-server or browser/CORS test.

## Interpret the diagnostic, then verify configuration

| Diagnostic | What to check; not a diagnosis by itself |
| --- | --- |
| `storage_upload`, `AccessDenied` / 400 or 403 | Owner-prefix INSERT policy; effective authenticated role; same project for key and token |
| `storage_upload`, `NoSuchBucket` | Exact private bucket ID `policy-documents` |
| `storage_upload`, `InvalidMimeType` / `EntityTooLarge` | PDF allowlist and 20 MiB bucket limit; project-level upload limit |
| `create_pdf_upload`, 404 / `PGRST202` | Missing/stale function signature, parameter names and schema cache |
| `create_pdf_upload`, 300 / `PGRST203` | Multiple incompatible overloads; inspect signatures |
| RPC, 401/403 / `42501` | Schema USAGE, function EXECUTE, underlying table grants and RLS |
| RPC, `23514` / `23502` / `22P02` | CHECK/NOT NULL/type mismatch; compare schema to payload table above |
| RPC, 409 / `23503` or `23505` | Owner-consistent foreign key or uniqueness conflict |
| RPC, `42P01` / `42883` | Missing table or function referenced by SQL |
| RPC, `P0001` | Explicit function guard raised; compare function definition and authenticated scope |
| `storage_cleanup` | Secondary compensation failure; retain the earlier RPC diagnostic as primary |
| Any, `failure=transport` | No HTTP response; inspect connectivity/TLS/timeouts locally without publishing exception text |
| Any, `failure=not_configured` | Application did not load URL/public key; run from backend/ |

Run these **read-only** files separately in the disposable project's SQL Editor:

1. `supabase/verify_pdf_ingestion.sql`: existing RLS/grant/bucket assertions and
   policy/constraint definitions.
2. `supabase/diagnose_pdf_upload.sql`: schema USAGE/auth.uid permissions, all RPC
   signatures/argument names/results/security mode, function configuration/definition,
   column metadata, user-defined triggers and private Storage configuration/policies.

The expected create function is exactly:
`public.create_pdf_upload(uuid,uuid,uuid,boolean,text,text,text,text,integer)` returning
void, with the nine names above, one matching signature, authenticated execute=true,
anon execute=false, SECURITY INVOKER, and search_path=public,pg_temp. The runtime role
also needs schema usage and authenticated CRUD under the owner-only RLS policies.
The bucket must be private, limit 20971520, MIME allowlist application/pdf.

If the database signature matches but `PGRST202` persists, an administrator can reload
PostgREST's schema cache in SQL Editor with `NOTIFY pgrst, 'reload schema';` and retry.
This is a conditional troubleshooting action, not something executed during this task.
If a real schema/grant defect is established, prepare a **new corrective migration**;
do not edit files already applied or blanket-grant access to make the tests pass.

References: [PostgREST errors](https://docs.postgrest.org/en/v14/references/errors.html),
[RPC parameters](https://postgrest.org/en/stable/references/api/functions.html),
[Supabase Storage error codes](https://supabase.com/docs/guides/storage/debugging/error-codes).

## Files changed / scope

- `backend/app/diagnostics.py`: fixed operation enum, request context and allowlisted logging.
- `backend/app/main.py`: generated request-ID context with cleanup in finally.
- `backend/app/supabase.py`: operation labels, safe diagnostics and non-2xx rejection.
- `backend/scripts/run_supabase_live.py`: safe WARNING output for live reruns.
- `backend/tests/test_supabase_diagnostics.py`: error masking, redaction, correlation,
  primary-error preservation, RPC 300/redirect rejection and malformed-body tests.
- `backend/tests/test_live_runner.py`: verifies safe logging flags on the child process.
- `supabase/diagnose_pdf_upload.sql`: read-only deployed-definition inspection.
- `backend/SUPABASE_SETUP.md`: link to this investigation/rerun procedure.
- `backend/UPLOAD_DIAGNOSTICS.md`: this report.

API contract changes: none. No frontend, original migration, RLS policy, credential,
shared contract or AI implementation changes. No commit, push, merge, or live SQL
execution performed. The confirmed live operation/root cause remains pending the
diagnostic and deployed-configuration results above.

## Verification

Baseline offline suite: 56 passed, 2 live cases deselected, one existing Starlette
TestClient deprecation warning. First expanded run: 72 passed, 2 deselected, 2 setup
errors; the oversized-body fixture generated an enormous automatic pytest ID.
Explicit short IDs were added before the final rerun. The initial Python launch in
the sandbox failed access to the relocated environment's base interpreter; the same
environment ran with approved execution outside the sandbox.

An intermediate rerun passed 73 tests. A final negative case also verifies that deeply
nested JSON cannot make diagnostic parsing raise RecursionError and mask the original
failure. Final checks below include that safeguard. Live tests remain excluded.

```text
rtk proxy .venv/Scripts/python.exe -m pytest -q -m "not live" --tb=short
........................................................................ [ 97%]
..                                                                       [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Projects\smart-insurance-ai\backend\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
74 passed, 2 deselected, 1 warning in 37.14s
Exit code: 0
```

```text
rtk proxy .venv/Scripts/python.exe -m ruff check app tests scripts
All checks passed!
Exit code: 0
```

```text
rtk proxy .venv/Scripts/python.exe -m ruff format --check app tests scripts
19 files already formatted
Exit code: 0
```


## Follow-up: explicitly select the public Data API schema

New user-supplied live evidence establishes the failed operation as
`create_pdf_upload`, upstream HTTP 404 / `PGRST202`. The user also reports that the
deployed signature, permissions, exposure and schema-cache reload were checked.
The remaining default-schema hypothesis is not yet confirmed by a successful rerun.

This change adds explicit profile headers to `/rest/v1/` requests: Accept-Profile:
public for GET/HEAD, Content-Profile: public for POST/PATCH/DELETE (and PUT). Header
merging is case-insensitive. Auth and Storage requests receive no added profiles.
The live suite's direct REST reads/writes and cleanup use the same selection, including
anonymous-access probes. Its Auth and Storage calls remain without profile headers.

Files changed in this follow-up: `backend/app/supabase.py`,
`backend/tests/test_supabase_profiles.py`, `backend/tests/test_supabase_api.py`,
`backend/tests/test_supabase_live.py`, and this report. Earlier uncommitted diagnostic
work was preserved. No SQL migrations, permissions, RLS, authentication, error mapping,
frontend or API contracts changed. No commit or push was performed.

PostgREST defaults to the first exposed schema when no profile is supplied:
[official schema-selection documentation](https://docs.postgrest.org/en/latest/references/api/schemas.html).
After the offline checks, rerun from an interactive PowerShell terminal:

```powershell
Set-Location C:\Projects\smart-insurance-ai\backend
rtk proxy .venv/Scripts/python.exe -m scripts.run_supabase_live
```

If PGRST202 persists with explicit public selection, inspect the effective deployed
PostgREST `db-schemas` configuration, confirm the API endpoint and inspected database
belong to the same project, and compare the function signature visible in that
instance's schema cache with the nine JSON arguments. Review deployed configuration
and cache reload logs; do not weaken grants/RLS or switch to service-role credentials.
Share only sanitized operation/status/code/request-ID diagnostics. No live rerun or
deployed configuration inspection was performed during this change.

Actual offline verification for this follow-up:

```text
rtk proxy .venv/Scripts/python.exe -m pytest -q -m "not live" --tb=short
........................................................................ [ 82%]
...............                                                          [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Projects\smart-insurance-ai\backend\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
87 passed, 2 deselected, 1 warning in 34.10s
Exit code: 0
```

```text
rtk proxy .venv/Scripts/python.exe -m ruff check app tests scripts
All checks passed!
Exit code: 0
```

```text
rtk proxy .venv/Scripts/python.exe -m ruff format --check app tests scripts
20 files already formatted
Exit code: 0
```


## Follow-up: direct job-start rejection returns 500

See [the job RPC denial report](JOB_RPC_DENIAL_REPORT.md) for the direct
PostgREST call path, STRICT lookup failure, new corrective migration,
safe diagnostics and required live verification.


Latest user-supplied failure at live-test line 232 confirms direct PostgREST
500/P0002 after the non-mutation assertion passed. The existing
`202610260002_job_rpc_not_found.sql` correction must be verified on the
tested project. See [the updated denial report](JOB_RPC_DENIAL_REPORT.md).


## Follow-up: anonymous RLS reads are tested by returned rows

Branch: `feature/ai-backend`. The user reports both live cases now pass uploads and
cross-user RPC checks. The next failure was a test assumption requiring anonymous
SELECT to return 401/403. A read-only probe performed during this follow-up against
the configured project, with only its verified publishable key and Accept-Profile:
public, returned HTTP 200 and exactly [] for policies, documents, document_pages,
and analysis_jobs. It requested only id with limit=1; no IDs, row contents, keys,
tokens, project hostname, or upstream bodies were printed. This confirms no rows
were disclosed by those probes, not that every deployed security rule is correct.
The historical failing response body cannot be recovered from the status alone.

The checked-in migrations enable RLS on all four tables and restrict all row policies
to authenticated owners using auth.uid() in USING and WITH CHECK. They also revoke
anonymous table privileges. A deployed 200 differs from that explicit-grant baseline:
effective deployed grants still need read-only review with verify_pdf_ingestion.sql.
Its strict anonymous-grant assertion is deliberately unchanged. No grant or policy
was changed to make the test pass. With SELECT privilege but no applicable row
policy, PostgreSQL filters out all rows; see
https://www.postgresql.org/docs/17/ddl-rowsecurity.html.

Changes in this follow-up only:
- tests/test_supabase_live.py accepts 401/403 or exactly 200 [] for hidden reads and
  zero-row PATCH/DELETE responses with return=representation. Nonempty/malformed
  responses fail without rendering their contents. The same check covers cross-user
  probes. Anonymous reads check all four tables before mutation probes.
- Anonymous PATCH/DELETE probes target each table's real fictional owner fixtures;
  owner reads verify full records remain unchanged. Anonymous policy INSERT must
  receive 401/403, and its generated ID is tracked for cleanup if unexpectedly allowed.
  All three protected RPCs must return 401/403. Existing private Storage and cross-user
  protections remain. Unexpected errors (including 400/404/409/500) are not treated
  as successful database denial evidence.
- tests/test_security_assertions.py adds offline regression checks for anonymous and
  cross-user empty responses, permission denials, exposed rows, wrong JSON shapes,
  malformed JSON, unexpected statuses, and strict INSERT/RPC denial handling.
- This report records the evidence and limits. Earlier uncommitted work is preserved.

Verification actually run:
`rtk proxy .venv/Scripts/python.exe -m pytest -q -m "not live" --tb=short`
returned 148 passed, 2 deselected, 1 existing Starlette deprecation warning (38.20s).
Ruff initially found one import-order issue in the new file; it was fixed.
Final `rtk proxy .venv/Scripts/python.exe -m ruff check app tests scripts` passed.
Final `rtk proxy .venv/Scripts/python.exe -m ruff format --check app tests scripts`
passed: 22 files already formatted. Offline tests validate the assertions, not live RLS.

No SQL, backend application behavior, API contract, frontend or permissions changed.
No migration is required for this test-assumption fix. No commit or push performed.
The full two-user live suite was not rerun here: it needs interactive credentials.
Run once from an interactive PowerShell terminal:

```powershell
Set-Location C:\Projects\smart-insurance-ai\backend
rtk proxy .venv/Scripts/python.exe -m scripts.run_supabase_live
```

Confirm the disposable project's hostname and enter both test users at the prompts.
Do not enable local-variable dumps or debug HTTP logging. If a SECURITY assertion
reports returned rows or changed owner records, stop for investigation; do not paste
response bodies or loosen permissions. Both live cases remain pending this rerun.


## Follow-up: anonymous RPC execution is a real permission mismatch

The latest attached live output fails `assert_write_denied` with HTTP 404, but the
old helper omitted which call failed. Its cross-user PT404 log entries are expected.
To distinguish the anonymous failure, anonymous POST probes used the configured
publishable key, Content-Profile public, and freshly generated nonexistent job IDs.
No Authorization token, service role, private record ID, or PDF contents were used.
Actual results:

```text
operation=start_pdf_extraction status=404 code=PT404
operation=finish_pdf_extraction status=404 code=PT404
```

This matches the functions' explicit hidden/missing-job guards, meaning anonymous
requests can reach these RPC bodies. The probes were blocked at lookup and did not
modify jobs. They do not demonstrate private data exposure, but anonymous execution
violates the intended authenticated-only function grants. Unlike 200 [] SELECT,
PT404 here must not be accepted as proof of EXECUTE permission denial. The attachment
alone cannot locate its first failing call; these separate probes establish the RPC
permission mismatch. The grant source (PUBLIC, direct anon, role inheritance, or a
dashboard change) has not been read from the deployed database.

Prepared `supabase/migrations/202610260003_restore_job_rpc_grants.sql` after the first
three migrations. It revokes EXECUTE from PUBLIC and anon on the exact three existing
ingestion RPC signatures, grants intended authenticated EXECUTE, checks effective
anon/authenticated permissions and SECURITY INVOKER, then reloads the schema cache.
Checks and changes are transactional. Missing functions or unresolved inherited
privileges fail and roll back. It does not replace function bodies or alter table
grants, policies, Storage, role memberships, or default privileges. Earlier migration
files remain unchanged. PostgreSQL PUBLIC function execution can be inherited even
without a direct anon grant:
https://www.postgresql.org/docs/17/ddl-priv.html.

Changed tests/test_supabase_live.py to identify denial failures using a fixed operation
label, HTTP status and allowlisted upstream code. Raw bodies, identifiers and URLs
are omitted. tests/test_security_assertions.py adds regression tests ensuring PT404,
PGRST202 and unrelated failures remain failures rather than accepted denials, and
diagnostics redact arbitrary upstream strings. No application/API contract/frontend
changes. Earlier uncommitted work preserved; no commit or push.

Actual checks:
- `rtk proxy .venv/Scripts/python.exe -m pytest -q -m "not live" --tb=short`:
  157 passed, 2 deselected, 1 existing Starlette warning in 37.30s.
- `rtk proxy .venv/Scripts/python.exe -m ruff check app tests scripts`: passed.
- `rtk proxy .venv/Scripts/python.exe -m ruff format --check app tests scripts`:
  passed, 22 files already formatted.

SQL was reviewed statically, not executed or database-tested. Full authenticated live
tests were not run in this session. The deployed issue is not fixed until the migration
is applied and the two-user suite passes.

Safe next steps:
1. Confirm the same disposable Supabase project. In SQL Editor, use the existing
   read-only diagnose_pdf_upload.sql to inspect exact signatures, effective EXECUTE
   permissions and SECURITY INVOKER. Expected post-fix: anon=false, authenticated=true
   on all three RPCs. Review unexpected definitions before proceeding.
2. Run the entire new 202610260003_restore_job_rpc_grants.sql file once as the project
   administrator, after the first three migrations. Do not re-run the older migrations
   or toggle broad exposure/grants to make tests pass. If its assertion fails, roll
   back the session and investigate effective role membership/grants; do not remove it.
3. Repeat the read-only RPC permission inspection. The existing full
   verify_pdf_ingestion.sql additionally enforces stricter table grants; previously
   observed anonymous empty reads mean that separate grant audit can still flag drift.
4. Run both live cases once in interactive PowerShell, confirming the disposable
   hostname and entering both users at the prompts:

```powershell
Set-Location C:\Projects\smart-insurance-ai\backend
rtk proxy .venv/Scripts/python.exe -m scripts.run_supabase_live
```

If the failure persists, share only the new operation/status/code failure line and
test name. Do not accept PT404/PGRST202 globally or publish upstream response bodies.


## Commit preparation: live gate passed (user-reported)

The user reports **2 passed, 0 failed** after the RPC permission fix. This supersedes
historical pending-live statements above. The agent did not rerun the full live suite
or inspect deployed migration history in this review. Branch: feature/ai-backend.

The existing new migration 202610260003_restore_job_rpc_grants.sql records the fix
for all three ingestion RPCs. No duplicate migration was added. It and the PT404
migration 202610260002_job_rpc_not_found.sql are included in the intended commit.
No migrations were edited in this review. If the fix was applied manually, reconcile
deployed migration history before future automatic deployment.

Review found no blocker in the scoped code/test changes. Diagnostics remain redacted,
profile headers target only REST, and PT404 mapping is limited to the two job RPCs.
RLS and Storage policies are unchanged. The strict SQL audit may still flag anonymous
table-grant drift even when RLS returns empty arrays; passing live tests do not certify
all deployed configuration or production readiness. This remains a hackathon POC.
