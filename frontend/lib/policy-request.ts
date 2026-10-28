import { PolicyDataError } from "./policy-intelligence";

// Transport only: callers validate unknown JSON against the shared v0.1 contract.
// Creating a reader never probes an endpoint or supplies demo fallbacks.
export function createPolicyReader(baseUrl: string, getAccessToken: () => Promise<string>) {
  const origin = baseUrl.replace(/\/$/, "");
  return async function request(path: string, signal: AbortSignal): Promise<unknown> {
    signal.throwIfAborted();
    const token = await getAccessToken();
    signal.throwIfAborted();
    if (!token) throw new PolicyDataError("Sign in is required to view policies.", 401);
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal.addEventListener("abort", abort, { once: true });
    const timeout = setTimeout(abort, 30_000);
    try {
      const response = await fetch(`${origin}${path}`, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal, cache: "no-store" });
      if (!response.ok) {
        const messages: Record<number, string> = {
          401: "Your session has expired. Sign in again to view policies.",
          403: "You do not have permission to view these policies or findings.",
          404: "This policy or report could not be found.",
          429: "The policy service is busy. Please try again shortly.",
        };
        throw new PolicyDataError(messages[response.status] ?? "The policy service is unavailable. Please try again.", response.status);
      }
      if (response.status !== 200) throw new PolicyDataError("The service returned an unexpected response status.");
      let data: unknown;
      try { data = await response.json(); }
      catch { throw new PolicyDataError("The service returned unreadable policy data."); }
      controller.signal.throwIfAborted();
      return data;
    } catch (error) {
      if (signal.aborted) throw new DOMException("Aborted", "AbortError");
      if (controller.signal.aborted) throw new PolicyDataError("The request timed out or the connection was interrupted. Please try again.");
      if (error instanceof PolicyDataError) throw error;
      throw new PolicyDataError("The request timed out or the connection was interrupted. Please try again.");
    } finally {
      clearTimeout(timeout);
      signal.removeEventListener("abort", abort);
    }
  };
}
