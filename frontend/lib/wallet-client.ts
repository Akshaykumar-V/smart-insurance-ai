import { mockPolicies } from "./mock-policies";
import { parsePolicyList, type PolicyList } from "./policies";
import { PolicyDataError } from "./policy-intelligence";
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
  if (!token) throw new PolicyDataError("Sign in to view your policies.", 401);
  try {
   const response = await fetch(`${baseUrl.replace(/\/$/, "")}/api/v1/policies`, { headers: { Authorization: `Bearer ${token}` }, signal, cache: "no-store" });
   if (!response.ok) {
    const messages: Record<number, string> = {
     401: "Your session has expired. Sign in again to view your policies.",
     403: "You do not have access to these policies.",
     429: "The policy service is busy. Please try again shortly.",
    };
    throw new PolicyDataError(messages[response.status] ?? "We could not load your policies. Please try again.", response.status);
   }
   if (response.status !== 200) throw new PolicyDataError("The service returned an unexpected response status.");
   try { return parsePolicyList(await response.json()); }
   catch (error) {
    if (error instanceof PolicyDataError) throw error;
    throw new PolicyDataError("The service returned invalid policy data.");
   }
  } catch (error) {
   if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
   if (error instanceof PolicyDataError) throw error;
   throw new PolicyDataError("The policy service could not be reached. Please try again.");
  }
 } };
}
