import type { Finding, FindingsResponse, PolicyDetails } from "./policy-intelligence";
import { mockPolicies } from "./mock-policies";

// Fictional UI fixtures. Document names, page numbers, quotes and verification states
// are illustrative references, not claims about actual files or completed AI analysis.
export const mockPolicyDetails: PolicyDetails[] = mockPolicies.items.map(policy => {
  const details: PolicyDetails = { ...policy, uin: null, policyholder_name: null, insured_members: [], documents: [] };
  if (policy.id === "demo-health-family") return { ...details,
    policyholder_name: "Maya Demo",
    insured_members: [{ name: "Maya Demo", age: 34 }, { name: "Arun Demo", age: null }],
    documents: [
      { id: "fixture-family-wording", type: "policy_wording" as const, name: "fictional-family-wording.pdf", page_count: 14, processing_status: "indexed" },
      { id: "fixture-family-schedule", type: "policy_schedule" as const, name: "fictional-family-schedule.pdf", page_count: 2, processing_status: "needs_review" },
    ],
  };
  if (policy.id === "demo-health-individual") return { ...details,
    documents: [{ id: "fixture-individual-wording", type: "policy_wording" as const, name: "fictional-individual-wording.pdf", page_count: null, processing_status: "extracting" }],
  };
  return details;
});

const base: Omit<Finding, "id" | "condition_type" | "title" | "explanation"> = {
  status: "found", verification_status: "needs_review", rule: null, applicability: null,
  exceptions: [], source: null, review_required: true,
};
export const mockFamilyReport: FindingsResponse = {
  policy_id: "demo-health-family", analysis_version: "v0.1-fictional-ui",
  findings: [
    {
      ...base, id: "fixture-waiting", condition_type: "waiting_period", title: "Waiting period depends on the condition",
      explanation: "This fictional example describes a waiting-period condition. The relevant condition and continuity of cover would need to be established before applying it.",
      verification_status: "verified", review_required: false,
      applicability: "Depends on the condition, policy start date and continuity information. No hospitalization scenario has been supplied.",
      exceptions: ["The fictional example distinguishes accident-related treatment; that exception must be checked against the full wording."],
      source: { document_id: "fixture-family-wording", page: 4, quote: "Fictional UI fixture: specified waiting-period terms apply to the listed conditions, subject to the accident-related exception." },
    },
    {
      ...base, id: "fixture-exclusions", condition_type: "exclusion", title: "No exclusion surfaced in the example search",
      status: "not_found_after_search", verification_status: "insufficient_evidence",
      explanation: "The fictional search result did not return an exclusion clause. This is a search limitation, not a statement that treatment is covered.",
    },
    {
      ...base, id: "fixture-copay", condition_type: "co_payment", title: "Member-linked co-payment needs context",
      explanation: "In this fictional example, a 20% contribution is modeled for a member aged 60 or above, using admissible expenses after the treatment sub-limit. Member and exception applicability still need a hypothetical scenario confirmation.",
      verification_status: "verified",
      rule: { percent: 20, basis: "admissible_expenses", minimum_age: 60, application_order: "after_sub_limits" },
      applicability: "For an insured member aged at least 60, only on admissible expenses remaining after the applicable per-hospitalization treatment cap. Schedule and exception applicability remain to be checked.",
      source: { document_id: "fixture-family-wording", page: 6, quote: "Fictional UI fixture: a 20% co-payment applies for members aged 60 or above to admissible expenses remaining after applicable per-hospitalization treatment sub-limits, subject to the governing schedule and exceptions." },
    },
    {
      ...base, id: "fixture-deductible", condition_type: "deductible", title: "Deductible references need reconciliation",
      status: "uncertain", verification_status: "conflicting",
      explanation: "This fixture represents conflicting deductible information between document versions. The governing schedule and endorsements have not been resolved.",
      applicability: "Unresolved until the applicable document version and deductible basis are confirmed.",
      source: { document_id: "fixture-family-wording", page: 7, quote: "Fictional UI fixture: the deductible, if applicable, is specified in the governing policy schedule." },
    },
    {
      ...base, id: "fixture-sublimit", condition_type: "sub_limit", title: "Fictional cataract expense cap",
      verification_status: "verified", review_required: false,
      explanation: "This fictional cap limits eligible cataract expenses to INR 50,000 per hospitalization, before applying the modeled co-payment. It does not cap unrelated admissible expenses.",
      rule: { amount_paise: 5000000, basis: "eligible_treatment_expenses", treatment_label: "Cataract", limit_scope: "per_hospitalization" },
      applicability: "Only eligible cataract expense amounts within one hypothetical hospitalization. The amount must already be included in estimated admissible expenses; scope and exceptions need confirmation.",
      source: { document_id: "fixture-family-wording", page: 8, quote: "Fictional UI fixture: eligible cataract treatment expenses are capped at INR 50,000 per hospitalization, before co-payment. This cap does not apply to other treatment categories and remains subject to the governing exceptions." },
    },
    {
      ...base, id: "fixture-room", condition_type: "room_rent", title: "Room eligibility refers to the schedule",
      explanation: "This example links room eligibility to schedule terms. It does not establish any reduction to a hospital bill.",
      applicability: "Requires the applicable schedule, room category and full restriction wording.",
      exceptions: ["An endorsement may alter room eligibility; no applicable endorsement has been confirmed."],
      source: { document_id: "fixture-family-wording", page: 9, quote: "Fictional UI fixture: eligible room category is as recorded in the policy schedule, subject to applicable endorsements." },
    },
  ],
};
