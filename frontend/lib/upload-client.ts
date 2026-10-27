import { parseJobResponse, parseUploadResponse, UploadError, type UploadClient, type UploadInput } from "./upload-contract";

export function createUploadForm(input: UploadInput): FormData {
  const body = new FormData();
  body.append("file", input.file);
  if (input.policy_id) body.append("policy_id", input.policy_id);
  if (input.document_type_hint) body.append("document_type_hint", input.document_type_hint);
  return body;
}

// Authentication is supplied by the caller; this adapter never caches a token.
export function createApiUploadClient(baseUrl: string, getAccessToken: () => Promise<string>): UploadClient {
  const origin = baseUrl.replace(/\/$/, "");
  async function request(path: string, signal: AbortSignal, body?: FormData): Promise<unknown> {
    signal.throwIfAborted();
    const token = await getAccessToken();
    signal.throwIfAborted();
    if (!token) throw new UploadError("Sign in is required before connecting to document services.", false, "UNAUTHENTICATED");
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal.addEventListener("abort", abort, { once: true });
    const timeout = setTimeout(abort, body ? 120_000 : 30_000);
    try {
      const response = await fetch(`${origin}${path}`, {
        method: body ? "POST" : "GET", body,
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal, cache: "no-store",
      });
      if (!response.ok) {
        const messages: Record<number, string> = {
          401: "Your session has expired. Sign in again before continuing.",
          403: "You do not have permission to access this policy or document.",
          404: "This policy or processing job could not be found.",
          413: "The server rejected this file as too large. Choose a smaller PDF.",
          429: "The document service is busy. Please wait before trying again.",
        };
        let message = messages[response.status] ?? "The document service could not complete this request.";
        let code: string | undefined;
        try {
          const data = await response.json();
          if (typeof data?.error?.code === "string") code = data.error.code;
          if (!messages[response.status] && typeof data?.error?.message === "string") message = data.error.message;
        } catch { /* Keep the safe fallback for non-JSON errors. */ }
        throw new UploadError(message, response.status === 429 || response.status >= 500, code, response.status);
      }
      if (response.status !== (body ? 202 : 200)) throw new UploadError("The server returned an unexpected status. The operation is unconfirmed.");
      try { return await response.json(); }
      catch { throw new UploadError("The server returned unreadable data. The operation is unconfirmed."); }
    } catch (error) {
      if (signal.aborted) throw new DOMException("Aborted", "AbortError");
      if (error instanceof UploadError) throw error;
      throw new UploadError("The request timed out or the connection was interrupted.", true);
    } finally {
      clearTimeout(timeout);
      signal.removeEventListener("abort", abort);
    }
  }
  return {
    mode: "api",
    async upload(input, signal) {
      const result = parseUploadResponse(await request("/api/v1/policies/upload", signal, createUploadForm(input)));
      if (input.policy_id && result.policy_id !== input.policy_id) throw new UploadError("The server returned a different policy. Attachment is unconfirmed.");
      return result;
    },
    async getJob(jobId, signal) {
      const result = parseJobResponse(await request(`/api/v1/jobs/${encodeURIComponent(jobId)}`, signal));
      if (result.job_id !== jobId) throw new UploadError("The server returned a different job. Processing is unconfirmed.");
      return result;
    },
  };
}
