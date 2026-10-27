"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertCircle, ArrowLeft, ArrowRight, BookOpen, ChevronRight, FileSearch, Info, RefreshCw, Sparkles } from "lucide-react";
import { mockPolicyClient, type PolicyClient } from "@/lib/policy-client";
import { analysisLabels, conditionGroups, PolicyDataError, reportAvailability, type FindingsResponse, type PolicyDetails } from "@/lib/policy-intelligence";
import { WorkspaceShell } from "./workspace-shell";
import { PolicyDetailsContent } from "./policy-details";
import { FindingCard } from "./finding-card";
import { ClaimSimulator } from "./claim-simulator";

type LoadState<T> = { status: "loading" } | { status: "error"; error: Error } | { status: "ready"; data: T };

function LoadingPanel({ label }: { label: string }) {
  return <div className="report-loading" role="status"><span className="sr-only">{label}</span><div className="skeleton"><div /><div /><div /><div /></div><div className="skeleton"><div /><div /><div /><div /></div></div>;
}

function ErrorPanel({ error, retry }: { error: Error; retry: () => void }) {
  const status = error instanceof PolicyDataError ? error.status : undefined;
  const title = status === 404 ? "Policy or report not found" : status === 403 ? "Access is restricted" : status === 401 ? "Sign-in is required" : "We could not load this information";
  return <div className="empty-state" role="alert"><AlertCircle size={28} /><h2>{title}</h2><p>{error.message}</p><div className="report-actions"><button className="button primary" onClick={retry}><RefreshCw size={15} />Try again</button><Link className="button secondary" href="/">Back to wallet</Link></div></div>;
}

function IntelligenceReport({ policy, client, refreshPolicy }: { policy: PolicyDetails; client: PolicyClient; refreshPolicy: () => void }) {
  const [simulatorOpen, setSimulatorOpen] = useState(false);
  const [state, setState] = useState<LoadState<FindingsResponse>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const availability = reportAvailability(policy);
  useEffect(() => {
    if (!availability.available) return;
    const controller = new AbortController();
    setState({ status: "loading" });
    client.getFindings(policy.id, controller.signal).then(data => {
      if (!controller.signal.aborted) setState({ status: "ready", data });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setState({ status: "error", error: error instanceof Error ? error : new Error("Unable to load findings.") });
    });
    return () => controller.abort();
  }, [policy.id, availability.available, client, attempt]);

  if (!availability.available) return <section className="empty-state"><FileSearch size={32} /><h2>{availability.title}</h2><p>{availability.message}</p><button className="button secondary" onClick={refreshPolicy}><RefreshCw size={15} />Refresh policy status</button></section>;
  if (state.status === "loading") return <LoadingPanel label="Loading policy findings" />;
  if (state.status === "error") return <ErrorPanel error={state.error} retry={() => setAttempt(value => value + 1)} />;
  const report = state.data;
  return <>
    <section className="report-intro"><div className="report-intro-icon"><Sparkles size={23} /></div><div><span className="eyebrow">SIX AREAS. THE CONTEXT BEHIND EACH.</span><h2>Understand the conditions, not just the cover.</h2><p>Read the interpretation alongside the source, applicability and exceptions. A condition found in a policy is not automatically applicable to your situation.</p></div></section>
    <div className="claim-entry"><div><strong>What could these conditions mean for a hypothetical bill?</strong><p>Explore co-payment and treatment-cap effects with explicit assumptions.</p></div><button className="button primary" aria-expanded={simulatorOpen} aria-controls="claim-simulator" onClick={() => setSimulatorOpen(value => !value)}>{simulatorOpen ? "Hide simulator" : "Simulate Claim Impact"}<ArrowRight size={16} /></button></div>
    {simulatorOpen && <ClaimSimulator policy={policy} report={report} mode={client.mode} />}
    <div className="report-meta"><span>{report.findings.length} {report.findings.length === 1 ? "finding" : "findings"} returned</span><span>{client.mode === "mock" ? "Fixture version" : "Analysis version"}: {report.analysis_version}</span></div>
    <nav className="report-jumps" aria-label="Report categories">{conditionGroups.map(group => <a key={group.type} href={`#condition-${group.type}`}>{group.label}</a>)}</nav>
    {report.findings.length === 0 && <div className="report-note"><Info size={19} /><p>No findings were returned for this report. This is not evidence that conditions or exclusions are absent.</p></div>}
    {policy.needs_review && <div className="report-note attention"><AlertCircle size={19} /><p>This policy is flagged for review. Personal details, applicability or supporting documents may still need confirmation.</p></div>}
    <div className="findings-sections">{conditionGroups.map(group => {
      const findings = report.findings.filter(finding => finding.condition_type === group.type);
      return <section id={`condition-${group.type}`} key={group.type} className="condition-section" aria-labelledby={`heading-${group.type}`}>
        <div className="condition-heading"><h2 id={`heading-${group.type}`}>{group.label} <span className="count-badge">{findings.length}</span></h2><p>{group.description}</p></div>
        {findings.length ? findings.map(finding => <FindingCard key={finding.id} finding={finding} documents={policy.documents} mode={client.mode} />) : <div className="no-finding"><FileSearch size={20} /><div><h3>No finding returned in this category</h3><p>The response does not establish whether this condition exists or applies. It does not guarantee coverage.</p></div></div>}
      </section>;
    })}</div>
    <div className="report-note"><BookOpen size={19} /><p>Source checks are app checks, not insurer certification. The simulator models selected fictional rules only. No insurer claim decision or rejection probability is provided here.</p></div>
  </>;
}

export function PolicyWorkspace({ policyId, view, client = mockPolicyClient }: { policyId: string; view: "details" | "findings"; client?: PolicyClient }) {
  const [state, setState] = useState<LoadState<PolicyDetails>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    client.getPolicy(policyId, controller.signal).then(data => {
      if (!controller.signal.aborted) setState({ status: "ready", data });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setState({ status: "error", error: error instanceof Error ? error : new Error("Unable to load policy details.") });
    });
    return () => controller.abort();
  }, [policyId, client, attempt]);
  const detailsPath = `/policies/${encodeURIComponent(policyId)}`;
  const title = view === "details" ? "Policy details" : "AI Policy Intelligence Report";
  return <WorkspaceShell section={title} mode={client.mode}>
    <nav className="policy-breadcrumbs" aria-label="Breadcrumb"><Link href="/">Insurance wallet</Link><ChevronRight size={13} />{view === "findings" ? <><Link href={detailsPath}>Policy details</Link><ChevronRight size={13} /><span aria-current="page">AI findings</span></> : <span aria-current="page">Policy details</span>}</nav>
    <div className="policy-page-heading"><div><span className="eyebrow">{view === "details" ? "THE DETAILS OF YOUR COVER" : "READ WITH CONTEXT"}</span><h1>{title}</h1><p>{state.status === "ready" ? `${state.data.product_name || "Untitled policy"} · ${state.data.insurer || "Insurer not available"}` : "Your documents and their supporting information."}</p></div><Link className="button secondary" href="/"><ArrowLeft size={15} />Wallet</Link></div>
    {client.mode === "mock" && <aside className="report-demo-note"><Info size={18} /><div><strong>Fictional demo · no actual AI analysis</strong><p>Policy details, findings, quotes, page references and verification labels are UI fixtures. No actual policy evidence or customer documents are represented.</p></div></aside>}
    <nav className="policy-page-tabs" aria-label="Policy sections"><Link href={detailsPath} aria-current={view === "details" ? "page" : undefined}>Policy details</Link><Link href={`${detailsPath}/findings`} aria-current={view === "findings" ? "page" : undefined}>AI findings <ArrowRight size={14} /></Link></nav>
    {state.status === "loading" ? <LoadingPanel label="Loading policy details" /> : state.status === "error" ? <ErrorPanel error={state.error} retry={() => setAttempt(value => value + 1)} /> : <>
      <div className="policy-status-line"><span className={`status ${state.data.analysis_status}`}>{client.mode === "mock" ? "Demo: " : ""}{analysisLabels[state.data.analysis_status]}</span><span>Unknown information is shown as unavailable.</span></div>
      {view === "details" ? <PolicyDetailsContent policy={state.data} mode={client.mode} /> : <IntelligenceReport policy={state.data} client={client} refreshPolicy={() => setAttempt(value => value + 1)} />}
    </>}
  </WorkspaceShell>;
}
