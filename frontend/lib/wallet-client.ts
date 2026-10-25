import { mockPolicies } from "./mock-policies";
import { parsePolicyList, type PolicyList } from "./policies";
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
 return { async listPolicies(signal) {
  const token = await getAccessToken();
  if (!token) throw new Error("Sign in to view your policies.");
  const response = await fetch(`${baseUrl.replace(/\/$/, "")}/api/v1/policies`, { headers: { Authorization: `Bearer ${token}` }, signal, cache: "no-store" });
  if (!response.ok) throw new Error(response.status === 401 ? "Your session has expired. Sign in again." : response.status === 403 ? "You do not have access to these policies." : "We could not load your policies. Please try again.");
  return parsePolicyList(await response.json());
 } };
}
