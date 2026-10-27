"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import type { LiveConfig } from "@/lib/app-config";
import type { AuthSession, AuthSessionController } from "@/lib/auth-session";
import { createLiveClients } from "@/lib/live-clients";
import { reportAvailability } from "@/lib/policy-intelligence";
import type { JobResponse, UploadResponse } from "@/lib/upload-contract";
import { UploadDialog } from "./upload-dialog";
import { WorkspaceShell } from "./workspace-shell";
import { PolicyWorkspace } from "./policy-workspace";
import type { PolicyRoute } from "./app-entry";

export function LiveWorkspace({ auth, user, config, route }: { auth: AuthSessionController; user: AuthSession["user"]; config: LiveConfig; route?: PolicyRoute }) {
  const clients = useMemo(() => createLiveClients(config, auth, user.id), [config, auth, user.id]);
  const [open, setOpen] = useState(false);
  const [receipt, setReceipt] = useState<UploadResponse | null>(null);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [reportReady, setReportReady] = useState(false);
  const [checking, setChecking] = useState(false);
  const [notice, setNotice] = useState("");
  const check = useRef<AbortController | null>(null);
  useEffect(() => () => check.current?.abort(), []);
  function accepted(value: UploadResponse) {
    check.current?.abort(); check.current = null; setChecking(false);
    setReceipt(value); setJob(null); setReportReady(false); setNotice("");
  }
  async function checkReport() {
    if (!receipt || !config.policyReadsEnabled || checking) return;
    const controller = new AbortController(); check.current = controller; setChecking(true); setNotice(""); setReportReady(false);
    try {
      const policy = await clients.policyClient.getPolicy(receipt.policy_id, controller.signal);
      if (controller.signal.aborted) return;
      const available = reportAvailability(policy);
      setReportReady(available.available);
      setNotice(available.available ? "Compatible policy details received. You can open the findings report." : available.message);
    } catch (error) {
      if (!controller.signal.aborted) setNotice(error instanceof Error ? error.message : "Compatible policy details are not available.");
    } finally { if (check.current === controller) { check.current = null; setChecking(false); } }
  }
  const account = <div className="live-account"><span>Signed in as {user.email || "authenticated user"}</span><button className="button secondary" onClick={() => void auth.signOut()}>Sign out</button></div>;
  if (route && config.policyReadsEnabled) return <>{account}<PolicyWorkspace key={route.policyId} {...route} client={clients.policyClient} /></>;
  return <><WorkspaceShell mode="api" section={route ? "Policy access" : "Live document upload"}>{account}
    <div className="page-heading"><div><span className="eyebrow">LIVE · AUTHENTICATED</span><h1>{route ? "Policy report is not connected" : "Upload a policy document"}</h1><p>Your PDF is sent to the configured backend after sign-in.</p></div>{!route && <button className="button primary" onClick={() => setOpen(true)}>Add policy</button>}</div>
    {route ? <div className="live-panel"><p>Policy ID: <code>{route.policyId}</code></p><p>Compatible policy details are not available yet. No report or fictional substitute is displayed.</p><Link className="button secondary" href="/">Back to live uploads</Link></div> : <>
      <div className="report-note"><p>The live wallet list is not connected. Only uploads accepted in this page session are shown below. Extraction or a completed job does not establish coverage or verified AI analysis.</p></div>
      {receipt && <section className="live-panel" aria-label="Latest accepted upload"><h2>Latest accepted upload</h2><dl className="job-details"><div><dt>Policy ID</dt><dd>{receipt.policy_id}</dd></div><div><dt>Document ID</dt><dd>{receipt.document_id}</dd></div><div><dt>Job ID</dt><dd>{receipt.job_id}</dd></div><div><dt>Reported status</dt><dd>{job?.status ?? receipt.status}</dd></div></dl>
        {job?.message && <p>{job.message}</p>}{job?.status === "failed" && <p>Processing failed. No report is implied; inspect the upload panel before choosing another document.</p>}
        {config.policyReadsEnabled && ["completed", "needs_review"].includes(job?.status ?? "") ? <button className="button secondary" disabled={checking} onClick={() => void checkReport()}>{checking ? "Checking policy details…" : "Check report availability"}</button> : <p>Findings navigation is unavailable until compatible policy details are enabled and processing reaches a reviewable state.</p>}
        {notice && <p role="status">{notice}</p>}{reportReady && <Link className="button primary" href={`/policies/${encodeURIComponent(receipt.policy_id)}/findings`}>Open findings</Link>}
      </section>}
      <p className="upload-hint">Reloading or signing out clears this page’s upload tracking. Sign-out stops local requests, not server processing. Keep the returned IDs to avoid duplicate uploads.</p>
    </>}
  </WorkspaceShell>{!route && <UploadDialog open={open} close={() => setOpen(false)} policies={[]} client={clients.uploadClient} onAccepted={accepted} onJob={setJob} />}</>;
}
