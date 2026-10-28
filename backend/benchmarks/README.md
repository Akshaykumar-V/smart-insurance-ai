# Offline clause benchmark

This is an evaluation tool, not part of the live v0.1 extraction or API path.
The six real-policy annotations and exact excerpts live in the Git-ignored
`backend/local_benchmarks/` directory. Do not stage that directory or the PDF.

## Local validation

From `backend/`, run:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_clause_benchmark --pdf <local-public-pdf> --benchmark local_benchmarks\hdfc_optima_secure_benchmark.json --mock-self-check
```

The report prints target IDs, physical pages, passage IDs and counts. It never
prints excerpts. Validation checks the PDF SHA-256, physical page count, canonical
text length, and each exact excerpt's page and character offsets through the
Milestone 8A anchorer. A changed PDF or extraction result fails closed.

The `oracle_mock_self_check_not_model_accuracy` results use candidate excerpts
copied from the local gold annotations. They verify the harness and adapter, not
real discovery recall. The self-check also includes an altered quote, a wrong
passage, a duplicate, and an unsupported financial-rule attempt.

## Manual annotation review

All six local real-policy targets start as `manual_review_status: pending`.
Before using them as accuracy gold, a reviewer must open the ignored JSON and
the matching PDF locally, then check each full clause, physical PDF page,
excerpt, passage, category, clause kind, schedule or endorsement dependency,
qualifications, and whether any financial rule is truly supported. Mark each
target `approved` or `rejected` only after review. Do not change a quotation to
make an anchor pass; revise the annotation selection and record a new local
benchmark version instead. An approved annotation remains a human review of
public wording, not an insurer claim determination.

The report distinguishes provisional recall against pending annotations from
recall against approved targets. Exact-span target recall is intentionally
strict. A later model quote that covers a different valid part of the same
clause requires manual adjudication rather than automatic credit.

## Disabled-provider pilot preflight

The offline preflight builds request shapes for only the passages for the
co-payment definition (physical page 3) and proportionate room-rent deduction
(physical page 12). It plans at most **two requests**, one primary passage per
request, with no context. The input budget is **6,000 tokens per request** for
instructions, schema, and passage payload together. It reserves **800 output
tokens per request**, for a maximum of **13,600 combined tokens** across the
pilot. The request body sets provider storage off and has no financial-rule
field. No provider client or sender is included.

From `backend/`, run:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_pilot_preflight --pdf <local-public-pdf> --benchmark local_benchmarks\hdfc_optima_secure_benchmark.json
```

The report contains counts, byte sizes, and identifiers, never passage text.
`tiktoken` maps the configured `gpt-4.1-mini` model to `o200k_base` and supplies
a **local estimate**, not a provider count. The offline gate also counts the
complete request as UTF-8 bytes (including instructions, passage input, schema,
and JSON structure), using the larger of literal and ASCII-escaped forms. It
adds a **1,600-token formatting allowance**, reserves the full **800 output
tokens**, and rejects requests above the configured limits. Missing tokenizer,
wrong model, changed request shape, or oversized requests fail closed. The
tokenizer is a pinned development-only dependency. Its public `o200k_base`
encoding asset must already be present in tiktoken's cache and match the pinned
hash; a missing or altered asset fails closed before tokenizer initialization.
The preflight does not download it.

The byte allowance is intentionally much larger than the local token estimate.
It is an engineering policy, **not a documented upper bound on provider-side
formatting**. Only the provider's input-token count can establish the exact
complete-request count; no provider call is made here. Passing the offline
policy does not authorize a paid request. Manual annotation approval and
explicit authorization are still required before any pilot. Do not retry paid
requests automatically or write to the database or live extraction path.

Every candidate must pass the exact passage anchorer. Save only local ignored
evaluation material and content-free counts; do not log PDF text or rejected
quotations. Evaluate source acceptance, target recall, duplicates, and unsafe
rule attempts before proposing a wider run. The complete 69-page plan has 31
batches and is outside the first pilot.
