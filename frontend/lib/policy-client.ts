import { abortableDelay } from "./upload-contract";
import { mockFamilyReport, mockPolicyDetails } from "./mock-intelligence";
import { parseFindings, parsePolicyDetails, PolicyDataError, type FindingsResponse, type PolicyDetails } from "./policy-intelligence";

export interface PolicyClient {
  readonly mode: "mock" | "api";
  getPolicy(policyId: string, signal: AbortSignal): Promise<PolicyDetails>;
  getFindings(policyId: string, signal: AbortSignal): Promise<FindingsResponse>;
}

export const mockPolicyClient: PolicyClient = {
  mode: "mock",
  async getPolicy(policyId, signal) {
    await abortableDelay(300, signal);
    const policy = mockPolicyDetails.find(item => item.id === policyId);
    if (!policy) throw new PolicyDataError("This policy was not found in the fictional demo collection.", 404);
    return parsePolicyDetails(structuredClone(policy), policyId);
  },
  async getFindings(policyId, signal) {
    await abortableDelay(300, signal);
    if (!mockPolicyDetails.some(item => item.id === policyId)) throw new PolicyDataError("This demo policy was not found.", 404);
    const response = policyId === mockFamilyReport.policy_id ? mockFamilyReport : { policy_id: policyId, analysis_version: "v0.1-fictional-ui", findings: [] };
    return parseFindings(structuredClone(response), policyId);
  },
};

// No authentication UI is implemented here. The integration owner provides a token.
export function createApiPolicyClient(baseUrl: string, getAccessToken: () => Promise<string>): PolicyClient {
  const origin = baseUrl.replace(/\/$/, "");
  async function request(path: string, signal: AbortSignal): Promise<unknown> {
    signal.throwIfAborted();
    const token = await getAccessToken();
    signal.throwIfAborted();
    if (!token) throw new PolicyDataError("Sign in is required to view this policy.", 401);
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal.addEventListener("abort", abort, { once: true });
    const timeout = setTimeout(abort, 30_000);
    try {
      const response = await fetch(`${origin}${path}`, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal, cache: "no-store" });
      if (!response.ok) {
        const messages: Record<number, string> = {
          401: "Your session has expired. Sign in again to view this policy.",
          403: "You do not have permission to view this policy or its findings.",
          404: "This policy or report could not be found.",
          429: "The policy service is busy. Please try again shortly.",
        };
        throw new PolicyDataError(messages[response.status] ?? "The policy service is unavailable. Please try again.", response.status);
      }
      if (response.status !== 200) throw new PolicyDataError("The service returned an unexpected response status.");
      try { return await response.json(); }
      catch { throw new PolicyDataError("The service returned unreadable policy data."); }
    } catch (error) {
      if (signal.aborted) throw new DOMException("Aborted", "AbortError");
      if (error instanceof PolicyDataError) throw error;
      throw new PolicyDataError("The request timed out or the connection was interrupted. Please try again.");
    } finally {
      clearTimeout(timeout);
      signal.removeEventListener("abort", abort);
    }
  }
  return {
    mode: "api",
    async getPolicy(id, signal) { return parsePolicyDetails(await request(`/api/v1/policies/${encodeURIComponent(id)}`, signal), id); },
    async getFindings(id, signal) { return parseFindings(await request(`/api/v1/policies/${encodeURIComponent(id)}/findings`, signal), id); },
  };
}
