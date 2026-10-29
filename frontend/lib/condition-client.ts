import { createPolicyTransport } from "./policy-request";
import { PolicyDataError } from "./policy-intelligence";
import { parseJobResponse, UploadError } from "./upload-contract";
import { ConditionError, parseConditionReceipt, parseConditionRun, type ConditionClient, type RunIdentity } from "./condition-extraction";
const uuid = (id: string) => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);
function validateIds(...ids: string[]) { if (!ids.every(uuid)) throw new ConditionError("Select valid policy, document and job UUIDs."); }
export function createApiConditionClient(baseUrl: string, getAccessToken: () => Promise<string>): ConditionClient {
 const request = createPolicyTransport(baseUrl, getAccessToken);
 async function safe<T>(run: () => Promise<T>): Promise<T> {
  try { return await run(); }
  catch (error) {
   if (error instanceof ConditionError || (error instanceof Error && error.name === "AbortError")) throw error;
   if (error instanceof PolicyDataError || error instanceof UploadError) throw new ConditionError(error.message, error.status);
   throw new ConditionError("The condition service could not be reached. Results are unavailable.");
  }
 }
 function scoped(identity: RunIdentity) { validateIds(identity.policy_id, identity.document_id, identity.job_id); }
 return { mode: "api",
  extract: (policyId, input, signal) => safe(async () => {
   validateIds(policyId, input.document_id);
   const data = await request(`/api/v1/policies/${encodeURIComponent(policyId)}/condition-extractions`, signal, { method: "POST", json: { document_id: input.document_id }, expectedStatus: 202 });
   const receipt = parseConditionReceipt(data, policyId, input.document_id);
   if (!uuid(receipt.job_id)) throw new ConditionError("Extraction acceptance could not be validated. Acceptance is unconfirmed; check existing jobs before sending again.");
   return receipt;
  }),
  getJob: (identity, signal) => safe(async () => {
   scoped(identity);
   const job = parseJobResponse(await request(`/api/v1/jobs/${encodeURIComponent(identity.job_id)}`, signal));
   if (job.job_id !== identity.job_id || job.policy_id !== identity.policy_id) throw new ConditionError("Stale or mismatched job status.");
   return job;
  }),
  getRun: (identity, signal) => safe(async () => {
   scoped(identity);
   return parseConditionRun(await request(`/api/v1/policies/${encodeURIComponent(identity.policy_id)}/conditions?job_id=${encodeURIComponent(identity.job_id)}`, signal), identity);
  }),
 };
}
