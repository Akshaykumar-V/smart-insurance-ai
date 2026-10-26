# Frontend foundation and document upload

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

Wallet: category filters, search, policy cards, loading skeletons, empty/error states and responsive navigation. Add policy opens the document upload dialog. Policy detail, evidence, authentication and simulation screens are deferred. Claim insights is labeled upcoming and is not a navigation link.

`components/wallet.tsx` uses `mockWalletClient` by default. Shared types are imported from `../frontend_api_types.ts`; API v0.1 is unchanged. Runtime validation rejects incompatible list responses. Unknown schedule values remain null and render as unknown. Currency conversion is formatting only; no insurance calculations run in the frontend.

## Backend integration dependencies

`lib/wallet-client.ts` centralizes adapters and exposes an opt-in real client for the documented authenticated `GET /api/v1/policies`. Supply a FastAPI origin and a Supabase access-token provider; configure backend CORS. The default demo makes no network calls. This milestone does not verify backend availability.

`lib/upload-client.ts` exposes `createApiUploadClient(baseUrl, getAccessToken)` for the documented `POST /api/v1/policies/upload` and `GET /api/v1/jobs/{job_id}`. Pass this adapter as the `uploadClient` prop to `Wallet`, alongside the real wallet client when integration is ready. The UI does not implement sign-in or hold a hard-coded token. The backend must enforce authentication, ownership, private storage, PDF parsing and its actual size/page limits. Configure CORS for the frontend origin. No backend endpoints were exercised in this milestone; adapter tests stub `fetch`.

Deep analysis is restricted to individual/family-floater indemnity health insurance. Category and policy type alone do not confirm indemnity eligibility; await backend classification. No pagination UI is implemented yet; the mock list has a null cursor.

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
