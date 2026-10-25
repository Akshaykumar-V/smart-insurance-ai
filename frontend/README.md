# Frontend foundation

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

Wallet only: category filters, search, policy cards, loading skeletons, empty/error states, responsive navigation, upload information dialog. Upload does not accept or transmit files in this milestone. Policy detail, evidence, authentication and simulation screens are deferred. Claim insights is labeled upcoming and is not a navigation link.

`components/wallet.tsx` uses `mockWalletClient` by default. Shared types are imported from `../frontend_api_types.ts`; API v0.1 is unchanged. Runtime validation rejects incompatible list responses. Unknown schedule values remain null and render as unknown. Currency conversion is formatting only; no insurance calculations run in the frontend.

## Backend integration dependencies

`lib/wallet-client.ts` centralizes adapters and exposes an opt-in real client for the documented authenticated `GET /api/v1/policies`. Supply a FastAPI origin and a Supabase access-token provider; configure backend CORS. The default demo makes no network calls. This milestone does not verify backend availability.

A later milestone requires `POST /api/v1/policies/upload` and `GET /api/v1/jobs/{job_id}` plus Supabase sign-in. Deep analysis is restricted to individual/family-floater indemnity health insurance. Category and policy type alone do not confirm indemnity eligibility; await backend classification. No pagination UI is implemented yet; the mock list has a null cursor.

## Manual acceptance

Check desktop and narrow mobile layouts; filter each category; search a nonexistent insurer to see the empty state; clear filters; open and dismiss the upload dialog with Escape; verify keyboard focus returns to the opener. Loading is visible briefly on reload. Backend errors offer retry. Browser visual QA must be reported separately from unit tests and build checks.
