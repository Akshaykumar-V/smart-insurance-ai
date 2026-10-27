# Frontend milestone 5A — October 27, 2026

Branch: `feature/frontend`; baseline simulator commit `6a5af99`. Hackathon proof-of-concept with a hard development deadline of October 28, 2026. No backend or shared API contract edits. The pre-existing uncommitted `TASK_BOARD.md` update is preserved.

## Configuration

Set these public variables in ignored `frontend/.env.local`. No environment file belongs in the commit.

| Variable | Behavior |
| --- | --- |
| `NEXT_PUBLIC_APP_MODE` | `demo` by default; `live` explicitly enables authentication and upload/job integration. Invalid values show a configuration error. |
| `NEXT_PUBLIC_SUPABASE_URL` | Existing Supabase project origin; supplied by the user and placed in the local ignored file. |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Required public publishable key, still awaiting user configuration. A legacy public anon key may instead use `NEXT_PUBLIC_SUPABASE_ANON_KEY`. Secret/service-role keys are rejected; never place them in any public variable. |
| `NEXT_PUBLIC_BACKEND_ORIGIN` | Required reachable origin, with no `/api/v1` suffix. Same-machine development may use `http://127.0.0.1:8000`; Laptop 2 must use Laptop 1's actual private LAN IP and port 8000. No LAN address is assumed. |
| `NEXT_PUBLIC_POLICY_READS_ENABLED` | Default `false`. Keep false for the currently confirmed backend. Enable only after both policy-detail and findings endpoints are implemented and verified compatible with v0.1. |

Public variables are bundled at build time. Restart development or rebuild production after changes. Supabase uses HTTPS; backend HTTPS is supported, and HTTP localhost/private IPv4 LAN origins are accepted for this development prototype. Use HTTPS for shared deployment. Laptop 1 must listen on a reachable interface, allow port 8000 through its firewall, and configure CORS to include Laptop 2's exact browser origin. The frontend does not alter server/network settings.

No public key has been invented or hardcoded. Demo mode initializes no Supabase client and performs no backend calls. Incomplete live settings fail visibly rather than falling back to fictional data.

## Authentication and request lifecycle

- Existing Supabase email/password accounts only; no sign-up, password reset, OAuth or admin user creation. The SDK is pinned to `@supabase/supabase-js` 2.118.0 and requires Node.js 22+.
- A browser-only singleton uses SDK-managed session persistence and automatic refresh. UI state contains identity, not cached access tokens. Password input is cleared after submission and never logged or written to files.
- `getAccessToken(ownerId)` asks the SDK for the current session on each request, refreshes near-expiry sessions, shares concurrent explicit refreshes and rejects missing/expired/wrong-owner results. The backend remains responsible for JWT validation and ownership; browser session state is not an authorization authority.
- Auth changes to a different owner, sign-out and failed session confirmation abort outstanding backend requests. A request created for an old owner cannot acquire the new owner's token. Private upload/report UI is unmounted when signed out and keyed to the signed-in user.
- Backend HTTP 401 locks the workspace and requires sign-in again. A 403 displays access denial without forcing logout. Uploads are never automatically replayed after token refresh, network errors or 401 responses. Only transient GET polling retries follow the existing bounded backoff.
- Sign-out uses the SDK's `scope: "local"`, immediately locks the UI and aborts requests, then attempts session revocation. Offline failure is reported as unconfirmed sign-out with a retry action; it is not described as successful revocation. SDK-persisted sessions may remain until sign-out succeeds.
- Upload tracking is page-session only. Reload, navigation or reauthentication clears it. IDs are shown after a validated 202 response; retain them before leaving. Interrupted uploads may exist on the server even without a receipt, so consult the backend operator before resending. No job restart/cancellation endpoint is invented.

The implementation follows the official [password sign-in](https://supabase.com/docs/reference/javascript/auth-signinwithpassword), [session retrieval](https://supabase.com/docs/reference/javascript/auth-getsession), [refresh](https://supabase.com/docs/reference/javascript/auth-refreshsession), and [local sign-out](https://supabase.com/docs/reference/javascript/auth-signout) interfaces.

## Confirmed endpoints and integration limits

The fetched backend snapshot `origin/feature/ai-backend` at `94ad558` exposes health, upload and jobs. The user's newer implementation status additionally confirms findings and previous live ingestion success; findings currently have mocked offline tests, not live AI extraction verification. That newer findings implementation/schema is not present in the fetched snapshot. The user's latest status takes precedence for the table below; this frontend run has not independently called the live services.

| Endpoint | Current frontend behavior |
| --- | --- |
| `GET /api/v1/health` | Confirmed implemented. No automatic probe needed or used as proof of other capabilities. |
| `POST /api/v1/policies/upload` | Wired after sign-in; existing multipart fields, current bearer token, exact 202 response validation. |
| `GET /api/v1/jobs/{job_id}` | Wired to sequential polling; ID checks, timeout/backoff, `completed`/`needs_review`/`failed` terminal handling. |
| `GET /api/v1/policies/{policy_id}/findings` | User confirms implementation/offline tests. Existing adapter is retained but report UI is gated until compatible policy details are available. No fabricated document metadata to make findings display. |
| `GET /api/v1/policies` | Missing; never requested by the live entry. Session receipts are labeled uploads, not a fabricated wallet list. |
| `GET /api/v1/policies/{policy_id}` | Missing; default gate prevents requests, including direct policy URLs. |
| `GET /api/v1/documents/{document_id}/access` | Missing; no authenticated PDF viewer wired. |
| `POST /api/v1/policies/{policy_id}/simulate` | Missing; never wired in live mode. Local calculator stays demo-only. |

The real upload's `policy_id`, `document_id`, `job_id` and reported status are shown. Once policy reads are explicitly enabled and the job is `completed` or `needs_review`, the user can check availability: the detail adapter validates the actual response/ID, and policy type/category/status determine report eligibility. Only then does a findings link appear. The report route authenticates again and revalidates fetched data. A 404, incompatible shape, unsupported policy or absent response produces an explicit state, never fixture data. Job completion alone is not AI verification or coverage confirmation.

## Exact simulator schema differences

There is no implemented simulation endpoint or backend rule schema in the fetched backend snapshot. The latest findings schema has not been supplied, so a field-by-field comparison against its actual response cannot yet be claimed. The exact known differences are between the demo calculator and shared v0.1:

| Concern | Demo calculator | v0.1 / live gap |
| --- | --- | --- |
| Co-payment | `percent` (0–100, at most 2 decimal places), `basis: "admissible_expenses"`, optional `minimum_age`, optional `application_order` | The contract example contains `percent`, `basis`, `minimum_age`; it does not establish `application_order`. The demo requires `application_order: "after_sub_limits"` when combining with an applicable co-payment. Do not infer that order from separate findings. |
| Treatment sub-limit | `amount_paise`, `basis: "eligible_treatment_expenses"`, `treatment_label`, `limit_scope: "per_hospitalization"` | No concrete sub-limit rule shape is defined by v0.1's generic `Record<string, unknown>`. All four semantics require agreement/verification; annual/lifetime caps are unsupported locally. |
| Additional conditions | Unknown rule keys or multiple candidates for a selected type block local math | Findings parsing intentionally preserves unknown fields. Shape acceptance is not rule-engine compatibility. |
| Scenario money | Separate `hospitalBillPaise`, `admissiblePaise`, `treatmentEligiblePaise` | API request supplies only `estimated_admissible_expenses_paise` plus optional room-rate fields; it has no hospital-bill or eligible-treatment-portion input. |
| Scenario context | `age`, `treatment`, `model`, `confirmedFindingIds`, `scopeAcknowledged` | API uses `insured_age`, `treatment_label`, `room_rent_per_day_paise`, `room_days`; no selection/acknowledgment fields. Local acknowledgments are not verified applicability. |
| Result | Breakdown with modeled insurer/patient totals; local statuses `incomplete`, `invalid`, `insufficient_evidence`, `illustrative` | API statuses are `illustrative`, `partially_calculable`, `insufficient_evidence`, with per-finding `customer_share_paise`; no aggregate insurer payout or patient total is specified. |
| Review flag / exceptions | Source-verified fixture may retain `review_required=true`; hypothetical user confirmation is explicitly labeled | This is insufficient for real calculations. A user checkbox cannot resolve review flags, absent exceptions, conflicting evidence or actual schedule applicability. |

Before any live numerical result: obtain and coordinate a typed rule schema; establish authoritative policy/document ownership, version, 1-indexed page and exact quote; verify scope, schedule/member inputs, definitions and exceptions; resolve conflicts/review flags; establish expense bases and adjustment order; and implement/test the deterministic server calculator in integer paise. Validate response finding IDs against verified evidence. Missing evidence must yield insufficient/partial results, with no LLM or frontend fallback and no unsupported complete payout. The backend snapshot also notes that owner-writable page/job records are not proof of evidence authenticity; trusted verification must address that before relying on a `verified` label.

No shared contract or TypeScript API DTO changes were made. The extra optional HTTP status on frontend `UploadError` is internal error handling only.

## Verification and remaining acceptance

- `npm run typecheck`: passed.
- `npm test`: 83 passed, 0 failed (64 existing + 19 new). Tests use synthetic accounts, documents and responses; include official SDK Auth HTTP stubs, current-token refresh, stale-account rejection, sign-out cancellation, sign-in during pending logout, owner changes during refresh, no upload replay, gated endpoints and live markup without demo reports.
- The first new test run found two issues (SSR React import and preservation of upload error codes); both were fixed and the complete suite rerun successfully.
- `npm run build`: passed, exit 0, including a final rerun after session-race hardening; all four route entries built. Demo mode succeeded with live key/origin unset.
- Public key and Laptop 1's actual LAN origin remain unset. No real sign-in, real upload, browser CORS or live AI extraction is claimed by these tests. Manual browser/mobile/keyboard acceptance remains pending.
- Dependency audit reports the existing Next/PostCSS chain (one moderate and one high finding). Existing lockfile package versions were preserved; no forced major framework upgrade was performed in this auth milestone.

Next small step: supply the public key and reachable backend origin locally, configure backend CORS, then perform a fictional-user browser sign-in/upload/job/sign-out smoke test. Keep policy reads disabled until the missing detail endpoint and findings schema are verified. The milestone commit scope is limited to the reviewed frontend source/docs/lockfile; `.env.local` and the pre-existing task-board edit are excluded.

## Files for review (all under frontend/)

Added: `INTEGRATION_STATUS.md`, `app/auth.css`, `components/app-entry.tsx`, `components/live-workspace.tsx`, `lib/app-config.ts`, `lib/auth-session.ts`, `lib/live-clients.ts`, `lib/live-integration.test.tsx`, `lib/supabase-browser.ts`.

Modified: `README.md`, `app/layout.tsx`, `app/page.tsx`, `app/policies/[policyId]/page.tsx`, `app/policies/[policyId]/findings/page.tsx`, `components/upload-dialog.tsx`, `components/workspace-shell.tsx`, `lib/upload-client.ts`, `lib/upload-contract.ts`, `package.json`, `package-lock.json`.

Local only, excluded from commit: `.env.local` with the public project URL, demo mode and blank public-key/backend-origin fields. The existing uncommitted `TASK_BOARD.md` edit is preserved. Real-service acceptance remains blocked by configuration and missing policy details; committing the frontend does not establish live-service verification.
