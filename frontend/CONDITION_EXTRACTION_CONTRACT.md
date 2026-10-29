# Feature 1 condition extraction: agreed schema and adapter

Final backend schema: https://github.com/Akshaykumar-V/smart-insurance-ai/issues/1#issuecomment-6494218395

Laptop 2 accepts this additive contract. It preserves existing v0.1 upload, wallet, findings, job-message and simulator behavior. Shared DTOs are in `../frontend_api_types.ts`; the additive specification is in section 10 of `../API_CONTRACT.md`.

## Wire alignment

- Category uses the six existing ConditionType values. Kind uses benefit, restriction, condition, definition, procedural_requirement or other.
- Dependencies are structured objects: kind policy_schedule|endorsement|other_clause, nullable label defaulting to null if omitted. Unknown dependency keys are rejected.
- Start receipts allow every JobStatus because a duplicate request returns the existing job's current state. Exact HTTP 202 is required. There are no automatic POST retries.
- Analysis state is null for queued/processing/failed; successful terminal runs use complete|incomplete. Failed/incomplete runs require non-empty content-free warnings. Successful zero-condition results must be incomplete with a warning.
- Each condition ID is condition_ plus 20 lowercase hexadecimal characters. Condition document/job identity must match its run. Source_verified and review_required are literal true.
- Evidence contains 1-6 entries, physical PDF page 1-200, non-empty passage ID, increasing zero-based/end-exclusive Unicode-code-point offsets and an exact quote of at least 12 code points. Quotations are displayed verbatim as escaped text; no frontend slicing/normalization or claim calculation occurs. Backend source anchoring is not independent frontend or insurer verification.

## Adapters and activation

`createApiConditionClient` uses the existing authenticated policy transport, generalized to support JSON POST with explicit expected status. All calls use a current bearer token, no-store, a 30-second request timeout, cancellation before/after token acquisition and after response parsing, safe errors and cleanup. No raw server errors or fabricated fallbacks are shown.

The adapter implements only the agreed routes:
- POST `/api/v1/policies/{policy_id}/condition-extractions`, JSON `{document_id}`.
- GET `/api/v1/jobs/{job_id}` using the existing JobResponse parser.
- GET `/api/v1/policies/{policy_id}/conditions?job_id=...` for exactly the selected run.

`createLiveClients` applies the existing account-scoped cancellation/ownership guards. HTTP 401 expires the session; 403 preserves the session. All three methods are blocked before network access unless `NEXT_PUBLIC_CONDITION_EXTRACTIONS_ENABLED=true`. The flag defaults false, independently of policy reads. No environment file was changed or flag enabled.

`/condition-extractions` now passes through AppEntry: demo mode supplies typed mocks, live mode requires existing authentication and the feature flag. Disabled live mode displays an unavailable state, never a mock preview. In enabled real mode users supply explicit policy/document/job UUIDs; no request is triggered on mount. Starting extraction is a deliberate action on an existing extracted document and may incur backend processing costs once activated.

The UI loads job messages/status first, then the explicit conditions run on terminal status. Automatic GET checks are sequential and bounded to 60 attempts at two-second intervals (plus request time); errors stop polling and permit manual reads. Stopping local checks, account changes or unmount cancels requests without claiming server processing stopped. A timed-out/interrupted start leaves acceptance unknown and must not be blindly repeated.

Historical-job discovery after refresh remains separate. A known job ID can be selected now; no newest-job fallback, privileged browser database query or local-storage workaround is used.

## Verification and remaining integration

Tests use synthetic fixtures/stubbed fetch only. No inactive endpoint, upload or paid operation is exercised. Backend route activation, configured ownership/CORS enforcement and authorized end-to-end verification remain prerequisites to enabling the flag. Shared types/contracts and frontend code remain local and uncommitted until explicitly reviewed for integration.
