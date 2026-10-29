"use client";
import React, { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { ConditionSession, type ConditionClient, type ConditionViewState } from "@/lib/condition-extraction";
import { createMockConditionClient, demoDocumentId, demoJobId, demoJobs, demoPolicyId, type DemoConditionJob } from "@/lib/mock-condition-extraction";
import { conditionGroups } from "@/lib/policy-intelligence";
import { WorkspaceShell } from "./workspace-shell";

export function ConditionResults({ state, mode = "mock" }: { state: ConditionViewState; mode?: "mock" | "api" }) {
 const run = state.run;
 const job = state.job;
 const status = run?.status ?? job?.status;
 const running = status === "queued" || status === "processing";
 const demo = mode === "mock";
 return <>
  <div role={state.phase === "error" ? "alert" : "status"} aria-live="polite" className="report-note">
   {state.phase === "error" ? state.error : state.phase === "requesting" ? `Requesting ${demo ? "fictional " : ""}extraction...` : state.phase === "loading" ? "Loading the explicitly selected job..." : status ? `Job ${state.identity?.job_id}: ${status.replaceAll("_", " ")}` : `Choose a job_id or start ${demo ? "a fictional" : "an"} extraction.`}
  </div>
  {(run || job) && <section className="detail-panel"><h2>Analysis context</h2><p>Policy: {state.identity?.policy_id} | Document: {state.identity?.document_id} | Job: {state.identity?.job_id}</p>
   {job?.message && <p className="job-message">{job.message}</p>}
   {job?.error && <p role="alert">Processing error: {job.error.message}</p>}
   {run && <><p>Analysis state: {run.analysis_state ?? "Not established"} | Rejected candidates: {run.rejected_candidate_count}</p>
    {run.warning && <div className="report-note attention" role="alert"><strong>{run.analysis_state === "incomplete" ? "Incomplete analysis. " : "Analysis notice. "}</strong>{run.warning}</div>}
    {run.analysis_state === "complete" && <p>Complete means planned passages were processed. It does not establish that every restriction was found.</p>}</>}
   {status === "failed" && <p role="alert">Extraction failed. No conclusions about policy restrictions can be drawn.</p>}
   {running && <p>Extraction is {status}. No completed condition results are available yet.</p>}
  </section>}
  <p className="report-note">No conditions returned in a category does not mean the policy has no restrictions. {demo ? "These are fictional fixtures, not real extracted evidence or claim calculations." : "Returned conditions require review and are not used for claim calculations."}</p>
  <div className="findings-sections">{conditionGroups.map(group => {
   const items = run?.conditions.filter(c => c.category === group.type) ?? [];
   return <section className="condition-section" key={group.type}><h2>{group.label} <span className="count-badge">{items.length}</span></h2><p>{group.description}</p>
    {items.length ? items.map(c => <article className="detail-panel condition-preview-card" key={c.id}>
     <h3>{c.title}</h3><p><strong>Review required.</strong> {demo ? "Source verified in fictional fixture" : "Backend exact-source anchoring reported"}; not independent verification, insurer certification or confirmation of applicability.</p>
     <p>Kind: {c.kind} | {c.specific_label ?? "Specific label not supplied"}</p>
     <p><strong>Literal observed values:</strong> {c.observed_value_mentions.join(", ") || "None returned; no value inferred."}</p>
     <p><strong>Applicability:</strong> {c.applicability ?? "Not established."}</p>
     <h4>Exceptions</h4>{c.exceptions.length ? <ul>{c.exceptions.map((v,i) => <li key={i}>{v}</li>)}</ul> : <p>No exceptions returned; this does not establish that none exist.</p>}
     <h4>Dependencies</h4>{c.dependencies.length ? <ul>{c.dependencies.map((v,i) => <li key={i}>{v.kind.replaceAll("_", " ")}: {v.label ?? "Label not supplied"}</li>)}</ul> : <p>No dependencies returned; applicability still needs review.</p>}
     <h4>Exact evidence quotations{demo ? " - fictional" : ""}</h4>{c.evidence.map((e,i) => <figure key={i}><figcaption>Document {c.document_id} | PDF page {e.page} (physical, 1-indexed) | Passage {e.passage_id}</figcaption><blockquote>{e.quote}</blockquote><small>Passage offsets [{e.start}, {e.end}); no PDF viewer is connected.</small></figure>)}
    </article>) : <p>{!run || running ? "Results unavailable or awaiting results for the selected run." : run.status === "failed" ? "Results unavailable for this failed run." : "No conditions returned in this category. Restrictions may still exist."}</p>}
   </section>;
  })}</div>
 </>;
}
export function ConditionExtractionWorkspace({ client: suppliedClient }: { client?: ConditionClient }) {
 const [scenario, setScenario] = useState<DemoConditionJob>("success");
 const client = useMemo(() => suppliedClient ?? createMockConditionClient(scenario), [suppliedClient, scenario]);
 const demo = client.mode === "mock";
 const [policyId, setPolicyId] = useState(demo ? demoPolicyId : "");
 const [documentId, setDocumentId] = useState(demo ? demoDocumentId : "");
 const [jobId, setJobId] = useState("");
 const [paused, setPaused] = useState(false);
 const polls = useRef({ job: "", attempts: 0 });
 const session = useMemo(() => new ConditionSession(client), [client]);
 const state = useSyncExternalStore(session.subscribe, session.getSnapshot, session.getSnapshot);
 useEffect(() => () => session.dispose(), [session]);
 useEffect(() => { if (state.identity) setJobId(state.identity.job_id); }, [state.identity]);
 useEffect(() => {
  if (paused || state.phase !== "ready" || !state.job || !["queued", "processing"].includes(state.run?.status ?? state.job.status) || !state.identity) return;
  const identity = state.identity;
  if (polls.current.job !== identity.job_id) polls.current = { job: identity.job_id, attempts: 0 };
  if (polls.current.attempts >= 60) { setPaused(true); return; }
  const timer = setTimeout(() => { polls.current.attempts++; void session.load(identity); }, 2000);
  return () => clearTimeout(timer);
 }, [state, session, paused]);
 const active = state.phase === "requesting" || state.phase === "loading";
 const running = !!state.job && ["queued", "processing"].includes(state.run?.status ?? state.job.status);
 const clear = () => { session.clear(); setPaused(false); polls.current = { job: "", attempts: 0 }; };
 return <WorkspaceShell section="Condition extraction" mode={client.mode}>
  <h1>Claim-affecting conditions</h1>
  <aside className="report-demo-note"><strong>{demo ? "Typed mock preview - no live extraction" : "Authenticated condition extraction"}</strong><p>{demo ? "All clauses, documents and jobs here are fictional. No PDF is uploaded and no paid AI operation runs." : "Use an existing extracted document that belongs to this policy. Starting extraction submits a backend processing request."} Historical warning retrieval remains a separate integration. Known job IDs can be selected explicitly.</p></aside>
  <section className="detail-panel condition-controls">
   {demo ? <><p>Fictional policy: {demoPolicyId} | Extracted document: {demoDocumentId}</p>
    <label htmlFor="condition-scenario">Fictional extraction outcome</label><select id="condition-scenario" value={scenario} onChange={e => { clear(); setScenario(e.target.value as DemoConditionJob); setJobId(""); }}>{demoJobs.map(v => <option key={v}>{v}</option>)}</select></>
    : <><label htmlFor="condition-policy">Policy ID (UUID)</label><input id="condition-policy" value={policyId} onChange={e => { clear(); setPolicyId(e.target.value); setJobId(""); }} />
     <label htmlFor="condition-document">Extracted document ID (UUID)</label><input id="condition-document" value={documentId} onChange={e => { clear(); setDocumentId(e.target.value); setJobId(""); }} /></>}
   <button className="button primary" disabled={active || running || !policyId.trim() || !documentId.trim()} onClick={() => { setPaused(false); polls.current.attempts = 0; void session.extract(policyId.trim(), { document_id: documentId.trim() }); }}>Extract Conditions</button>
   <form onSubmit={e => { e.preventDefault(); setPaused(false); polls.current.attempts = 0; void session.load({ policy_id: policyId.trim(), document_id: documentId.trim(), job_id: jobId.trim() }); }}>
    <label htmlFor="condition-job">Explicit job_id</label><input id="condition-job" list={demo ? "condition-jobs" : undefined} value={jobId} onChange={e => { clear(); setJobId(e.target.value); }} required placeholder={demo ? "Choose a fictional job_id" : "Enter an existing job UUID"} />
    {demo && <datalist id="condition-jobs">{demoJobs.map(v => <option key={v} value={demoJobId(v)}>{v}</option>)}</datalist>}
    <button className="button secondary" disabled={!jobId.trim() || !policyId.trim() || !documentId.trim() || active}>Load selected job</button>
   </form><p>No newest-job fallback. Extraction selects only its returned receipt job_id; manual selection loads only the specified run. A lost start response does not prove that extraction failed; check existing jobs before starting again.</p>
   {state.identity && <p>Selected job_id: <code>{state.identity.job_id}</code></p>}
   {(active || running) && <button className="button secondary" onClick={() => { session.pause(); setPaused(true); }}>Stop local checks</button>}
   {paused && <p role="status">Local checks are paused. This does not cancel server processing. Load the selected job to resume; do not start another extraction to check status.</p>}
  </section><ConditionResults state={state} mode={client.mode} />
 </WorkspaceShell>;
}
