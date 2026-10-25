# Database Design v0.1 — Supabase PostgreSQL

**Contract-level schema**, not proof migrations have been executed. Laptop 1 owns migrations, RLS policies and storage access. UUID IDs may be used internally even if UI examples use demo strings. Money is in `BIGINT` integer INR **paise**, not float.

## Core tables (P0)

| Table | Minimum fields | Purpose |
|---|---|---|
| `policies` | `id`, `owner_id` references auth user, `category`, `policy_type`, `insurer`, `product_name`, `uin`, `policyholder_name`, `sum_insured_paise`, `start_date`, `end_date`, `analysis_status`, timestamps | Per-user policy container; nullable person-specific fields |
| `documents` | `id`, `owner_id`, `policy_id`, `type`, `file_name`, `storage_path`, `sha256`, `page_count`, `processing_status`, `version_label`, timestamps | Private uploaded files; many documents per policy |
| `document_pages` | `id`, `owner_id`, `document_id`, `page_number`, `text`, `extraction_quality`, `method` | Page-wise extracted content; page numbers 1-indexed |
| `document_chunks` | `id`, `owner_id`, `policy_id`, `document_id`, `page_start`, `page_end`, `heading`, `content`, `embedding VECTOR(1536)`, `fts TSVECTOR` | Policy-scoped hybrid RAG search |
| `analysis_jobs` | `id`, `owner_id`, `policy_id`, `document_id`, `status`, `stage`, `message`, `error_code`, `created_at`, `updated_at` | Async upload/analysis status |
| `findings` | `id`, `owner_id`, `policy_id`, `condition_type`, `status`, `verification_status`, `title`, `explanation`, `rule_json JSONB`, `applicability`, `exceptions JSONB`, `source_document_id`, `source_page`, `exact_quote`, `analysis_version`, timestamps | Structured, evidence-based findings |
| `scenarios` (P1 if necessary) | `id`, `owner_id`, `policy_id`, `input_json JSONB`, `result_json JSONB`, `created_at` | Persisted hypothetical analyses |

Dev-only `golden_cases` / evaluation fixtures may be kept as versioned synthetic files initially instead of user-facing tables.

## Invariants
1. All user data uses `owner_id` taken from **validated authentication**, never trusted frontend input.
2. Supabase private Storage paths scoped by `owner_id` and `policy_id`; NEVER a public customer document bucket.
3. Enable RLS on all private tables and restrict storage objects. If FastAPI uses service-role access, it MUST enforce ownership itself. Test a second account cannot access documents/jobs of the first.
4. Foreign keys protect policy/document/chunk relationships. On policy deletion remove private artifacts and embeddings as well as rows.
5. Keep `document_chunks` under a composite policy/owner filter **before** retrieval or ranking. Do not embed user text with other users' data in retrieval context.
6. Use exact PDF `page_number` (1-indexed), not the page number printed inside the PDF.
7. Prefer versioned source records; don't treat a current public wording as proof of an older customer's applicable contract.
8. For demo, prefer fictional policy schedules and no patient health records. Avoid raw document text in logs and analytics.

## P0 indexes
- `policies(owner_id)`; `documents(owner_id, policy_id)`; `analysis_jobs(owner_id, policy_id)`; `findings(owner_id, policy_id)`.
- `document_chunks(owner_id, policy_id)` plus PostgreSQL full-text GIN index and pgvector index if dataset warrants it.
- `UNIQUE(document_id, page_number)` for page rows; optional checksum-based document deduplication **within** user scope.

## Migrations acceptance tests
- Owner A can list their own policies; Owner B cannot read Owner A's policy, job, PDF, chunks, findings or signed access URL.
- Removing an uploaded policy invalidates document references and cleans up associated storage and embeddings.
- Null schedule data remains null; no default fake expiry, policyholder or sum insured.
- Search returns chunks only for the target policy and owner.
