import { abortableDelay, isTerminal, parseJobResponse, UploadError, type JobResponse, type UploadClient, type UploadResponse } from "./upload-contract";

interface PollOptions {
  intervalMs?: number;
  maxAttempts?: number;
  maxConsecutiveErrors?: number;
  wait?: typeof abortableDelay;
}

// Sequential requests avoid overlapping polls and stale/out-of-order updates.
// Only GET requests retry. There is no job restart endpoint in contract v0.1.
export async function pollJob(
  client: UploadClient,
  receipt: UploadResponse,
  signal: AbortSignal,
  onUpdate: (job: JobResponse) => void,
  onRetry: (message: string) => void,
  options: PollOptions = {},
): Promise<JobResponse> {
  const { intervalMs = 2000, maxAttempts = 60, maxConsecutiveErrors = 3, wait = abortableDelay } = options;
  let failures = 0;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    signal.throwIfAborted();
    let delay = intervalMs;
    try {
      const job = parseJobResponse(await client.getJob(receipt.job_id, signal));
      signal.throwIfAborted();
      if (job.job_id !== receipt.job_id || job.policy_id !== receipt.policy_id) {
        throw new UploadError("The status response belongs to a different policy or job. Processing is unconfirmed.");
      }
      failures = 0;
      onRetry("");
      onUpdate(job);
      if (isTerminal(job)) return job;
    } catch (error) {
      signal.throwIfAborted();
      if (!(error instanceof UploadError) || !error.retryable || ++failures >= maxConsecutiveErrors) throw error;
      delay = Math.min(intervalMs * 2 ** failures, 16000);
      onRetry(`${error.message} Checking again in ${delay / 1000} seconds.`);
    }
    if (attempt < maxAttempts - 1) await wait(delay, signal);
  }
  throw new UploadError("Automatic checks are paused because processing is taking longer than expected. Completion has not been confirmed.");
}
