import type { DocumentType, JobResponse, UploadResponse } from "../../frontend_api_types";

export type { DocumentType, JobResponse, UploadResponse };

// A local UX limit, not an assertion about the backend's upload limit.
export const MAX_PDF_BYTES = 20 * 1024 * 1024;
export const documentTypes: { value: DocumentType; label: string }[] = [
  { value: "policy_wording", label: "Policy wording" },
  { value: "policy_schedule", label: "Policy schedule" },
  { value: "cis", label: "Customer information sheet (CIS)" },
  { value: "endorsement", label: "Endorsement" },
  { value: "other", label: "Other document" },
];

export const stageLabels = {
  uploaded: "Document received",
  extracting: "Reading PDF pages",
  classifying: "Identifying the document",
  indexing: "Organizing document text",
  retrieving: "Finding relevant clauses",
  analyzing: "Analyzing policy wording",
  verifying: "Checking source evidence",
  completed: "Processing stage finished",
} satisfies Record<JobResponse["stage"], string>;

export interface UploadInput {
  file: File;
  policy_id?: string;
  document_type_hint?: DocumentType;
}

export interface UploadClient {
  readonly mode: "mock" | "api";
  upload(input: UploadInput, signal: AbortSignal): Promise<UploadResponse>;
  getJob(jobId: string, signal: AbortSignal): Promise<JobResponse>;
}

export class UploadError extends Error {
  constructor(message: string, readonly retryable = false, readonly code?: string, readonly status?: number) {
    super(message);
    this.name = "UploadError";
  }
}

export async function validatePdf(files: readonly File[]): Promise<File> {
  if (files.length !== 1) throw new UploadError("Choose one PDF at a time.");
  const file = files[0];
  if (!/\.pdf$/i.test(file.name) || (file.type && !["application/pdf", "application/octet-stream"].includes(file.type))) {
    throw new UploadError("Choose a PDF file (.pdf).");
  }
  if (!file.size) throw new UploadError("This file is empty. Choose a readable PDF.");
  if (file.size > MAX_PDF_BYTES) throw new UploadError("This demo accepts PDFs up to 20 MiB. Choose a smaller document.");
  let header: string;
  try {
    header = new TextDecoder().decode(await file.slice(0, 1024).arrayBuffer());
  } catch {
    throw new UploadError("This file could not be read. Choose it again or try another PDF.");
  }
  if (!/%PDF-\d\.\d/.test(header)) throw new UploadError("This file does not have a PDF header. Renaming a file to .pdf is not enough.");
  // Header validation cannot establish readability, encryption, or scan quality.
  return file;
}

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new UploadError("The server returned an invalid response.");
  return value as Record<string, unknown>;
}
function id(value: unknown): value is string { return typeof value === "string" && value.trim().length > 0; }

export function parseUploadResponse(value: unknown): UploadResponse {
  const data = record(value);
  if (!id(data.policy_id) || !id(data.document_id) || !id(data.job_id) || data.status !== "queued") {
    throw new UploadError("The upload response did not match API contract v0.1. Acceptance is unconfirmed.");
  }
  return data as unknown as UploadResponse;
}

export function parseJobResponse(value: unknown): JobResponse {
  const data = record(value);
  const error = data.error === null ? null : record(data.error);
  if (!id(data.job_id) || !id(data.policy_id) || !["queued", "processing", "completed", "failed", "needs_review"].includes(data.status as string)
    || !Object.hasOwn(stageLabels, data.stage as string)
    || !(data.message === null || typeof data.message === "string")
    || (error !== null && (!id(error.code) || typeof error.message !== "string"))) {
    throw new UploadError("The job response did not match API contract v0.1. Processing is unconfirmed.");
  }
  return data as unknown as JobResponse;
}

export function isTerminal(job: JobResponse): boolean {
  return ["completed", "failed", "needs_review"].includes(job.status);
}

export function abortableDelay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(new DOMException("Aborted", "AbortError")); return; }
    const abort = () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, ms);
    signal.addEventListener("abort", abort, { once: true });
  });
}
