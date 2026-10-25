# START HERE — Two-Laptop Execution Handoff

**Status:** Design contracts agreed for implementation, **not** claims that any code is built.

## What to do next (both laptops)
1. Read `PROJECT_CONTEXT.md`, `API_CONTRACT.md`, `DATABASE_SCHEMA.md`, `AGENTS.md`.
2. Put these files in the **root of ONE GitHub repository**. Commit them on `develop`, then have both laptops pull that same commit.
3. Laptop 1 owns `backend/`, `supabase/` and `datasets/`; Laptop 2 owns `frontend/`.
4. Laptop 2 can immediately build components against `frontend_api_types.ts` and a **clearly labeled mock adapter**. Laptop 1 implements exact v0.1 endpoints.
5. Work on `feature/ai-backend` and `feature/frontend`. Each submits a pull request to `develop`; tested `develop` advances to `main`.
6. Use `TASK_BOARD.md` as the single task tracker. Don't silently revise v0.1 contracts: update contract, notify other laptop, then change implementations.

## The first demonstrable checkpoint
A fictional or public **health policy wording PDF** uploads, returns a job ID, becomes processed, and shows **one extracted co-payment condition with a source page, scope and verification status**. The policy alone may lack member ages and schedule details; label unknowns honestly.

## Immediately send to Laptop 2
"I've committed the shared handoff files. Pull `develop` and treat `API_CONTRACT.md` and `frontend_api_types.ts` as the frontend contract v0.1. Start UI in mock mode, using mock labels; do not invent backend endpoints or rules. Own only `frontend/`. Implement wallet → upload → processing → evidence-backed finding → simulation UI. Return tested changes as a pull request."

## Immediately do on Laptop 1
Implement FastAPI `GET /api/v1/health` first, then `POST /api/v1/policies/upload` and `GET /api/v1/jobs/{job_id}`, and a simple fixture-compatible co-payment analysis. Before real policy AI, implement ownership/auth checks and a safe PDF parsing path. Start with 1 policy then extend.

## Important
- ChatGPT accounts do not share chats or memory; **GitHub files are shared memory**.
- There is no need to train a foundation model; use API-based extraction + retrieval + rule checks, measure results with golden cases.
- Pre-event development eligibility still needs organizer confirmation.
- Contract below is our agreed **starting design**, not automatically an already-existing backend. If a repository already exists, reconcile actual code before adopting this verbatim.
