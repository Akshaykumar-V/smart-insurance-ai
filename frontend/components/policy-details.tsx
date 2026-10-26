import React from "react";
import Link from "next/link";
import { AlertCircle, ArrowRight, FileText, Users } from "lucide-react";
import { formatDate, formatMoney } from "@/lib/policies";
import { documentTypes } from "@/lib/upload-contract";
import { analysisLabels, missingInformation, policyTypeLabels, type PolicyDetails } from "@/lib/policy-intelligence";

export function PolicyDetailsContent({ policy, mode }: { policy: PolicyDetails; mode: "mock" | "api" }) {
  const missing = missingInformation(policy);
  const reportUrl = `/policies/${encodeURIComponent(policy.id)}/findings`;
  return <>
    {(missing.length > 0 || policy.needs_review) && <section className="missing-information" aria-labelledby="missing-title"><AlertCircle size={20} /><div><h2 id="missing-title">Information that needs attention</h2>{policy.needs_review && <p>This policy is flagged for review. Available metadata does not confirm cover in force or claim applicability.</p>}{missing.length > 0 && <ul>{missing.map(item => <li key={item}>{item}</li>)}</ul>}</div></section>}
    <div className="details-grid">
      <section className="detail-panel" aria-labelledby="overview-title"><div className="panel-heading"><h2 id="overview-title">Policy overview</h2><span className={`status ${policy.analysis_status}`}>{analysisLabels[policy.analysis_status]}</span></div>
        <dl className="policy-fields">
          <div><dt>Insurer</dt><dd>{policy.insurer || "Not available"}</dd></div>
          <div><dt>Product</dt><dd>{policy.product_name || "Not available"}</dd></div>
          <div><dt>Category</dt><dd className="capitalize">{policy.category}</dd></div>
          <div><dt>Policy type</dt><dd>{policyTypeLabels[policy.policy_type]}</dd></div>
          <div><dt>Sum insured</dt><dd className="detail-amount">{formatMoney(policy.sum_insured_paise)}</dd></div>
          <div><dt>Product UIN</dt><dd>{policy.uin || "Not available"}</dd></div>
          <div><dt>Start date</dt><dd>{policy.start_date ? formatDate(policy.start_date) : "Not available"}</dd></div>
          <div><dt>End date</dt><dd>{policy.end_date ? formatDate(policy.end_date) : "Not available"}</dd></div>
          <div><dt>Policyholder</dt><dd>{policy.policyholder_name || "Not available"}</dd></div>
          <div><dt>Policy reference</dt><dd className="opaque-id">{policy.id}</dd></div>
        </dl>
      </section>
      <section className="detail-panel" aria-labelledby="members-title"><div className="panel-heading"><h2 id="members-title">Insured members</h2><Users size={20} /></div>
        {policy.insured_members.length ? <ul className="member-list">{policy.insured_members.map((member, index) => <li key={index}><span className="member-avatar"><Users size={18} /></span><div><strong>{member.name || "Name not available"}</strong><span>{member.age === null ? "Age not available" : `Age ${member.age}`}{mode === "mock" ? " · fictional member" : ""}</span></div></li>)}</ul> : <div className="panel-empty"><Users size={26} /><h3>Member details are not available</h3><p>A personal schedule may be needed. No names or ages have been inferred.</p></div>}
        <div className="report-invitation"><span className="eyebrow">UNDERSTAND THE DETAILS</span><h3>Read the policy intelligence report</h3><p>See findings, qualifications and the source references behind them.</p><Link className="text-action" href={reportUrl}>View AI findings <ArrowRight size={15} /></Link></div>
      </section>
    </div>
    <section className="detail-panel document-panel" aria-labelledby="documents-title"><div className="panel-heading"><h2 id="documents-title">Attached documents <span className="count-badge">{policy.documents.length}</span></h2></div>
      {mode === "mock" && <p className="panel-caption">Fictional document metadata only. These entries do not represent stored or downloadable PDFs.</p>}
      {policy.documents.length ? <ul className="document-list">{policy.documents.map(document => <li key={document.id}><span className="policy-icon health"><FileText size={20} /></span><div><h3>{document.name}</h3><p>{documentTypes.find(type => type.value === document.type)?.label} · {document.page_count === null ? "Page count unknown" : `${document.page_count} pages`}</p></div><span className="document-state">{document.processing_status.replaceAll("_", " ")}</span></li>)}</ul> : <div className="panel-empty"><FileText size={26} /><h3>No documents attached</h3><p>No document metadata was returned for this policy. Use Add policy in the wallet to attach a document.</p></div>}
      <p className="evidence-footnote">Document viewing will be added in a later milestone.</p>
    </section>
  </>;
}
