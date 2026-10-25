# AI Coding Instructions — Both Laptops

Read `START_HERE.md`, `PROJECT_CONTEXT.md`, `API_CONTRACT.md`, `DATABASE_SCHEMA.md` before editing. These files are **shared source-of-truth decisions**. The product is a hackathon proof-of-concept and must be honestly described as such.

## Ownership
- Laptop 1 agent: modify `backend/`, `supabase/`, `datasets/`; controls data processing, auth, LLM, retrieval, verification, calculations.
- Laptop 2 agent: modify `frontend/`; controls Next.js components, routes, PDF viewer, forms, mock adapter and real API client.
- Shared docs changed only after coordinating and updating both accounts via GitHub.

## Do
- Make small vertical slices with tests and explicit exit criteria.
- Check existing repository state; don't overwrite unrelated or uncommitted changes.
- Use static types/schemas and validate data at the API boundary.
- Build negative paths: missing schedule, scanned/garbled PDF, uncertain clauses, unauthorized documents, absent exceptions.
- Separate original evidence, AI interpretation and deterministic calculation visually and in APIs.
- Link findings to PDF page/quote. No unsupported numerical calculations.
- Commit focused changes on own feature branch; use PRs for integration.
- Always report files changed, tests actually executed, failures, unresolved work, and API contract changes.

## Do NOT
- Claim API endpoints already work without running them.
- Invent insurers' claim decisions, policy wording, source pages, accuracy percentages, or financial payouts.
- Expose secrets in Git, frontend, logs or markdown.
- Add an LLM-based calculation fallback when the deterministic rule engine lacks evidence.
- Implement life/motor claims processing in MVP; categories are wallet-only.
- Automatically conclude a claim is not covered because no relevant clause was retrieved.
- Add autonomous multi-agent systems, production payment/claim workflows, or large optional features.

## Contract changes
`API_CONTRACT.md` is **v0.1**. If a field or endpoint must change, stop, record a proposal, communicate to other laptop, update contract/TypeScript type first, then implement. Money in paise, PDF pages 1-indexed, auth bearer token. No silent breaking changes.

## Status report after each milestone
```
Branch:
Files changed:
Implemented:
Tests run (commands + results):
Known limitations:
API contract changes:
Next small step:
```
