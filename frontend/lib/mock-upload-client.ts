import { abortableDelay, UploadError, type JobResponse, type UploadClient } from "./upload-contract";

export type DemoOutcome = "completed" | "needs_review" | "failed" | "upload_error" | "status_error";

// In-memory fixtures only. File content is never transmitted, parsed or persisted.
export function createMockUploadClient(outcome: DemoOutcome = "needs_review", delayMs = 650): UploadClient {
  const jobs = new Map<string, { policyId: string; reads: number }>();
  let uploadFailed = false;
  return {
    mode: "mock",
    async upload(input, signal) {
      await abortableDelay(delayMs, signal);
      if (outcome === "upload_error" && !uploadFailed) {
        uploadFailed = true;
        throw new UploadError("Demo: simulated connection interruption. Retry to continue the example.", true);
      }
      const suffix = crypto.randomUUID();
      const policyId = input.policy_id || `mock-policy-${suffix}`;
      const jobId = `mock-job-${suffix}`;
      jobs.set(jobId, { policyId, reads: 0 });
      return { policy_id: policyId, document_id: `mock-document-${suffix}`, job_id: jobId, status: "queued" };
    },
    async getJob(jobId, signal) {
      await abortableDelay(delayMs / 3, signal);
      const job = jobs.get(jobId);
      if (!job) throw new UploadError("Demo job not found. Demo jobs exist only in this page session.");
      const read = job.reads++;
      if (outcome === "status_error" && read < 3) throw new UploadError("Demo: status service temporarily unavailable.", true);
      const status: JobResponse = { job_id: jobId, policy_id: job.policyId, status: "processing", stage: "extracting", message: "Demo: simulating PDF text extraction.", error: null };
      if (read === 0) return { ...status, status: "queued", stage: "uploaded", message: "Demo: document queued." };
      if (read === 1) return status;
      if (read === 2) return { ...status, stage: "verifying", message: "Demo: simulating evidence checks." };
      if (outcome === "failed") return { ...status, status: "failed", message: "Demo: the PDF could not be read. Try a readable, text-based copy.", error: { code: "UNREADABLE_PDF", message: "Demo fixture for scanned or garbled document text." } };
      if (outcome === "needs_review") return { ...status, status: "needs_review", stage: "verifying", message: "Demo: a policy schedule is missing. Member details and applicability remain unknown." };
      return { ...status, status: "completed", stage: "completed", message: "Demo workflow ended. No file was uploaded or analyzed; no coverage has been verified." };
    },
  };
}
