import { createPolicyReader } from "./policy-request";
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

// The live session wrapper supplies the current authenticated token for each read.
export function createApiPolicyClient(baseUrl: string, getAccessToken: () => Promise<string>): PolicyClient {
  const request = createPolicyReader(baseUrl, getAccessToken);
  return {
    mode: "api",
    async getPolicy(id, signal) { return parsePolicyDetails(await request(`/api/v1/policies/${encodeURIComponent(id)}`, signal), id); },
    async getFindings(id, signal) { return parseFindings(await request(`/api/v1/policies/${encodeURIComponent(id)}/findings`, signal), id); },
  };
}
