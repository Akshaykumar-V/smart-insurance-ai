# Milestone 1 status — 2026-10-25

**Branch:** `feature/ai-backend` (verified before editing).

**Result:** local PDF ingestion implementation and offline checks pass. Live Supabase
integration is not verified. This remains a hackathon proof-of-concept.

## Files created

- `backend/.gitignore`
- `backend/.env.example`
- `backend/pyproject.toml`
- `backend/uv.lock`
- `backend/README.md`
- `backend/MILESTONE_1_STATUS.md`
- `backend/app/__init__.py`
- `backend/app/config.py`
- `backend/app/errors.py`
- `backend/app/models.py`
- `backend/app/main.py`
- `backend/app/pdf.py`
- `backend/app/pdf_worker.py`
- `backend/app/supabase.py`
- `backend/tests/conftest.py`
- `backend/tests/test_api.py`
- `backend/tests/test_pdf.py`
- `backend/tests/test_request_boundary.py`
- `backend/tests/test_supabase.py`
- `backend/tests/test_supabase_live.py`
- `supabase/migrations/202610250001_pdf_ingestion.sql`

No existing tracked files, shared handoff documents, or frontend files were changed.
No commit, push, merge, or remote migration was performed. Workspace-local Python,
virtual environment, and package-cache directories are ignored by Git.

## Implemented

- Public health endpoint, authenticated PDF upload, and owner-scoped job polling.
- Supabase Auth validation, private Storage adapter, and an initial four-table migration
  with RLS, owner-consistent foreign keys, and transactional database operations.
- Size/type/content/page validation; isolated PyMuPDF parsing with timeouts; exact
  extracted text and 1-indexed physical PDF pages, including blank/scanned pages.
- Sanitized errors for invalid, encrypted, empty, damaged, oversized, and unsupported
  uploads; extraction failures remain visible through job polling.
- No AI extraction, retrieval, embeddings, OCR, or claim simulation.

## Tests actually executed

Commands below ran from `backend/` with the workspace-local Python 3.12.14 environment:

```powershell
rtk proxy .venv/Scripts/python.exe -m pytest -q
# 50 passed, 1 skipped, 1 warning in 13.99s

rtk proxy .venv/Scripts/python.exe -m ruff check app tests
# All checks passed!

rtk proxy .venv/Scripts/python.exe -m ruff format --check app tests
# 14 files already formatted
```

The skipped test is `test_live_upload_pages_and_cross_user_isolation`: no live test-user
tokens were supplied. The warning is Starlette's deprecation of HTTPX-based TestClient
in favor of HTTPX2. It did not fail tests. Initial lint import/format issues were fixed
before the final checks. No remaining local test/lint failures were observed.

The first Python/package downloads failed under sandbox network restrictions, then
succeeded with approved network access. Dependencies are pinned in `uv.lock`.
FastAPI endpoints were exercised through TestClient; no deployed endpoint or live
Supabase behavior is claimed. `git diff --check` also passed for tracked changes
(all implementation files are new/untracked, so that check alone does not validate them).

## Known limitations

The migration has not been executed against PostgreSQL/Supabase in this workspace.
Mocked transport tests verify request/ownership behavior, not deployed RLS enforcement.
Integration requires a configured Supabase project, the migration, and two test users.
Process-local background tasks are not durable across restarts; expired tokens or an
upstream outage can prevent status updates. Storage cleanup after database failures is
best effort. Parsing has timeout and output limits but no hard process-memory limit.
Garbled-text detection is limited; `text_present` does not mean verified evidence.
See README for full operating limits and recovery guidance.

## API contract changes

None to paths, request/response fields, enums, authentication, or page numbering.
This is a partial v0.1 implementation: upload-triggered AI analysis is deferred as
requested. Successfully extracted jobs stop at `needs_review` / `extracting` and
explicitly say AI analysis is not implemented. Extracted pages are persisted, not
added to the agreed upload response. No raw-text endpoint was invented.

The broader first checkpoint in `START_HERE.md` includes a co-payment finding; it is
outside this milestone. Limits and page quality labels were unspecified in the shared
docs, so backend defaults are documented in README without changing shared contracts.

## Next small step

Configure a disposable Supabase project, apply the migration, and run the opt-in
two-user integration test. Only after that gate passes, implement structured policy
extraction as a separate approved milestone with page/quote provenance.
