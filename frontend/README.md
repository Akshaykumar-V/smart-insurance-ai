# Insurance wallet, document upload and policy intelligence

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

Wallet: category filters, search, policy cards, loading skeletons, empty/error states and responsive navigation. Add policy opens the document upload dialog. View policy details opens a policy's metadata, members and document list; AI findings opens its six-category intelligence report. Source reference buttons open a reference placeholder. Authentication, the full PDF viewer and the simulator remain deferred. The sidebar's claim simulator is labeled upcoming.

`components/wallet.tsx` uses `mockWalletClient` by default. Shared types are imported from `../frontend_api_types.ts`; API v0.1 is unchanged. Runtime validation rejects incompatible list responses. Unknown schedule values remain null and render as unknown. Currency conversion is formatting only; no insurance calculations run in the frontend.

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
- Loading, retry, not-found, unauthorized, unsupported, processing and empty-report states are implemented. Route navigation and unmount abort stale requests. There are no insurance calculations, rejection probabilities or claim decisions.
- `workspace-shell.tsx` shares the existing wallet sidebar, header, scope note and footer across the new pages. The wallet's category filtering, search and upload dialog remain available.

### Demo paths

Start with **Family Health Plus → View policy details → AI findings → Inspect source reference**. This fixture has six findings, a missing member age, a document needing review, an illustrative source-checked finding, an exclusion search with no result, and conflicting/insufficient evidence examples. All quotes, pages and verification labels are fictional UI fixtures, not real AI output or original policy evidence.

**Everyday Health** demonstrates missing schedule/member/amount/date information and analysis still processing. **Drive Secure** and **Tomorrow Term** show wallet-only report states. An unknown ID such as `/policies/not-a-demo-policy` displays an explicit not-found state. Mock uploads still do not create persistent entries in this fixture collection.

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
