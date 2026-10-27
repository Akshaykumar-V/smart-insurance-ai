# Job RPC denial investigation

Branch: `feature/ai-backend`. Prior uncommitted diagnostics/profile work was preserved.

## Findings and confidence

The failing `denied_start` request is a direct `httpx.Client.post` to
`/rest/v1/rpc/start_pdf_extraction`, carrying test user B's JWT and Content-Profile:
public. It bypasses FastAPI and SupabaseGateway. Its reported 500 is already the
upstream PostgREST status, not a conversion by the Python adapter.

The original ingestion migration's start RPC uses `SELECT ... INTO STRICT` with job ID, `owner_id =
auth.uid()` and queued status. A hidden/foreign, nonexistent, or ineligible job returns
no row and raises SQLSTATE **P0002 / no_data_found** before any UPDATE. PostgREST maps
P0* (except P0001) to HTTP 500. This is the source-level root cause of the expected
denial becoming 500. The finish RPC has the same defect in its initial job lookup.
Its later STRICT document lookup is a different, unexpected consistency failure.

Latest user-supplied live evidence confirms upstream HTTP 500 / P0002 from
start_pdf_extraction at tests/test_supabase_live.py:232. That call still bypasses
FastAPI. Immediately before line 232, the test asserts the inspected job/document/page
state is unchanged. Reaching line 232 means that non-mutation check passed in the
reported run. This confirms the expected owner-scoped denial path for the original
function, rather than a successful cross-user job mutation.

The existing corrective migration's start function has no STRICT lookup: it raises
PT404 for this condition. Persistent P0002 strongly indicates that the original
function remains active on the tested project (or that deployed SQL differs). Its
current deployed definition was not retrieved here. Inspect it with the updated
read-only diagnose_pdf_upload.sql before making further changes. SQLSTATE alone is
not globally sufficient to identify an authorization failure; triggers or other
STRICT lookups could also raise it in different circumstances.

For the checked-in function, cross-user access is blocked before mutation by RLS plus
the explicit owner filter. The supplied run reached this assertion after successful
owner uploads/page processing and earlier isolation checks. A 500 alone, however,
does not prove absence of changes in the deployed database. The enhanced live test
compares job/document/page state before and after each denied RPC, then checks that
the owner can still start and finish that same job. Both live cases remain pending.

## Narrow correction

New migration: `supabase/migrations/202610260002_job_rpc_not_found.sql`.
It uses CREATE OR REPLACE for start/finish, retaining signatures, existing privileges,
SECURITY INVOKER, search_path, RLS, owner/status filters and row locks. It changes only
each initial lookup from INTO STRICT to INTO plus immediate IF NOT FOUND, which raises
`PT404` with a constant `Job not found.` message. Missing, foreign and state-ineligible
jobs are indistinguishable. No caller-controlled details or resource IDs are returned.

There is no blanket NO_DATA_FOUND handler. Internal document consistency errors and
all other unexpected database failures still propagate normally. The adapter recognizes
only HTTP 404 + PT404 for the exact start/finish RPC operations/paths and maps them to
the existing API error envelope: 404 / NOT_FOUND / Job not found. P0002/500 remains a
server error, as does PGRST202 (missing deployed function), and PT404 on unrelated RPCs.

There is no public FastAPI job-start endpoint. Normal uploads queue `extract_job`, which
calls gateway.start_job, parses pages, then gateway.finish_job; those calls forward the
validated owner's JWT. This change adds no API endpoint or contract fields.

## Files changed in this step

- `supabase/migrations/202610260002_job_rpc_not_found.sql`: new corrective migration.
- `backend/app/supabase.py`: narrowly scoped PT404 mapping.
- `backend/app/diagnostics.py`: allowlist P0002 and PT404, no response-body logging.
- `backend/tests/test_supabase_live.py`: direct RPC diagnostics, strict 404/PT404
  expectations, missing-ID probes, non-mutation and owner-success assertions.
- `backend/tests/test_job_rpc_errors.py`: authorized success, expected denial,
  unexpected-error preservation, scope and redaction regressions (mocked HTTP).
- `backend/JOB_RPC_DENIAL_REPORT.md`: this report with actual local results.
- `backend/UPLOAD_DIAGNOSTICS.md`: pointer to this follow-up.

No already-applied migration was edited. No grants or RLS policies were changed.
No frontend, secrets or API contract changes; no commit, push, merge or live SQL execution.

## Exact next steps

1. Run `supabase/diagnose_pdf_upload.sql` in the SAME project's SQL Editor. It now
   returns the start and finish definitions plus source indicators. With the correction
   deployed, both should show legacy_strict_job_lookup=false and
   has_explicit_not_found_code=true. Inspect the full definitions, not just the flags.
2. If the legacy lookup remains, apply the already-prepared complete file
   `supabase/migrations/202610260002_job_rpc_not_found.sql`, after the two earlier
   migrations. It is transactional and notifies PostgREST to reload schema metadata.
   No additional/duplicate migration is needed for this same defect. Do not edit
   already-applied migrations. If you already applied this correction but the expected
   body is missing, verify the project/endpoint and deployment result before proceeding.
   If the expected body IS present but P0002 persists, stop and inspect custom triggers,
   called functions and the actual PostgREST target; do not add a blanket Python mapping.
3. Rerun the two-user integration suite locally:

```powershell
Set-Location C:\Projects\smart-insurance-ai\backend
rtk proxy .venv/Scripts/python.exe -m scripts.run_supabase_live
```

Enter the two test-user passwords at the hidden prompts. Share only sanitized
operation/status/code lines and the test summary. Direct fixture probes have
request_id=none because they bypass FastAPI; never share tokens or raw upstream bodies.
Expected after applying the correction: denied start/finish and missing jobs return
404/PT404; state remains unchanged; owner operations succeed; both live cases pass.
Expected denial logs may appear at WARNING even in a passing run.

If 500/P0002 persists, confirm this migration replaced the actual deployed functions.
If a different error occurs, inspect that error independently. Do not weaken security
or convert all database errors to a successful/expected denial.

## Verification limits

No psql or Docker executable was available on PATH. The SQL change was source-reviewed
but not executed here. Offline tests mock PostgREST and do not prove live database
enforcement. The live non-mutation/authorized-operation tests are prepared, not claimed
as passed. All acceptance criteria require the post-migration live run.

References: [PostgreSQL STRICT lookup semantics](https://www.postgresql.org/docs/16/plpgsql-statements.html),
[PostgREST error mapping and PT status codes](https://docs.postgrest.org/en/v14/references/errors.html).

## Actual offline checks

```text
rtk proxy .venv/Scripts/python.exe -m pytest -q -m "not live" --tb=short
........................................................................ [ 70%]
..............................                                           [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Projects\smart-insurance-ai\backend\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
102 passed, 2 deselected, 1 warning in 35.94s
Exit code: 0
```

```text
rtk proxy .venv/Scripts/python.exe -m ruff check app tests scripts
All checks passed!
Exit code: 0
```

```text
rtk proxy .venv/Scripts/python.exe -m ruff format --check app tests scripts
21 files already formatted
Exit code: 0
```


## Latest confirmation and additional regression checks

This follow-up changes only `backend/tests/test_job_rpc_errors.py`,
`supabase/diagnose_pdf_upload.sql`, this report and the pointer in
`backend/UPLOAD_DIAGNOSTICS.md`. Runtime mapping and the corrective migration were
already implemented and have been retained unchanged; no second SQL patch is justified.

Additional tests verify the actual GET job API's owner success, indistinguishable
cross-user/missing-job 404 envelopes, preservation of unrelated P0002 server errors,
and exact operation/path scoping of PT404 handling. Existing start/finish regression
and live two-user/missing-job cases remain in place. No production job-start endpoint
was invented. No RLS, grants, frontend or contract changes. No commit/push/merge.

Fresh offline verification (live tests excluded):

```text
rtk proxy .venv/Scripts/python.exe -m pytest -q -m "not live" --tb=short
........................................................................ [ 66%]
....................................                                     [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Projects\smart-insurance-ai\backend\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
108 passed, 2 deselected, 1 warning in 49.49s
Exit code: 0
```

```text
rtk proxy .venv/Scripts/python.exe -m ruff check app tests scripts
All checks passed!
Exit code: 0
```

```text
rtk proxy .venv/Scripts/python.exe -m ruff format --check app tests scripts
21 files already formatted
Exit code: 0
```


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
