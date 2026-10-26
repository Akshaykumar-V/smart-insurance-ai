# Supabase integration preparation status — 2026-10-26

Branch: `feature/ai-backend`, checked before and after changes.

Result: preparation and offline verification complete; **live integration is unverified**.
No live Auth/Storage/PostgREST tests, dashboard changes, SQL execution, or deployment
were performed. This is still a hackathon proof-of-concept. AI extraction is deferred.

## Files changed in this task

Modified:

- `backend/README.md` — migration sequence and explicit live-test opt-in instructions.
- `backend/pyproject.toml` — registered the `live` pytest marker; no dependency changes.
- `backend/tests/test_supabase_live.py` — two-way user isolation, authenticated uploads,
  own-policy attachment, jobs, table writes, active-state RPC transitions, private
  downloads/signing/listing/writes/deletion, anonymous denial and cascade checks.

Added:

- `backend/SUPABASE_SETUP.md` — disposable-project runbook, variables, audit expectations,
  cleanup, troubleshooting, security review and outstanding limitations.
- `backend/scripts/run_supabase_live.py` — interactive sign-in and explicit live runner;
  passwords/tokens are not printed or written to files.
- `backend/tests/test_live_runner.py` — mocked sign-in/child-process credential handling.
- `backend/tests/test_supabase_api.py` — FastAPI + real Supabase adapter + parser with
  mocked HTTP, covering upload/job flow, owner scope, and rejected/expired tokens.
- `supabase/migrations/202610260001_ingestion_security.sql` — follow-up grant hardening,
  canonical document path constraint, strict private-bucket configuration check.
- `supabase/verify_pdf_ingestion.sql` — read-only live configuration assertions plus
  policy/constraint definitions for administrator review.
- `backend/SUPABASE_INTEGRATION_STATUS.md` — this record.

Milestone 1 was already staged when work began. Its staging and original migration
were preserved; these changes were not staged or committed. No frontend, shared
contract, root handoff document, application runtime code, or dependency lockfile changed.
No commit, push, or merge was performed.

## Implemented and reviewed

The original four-table schema uses nullable schedule data, integer paise, physical
page numbering, indexed owner filters, owner-consistent composite foreign keys and RLS.
Auth is validated remotely through `/auth/v1/user`; the application uses the resulting
user ID and forwards the user's JWT to database/Storage operations. No service-role key
is needed. Object names are owner/policy/document scoped. Errors avoid upstream bodies.

The follow-up migration explicitly revokes inherited grants before regranting only
authenticated CRUD/EXECUTE. This closes potential anonymous RPC grants and excess table
privileges such as TRUNCATE. It also enforces canonical document metadata paths and
rejects a pre-existing private bucket with incorrect size/MIME restrictions. These are
source-reviewed fixes; no deployed database is claimed to have been changed or verified.

The original bucket is private, with owner-prefix INSERT/SELECT/DELETE policies and no
UPDATE policy. The live audit checks for extra policies that could widen access. The
test suite exercises both identities as owner and attacker, not just one direction.

## Tests run (commands + results)

From `backend/`, using the existing local virtual environment:

```powershell
rtk proxy .venv/Scripts/python.exe -m pytest -q -k 'not live'
# Baseline: 50 passed, 1 deselected, 1 warning in 26.85s.

rtk proxy .venv/Scripts/python.exe -m pytest -q -m 'not live'
# Intermediate: 53 passed, 2 deselected, 1 warning in 30.33s.

rtk proxy .venv/Scripts/python.exe -c "import os, pytest; os.environ.pop('RUN_SUPABASE_LIVE', None); raise SystemExit(pytest.main(['-q']))"
# Final: 56 passed, 2 skipped, 1 warning in 33.33s.
# Explicitly disabled live opt-in before collection; no external credentials used.

rtk proxy .venv/Scripts/python.exe -m ruff check app tests scripts
# All checks passed.

rtk proxy .venv/Scripts/python.exe -m ruff format --check app tests scripts
# 17 files already formatted.
```

From repository root: `rtk proxy git diff --check` passed (Git emitted LF/CRLF conversion
notices). New untracked files are not covered by that Git check. The final Python lint
and formatting checks include all new Python files.

The warning is the existing Starlette deprecation of HTTPX-based TestClient. No test
failures remain. Initial lint found four long lines and formatting differences in new
test edits; formatting resolved them and the final checks passed. RTK's filtered Git
wrapper could not locate its Claude config directory; `rtk proxy git ...` succeeded.

Neither `psql` nor Docker was found on PATH. SQL migrations/audit have **not** been
executed, and offline mocked HTTP tests cannot prove deployed RLS or Storage behavior.
The live runner's network and subprocess behavior was mocked in its unit tests; its
real interactive sign-in still awaits the disposable project.

## Known limitations and security issues

- Owner-authenticated CRUD/RPC access allows an owner to fabricate their own pages or
  job state and bypass FastAPI validation. Cross-user isolation is not evidence
  authenticity. Trusted worker writes must be addressed before future source-verified
  AI results rely on these rows. No AI/evidence verification is implemented here.
- Owner-prefix Storage policies permit orphan uploads within one's own folder. File
  MIME is not proof of PDF content. Rate limits and lifecycle cleanup remain absent.
- Background jobs are process-local and use expiring user tokens; restarts/outages can
  leave jobs queued/processing. Storage/DB compensation and test cleanup are best effort.
- Full-schema chunks/findings/retrieval acceptance and the backend document-access
  endpoint are deferred. Direct Storage signing tests do not implement that endpoint.
- Signed URLs are bearer capabilities until expiry; do not share or log them.

## API contract changes

None. No shared contract/types or public endpoint fields, paths, statuses, auth scheme,
money units or page numbering changed. The database constraint and privileges enforce
existing ownership/path requirements; no shared table/field redesign was introduced.

## Next small step / manual setup

Follow `backend/SUPABASE_SETUP.md`: create a disposable project; enable the Data API;
apply the original migration followed by the hardening migration; run the read-only
audit and inspect policies; confirm the private PDF bucket; create two confirmed test
users; set only the project URL and public key in local `.env`.

Then run `rtk proxy .venv/Scripts/python.exe -m scripts.run_supabase_live` from `backend/`
in an interactive local terminal. It obtains fresh user sessions without displaying
tokens and runs the explicit live gate. Report the actual two-case result and inspect
cleanup. Do not treat skipped tests as success or proceed to AI extraction yet.
