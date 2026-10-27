"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, FileText, Info, LoaderCircle, UploadCloud, X } from "lucide-react";
import type { PolicyCard } from "../../frontend_api_types";
import { createMockUploadClient, type DemoOutcome } from "@/lib/mock-upload-client";
import { pollJob } from "@/lib/poll-job";
import { documentTypes, stageLabels, validatePdf, type DocumentType, type JobResponse, type UploadClient, type UploadResponse } from "@/lib/upload-contract";

type Phase = "form" | "uploading" | "tracking" | "paused" | "terminal" | "upload_error";
const outcomeLabels: Record<DemoOutcome, string> = {
  needs_review: "Missing schedule → needs review",
  completed: "Completed workflow (simulated)",
  failed: "Unreadable / scanned PDF → failed",
  upload_error: "Upload connection error → retry",
  status_error: "Status connection errors → resume",
};

interface Props {
  open: boolean;
  close: () => void;
  policies: PolicyCard[];
  client?: UploadClient;
  onAccepted?: (receipt: UploadResponse) => void;
  onJob?: (job: JobResponse) => void;
}

export function UploadDialog({ open, close, policies, client: suppliedClient, onAccepted, onJob }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const operation = useRef<AbortController | null>(null);
  const validationVersion = useRef(0);
  const [phase, setPhase] = useState<Phase>("form");
  const [file, setFile] = useState<File | null>(null);
  const [validating, setValidating] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [policyId, setPolicyId] = useState("");
  const [sessionPolicyId, setSessionPolicyId] = useState("");
  const [documentType, setDocumentType] = useState<DocumentType | "">("");
  const [outcome, setOutcome] = useState<DemoOutcome>("needs_review");
  const [receipt, setReceipt] = useState<UploadResponse | null>(null);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [error, setError] = useState("");
  const [retryNotice, setRetryNotice] = useState("");
  const [fileName, setFileName] = useState("");
  const mockClient = useMemo(() => createMockUploadClient(outcome), [outcome]);
  const client = suppliedClient ?? mockClient;
  const demo = client.mode === "mock";
  const editing = phase === "form" || phase === "upload_error";
  const active = phase === "uploading" || phase === "tracking";

  useEffect(() => {
    const dialog = dialogRef.current;
    if (open && !dialog?.open) dialog?.showModal();
    else if (!open && dialog?.open) dialog.close();
  }, [open]);

  useEffect(() => () => {
    operation.current?.abort();
    validationVersion.current++;
  }, []);

  async function selectFiles(files: File[]) {
    if (!editing || operation.current) return;
    const version = ++validationVersion.current;
    setValidating(true);
    setFile(null);
    setError("");
    setPhase("form");
    try {
      const chosen = await validatePdf(files);
      if (version === validationVersion.current) setFile(chosen);
    } catch (failure) {
      if (version === validationVersion.current) setError(failure instanceof Error ? failure.message : "Unable to read this PDF.");
    } finally {
      if (version === validationVersion.current) setValidating(false);
    }
  }

  async function track(accepted: UploadResponse, controller: AbortController) {
    setPhase("tracking");
    setError("");
    setRetryNotice("");
    try {
      await pollJob(client, accepted, controller.signal, value => { setJob(value); onJob?.(value); }, setRetryNotice);
      if (!controller.signal.aborted) setPhase("terminal");
    } catch (failure) {
      if (!controller.signal.aborted) {
        setPhase("paused");
        setError(failure instanceof Error ? failure.message : "Status is unavailable. Processing is unconfirmed.");
      }
    } finally {
      if (operation.current === controller) operation.current = null;
      if (!controller.signal.aborted) setRetryNotice("");
    }
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || validating || operation.current) return;
    const controller = new AbortController();
    operation.current = controller;
    setPhase("uploading");
    setError("");
    setJob(null);
    setFileName(file.name);
    try {
      const accepted = await client.upload({ file, policy_id: policyId || undefined, document_type_hint: documentType || undefined }, controller.signal);
      if (controller.signal.aborted) return;
      setReceipt(accepted);
      setSessionPolicyId(accepted.policy_id);
      onAccepted?.(accepted);
      setFile(null); // Release the selected file after acceptance; retain only its display name.
      await track(accepted, controller);
    } catch (failure) {
      if (!controller.signal.aborted) {
        setPhase("upload_error");
        setError(failure instanceof Error ? failure.message : "Upload could not be confirmed.");
      }
    } finally {
      if (operation.current === controller) operation.current = null;
    }
  }

  function resume() {
    if (!receipt || operation.current) return;
    const controller = new AbortController();
    operation.current = controller;
    void track(receipt, controller);
  }

  function pause() {
    operation.current?.abort();
    operation.current = null;
    setPhase("paused");
    setRetryNotice("");
    setError("Status checks are paused. This does not cancel processing on the server.");
  }

  function anotherDocument() {
    if (receipt) setPolicyId(receipt.policy_id);
    setPhase("form");
    setReceipt(null);
    setJob(null);
    setFile(null);
    setError("");
    setDocumentType("");
    if (inputRef.current) inputRef.current.value = "";
  }

  const statusTitle = phase === "uploading" ? (demo ? "Simulating upload" : "Sending your PDF")
    : phase === "paused" ? "Status checks paused"
    : job?.status === "completed" ? (demo ? "Demo outcome: completed" : "Backend confirmed processing complete")
    : job?.status === "needs_review" ? (demo ? "Demo outcome: needs review" : "Your document needs review")
    : job?.status === "failed" ? (demo ? "Demo outcome: processing failed" : "Document processing failed")
    : demo ? "Simulating document processing" : "Waiting for processing updates";

  return <dialog ref={dialogRef} className="upload-dialog" aria-labelledby="upload-title" aria-describedby="upload-intro"
    onCancel={event => { event.preventDefault(); close(); }}
    onClick={event => { if (event.target === event.currentTarget) close(); }}>
    <div className="dialog-top">
      <span className="policy-icon health"><UploadCloud size={23} /></span>
      <button type="button" className="icon-button" onClick={close} aria-label="Close upload dialog"><X /></button>
    </div>
    <div className="upload-heading"><span className="eyebrow">YOUR DOCUMENTS, TOGETHER</span><h2 id="upload-title">Add a policy document</h2></div>
    <p id="upload-intro">Start with policy wording, or add a schedule and supporting documents to an existing policy.</p>
    <div className={`upload-mode ${demo ? "is-demo" : ""}`}>
      <Info size={18} /><div><strong>{demo ? "Demo only · simulated responses" : "Connected document service"}</strong>
        <p>{demo ? "Files stay in this browser. Nothing is uploaded, stored or analyzed. The wallet is unchanged. Use public or fictional PDFs." : "Uploads and processing states are confirmed by the backend. Use public or fictional documents for this prototype."}</p>
      </div>
    </div>

    {editing && <form onSubmit={submit}>
      <fieldset disabled={validating} className="upload-fields">
        <label htmlFor="upload-policy">Add to policy</label>
        <select id="upload-policy" value={policyId} onChange={event => setPolicyId(event.target.value)}>
          <option value="">Create a new policy</option>
          {policies.map(policy => <option value={policy.id} key={policy.id}>{policy.product_name ?? "Untitled policy"} · {policy.insurer ?? policy.id}</option>)}
          {sessionPolicyId && !policies.some(policy => policy.id === sessionPolicyId) && <option value={sessionPolicyId}>Policy created in this {demo ? "demo " : ""}session</option>}
        </select>
        <label htmlFor="document-type">Document type <span>(optional)</span></label>
        <select id="document-type" value={documentType} onChange={event => setDocumentType(event.target.value as DocumentType | "")}>
          <option value="">Not sure — let the service identify it</option>
          {documentTypes.map(type => <option key={type.value} value={type.value}>{type.label}</option>)}
        </select>
        <div className={`pdf-dropzone ${dragging ? "dragging" : ""}`}
          onDragOver={event => { event.preventDefault(); setDragging(true); }}
          onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false); }}
          onDrop={event => { event.preventDefault(); setDragging(false); void selectFiles(Array.from(event.dataTransfer.files)); }}>
          <UploadCloud size={28} aria-hidden="true" />
          <strong>Drop your PDF here</strong><span>or choose a file from your device</span>
          <input ref={inputRef} type="file" accept=".pdf,application/pdf" hidden aria-label="Choose a PDF"
            onChange={event => { const files = Array.from(event.target.files ?? []); event.target.value = ""; if (files.length) void selectFiles(files); }} />
          <button type="button" className="button secondary" onClick={() => inputRef.current?.click()}>Choose PDF</button>
          <small>One PDF · up to 20 MiB (local demo limit)</small>
        </div>
        {file && <div className="selected-pdf"><FileText size={20} /><div><strong>{file.name}</strong><span>{(file.size / 1024).toFixed(1)} KiB · PDF header checked</span></div><button type="button" className="icon-button" aria-label="Remove selected file" onClick={() => setFile(null)}><X size={17} /></button></div>}
        {!suppliedClient && <div className="demo-controls"><label htmlFor="demo-outcome">Demo scenario</label><select id="demo-outcome" value={outcome} onChange={event => setOutcome(event.target.value as DemoOutcome)}>{Object.entries(outcomeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><small>This selects a fictional outcome; it does not inspect your document.</small></div>}
      </fieldset>
      {validating && <p role="status">Checking the file header…</p>}
      {error && <div className="upload-error" role="alert"><AlertCircle size={18} /><div>{error}{phase === "upload_error" && !demo && <p>Acceptance is unconfirmed. A lost response can leave an uploaded document on the server. Confirm with the backend operator before sending again; the live wallet list is not available yet.</p>}</div></div>}
      <p className="upload-hint">A PDF header check cannot confirm readable text. Scanned, encrypted or damaged PDFs may require review or be rejected by the backend.</p>
      <button className="button primary upload-submit" type="submit" disabled={!file || validating}>
        <UploadCloud size={17} />{phase === "upload_error" ? (demo ? "Retry demo upload" : "Send PDF again") : demo ? "Run demo upload" : "Upload PDF"}
      </button>
    </form>}

    {!editing && <section className="processing-panel" aria-labelledby="processing-title">
      <div className="processing-heading">{active ? <LoaderCircle className="upload-spinner" size={22} /> : job?.status === "completed" ? <CheckCircle2 size={22} /> : <Info size={22} />}
        <h3 id="processing-title" role="status">{statusTitle}</h3></div>
      <p className="processing-filename">{fileName}</p>
      {phase === "uploading" && <><progress aria-label={demo ? "Simulated upload in progress" : "Upload awaiting server confirmation"} /><p>{demo ? "Rehearsing the upload flow. No data is being sent." : "Sending the file and waiting for server acceptance. Transfer percentage is unavailable."}</p></>}
      {receipt && <>
        <dl className="job-details"><div><dt>Policy ID</dt><dd>{receipt.policy_id}</dd></div><div><dt>{demo ? "Demo job" : "Job ID"}</dt><dd>{receipt.job_id}</dd></div><div><dt>Latest {demo ? "simulated" : "reported"} stage</dt><dd>{job ? stageLabels[job.stage] : "Awaiting first status update"}</dd></div><div><dt>Job status</dt><dd>{job?.status.replaceAll("_", " ") ?? "queued"}{demo ? " (simulated)" : ""}</dd></div></dl>
        {job?.message && <p className="job-message">{job.message}</p>}
        {job?.error && <div className="upload-error" role="alert"><AlertCircle size={18} /><div><strong>{job.error.code}</strong><p>{job.error.message}</p></div></div>}
        {job?.status === "failed" && <p>The job has stopped. You can upload another document; restarting this job is not available.</p>}
        {job?.status === "needs_review" && <p>Required information or readable evidence may be missing. Review the reported message before adding supporting documents. This is not a claim decision.</p>}
        {job?.status === "completed" && <p>{demo ? "This is a simulated end state. Your PDF has not been processed." : "The job has completed. Findings and source evidence will be available in a later screen; completion alone does not verify coverage."}</p>}
      </>}
      {retryNotice && <p className="retry-notice" role="status">{retryNotice}</p>}
      {error && <div className="upload-error" role="alert"><AlertCircle size={18} /><div>{error}</div></div>}
      <div className="processing-actions">
        {phase === "tracking" && <button type="button" className="button secondary" onClick={pause}>Pause status checks</button>}
        {phase === "paused" && <button type="button" className="button primary" onClick={resume}>Resume status checks</button>}
        {phase === "terminal" && <button type="button" className="button primary" onClick={anotherDocument}>Add another document</button>}
        <button type="button" className="button secondary" onClick={close}>Back to wallet</button>
      </div>
      <p className="upload-hint">Reopen this panel from Add policy. {active ? "Closing the panel keeps this session running. " : ""}Reloading the page clears this upload session.</p>
    </section>}
    <p className="upload-scope">Deep analysis supports only individual and family-floater indemnity health insurance. Other categories remain wallet-only.</p>
  </dialog>;
}
