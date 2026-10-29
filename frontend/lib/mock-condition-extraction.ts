import { abortableDelay } from "./upload-contract";
import { ConditionError, type ConditionClient, type ConditionExtractionResponse, type ExtractedCondition, type RunIdentity } from "./condition-extraction";
export const demoPolicyId = "10000000-0000-0000-0000-000000000001";
export const demoDocumentId = "20000000-0000-0000-0000-000000000001";
export const demoJobs = ["success", "incomplete", "failure", "empty", "unauthorized", "stale"] as const;
export type DemoConditionJob = typeof demoJobs[number];
export const demoJobId = (name: string) => { const index = demoJobs.indexOf(name as DemoConditionJob); return index < 0 ? `demo-${name}` : `30000000-0000-0000-0000-${String(index + 1).padStart(12, "0")}`; };
const rows = [
 ["co_payment", "Co-payment", "A 10% contribution applies to eligible expenses.", "10%"],
 ["deductible", "Deductible", "An annual deductible of INR 5,000 applies.", "INR 5,000"],
 ["sub_limit", "Treatment sub-limit", "The listed treatment has a limit of INR 25,000.", "INR 25,000"],
 ["room_rent", "Room-rent restriction", "Room eligibility is a single private room.", "single private room"],
 ["waiting_period", "Waiting period", "The listed condition has a waiting period of 24 months.", "24 months"],
 ["exclusion", "Exclusion", "Cosmetic treatment is excluded except after an accident.", "Cosmetic treatment"],
] as const;
export function conditionFixture(identity: RunIdentity, scenario: DemoConditionJob): ConditionExtractionResponse {
 const failed = scenario === "failure";
 const incomplete = scenario === "incomplete" || scenario === "empty";
 const conditions: ExtractedCondition[] = rows.map(([category, title, quote, value], index) => ({
  id: `condition_${index.toString(16).padStart(20, "0")}`, document_id: identity.document_id, job_id: identity.job_id,
  category, kind: "condition", title, specific_label: null, observed_value_mentions: [value],
  applicability: "Fictional wording only; personal applicability is not established.",
  exceptions: category === "exclusion" ? ["Except after an accident."] : [],
  dependencies: [{ kind: "policy_schedule", label: "Confirm the policy schedule and relevant definitions." }],
  evidence: [{ passage_id: `fictional-passage-${index}`, page: index + 1, start: 0, end: Array.from(quote).length, quote }],
  source_verified: true, review_required: true,
 }));
 return { ...identity, status: failed ? "failed" : incomplete ? "needs_review" : "completed",
  analysis_state: failed ? null : incomplete ? "incomplete" : "complete",
  warning: failed ? "Fictional extraction failed. Results are unavailable." : incomplete ? "Analysis is incomplete; planned passages could not all be processed. Review is required." : null,
  rejected_candidate_count: scenario === "incomplete" ? 2 : 0,
  conditions: failed || scenario === "empty" ? [] : incomplete ? conditions.slice(0, 2) : conditions };
}
// Entirely local: no fetch, uploads, model calls or browser credentials.
export function createMockConditionClient(scenario: DemoConditionJob = "success", delayMs = 400): ConditionClient {
 const reads = new Map<string, number>();
 return { mode: "mock",
  async extract(policyId, request, signal) {
   await abortableDelay(delayMs, signal);
   if (scenario === "unauthorized") throw new ConditionError("Unauthorized", 401);
   return { policy_id: policyId, document_id: request.document_id, job_id: demoJobId(scenario), status: "queued" };
  },
  async getJob(identity, signal) {
   await abortableDelay(delayMs, signal);
   const key = demoJobs.find(name => demoJobId(name) === identity.job_id);
   if (!key || identity.policy_id !== demoPolicyId || identity.document_id !== demoDocumentId) throw new ConditionError("Not found", 404);
   if (key === "unauthorized") throw new ConditionError("Unauthorized", 401);
   const count = reads.get(identity.job_id) ?? 0; reads.set(identity.job_id, count + 1);
   const status = key === "stale" ? "completed" : count < 2 ? count ? "processing" : "queued" : conditionFixture(identity, key).status;
   return { policy_id: identity.policy_id, job_id: identity.job_id, status, stage: "analyzing", message: status === "processing" ? "Fictional job processing." : null, error: null };
  },
  async getRun(identity, signal) {
   await abortableDelay(delayMs, signal);
   const key = demoJobs.find(name => demoJobId(name) === identity.job_id);
   if (!key || identity.policy_id !== demoPolicyId || identity.document_id !== demoDocumentId) throw new ConditionError("Not found", 404);
   if (key === "unauthorized") throw new ConditionError("Unauthorized", 401);
   if (key === "stale") return conditionFixture({ ...identity, job_id: "another-job" }, "success");
   return conditionFixture(identity, key);
  },
 };
}
