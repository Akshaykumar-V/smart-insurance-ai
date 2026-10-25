// Shared API types v0.1 for Laptop 2. Contract: API_CONTRACT.md
// Example types only; no runtime network calls or real data here.
export type InsuranceCategory = 'health' | 'life' | 'vehicle' | 'animal' | 'property' | 'other';
export type PolicyType = 'individual' | 'family_floater' | 'other' | 'unknown';
export type AnalysisStatus = 'not_started' | 'processing' | 'ready' | 'needs_review' | 'failed' | 'unsupported';
export type DocumentType = 'policy_wording' | 'policy_schedule' | 'cis' | 'endorsement' | 'other';
export type ConditionType = 'co_payment' | 'deductible' | 'sub_limit' | 'room_rent' | 'waiting_period' | 'exclusion';
export type FindingStatus = 'found' | 'not_found_after_search' | 'uncertain' | 'not_applicable';
export type VerificationStatus = 'verified' | 'needs_review' | 'insufficient_evidence' | 'conflicting';
export type JobStatus = 'queued' | 'processing' | 'completed' | 'failed' | 'needs_review';
export type JobStage = 'uploaded' | 'extracting' | 'classifying' | 'indexing' | 'retrieving' | 'analyzing' | 'verifying' | 'completed';

export interface PolicyCard {
  id: string; category: InsuranceCategory; policy_type: PolicyType;
  insurer: string | null; product_name: string | null;
  sum_insured_paise: number | null; start_date: string | null; end_date: string | null;
  analysis_status: AnalysisStatus; needs_review: boolean;
}
export interface PolicyDocument {
  id: string; type: DocumentType; name: string;
  page_count: number | null; processing_status: string;
}
export interface PolicyDetails extends PolicyCard {
  uin: string | null; policyholder_name: string | null;
  insured_members: Array<{ name: string | null; age: number | null }>;
  documents: PolicyDocument[];
}
export interface UploadResponse { policy_id: string; document_id: string; job_id: string; status: 'queued'; }
export interface JobResponse {
  job_id: string; policy_id: string; status: JobStatus;
  stage: JobStage; message: string | null;
  error: { code: string; message: string } | null;
}
export interface Finding {
  id: string; condition_type: ConditionType; status: FindingStatus;
  verification_status: VerificationStatus; title: string; explanation: string;
  rule: Record<string, unknown> | null; applicability: string | null;
  exceptions: string[];
  source: { document_id: string; page: number; quote: string } | null;
  review_required: boolean;
}
export interface FindingsResponse { policy_id: string; analysis_version: string; findings: Finding[]; }
export interface SimulatorRequest {
  insured_age: number | null; estimated_admissible_expenses_paise: number | null;
  treatment_label: string | null; room_rent_per_day_paise: number | null; room_days: number | null;
}
export interface SimulatorResult {
  condition_type: ConditionType; customer_share_paise: number | null;
  calculation: string; finding_id: string;
}
export interface SimulatorResponse {
  policy_id: string; status: 'illustrative' | 'partially_calculable' | 'insufficient_evidence';
  scenario: Partial<SimulatorRequest>; results: SimulatorResult[];
  missing_information: string[]; disclaimer: string;
}
export interface ApiError { error: { code: string; message: string; request_id?: string } }
