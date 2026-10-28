import type { ConditionType, Finding, FindingsResponse, PolicyDetails, PolicyDocument } from "../../frontend_api_types";
import { parsePolicyList } from "./policies";

export type { Finding, FindingsResponse, PolicyDetails, PolicyDocument };

export const conditionGroups: { type: ConditionType; label: string; description: string }[] = [
  { type: "waiting_period", label: "Waiting periods", description: "When a condition may become eligible for consideration." },
  { type: "exclusion", label: "Exclusions", description: "Restrictions that need to be read with their definitions and exceptions." },
  { type: "co_payment", label: "Co-payments", description: "Circumstances where a customer contribution may apply." },
  { type: "deductible", label: "Deductibles", description: "Amounts or thresholds that need confirmation from your documents." },
  { type: "sub_limit", label: "Treatment-specific sub-limits", description: "Limits tied to particular treatments, expenses or benefits." },
  { type: "room_rent", label: "Room-rent restrictions", description: "Room eligibility and associated conditions, where evidenced." },
];

export const findingStatusLabels: Record<Finding["status"], string> = {
  found: "Condition found",
  not_found_after_search: "Not found after search",
  uncertain: "Uncertain interpretation",
  not_applicable: "Reported not applicable",
};
export const verificationLabels: Record<Finding["verification_status"], string> = {
  verified: "Source checked by app",
  needs_review: "Needs review",
  insufficient_evidence: "Insufficient evidence",
  conflicting: "Conflicting evidence",
};
export const analysisLabels: Record<PolicyDetails["analysis_status"], string> = {
  ready: "Analysis available", needs_review: "Review required", processing: "Processing documents",
  failed: "Processing failed", not_started: "Not analyzed", unsupported: "Wallet only",
};
export const policyTypeLabels: Record<PolicyDetails["policy_type"], string> = {
  individual: "Individual", family_floater: "Family floater", other: "Other", unknown: "Not available",
};

export class PolicyDataError extends Error {
  constructor(message: string, readonly status?: number) { super(message); this.name = "PolicyDataError"; }
}
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new PolicyDataError("The policy service returned invalid data.");
  return value as Record<string, unknown>;
}
function text(value: unknown): value is string { return typeof value === "string" && !!value.trim(); }
function nullableText(value: unknown) { return value === null || typeof value === "string"; }
function positiveInteger(value: unknown) { return typeof value === "number" && Number.isSafeInteger(value) && value > 0; }
function uniqueIds(items: { id: string }[]) { return new Set(items.map(item => item.id)).size === items.length; }

export function parsePolicyDetails(value: unknown, expectedId: string): PolicyDetails {
  const data = record(value);
  parsePolicyList({ items: [data], next_cursor: null });
  if (data.id !== expectedId) throw new PolicyDataError("The response belongs to a different policy.");
  if (!nullableText(data.uin) || !nullableText(data.policyholder_name) || !Array.isArray(data.insured_members) || !Array.isArray(data.documents)) {
    throw new PolicyDataError("Policy details did not match API contract v0.1.");
  }
  for (const value of data.insured_members) {
    const member = record(value);
    if (!nullableText(member.name) || !(member.age === null || (typeof member.age === "number" && Number.isSafeInteger(member.age) && member.age >= 0))) {
      throw new PolicyDataError("Insured member details are invalid.");
    }
  }
  for (const value of data.documents) {
    const doc = record(value);
    if (!text(doc.id) || !text(doc.name) || !["policy_wording", "policy_schedule", "cis", "endorsement", "other"].includes(doc.type as string)
      || !(doc.page_count === null || positiveInteger(doc.page_count)) || !text(doc.processing_status)) {
      throw new PolicyDataError("Document details are invalid.");
    }
  }
  if (!uniqueIds(data.documents as PolicyDocument[])) throw new PolicyDataError("Document references are ambiguous.");
  return data as unknown as PolicyDetails;
}

export function parseFindings(value: unknown, expectedId: string): FindingsResponse {
  const data = record(value);
  if (data.policy_id !== expectedId) throw new PolicyDataError("The report belongs to a different policy.");
  if (!text(data.analysis_version) || !Array.isArray(data.findings)) throw new PolicyDataError("The findings response is invalid.");
  for (const value of data.findings) {
    const finding = record(value);
    if (!text(finding.id) || !text(finding.title) || typeof finding.explanation !== "string"
      || !conditionGroups.some(group => group.type === finding.condition_type)
      || !Object.hasOwn(findingStatusLabels, finding.status as string)
      || !Object.hasOwn(verificationLabels, finding.verification_status as string)
      || !nullableText(finding.applicability) || typeof finding.review_required !== "boolean"
      || !Array.isArray(finding.exceptions) || !finding.exceptions.every(item => typeof item === "string")) {
      throw new PolicyDataError("A finding did not match API contract v0.1.");
    }
    if (finding.rule !== null) record(finding.rule); // Preserve unknown rule keys; never calculate from them.
    if (finding.source !== null) {
      const source = record(finding.source);
      if (!text(source.document_id) || !positiveInteger(source.page) || !text(source.quote)) {
        throw new PolicyDataError("A source reference is invalid. PDF pages must be positive, 1-indexed integers.");
      }
    }
  }
  if (!uniqueIds(data.findings as Finding[])) throw new PolicyDataError("Finding references are ambiguous.");
  return data as unknown as FindingsResponse;
}

export function reportAvailability(policy: PolicyDetails): { available: boolean; title: string; message: string } {
  if (policy.category !== "health" || policy.analysis_status === "unsupported") {
    return { available: false, title: "This policy is wallet-only", message: "Specialized analysis is unavailable for this policy. Advanced analysis supports only individual and family-floater indemnity health insurance." };
  }
  if (!["individual", "family_floater"].includes(policy.policy_type)) {
    return { available: false, title: "Analysis scope is not established", message: "The policy type is not confirmed as an individual or family-floater policy. No specialized findings are displayed." };
  }
  if (policy.analysis_status === "failed") return { available: false, title: "Document processing failed", message: "A usable report is not available. A readable policy document may be needed; failure does not determine coverage." };
  if (["processing", "not_started"].includes(policy.analysis_status)) return { available: false, title: policy.analysis_status === "processing" ? "Your report is still being prepared" : "Analysis has not started", message: "No completed report has been reported. Refresh the status to check again; missing findings do not establish coverage." };
  return { available: true, title: "Report available", message: "Read each finding with its applicability, exceptions and source evidence." };
}

// Reading persisted evidence does not establish eligibility for specialized analysis.
// Keep reportAvailability strict because the fictional calculator also uses it.
export function findingsAvailability(policy: PolicyDetails, mode: "mock" | "api"): { available: boolean; reviewOnly: boolean; title: string; message: string } {
  const eligibility = reportAvailability(policy);
  if (eligibility.available || mode !== "api") return { ...eligibility, reviewOnly: false };
  if (policy.category === "other" && policy.policy_type === "unknown" && policy.analysis_status === "needs_review") {
    return {
      available: true,
      reviewOnly: true,
      title: "Extracted evidence available for review",
      message: "Policy category and type are unconfirmed. Any extracted findings shown here need review and do not establish eligibility for specialized analysis.",
    };
  }
  return { ...eligibility, reviewOnly: false };
}

export function missingInformation(policy: PolicyDetails): string[] {
  const missing: string[] = [];
  if (!policy.documents.some(doc => doc.type === "policy_schedule")) missing.push("No policy schedule is attached. Personal cover details and applicability may remain unknown.");
  if (!policy.documents.some(doc => doc.type === "policy_wording")) missing.push("No policy wording document is attached. Conditions cannot be established from metadata alone.");
  if (policy.sum_insured_paise === null) missing.push("Sum insured is not available.");
  if (!policy.start_date || !policy.end_date) missing.push("The full policy period is not available; cover in force is not confirmed.");
  if (!policy.policyholder_name) missing.push("Policyholder details are not available.");
  if (!policy.insured_members.length) missing.push("Insured member information is not available.");
  else if (policy.insured_members.some(member => !member.name || member.age === null)) missing.push("Some insured member names or ages are missing. Age-based conditions cannot be assumed to apply.");
  if (policy.documents.some(doc => ["failed", "needs_review"].includes(doc.processing_status))) missing.push("One or more documents could not be fully processed or require review.");
  return missing;
}

export type SourceReference = { available: true; document: PolicyDocument; source: NonNullable<Finding["source"]> }
  | { available: false; reason: string };

export function sourceReference(finding: Finding, documents: PolicyDocument[]): SourceReference {
  if (!finding.source) return { available: false, reason: "No source quote or page was returned. This finding cannot be checked against a document here." };
  const document = documents.find(doc => doc.id === finding.source?.document_id);
  if (!document) return { available: false, reason: "The source document could not be matched to this policy. Its quote and page cannot be presented as linked evidence." };
  if (document.page_count !== null && finding.source.page > document.page_count) return { available: false, reason: "The source page is outside this document's reported page count. The reference needs review." };
  return { available: true, document, source: finding.source };
}

export function findingCautions(finding: Finding): string[] {
  const messages: string[] = [];
  if (finding.status === "not_found_after_search") messages.push("Not found in the searched material does not mean covered or free of this condition.");
  if (finding.status === "uncertain") messages.push("The interpretation is uncertain. Do not assume this condition applies or does not apply.");
  if (finding.status === "not_applicable") messages.push("Reported non-applicability is limited to the supplied context; it is not a coverage guarantee.");
  if (finding.verification_status === "conflicting") messages.push("The evidence conflicts. The applicable wording and document version need review before drawing a conclusion.");
  if (finding.verification_status === "insufficient_evidence") messages.push("There is insufficient evidence to establish this condition safely.");
  if (finding.verification_status === "needs_review") messages.push("This extracted finding needs review. Its wording and applicability have not been confirmed; do not treat it as a verified claim rule.");
  if (finding.review_required) messages.push("This finding is flagged for review, regardless of its source-check status.");
  return messages;
}
