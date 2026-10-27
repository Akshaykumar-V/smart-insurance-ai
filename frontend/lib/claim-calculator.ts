import { reportAvailability, sourceReference, type Finding, type FindingsResponse, type PolicyDetails } from "./policy-intelligence";

// Frontend-only, hypothetical model authorized for milestone 4. Not an API DTO.
export type ModelSelection = "combined" | "co_payment" | "sub_limit";
export interface ClaimScenario {
  hospitalBillPaise: number | null;
  admissiblePaise: number | null;
  treatmentEligiblePaise: number | null;
  treatment: string;
  age: number | null;
  model: ModelSelection;
  confirmedFindingIds: string[];
  scopeAcknowledged: boolean;
}
export interface RuleDecision {
  findingId: string;
  title: string;
  kind: "co_payment" | "sub_limit";
  outcome: "applied" | "not_applicable";
  reason: string;
  source: NonNullable<Finding["source"]>;
}
export interface ClaimBreakdown {
  hospitalBillPaise: number;
  admissiblePaise: number;
  outsideAdmissiblePaise: number;
  aboveSubLimitPaise: number;
  afterSubLimitPaise: number;
  copaymentPaise: number;
  modeledInsurerPaise: number;
  modeledPatientPaise: number;
  copaymentPercent: number | null;
  treatmentCapPaise: number | null;
  treatmentEligiblePaise: number | null;
}
export type ClaimCalculation =
  | { status: "incomplete" | "invalid" | "insufficient_evidence"; issues: string[]; warnings: string[]; breakdown: null; decisions: RuleDecision[] }
  | { status: "illustrative"; issues: []; warnings: string[]; breakdown: ClaimBreakdown; decisions: RuleDecision[] };

const modelingWarnings = [
  "These are shares under the selected rules only, not a full claim payout estimate or approval.",
  "Deductibles, waiting periods, exclusions, room-rent adjustments, remaining cover, endorsements and other limits are not modeled.",
  "The bill minus your admissible estimate is an assumed non-admissible portion, not an insurer-confirmed exclusion.",
];
const money = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const ageValue = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const normalize = (value: string) => value.trim().toLowerCase();

// Exact decimal conversion. No parseFloat multiplication or hidden bill-to-admissible fallback.
export function parseInr(raw: string): { value: number | null; error?: string } {
  const input = raw.trim();
  if (!input) return { value: null };
  const [whole, fraction = "", ...extra] = input.split(".");
  const plain = /^\d+$/.test(whole);
  const grouped = /^\d{1,3}(,\d{3})+$/.test(whole) || /^\d{1,2}(,\d{2})*,\d{3}$/.test(whole);
  if ((!plain && !grouped) || extra.length || !/^\d{0,2}$/.test(fraction) || input.endsWith(".")) {
    return { value: null, error: "Enter a non-negative INR amount with up to two decimal places." };
  }
  const digits = whole.replaceAll(",", "").replace(/^0+(?=\d)/, "");
  if (digits.length > 14) return { value: null, error: "This amount is too large to model safely." };
  const paise = BigInt(digits) * BigInt(100) + BigInt(fraction.padEnd(2, "0"));
  if (paise > BigInt(Number.MAX_SAFE_INTEGER)) return { value: null, error: "This amount is too large to model safely." };
  return { value: Number(paise) };
}

function percentageUnits(percent: unknown): number | null {
  if (typeof percent !== "number" || !Number.isFinite(percent) || percent < 0 || percent > 100 || !/^\d+(\.\d{1,2})?$/.test(String(percent))) return null;
  const [whole, decimals = ""] = String(percent).split(".");
  return Number(whole) * 100 + Number(decimals.padEnd(2, "0"));
}

export function roundedPercentage(basePaise: number, percent: number): number {
  const units = percentageUnits(percent);
  if (!money(basePaise) || units === null) throw new Error("Invalid percentage calculation inputs.");
  // Round half-up once, to the nearest paise. BigInt avoids intermediate overflow.
  return Number((BigInt(basePaise) * BigInt(units) + BigInt(5000)) / BigInt(10000));
}

function supportedRule(finding: Finding): string | null {
  const rule = finding.rule;
  if (!rule) return "No structured numeric rule was returned.";
  if (finding.condition_type === "co_payment") {
    const allowed = ["percent", "basis", "minimum_age", "application_order"];
    if (Object.keys(rule).some(key => !allowed.includes(key))) return "The co-payment has additional conditions this model cannot interpret.";
    if (percentageUnits(rule.percent) === null) return "A valid co-payment percentage with at most two decimal places is required.";
    if (rule.basis !== "admissible_expenses") return "The co-payment expense base is unsupported or unknown.";
    if (rule.minimum_age !== undefined && !ageValue(rule.minimum_age)) return "The age condition is invalid.";
    if (rule.application_order !== undefined && rule.application_order !== "after_sub_limits") return "The co-payment calculation order is unsupported.";
  } else {
    const allowed = ["amount_paise", "basis", "treatment_label", "limit_scope"];
    if (Object.keys(rule).some(key => !allowed.includes(key))) return "The sub-limit has additional conditions this model cannot interpret.";
    if (!money(rule.amount_paise)) return "A valid sub-limit amount in integer paise is required.";
    if (rule.basis !== "eligible_treatment_expenses" || rule.limit_scope !== "per_hospitalization") return "Only an eligible-treatment expense cap per hospitalization can be modeled.";
    if (typeof rule.treatment_label !== "string" || !rule.treatment_label.trim()) return "The treatment scope of this sub-limit is unknown.";
  }
  return null;
}

export function ruleReadiness(finding: Finding, policy: PolicyDetails): string | null {
  if (!["co_payment", "sub_limit"].includes(finding.condition_type)) return "This condition is outside the model.";
  if (finding.status !== "found" || finding.verification_status !== "verified") return "Missing, uncertain or conflicting rule evidence cannot be overridden by a scenario assumption.";
  const reference = sourceReference(finding, policy.documents);
  if (!reference.available) return reference.reason;
  if (!Number.isSafeInteger(reference.source.page) || reference.source.page < 1 || !reference.source.quote.trim() || reference.document.page_count === null) return "A valid quoted source and known PDF page range are required.";
  if (!finding.applicability?.trim()) return "The rule's applicability has not been described.";
  return supportedRule(finding);
}

export function calculateClaimImpact(policy: PolicyDetails, report: FindingsResponse, scenario: ClaimScenario): ClaimCalculation {
  const warnings = [...modelingWarnings];
  const decisions: RuleDecision[] = [];
  const stop = (status: "incomplete" | "invalid" | "insufficient_evidence", issues: string[]): ClaimCalculation => ({ status, issues, warnings, breakdown: null, decisions });
  if (report.policy_id !== policy.id) return stop("insufficient_evidence", ["Findings do not belong to the selected policy."]);
  if (!reportAvailability(policy).available) return stop("insufficient_evidence", [reportAvailability(policy).message]);
  if (!["combined", "co_payment", "sub_limit"].includes(scenario.model)) return stop("invalid", ["Choose a supported model."]);
  const amounts = [scenario.hospitalBillPaise, scenario.admissiblePaise, scenario.treatmentEligiblePaise];
  if (amounts.some(value => value !== null && !money(value))) return stop("invalid", ["Amounts must be non-negative, safe integer paise."]);
  if (scenario.age !== null && !ageValue(scenario.age)) return stop("invalid", ["Age must be a non-negative whole number."]);
  if (scenario.hospitalBillPaise === null || scenario.admissiblePaise === null) return stop("incomplete", ["Enter both a hospital bill and a separate admissible-expense estimate. The bill is never assumed to be fully admissible."]);
  const bill = scenario.hospitalBillPaise;
  const admissible = scenario.admissiblePaise;
  if (admissible > bill) return stop("invalid", ["Estimated admissible expenses cannot exceed the hospital bill."]);
  if (scenario.treatmentEligiblePaise !== null && scenario.treatmentEligiblePaise > admissible) return stop("invalid", ["Eligible treatment expenses must be a portion of the estimated admissible expenses, not an additional amount."]);
  if (!scenario.treatment.trim()) return stop("incomplete", ["Choose a hypothetical treatment category."]);
  if (!scenario.scopeAcknowledged) return stop("incomplete", ["Acknowledge that this model leaves other policy terms unresolved and does not estimate a complete claim payout."]);

  const kinds = scenario.model === "combined" ? ["sub_limit", "co_payment"] as const : [scenario.model];
  const chosen: Finding[] = [];
  for (const kind of kinds) {
    const candidates = report.findings.filter(item => item.condition_type === kind);
    if (candidates.length !== 1) return stop("insufficient_evidence", [`${kind === "co_payment" ? "Co-payment" : "Sub-limit"}: exactly one unambiguous finding is required. Missing findings do not mean there is no condition.`]);
    const finding = candidates[0];
    const problem = ruleReadiness(finding, policy);
    if (problem) return stop("insufficient_evidence", [`${finding.title}: ${problem}`]);
    chosen.push(finding);
  }
  if (new Set(chosen.map(item => item.id)).size !== chosen.length) return stop("insufficient_evidence", ["Finding identifiers are ambiguous."]);
  const unresolved = report.findings.filter(item => !chosen.includes(item));
  if (unresolved.length) warnings.push(`Outside this model: ${unresolved.map(item => item.title).join("; ")}. Their absence from the calculation does not resolve them.`);

  let aboveLimit = 0;
  let percent: number | null = null;
  let cap: number | null = null;
  let copayment = 0;
  let eligible: number | null = null;
  for (const finding of chosen) {
    const rule = finding.rule!;
    const kind = finding.condition_type as "co_payment" | "sub_limit";
    let applies: boolean;
    let reason: string;
    if (kind === "sub_limit") {
      applies = normalize(scenario.treatment) === normalize(rule.treatment_label as string);
      reason = applies ? "The selected treatment matches the rule. Only its eligible expense portion is capped." : "The selected treatment does not match this rule's treatment category; this specific cap was not applied.";
    } else {
      if (rule.minimum_age !== undefined && scenario.age === null) return stop("incomplete", ["Enter the applicable age to evaluate this age-linked co-payment."]);
      applies = rule.minimum_age === undefined || scenario.age! >= (rule.minimum_age as number);
      reason = applies ? "The supplied age satisfies the modeled condition. Co-payment uses admissible expenses after the modeled sub-limit." : "The supplied age is below this rule's minimum age; this specific co-payment was not applied.";
    }
    if (applies) {
      if (!scenario.confirmedFindingIds.includes(finding.id)) return stop("incomplete", [`Confirm the hypothetical applicability and exception assumption for: ${finding.title}.`]);
      if (finding.review_required) warnings.push(`${finding.title} remains flagged for review. Its applicability is only a user-confirmed hypothetical assumption.`);
      if (kind === "sub_limit") {
        if (scenario.treatmentEligiblePaise === null) return stop("incomplete", ["Enter the eligible expenses for the matching treatment. Do not substitute the entire bill."]);
        eligible = scenario.treatmentEligiblePaise;
        cap = rule.amount_paise as number;
        aboveLimit = Math.max(0, eligible - cap);
      } else {
        if (chosen.some(item => item.condition_type === "sub_limit") && rule.application_order !== "after_sub_limits") return stop("insufficient_evidence", ["The co-payment/sub-limit order is not established; the model will not guess an order."]);
        percent = rule.percent as number;
        copayment = roundedPercentage(admissible - aboveLimit, percent);
      }
    }
    decisions.push({ findingId: finding.id, title: finding.title, kind, outcome: applies ? "applied" : "not_applicable", reason, source: finding.source! });
  }
  const afterLimit = admissible - aboveLimit;
  const outside = bill - admissible;
  const insurer = afterLimit - copayment;
  const patient = outside + aboveLimit + copayment;
  return { status: "illustrative", issues: [], warnings, decisions, breakdown: {
    hospitalBillPaise: bill, admissiblePaise: admissible, outsideAdmissiblePaise: outside,
    aboveSubLimitPaise: aboveLimit, afterSubLimitPaise: afterLimit, copaymentPaise: copayment,
    modeledInsurerPaise: insurer, modeledPatientPaise: patient, copaymentPercent: percent,
    treatmentCapPaise: cap, treatmentEligiblePaise: eligible,
  } };
}
