import type { SimulatorRequest, SimulatorResponse } from "../../frontend_api_types";
import { calculateClaimImpact, type ClaimCalculation, type ClaimScenario } from "./claim-calculator";
import { abortableDelay } from "./upload-contract";
import { PolicyDataError, type FindingsResponse, type PolicyDetails } from "./policy-intelligence";

export const localSimulationClient = {
  async simulate(policy: PolicyDetails, report: FindingsResponse, scenario: ClaimScenario, signal: AbortSignal): Promise<ClaimCalculation> {
    await abortableDelay(150, signal);
    return calculateClaimImpact(policy, report, scenario);
  },
};

// Live integration remains server-owned. Never send the frontend-only bill, model
// selection or acknowledgment fields as undocumented v0.1 request fields.
export function parseSimulatorResponse(value: unknown, policyId: string): SimulatorResponse {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new PolicyDataError("Invalid simulation response.");
  const data = value as Record<string, unknown>;
  if (data.policy_id !== policyId || !["illustrative", "partially_calculable", "insufficient_evidence"].includes(data.status as string)
    || !data.scenario || typeof data.scenario !== "object" || Array.isArray(data.scenario)
    || !Array.isArray(data.results) || !Array.isArray(data.missing_information) || !data.missing_information.every(item => typeof item === "string") || typeof data.disclaimer !== "string") throw new PolicyDataError("Simulation response did not match API contract v0.1.");
  const scenario = data.scenario as Record<string, unknown>;
  for (const key of ["insured_age", "estimated_admissible_expenses_paise", "room_rent_per_day_paise", "room_days"]) {
    const amount = scenario[key];
    if (amount !== undefined && amount !== null && !(typeof amount === "number" && Number.isSafeInteger(amount) && amount >= 0)) throw new PolicyDataError("Invalid returned scenario input.");
  }
  if (scenario.treatment_label !== undefined && scenario.treatment_label !== null && typeof scenario.treatment_label !== "string") throw new PolicyDataError("Invalid returned treatment.");
  for (const result of data.results) {
    if (!result || typeof result !== "object" || !["co_payment", "deductible", "sub_limit", "room_rent", "waiting_period", "exclusion"].includes(result.condition_type)
      || typeof result.finding_id !== "string" || !result.finding_id || typeof result.calculation !== "string"
      || !(result.customer_share_paise === null || (Number.isSafeInteger(result.customer_share_paise) && result.customer_share_paise >= 0))) throw new PolicyDataError("Invalid simulation result.");
  }
  return data as unknown as SimulatorResponse;
}

export function createApiSimulatorClient(baseUrl: string, getAccessToken: () => Promise<string>) {
  return { async simulate(policyId: string, input: SimulatorRequest, signal: AbortSignal): Promise<SimulatorResponse> {
    signal.throwIfAborted();
    const token = await getAccessToken();
    signal.throwIfAborted();
    if (!token) throw new PolicyDataError("Sign in is required to simulate a scenario.", 401);
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal.addEventListener("abort", abort, { once: true });
    const timer = setTimeout(abort, 30_000);
    try {
      const body: SimulatorRequest = {
        insured_age: input.insured_age, estimated_admissible_expenses_paise: input.estimated_admissible_expenses_paise,
        treatment_label: input.treatment_label, room_rent_per_day_paise: input.room_rent_per_day_paise, room_days: input.room_days,
      };
      const response = await fetch(`${baseUrl.replace(/\/$/, "")}/api/v1/policies/${encodeURIComponent(policyId)}/simulate`, {
        method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(body), signal: controller.signal, cache: "no-store",
      });
      if (!response.ok) {
        const messages: Record<number, string> = { 401: "Sign in again to continue.", 403: "You do not have permission to simulate this policy.", 404: "The policy was not found.", 422: "The server could not validate this scenario.", 429: "The service is busy. Try again shortly." };
        throw new PolicyDataError(messages[response.status] ?? "Simulation is unavailable. Please try again.", response.status);
      }
      if (response.status !== 200) throw new PolicyDataError("Unexpected simulation response status.");
      return parseSimulatorResponse(await response.json(), policyId);
    } catch (error) {
      if (signal.aborted) throw new DOMException("Aborted", "AbortError");
      if (error instanceof PolicyDataError) throw error;
      throw new PolicyDataError("Simulation could not be confirmed. The connection may have been interrupted.");
    } finally { clearTimeout(timer); signal.removeEventListener("abort", abort); }
  } };
}
