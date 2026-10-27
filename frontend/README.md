# Insurance wallet, policy intelligence and claim impact simulator

Next.js App Router, TypeScript, Tailwind CSS. All displayed policies are fictional. This is a hackathon proof-of-concept, not a coverage or claim decision service.

## Run

From `frontend/` with Node.js 20.9+ (Node.js 22 LTS recommended):

```sh
npm ci
npm run dev
```

Open http://localhost:3000. For a production server: `npm run build` then `npm start`.

## Checks

```sh
npm run typecheck
npm test
npm run build
```

## Scope

Wallet: category filters, search, policy cards, loading skeletons, empty/error states and responsive navigation. Add policy opens the document upload dialog. View policy details opens a policy's metadata, members and document list; AI findings opens its six-category intelligence report. Source reference buttons open a reference placeholder. **Simulate Claim Impact** expands the fictional simulator within an available policy report. Authentication and the full PDF viewer remain deferred.

`components/wallet.tsx` uses `mockWalletClient` by default. Shared types are imported from `../frontend_api_types.ts`; API v0.1 is unchanged. Runtime validation rejects incompatible responses. Unknown schedule values remain null and render as unknown. Milestone 4's explicit user request authorizes isolated, deterministic TypeScript calculations for the fictional simulator, overriding the earlier frontend-no-calculations guideline for this scope. Live policy arithmetic remains server-owned; the local model is not a fallback for live data.

## Backend integration dependencies

`lib/wallet-client.ts` centralizes adapters and exposes an opt-in real client for the documented authenticated `GET /api/v1/policies`. Supply a FastAPI origin and a Supabase access-token provider; configure backend CORS. The default demo makes no network calls. This milestone does not verify backend availability.

`lib/upload-client.ts` exposes `createApiUploadClient(baseUrl, getAccessToken)` for the documented `POST /api/v1/policies/upload` and `GET /api/v1/jobs/{job_id}`. Pass this adapter as the `uploadClient` prop to `Wallet`, alongside the real wallet client when integration is ready. The UI does not implement sign-in or hold a hard-coded token. The backend must enforce authentication, ownership, private storage, PDF parsing and its actual size/page limits. Configure CORS for the frontend origin. No backend endpoints were exercised in this milestone; adapter tests stub `fetch`.

Deep analysis is restricted to individual/family-floater indemnity health insurance. Category and policy type alone do not confirm indemnity eligibility; await backend classification. No pagination UI is implemented yet; the mock list has a null cursor.

`lib/policy-client.ts` exposes `createApiPolicyClient(baseUrl, getAccessToken)` for `GET /api/v1/policies/{policy_id}` and `GET /api/v1/policies/{policy_id}/findings`. The two Next.js policy routes currently use the mock adapter; supply a real client to `PolicyWorkspace` when integrating authentication. The client validates the response shape and requested policy ID, encodes opaque IDs, forwards bearer tokens, uses a 30-second timeout, and handles 401/403/404/429/server errors without displaying raw server bodies. It never calls a document-access or simulation endpoint in this milestone.

The backend must classify analysis eligibility, report authoritative analysis statuses, scope documents/findings to the authenticated owner and return 1-indexed source pages with exact quotes. The v0.1 policy type does not independently encode indemnity eligibility. The frontend blocks non-health, unsupported and unknown/other policy types, and fetches findings only for `ready` or `needs_review` policies; backend eligibility enforcement is still required.

## Policy details and intelligence report

- `/policies/[policyId]`: insurer, product, type, sum insured (paise formatted into INR), dates, policyholder, members, documents, analysis status and missing-information warnings. Null fields stay unknown. Document metadata does not imply a downloadable file.
- `/policies/[policyId]/findings`: waiting periods, exclusions, co-payments, deductibles, treatment-specific sub-limits and room-rent restrictions. All six categories remain visible when a report is available, including categories with no returned findings.
- Reusable finding cards separate interpretation, applicability, exceptions, status, verification and source text. Empty exceptions do not mean there are none; not-found search results and empty categories never guarantee coverage. Conflicting evidence and review flags remain prominent even when other status fields are favorable.
- Source references must match the policy's attached document list and stay within its known page count. Invalid references are shown as review warnings without presenting their quotes as linked evidence. Unknown page counts are explicitly labeled. The source dialog displays the document ID, reported 1-indexed page and returned quote; it does not open or fetch a PDF. Returned strings are escaped by React.
- Loading, retry, not-found, unauthorized, unsupported, processing and empty-report states are implemented. Route navigation and unmount abort stale requests. The separate simulator calculates only selected fictional rules; there are no rejection probabilities or claim decisions.
- `workspace-shell.tsx` shares the existing wallet sidebar, header, scope note and footer across the new pages. The wallet's category filtering, search and upload dialog remain available.

### Demo paths

Start with **Family Health Plus → View policy details → AI findings → Inspect source reference**. This fixture has six findings, a missing member age, a document needing review, an illustrative source-checked finding, an exclusion search with no result, and conflicting/insufficient evidence examples. All quotes, pages and verification labels are fictional UI fixtures, not real AI output or original policy evidence.

**Everyday Health** demonstrates missing schedule/member/amount/date information and analysis still processing. **Drive Secure** and **Tomorrow Term** show wallet-only report states. An unknown ID such as `/policies/not-a-demo-policy` displays an explicit not-found state. Mock uploads still do not create persistent entries in this fixture collection.

## Claim impact simulator (milestone 4)

Open **Family Health Plus → AI findings → Simulate Claim Impact**. Enter a hospital bill, separate admissible-expense estimate, treatment category, eligible treatment portion where relevant, and member/hypothetical age. Member selection fills only a known age; an unknown age stays blank. Editing age never updates policy records. Choose co-payment only, sub-limit only, or both. Confirm the relevant hypothetical scope/exception assumptions and acknowledge the limited model. Changes to scenario inputs clear previous results and confirmations. Nothing is persisted or sent to an AI model.

The fictional intelligence adapter now supplies a 20% co-payment for age 60+ and a cataract cap of INR 50,000 per hospitalization. Numeric values and source quotes live in `lib/mock-intelligence.ts`, not the UI. Other report findings, including conflicting deductible evidence and an exclusion search with no result, remain unresolved and are listed as outside the model.

### Calculation assumptions and rounding

`lib/claim-calculator.ts` contains pure functions, separate from presentation. `lib/simulation-client.ts` provides an abortable local adapter and a distinct real API adapter.

1. All internal amounts are non-negative safe integer **paise**. INR input is parsed as an exact decimal string, accepting valid Indian/international digit grouping and at most two decimal places. Negative, fractional-paise, nonfinite and unsafe amounts are rejected.
2. Both bill and admissible estimates are needed for the financial breakdown. Unknown admissibility blocks totals; the bill is never silently used as the admissible base. Admissible expenses cannot exceed the bill.
3. Eligible treatment expenses are a subset of the admissible estimate. For a matching treatment, `above_cap = max(eligible_treatment - cap, 0)`. Other admissible expenses are preserved. A nonmatching category does not apply that specific cap; it does not imply that all other limits are absent.
4. When both rules are modeled, the co-payment base is `admissible - above_cap`. The structured fictional rule must explicitly establish this order. No co-payment is applied to the above-cap amount or to assumed non-admissible expenses.
5. The co-payment uses exact integer arithmetic (`BigInt` internally), with a percentage of at most two decimal places, rounded half-up once to the nearest paise. Monetary outputs remain safe integers.
6. Selected-rule insurer share = `admissible - above_cap - co_payment`. Selected-rule patient share = `(bill - admissible) + above_cap + co_payment`. These sum to the bill, without double-counting. They are **not a complete claim payout estimate**.
7. Deductibles, exclusions, waiting periods, room restrictions, remaining cover, endorsements and other limits are not modeled. Bill minus admissible is a user-assumed non-admissible portion, not an insurer-confirmed exclusion.
8. A numeric rule must be `found`, source-`verified`, have described applicability and a valid quote/page within an attached document's known page range. Each selected type must have exactly one unambiguous rule. Unknown rule keys, unsupported bases, annual/lifetime caps, missing numeric parameters and uncertain/conflicting evidence block calculation. User confirmations cannot override these evidence failures.
9. Scenario scope/exception assumptions must be explicitly confirmed for applied rules. A `review_required` flag remains visible as unresolved; confirmation is hypothetical, not evidence verification. Missing exception entries are never interpreted as proof that none exist. Source links return to the original finding and its illustrative PDF page.

Example: bill INR 1,00,000; admissible INR 90,000; eligible cataract portion INR 70,000; age 65. The model counts INR 10,000 outside the admissible estimate, INR 20,000 above the treatment cap, then 20% of INR 70,000 = INR 14,000 co-payment. The selected-rule shares are INR 56,000 insurer / INR 44,000 patient. Other terms remain unresolved.

### Live integration boundary

`createApiSimulatorClient(baseUrl, getAccessToken)` calls only the documented authenticated `POST /api/v1/policies/{policy_id}/simulate`. It accepts/validates the existing `SimulatorRequest` / `SimulatorResponse` shapes, forwards a bearer token, enforces policy-ID matching, and supports timeout/cancellation and 401/403/404/422/429/server errors. It does not calculate a local fallback on failure. Tests stub this endpoint; no backend endpoint was verified.

The current screen deliberately exposes local modeling only in mock mode. API-mode reports display a live-simulation-not-connected state. Connecting the live screen requires token provisioning, backend availability/CORS, source/applicability verification, and presentation of the backend's partial/insufficient results. Contract v0.1 has no separate hospital-bill or eligible-treatment-portion field and no aggregate insurer/patient totals. The real adapter sends only the documented age, admissible-expense, treatment-label and room fields; it never sneaks frontend-only inputs into the request or invents a backend total. Full parity would require coordination with Laptop 1 before any contract amendment. Shared contracts were not changed.

The fixture's extra `rule` keys (`application_order`, `limit_scope`, treatment expense basis) are local interpretations of the existing generic rule object, not new API requirements for the backend. Live responses are never evaluated by this local model.

## Upload and processing behavior

- Browse or drag/drop one PDF. Local checks cover extension, browser MIME when present, empty files, a 20 MiB frontend limit, and a PDF header in the first 1,024 bytes. These checks do not validate the entire PDF, encryption, text readability or scan quality. The backend remains authoritative. The 20 MiB limit is a UI choice, not an API contract amendment.
- Select a new or existing policy and an optional document type hint. Existing-policy attachments use `policy_id` in the same upload request. No additional endpoint is introduced.
- Upload activity uses an indeterminate progress indicator. No transfer or processing percentages are invented. The UI waits for a valid HTTP 202 receipt before polling, then displays reported stages. Only a terminal job **status**, not a stage name or elapsed time, ends polling.
- Polling uses sequential requests every two seconds, exponential backoff on transient failures (up to 16 seconds), at most three consecutive errors and 60 attempts per run. Status requests have a 30-second timeout; upload requests have a 120-second timeout. Unauthorized/forbidden responses and invalid/mismatched data stop automatic checking.
- Pausing/resuming checks only stops/resumes GET polling; it never restarts a job. Failed jobs offer a new document upload, not an invented job-retry action. An unconfirmed upload is never automatically retried; the real-mode UI warns that manually sending again may create a duplicate after a lost response.
- The dialog stays mounted when closed, so in-progress work can be reopened using Add policy. Page reload/navigation clears this session; persistent job recovery is deferred. Unmount aborts local work without claiming server cancellation. A completed/review/failed run can attach another document to the returned policy ID.

## Mock scenarios

The default adapter never calls the network, parses PDF content or persists documents. It does not add entries to the wallet. Selected file bytes are released after simulated acceptance. Status messages, IDs, and terminal outcomes are explicitly labeled as demo/simulated. Choose a public or fictional PDF and one of these scenarios in the dialog:

- Missing schedule: reaches `needs_review`; member details and applicability remain unknown.
- Completed workflow: clearly simulated completion, with no analysis or coverage claim.
- Unreadable/scanned PDF: a fictional `failed` job, not a file-content detector.
- Upload connection error: first attempt fails; explicit retry proceeds.
- Status connection errors: checks back off, pause after three failures, then Resume status checks continues the same job.

## Manual acceptance

Check desktop and narrow mobile layouts; filter each category; search a nonexistent insurer; clear filters. Open and dismiss the upload dialog with Escape and verify focus returns to the opener. Choose/drop invalid, empty, oversized and valid fictional PDFs. Check each demo scenario, policy attachment, optional type hint, upload retry, pause/resume, closing/reopening during processing, and adding another document after a terminal outcome. Verify that processing shows no invented percentages and failed jobs have no restart action.

Automated tests cover local validation, typed mock flows, request fields, bearer-token forwarding, response validation, HTTP errors, mismatched IDs, backoff, cancellation and terminal stopping. Browser visual and keyboard QA remains outstanding: the computer-use tool reported no available browser or native connection in this environment.

Milestone 3 tests also cover detail/finding schemas, all six fixture categories, missing fields, report eligibility, absent exceptions, conflicting evidence, source matching/page bounds, escaped quotes, and server-rendered detail/finding-card markup. Tests use stubbed network responses; no real backend behavior or AI accuracy is claimed. Manual QA should include wallet-to-details navigation, both policy tabs, all six category anchors, source-dialog Escape/focus restoration, a narrow viewport, unknown-policy URLs, and the existing upload flow after the shared-shell extraction.

Milestone 4 verification rerun on October 27, 2026: `npm run typecheck`, all **64** tests (25 simulator tests and the existing 39), and `npm run build` passed with exit code 0. Tests cover co-payment, matching/nonmatching caps, combination order, missing/uncertain evidence, invalid inputs, exact rounding, deterministic invariants, mock/live isolation, request/response validation, and accessible form/result markup. The sandboxed test runner initially failed reading Windows user information (`uv_os_get_passwd`); the permitted outside-sandbox run passed. No code fixes were required. Browser interaction checks were not rerun; live mobile layout, Tab/Space/Enter behavior and focus transitions remain unverified. Native labeled inputs, selects, checkboxes, submit buttons and a `details/summary` calculation explanation are used; CSS stacks the layout and provides mobile-sized controls.

Manual simulator checks: submit with unknown admissible expenses; try negative amounts and inconsistent expense portions; choose a member with unknown age; test ages 59/60; compare cataract with Other treatment; confirm only matching-rule assumptions; recalculate after input changes; follow source anchors; navigate the form and calculation disclosure entirely by keyboard at desktop and narrow mobile widths. Verify stale results disappear and no result is described as an approved claim.
