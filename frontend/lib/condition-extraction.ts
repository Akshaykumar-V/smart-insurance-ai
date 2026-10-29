// Final additive schema: issue #1, backend alignment comment 6494218395.
import type { ConditionType, ConditionExtractionAccepted, ConditionExtractionRequest, ConditionExtractionResponse, ConditionEvidence, JobResponse } from "../../frontend_api_types";
export type { ConditionExtractionAccepted, ConditionExtractionRequest, ConditionExtractionResponse, ConditionEvidence, ExtractedCondition, ConditionDependency } from "../../frontend_api_types";
export type ConditionCategory = ConditionType;
export interface RunIdentity { policy_id: string; document_id: string; job_id: string }
export interface ConditionClient {
 readonly mode: "mock" | "api";
 getJob(identity: RunIdentity, signal: AbortSignal): Promise<JobResponse>;
 extract(policyId: string, request: ConditionExtractionRequest, signal: AbortSignal): Promise<ConditionExtractionAccepted>;
 getRun(identity: RunIdentity, signal: AbortSignal): Promise<ConditionExtractionResponse>;
}
export class ConditionError extends Error {
 constructor(message: string, readonly status?: number) { super(message); this.name = "ConditionError"; }
}
const statuses = ["queued", "processing", "completed", "failed", "needs_review"];
const kinds = ["benefit", "restriction", "condition", "definition", "procedural_requirement", "other"];
const categories = ["co_payment", "deductible", "sub_limit", "room_rent", "waiting_period", "exclusion"];
function object(value: unknown): Record<string, unknown> {
 if (!value || typeof value !== "object" || Array.isArray(value)) throw new ConditionError("Invalid condition response.");
 return value as Record<string, unknown>;
}
const text = (v: unknown): v is string => typeof v === "string" && !!v.trim();
const nullableText = (v: unknown) => v === null || typeof v === "string";
const integer = (v: unknown) => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
export function parseConditionReceipt(value: unknown, policyId: string, documentId: string): ConditionExtractionAccepted {
 const data = object(value);
 if (data.policy_id !== policyId || data.document_id !== documentId || !text(data.job_id) || !statuses.includes(data.status as string))
  throw new ConditionError("Extraction acceptance did not match the selected document. Acceptance is unconfirmed; check existing jobs before sending again.");
 return data as unknown as ConditionExtractionAccepted;
}
export function parseConditionRun(value: unknown, expected: RunIdentity): ConditionExtractionResponse {
 const data = object(value);
 if (data.policy_id !== expected.policy_id || data.document_id !== expected.document_id || data.job_id !== expected.job_id)
  throw new ConditionError("Stale or mismatched job response. Select the correct job_id; no latest-job fallback is used.");
 if (!statuses.includes(data.status as string)
  || ![null, "complete", "incomplete"].includes(data.analysis_state as string | null)
  || !nullableText(data.warning) || !integer(data.rejected_candidate_count) || !Array.isArray(data.conditions))
  throw new ConditionError("Invalid analysis status or warning metadata.");
 const running = data.status === "queued" || data.status === "processing";
 if ((running || data.status === "failed") && (data.analysis_state !== null || data.conditions.length !== 0))
  throw new ConditionError("Unfinished runs cannot be shown as completed analysis.");
 if (!running && data.status !== "failed" && (data.analysis_state === null
  || (data.conditions.length === 0 && data.analysis_state !== "incomplete")
  || (data.analysis_state === "incomplete" && !text(data.warning))))
  throw new ConditionError("Incomplete or empty analysis requires an explicit warning.");
 if (data.status === "failed" && !text(data.warning)) throw new ConditionError("Failed analysis requires an explicit warning.");
 const ids = new Set<string>();
 for (const raw of data.conditions) {
  const c = object(raw);
  if (!text(c.id) || !/^condition_[0-9a-f]{20}$/.test(c.id) || ids.has(c.id) || c.document_id !== expected.document_id || c.job_id !== expected.job_id
   || !categories.includes(c.category as string) || !kinds.includes(c.kind as string) || !text(c.title) || !nullableText(c.specific_label)
   || !nullableText(c.applicability) || !Array.isArray(c.observed_value_mentions) || !c.observed_value_mentions.every(v => typeof v === "string") || !Array.isArray(c.exceptions) || !c.exceptions.every(v => typeof v === "string") || !Array.isArray(c.dependencies)
   || c.source_verified !== true || c.review_required !== true || !Array.isArray(c.evidence) || !c.evidence.length || c.evidence.length > 6)
   throw new ConditionError("A condition has invalid identity, review flags or evidence.");
  ids.add(c.id);
  c.dependencies = c.dependencies.map(value => {
   const dependency = object(value);
   if (Object.keys(dependency).some(key => !["kind", "label"].includes(key)) || !["policy_schedule", "endorsement", "other_clause"].includes(dependency.kind as string)
    || !(dependency.label === undefined || nullableText(dependency.label))) throw new ConditionError("Invalid structured condition dependency.");
   return { kind: dependency.kind, label: dependency.label ?? null };
  });
  for (const rawEvidence of c.evidence) {
   const e = object(rawEvidence);
   if (!text(e.passage_id) || !integer(e.page) || ((e.page as number) < 1 || (e.page as number) > 200) || !integer(e.start) || !integer(e.end)
    || (e.end as number) <= (e.start as number) || !text(e.quote) || Array.from(e.quote).length < 12) throw new ConditionError("Invalid physical PDF page or evidence offsets.");
  }
  if (!c.observed_value_mentions.every(mention => (c.evidence as ConditionEvidence[]).some(e => e.quote.includes(mention))))
   throw new ConditionError("An observed value is absent from the supplied quotations.");
 }
 return data as unknown as ConditionExtractionResponse;
}
export type ConditionViewState = { phase: "idle" | "requesting" | "loading" | "ready" | "error"; identity: RunIdentity | null; job: JobResponse | null; run: ConditionExtractionResponse | null; error: string };
export class ConditionSession {
 private state: ConditionViewState = { phase: "idle", identity: null, job: null, run: null, error: "" };
 private listeners = new Set<() => void>();
 private operation?: AbortController;
 private revision = 0;
 constructor(private client: ConditionClient) {}
 getSnapshot = () => this.state;
 subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
 private publish(state: ConditionViewState) { this.state = state; this.listeners.forEach(fn => fn()); }
 cancel() { this.revision++; this.operation?.abort(); this.operation = undefined; }
 pause() {
  const starting = this.state.phase === "requesting";
  this.cancel();
  this.publish({ ...this.state, phase: starting ? "error" : "ready", error: starting ? "Local request stopped. Extraction acceptance is unconfirmed; check existing jobs before sending again." : "" });
 }
 dispose() { this.cancel(); this.listeners.clear(); }
 clear() { this.cancel(); this.publish({ phase: "idle", identity: null, job: null, run: null, error: "" }); }
 async extract(policyId: string, request: ConditionExtractionRequest) {
  if (this.operation) return; // Synchronous guard against duplicate extraction clicks.
  const controller = new AbortController(); this.operation = controller; const revision = ++this.revision;
  this.publish({ phase: "requesting", identity: null, job: null, run: null, error: "" });
  try {
   const receipt = await this.client.extract(policyId, request, controller.signal);
   if (revision !== this.revision) return;
   parseConditionReceipt(receipt, policyId, request.document_id);
   this.operation = undefined;
   await this.load({ policy_id: policyId, document_id: request.document_id, job_id: receipt.job_id });
  } catch (e) { if (revision === this.revision) this.fail(e); }
  finally { if (this.operation === controller) this.operation = undefined; }
 }
 private fail(error: unknown) {
  this.publish({ phase: "error", identity: this.state.identity, job: error instanceof ConditionError && [401, 403, 404].includes(error.status ?? 0) ? null : this.state.job, run: null, error: error instanceof ConditionError && error.status === 401
   ? "Sign-in is required. No condition results are displayed." : error instanceof ConditionError && (error.status === 403 || error.status === 404)
   ? "This run is unavailable or you do not have access. No condition results are displayed." : error instanceof Error ? error.message : "Condition results are unavailable." });
 }
 async load(identity: RunIdentity) {
  this.cancel(); const revision = this.revision; const controller = new AbortController(); this.operation = controller;
  this.publish({ phase: "loading", identity, job: null, run: null, error: "" });
  try {
   if (![identity.policy_id, identity.document_id, identity.job_id].every(text)) throw new ConditionError("Select an explicit policy, document and job_id.");
   const job = await this.client.getJob(identity, controller.signal);
   if (revision !== this.revision || controller.signal.aborted) return;
   if (job.job_id !== identity.job_id || job.policy_id !== identity.policy_id) throw new ConditionError("Stale or mismatched job status.");
   this.publish({ phase: job.status === "queued" || job.status === "processing" ? "ready" : "loading", identity, job, run: null, error: "" });
   if (job.status === "queued" || job.status === "processing") return;
   // The explicitly selected run may be re-read; GETs never restart extraction.
   const run = parseConditionRun(await this.client.getRun(identity, controller.signal), identity);
   if (revision === this.revision && !controller.signal.aborted) this.publish({ phase: "ready", identity, job, run, error: "" });
  } catch (e) { if (revision === this.revision && !controller.signal.aborted) this.fail(e); }
  finally { if (this.operation === controller) this.operation = undefined; }
 }
}
