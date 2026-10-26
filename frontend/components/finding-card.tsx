"use client";

import React, { useEffect, useRef, useState } from "react";
import { AlertCircle, ArrowUpRight, FileText, Info, X } from "lucide-react";
import { findingCautions, findingStatusLabels, sourceReference, verificationLabels, type Finding, type PolicyDocument, type SourceReference } from "@/lib/policy-intelligence";

function SourceDialog({ reference, demo, close }: { reference: Extract<SourceReference, { available: true }>; demo: boolean; close: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const dialog = ref.current; dialog?.showModal(); return () => dialog?.close(); }, []);
  return <dialog className="source-dialog" ref={ref} aria-labelledby="source-title" onCancel={close} onClick={event => { if (event.target === event.currentTarget) close(); }}>
    <div className="dialog-top"><span className="policy-icon health"><FileText /></span><button className="icon-button" onClick={close} aria-label="Close source reference"><X /></button></div>
    <h2 id="source-title">{demo ? "Fictional source reference" : "Original policy source reference"}</h2>
    <p>{demo ? "This is a UI fixture. The document, page and quote are illustrative; no actual PDF or AI analysis is available." : "This reference was returned by the policy service. The PDF viewer is not available in this milestone."}</p>
    <dl className="source-metadata"><div><dt>Document</dt><dd>{reference.document.name}</dd></div><div><dt>Document ID</dt><dd>{reference.source.document_id}</dd></div><div><dt>{demo ? "Illustrative PDF page" : "Reported PDF page"}</dt><dd>{reference.source.page} · 1-indexed, not the printed page number</dd></div></dl>
    <div className="source-excerpt"><span className="content-label">{demo ? "Fictional quote · not policy evidence" : "Exact quoted text returned by the service"}</span><blockquote>{reference.source.quote}</blockquote></div>
    {reference.document.page_count === null && <p>Document page count is unknown. The page range cannot yet be checked.</p>}
    <div className="report-note"><Info size={18} /><p>PDF viewer coming later. This placeholder does not open or fetch a document.</p></div>
    <button className="button primary" onClick={close}>Back to finding</button>
  </dialog>;
}

export function FindingCard({ finding, documents, mode }: { finding: Finding; documents: PolicyDocument[]; mode: "mock" | "api" }) {
  const [sourceOpen, setSourceOpen] = useState(false);
  const demo = mode === "mock";
  const source = sourceReference(finding, documents);
  const cautions = findingCautions(finding);
  return <article className="finding-card" aria-labelledby={`finding-${finding.id}`}>
    <div className="finding-card-heading"><h3 id={`finding-${finding.id}`}>{finding.title}</h3><span className={`evidence-badge ${finding.verification_status}`}>{demo ? "Demo: " : ""}{verificationLabels[finding.verification_status]}</span></div>
    <div className="finding-state">{findingStatusLabels[finding.status]}</div>
    <div className="finding-interpretation"><span className="content-label">{demo ? "Fictional AI interpretation" : "AI interpretation"}</span><p>{finding.explanation || "No plain-language explanation was returned."}</p></div>
    {cautions.length > 0 && <div className="finding-cautions"><AlertCircle size={17} /><ul>{cautions.map(message => <li key={message}>{message}</li>)}</ul></div>}
    <dl className="finding-context"><div><dt>When this may apply</dt><dd>{finding.applicability || "Applicability has not been established from the available information."}</dd></div><div><dt>Exceptions & qualifications</dt><dd>{finding.exceptions.length ? <ul>{finding.exceptions.map((exception, index) => <li key={index}>{exception || "An exception entry was returned without details."}</li>)}</ul> : "No exceptions were returned. This does not establish that no exceptions exist."}</dd></div></dl>
    <div className={`finding-source ${source.available ? "" : "source-missing"}`}>
      <span className="content-label"><FileText size={14} />{demo ? "Fictional source reference" : "Original policy evidence"}</span>
      {source.available ? <>
        <blockquote>{source.source.quote}</blockquote>
        <div className="source-link-row"><span>{source.document.name} · {demo ? "Illustrative page" : "PDF page"} {source.source.page}</span><button className="text-action" onClick={() => setSourceOpen(true)}>Inspect source reference <ArrowUpRight size={14} /></button></div>
        {source.document.page_count === null && <p className="evidence-footnote">Page count is unknown; this reference has not been range-checked.</p>}
      </> : <p>{source.reason}</p>}
    </div>
    {finding.verification_status === "verified" && <p className="evidence-footnote">{demo ? "The verified label is simulated in this fixture." : "Verified means source evidence passed app checks."} It is not insurer certification or confirmation of coverage.</p>}
    {sourceOpen && source.available && <SourceDialog reference={source} demo={demo} close={() => setSourceOpen(false)} />}
  </article>;
}
