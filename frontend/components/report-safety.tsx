"use client";

import React from "react";
import { AlertCircle } from "lucide-react";
import type { FindingsResponse, PolicyDetails } from "@/lib/policy-intelligence";

type ReportProps = { policy: PolicyDetails; report: FindingsResponse };

export function ReportReviewNotice({ policy, report }: ReportProps) {
  const findingsNeedReview = report.findings.some(finding => finding.review_required || finding.verification_status !== "verified" || finding.status === "uncertain");
  if (!policy.needs_review && policy.analysis_status !== "needs_review" && !findingsNeedReview) return null;
  return <div className="report-note attention" role="note"><AlertCircle size={19} /><p><strong>Needs review.</strong> This policy or its extracted findings require review. Check the source wording, applicability, exceptions and schedule before relying on an interpretation. Extraction completion is not confirmation of coverage or an insurance payout.</p></div>;
}
