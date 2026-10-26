import { test } from "node:test";
import assert from "node:assert/strict";
import { File as NodeFile } from "node:buffer";
import { createApiUploadClient, createUploadForm } from "./upload-client";
import { createMockUploadClient, type DemoOutcome } from "./mock-upload-client";
import { pollJob } from "./poll-job";
import { MAX_PDF_BYTES, parseJobResponse, parseUploadResponse, UploadError, validatePdf, type JobResponse, type UploadClient } from "./upload-contract";

const receipt = { policy_id: "policy-1", document_id: "doc-1", job_id: "job-1", status: "queued" as const };
const queued: JobResponse = { policy_id: "policy-1", job_id: "job-1", status: "queued", stage: "uploaded", message: null, error: null };
const signal = () => new AbortController().signal;
const pdf = (body = "%PDF-1.7\nfictional test fixture", name = "fictional.pdf", type = "application/pdf") => new NodeFile([body], name, { type }) as unknown as File;
const noWait = async () => {};

test("PDF validation accepts PDF headers with absent browser MIME and mixed-case extensions", async () => {
  const file = pdf(undefined, "Fictional.PDF", "");
  assert.equal(await validatePdf([file]), file);
});

test("PDF validation rejects missing/multiple files, empty, wrong type, spoofed and oversized PDFs", async () => {
  for (const files of [[], [pdf(), pdf()], [pdf("")], [pdf("text", "notes.txt", "text/plain")], [pdf("not PDF")], [pdf(undefined, "x.pdf", "image/png")]]) {
    await assert.rejects(validatePdf(files), UploadError);
  }
  const oversized = { name: "large.pdf", type: "application/pdf", size: MAX_PDF_BYTES + 1 } as File;
  await assert.rejects(validatePdf([oversized]), /20 MiB/);
  const unreadable = { name: "locked.pdf", type: "application/pdf", size: 40, slice() { throw new Error("disk error"); } } as unknown as File;
  await assert.rejects(validatePdf([unreadable]), /could not be read/);
});

test("boundary validation rejects malformed responses and unknown statuses", () => {
  assert.deepEqual(parseUploadResponse(receipt), receipt);
  assert.deepEqual(parseJobResponse(queued), queued);
  for (const data of [null, {}, { ...receipt, status: "completed" }, { ...receipt, job_id: "" }]) assert.throws(() => parseUploadResponse(data));
  for (const patch of [{ status: "success" }, { stage: "99%" }, { message: 7 }, { error: {} }, { error: undefined }, { policy_id: null }]) assert.throws(() => parseJobResponse({ ...queued, ...patch }));
});

test("multipart form uses documented names and omits optional fields for a new policy", () => {
  const newPolicy = createUploadForm({ file: pdf() });
  assert.deepEqual([...newPolicy.keys()], ["file"]);
  const attachment = createUploadForm({ file: pdf(), policy_id: "policy-1", document_type_hint: "policy_schedule" });
  assert.deepEqual([...attachment.keys()], ["file", "policy_id", "document_type_hint"]);
  assert.equal(attachment.get("policy_id"), "policy-1");
  assert.equal(attachment.get("document_type_hint"), "policy_schedule");
});

test("API adapter sends bearer-authenticated multipart and encodes opaque job IDs", async () => {
  const original = globalThis.fetch;
  const paths: string[] = [];
  globalThis.fetch = async (input, init) => {
    paths.push(String(input));
    assert.deepEqual(init?.headers, { Authorization: "Bearer example-token" });
    if (init?.method === "POST") {
      assert.ok(init.body instanceof FormData);
      assert.equal(init.body.get("policy_id"), "policy-1");
      return Response.json(receipt, { status: 202 });
    }
    return Response.json({ ...queued, job_id: "opaque/job?1" });
  };
  try {
    const client = createApiUploadClient("https://example.test/", async () => "example-token");
    await client.upload({ file: pdf(), policy_id: "policy-1" }, signal());
    await client.getJob("opaque/job?1", signal());
    assert.deepEqual(paths, ["https://example.test/api/v1/policies/upload", "https://example.test/api/v1/jobs/opaque%2Fjob%3F1"]);
  } finally { globalThis.fetch = original; }
});

test("API adapter handles unauthorized, forbidden, oversized and throttled responses", async () => {
  const original = globalThis.fetch;
  try {
    for (const status of [401, 403, 413, 429, 500]) {
      globalThis.fetch = async () => Response.json({ error: { code: "EXAMPLE", message: "Readable example" } }, { status });
      await assert.rejects(createApiUploadClient("https://example.test", async () => "token").getJob("job-1", signal()), error => {
        assert.ok(error instanceof UploadError);
        assert.equal(error.retryable, status === 429 || status === 500);
        assert.equal(error.code, "EXAMPLE");
        return true;
      });
    }
  } finally { globalThis.fetch = original; }
});

test("missing token or pre-aborted request never reaches the network", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => { assert.fail("Network must not be called"); };
  try {
    const client = createApiUploadClient("https://example.test", async () => "");
    await assert.rejects(client.upload({ file: pdf() }, signal()), /Sign in/);
    const controller = new AbortController(); controller.abort();
    await assert.rejects(client.getJob("job-1", controller.signal), { name: "AbortError" });
  } finally { globalThis.fetch = original; }
});

test("API adapter rejects an unexpected success code, malformed JSON and wrong policy attachment", async () => {
  const original = globalThis.fetch;
  try {
    const client = createApiUploadClient("https://example.test", async () => "token");
    globalThis.fetch = async () => Response.json(receipt); // Upload requires 202, not 200.
    await assert.rejects(client.upload({ file: pdf() }, signal()), /unexpected status/);
    globalThis.fetch = async () => new Response("not-json", { status: 202 });
    await assert.rejects(client.upload({ file: pdf() }, signal()), /unreadable data/);
    globalThis.fetch = async () => Response.json(receipt, { status: 202 });
    await assert.rejects(client.upload({ file: pdf(), policy_id: "another-policy" }, signal()), /different policy/);
  } finally { globalThis.fetch = original; }
});

function fakeClient(getJob: UploadClient["getJob"]): UploadClient {
  return { mode: "mock", upload: async () => receipt, getJob };
}

test("polling stops for each terminal status, including review and failure", async () => {
  for (const status of ["completed", "needs_review", "failed"] as const) {
    let calls = 0;
    const client = fakeClient(async () => { calls++; return { ...queued, status }; });
    const result = await pollJob(client, receipt, signal(), () => {}, () => {}, { wait: noWait });
    assert.equal(result.status, status);
    assert.equal(calls, 1);
  }
});

test("a completed stage alone does not imply a completed job", async () => {
  let calls = 0;
  const client = fakeClient(async () => { calls++; return { ...queued, stage: "completed", status: "processing" }; });
  await assert.rejects(pollJob(client, receipt, signal(), () => {}, () => {}, { wait: noWait, maxAttempts: 2 }), /Completion has not been confirmed/);
  assert.equal(calls, 2);
});

test("polling rejects a status belonging to another policy or job before updating UI", async () => {
  for (const patch of [{ policy_id: "other-policy" }, { job_id: "other-job" }]) {
    await assert.rejects(pollJob(fakeClient(async () => ({ ...queued, ...patch, status: "completed" })), receipt, signal(), () => assert.fail("Do not show mismatched results"), () => {}), /different policy or job/);
  }
});

test("transient status failures back off, stop after three, and can resume without uploading again", async () => {
  let calls = 0;
  const delays: number[] = [];
  const client = fakeClient(async () => {
    if (++calls <= 3) throw new UploadError("Offline", true);
    return { ...queued, status: "completed" };
  });
  client.upload = async () => assert.fail("Never reupload while resuming status checks");
  await assert.rejects(pollJob(client, receipt, signal(), () => {}, () => {}, { wait: async ms => { delays.push(ms); } }), /Offline/);
  assert.deepEqual(delays, [4000, 8000]);
  assert.equal(calls, 3);
  assert.equal((await pollJob(client, receipt, signal(), () => {}, () => {})).status, "completed");
});

test("non-retryable status errors stop immediately", async () => {
  let calls = 0;
  await assert.rejects(pollJob(fakeClient(async () => { calls++; throw new UploadError("Forbidden", false); }), receipt, signal(), () => {}, () => {}), /Forbidden/);
  assert.equal(calls, 1);
});

test("aborting an in-flight poll prevents stale updates", async () => {
  const controller = new AbortController();
  await assert.rejects(pollJob(fakeClient(async () => { controller.abort(); return { ...queued, status: "completed" }; }), receipt, controller.signal, () => assert.fail("No update after abort"), () => {}), { name: "AbortError" });
});

test("mock scenarios are typed, attach to the requested policy, and never call fetch", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => assert.fail("Mock must stay local");
  try {
    for (const outcome of ["completed", "needs_review", "failed", "upload_error", "status_error"] as DemoOutcome[]) {
      const client = createMockUploadClient(outcome, 0);
      assert.equal(client.mode, "mock");
      if (outcome === "upload_error") await assert.rejects(client.upload({ file: pdf() }, signal()), /simulated connection/);
      const accepted = parseUploadResponse(await client.upload({ file: pdf(), policy_id: "existing-policy" }, signal()));
      assert.equal(accepted.policy_id, "existing-policy");
      if (outcome === "status_error") await assert.rejects(pollJob(client, accepted, signal(), () => {}, () => {}, { wait: noWait }), /unavailable/);
      const job = await pollJob(client, accepted, signal(), () => {}, () => {}, { wait: noWait });
      assert.equal(job.status, outcome === "upload_error" || outcome === "status_error" ? "completed" : outcome);
      assert.match(job.message!, /Demo/);
    }
  } finally { globalThis.fetch = original; }
});
