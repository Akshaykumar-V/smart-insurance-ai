import { test } from "node:test";
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

