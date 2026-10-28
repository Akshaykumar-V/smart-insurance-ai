import { PolicyDataError } from "./policy-intelligence";
﻿import { test } from "node:test";
import assert from "node:assert/strict";
import { parsePolicyList, formatMoney } from "./policies";
import { mockPolicies } from "./mock-policies";
import { createApiWalletClient, mockWalletClient } from "./wallet-client";
test("fictional fixtures match v0.1 and preserve unknown schedule fields", () => {
 const result = parsePolicyList(mockPolicies);
 assert.equal(result.items[1].sum_insured_paise, null);
 assert.equal(result.items[1].end_date, null);
 assert.ok(result.items.filter(p => p.category !== "health").every(p => p.analysis_status === "unsupported"));
});
test("reject invalid money, enums and missing fields at boundary", () => {
 for (const patch of [{ sum_insured_paise: 1.5 }, { sum_insured_paise: -10 }, { category: "motor" }, { analysis_status: "covered" }, { needs_review: undefined }, { end_date: "unknown" }]) {
  assert.throws(() => parsePolicyList({ items: [{ ...mockPolicies.items[0], ...patch }], next_cursor: null }));
 }
 assert.throws(() => parsePolicyList({ items: [], next_cursor: 1 }));
});
test("money formatting converts paise for display and preserves unknown", () => {
 assert.equal(formatMoney(null), "Not available"); assert.equal(formatMoney(12345), "₹123.45");
 assert.equal(formatMoney(100000000), "₹10,00,000");
});
test("mock request supports cancellation", async () => {
 const controller = new AbortController(); controller.abort();
 await assert.rejects(mockWalletClient.listPolicies(controller.signal), { name: "AbortError" });
});
test("real client uses contract path and bearer authentication", async () => {
 const original = globalThis.fetch;
 globalThis.fetch = async (input, init) => {
  assert.equal(input, "https://example.test/api/v1/policies");
  assert.equal((init?.headers as Record<string, string>).Authorization, "Bearer demo-token");
  return new Response(JSON.stringify(mockPolicies));
 };
 try { assert.deepEqual(await createApiWalletClient("https://example.test/", async () => "demo-token").listPolicies(), mockPolicies); }
 finally { globalThis.fetch = original; }
});
test("real client stops unauthenticated requests", async () => {
 await assert.rejects(createApiWalletClient("https://example.test", async () => "").listPolicies(), /Sign in/);
});


test("wallet reader rejects HTTP failures, malformed JSON and unconfirmed response shapes", async () => {
 const original = globalThis.fetch;
 const client = createApiWalletClient("https://example.test", async () => "fictional-token");
 try {
  for (const status of [401, 403, 404, 429, 500]) {
   globalThis.fetch = async () => new Response("private server details", { status });
   await assert.rejects(client.listPolicies(), error => {
    assert.ok(error instanceof PolicyDataError);
    assert.equal(error.status, status);
    assert.doesNotMatch(error.message, /private server details/);
    return true;
   });
  }
  globalThis.fetch = async () => new Response(null, { status: 204 });
  await assert.rejects(client.listPolicies(), /unexpected response status/);
  globalThis.fetch = async () => new Response("not json");
  await assert.rejects(client.listPolicies(), /unreadable/);
  for (const body of [mockPolicies.items, { policies: mockPolicies.items }, { items: [] }]) {
   globalThis.fetch = async () => Response.json(body);
   await assert.rejects(client.listPolicies());
  }
  globalThis.fetch = async () => Response.json({ items: [], next_cursor: null });
  assert.deepEqual(await client.listPolicies(), { items: [], next_cursor: null });
 } finally { globalThis.fetch = original; }
});

test("wallet cancellation while obtaining a token prevents the network request", async () => {
 const original = globalThis.fetch;
 const controller = new AbortController();
 globalThis.fetch = async () => assert.fail("Cancelled wallet must not fetch");
 try {
  const client = createApiWalletClient("https://example.test", async () => { controller.abort(); return "fictional-token"; });
  await assert.rejects(client.listPolicies(controller.signal), { name: "AbortError" });
 } finally { globalThis.fetch = original; }
});


test("wallet timeout aborts the request and returns a safe error", async (t) => {
 const original = globalThis.fetch;
 t.mock.timers.enable({ apis: ["setTimeout"] });
 let started!: () => void;
 const ready = new Promise<void>(resolve => { started = resolve; });
 let requestSignal: AbortSignal | null | undefined;
 globalThis.fetch = async (_url, init) => new Promise<Response>((_resolve, reject) => {
  requestSignal = init?.signal;
  requestSignal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
  started();
 });
 try {
  const client = createApiWalletClient("https://example.test", async () => "fictional-token");
  const rejected = assert.rejects(client.listPolicies(), /timed out or the connection was interrupted/);
  await ready;
  t.mock.timers.tick(30_000);
  await rejected;
  assert.equal(requestSignal?.aborted, true);
 } finally { globalThis.fetch = original; t.mock.timers.reset(); }
});

test("wallet cancellation during JSON parsing rejects the late response", async () => {
 const original = globalThis.fetch;
 const controller = new AbortController();
 const response = Response.json(mockPolicies);
 response.json = async () => { controller.abort(); return mockPolicies; };
 globalThis.fetch = async () => response;
 try {
  const client = createApiWalletClient("https://example.test", async () => "fictional-token");
  await assert.rejects(client.listPolicies(controller.signal), { name: "AbortError" });
 } finally { globalThis.fetch = original; }
});
