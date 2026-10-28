import { mockPolicies } from "./mock-policies";
import { parsePolicyList, type PolicyList } from "./policies";
import { PolicyDataError } from "./policy-intelligence";
import { createPolicyReader } from "./policy-request";
export interface WalletClient { listPolicies(signal?: AbortSignal): Promise<PolicyList> }
export const mockWalletClient: WalletClient = {
 async listPolicies(signal) {
  await new Promise<void>((resolve, reject) => {
   if (signal?.aborted) { reject(new DOMException("Aborted", "AbortError")); return; }
   const abort = () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); };
   const timer = setTimeout(() => { signal?.removeEventListener("abort", abort); resolve(); }, 350);
   signal?.addEventListener("abort", abort, { once: true });
  });
  return parsePolicyList(structuredClone(mockPolicies));
 }
};
// Explicit opt-in for integration; the demo never sends network requests.
// baseUrl is the FastAPI origin. Obtain the token through Supabase Auth.
export function createApiWalletClient(baseUrl: string, getAccessToken: () => Promise<string>): WalletClient {
 const request = createPolicyReader(baseUrl, getAccessToken);
 return { async listPolicies(signal = new AbortController().signal) {
  const data = await request("/api/v1/policies", signal);
  try { return parsePolicyList(data); }
  catch (error) {
   if (error instanceof PolicyDataError) throw error;
   throw new PolicyDataError("The service returned invalid policy data.");
  }
 } };
}
