# Work Board — Two-Laptop Hackathon Build

Status symbols: `[ ]` planned; `[~]` underway; `[x]` completed **with test evidence**. This board starts with no implementation claims.

## First sync (both laptops)
- [ ] [Both] GitHub repository created/shared; `develop` committed with handoff files
- [ ] [Both] Confirm frontend/backend ownership and exact API contract v0.1
- [ ] [Laptop 1] Configure protected secrets and Supabase project; no keys in Git
- [ ] [Laptop 2] Set Next.js frontend to use TypeScript `frontend_api_types.ts`

## Laptop 1 — Backend and AI
- [ ] B1. `GET /api/v1/health` running and tested
- [ ] B2. Auth validation + private file storage + PDF upload (test unauthorized file access)
- [ ] B3. Async job/stage endpoint working; parse pages with 1-indexed evidence
- [ ] B4. Classify document and store policy metadata; unknown fields stay null
- [ ] B5. First co-payment finding from a **genuine public wording PDF**, including conditional scope and quote/page
- [ ] B6. Add remaining 5 condition families and uncertainty states
- [ ] B7. Keyword + pgvector hybrid retrieval with policy isolation, nearby definitions/exceptions
- [ ] B8. Evidence verifier: page/quote check, conflicting or missing context handling
- [ ] B9. Deterministic co-payment / simple sub-limit scenario API and unit tests
- [ ] B10. Test 3+ insurer policy documents; save actual evaluation results

## Laptop 2 — Frontend
- [ ] F1. Next.js shell compiles and builds; design system + navigation
- [ ] F2. Wallet/category tabs, policy cards, mock API adapter
- [ ] F3. Upload form and job status UI aligned to contract
- [ ] F4. Policy detail screen with unknown fields and document list
- [ ] F5. Six-condition report with verified/uncertain/missing evidence states
- [ ] F6. PDF evidence viewer opens **actual page numbers** from response
- [ ] F7. Scenario form + result breakdown, no frontend insurance-rule calculations
- [ ] F8. Replace mocks with authenticated API client, handle errors
- [ ] F9. Responsive polish, accessible controls, real browser testing

## Integration / demo
- [ ] I1. Upload-to-finding end-to-end works using policy PDF
- [ ] I2. Source link navigates to correct PDF page
- [ ] I3. Co-pay applicability example; unsupported case says insufficient evidence
- [ ] I4. Second-user auth isolation test passes
- [ ] I5. Build and deploy stable demo; backup known-good demo flow
- [ ] I6. PPT screenshots and honest metrics; rehearse 90-second demonstration

## Guardrail for 90% pre-hackathon goal
Focus on B1–B5, B8–B9 and F1–F8 before polishing. A stable complete vertical slice outranks six incomplete features. Confirm pre-built project rules with event organizer.
