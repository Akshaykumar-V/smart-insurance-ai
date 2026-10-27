import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { calculateClaimImpact, parseInr, roundedPercentage, type ClaimScenario } from "./claim-calculator";
import { mockFamilyReport, mockPolicyDetails } from "./mock-intelligence";
import { ClaimSimulator, SimulationBreakdown } from "../components/claim-simulator";
import { createApiSimulatorClient, localSimulationClient, parseSimulatorResponse } from "./simulation-client";
import type { SimulatorRequest, SimulatorResponse } from "../../frontend_api_types";

const policy = mockPolicyDetails.find(item => item.id === mockFamilyReport.policy_id)!;
const defaultScenario: ClaimScenario = { hospitalBillPaise: 10000000, admissiblePaise: 9000000, treatmentEligiblePaise: 7000000, treatment: "Cataract", age: 65, model: "combined", confirmedFindingIds: ["fixture-copay", "fixture-sublimit"], scopeAcknowledged: true };
const calculate = (patch: Partial<ClaimScenario> = {}, report = mockFamilyReport) => calculateClaimImpact(policy, report, { ...defaultScenario, ...patch });
function breakdown(patch: Partial<ClaimScenario> = {}, report = mockFamilyReport) {
  const result = calculate(patch, report);
  assert.equal(result.status, "illustrative", JSON.stringify(result.issues));
  assert.ok(result.breakdown);
  return result.breakdown;
}
function changedRule(kind: "co_payment" | "sub_limit", patch: Record<string, unknown>) {
  return { ...mockFamilyReport, findings: mockFamilyReport.findings.map(finding => finding.condition_type === kind ? { ...finding, rule: { ...finding.rule, ...patch } } : finding) };
}

test("basic co-payment uses admissible expenses, never the entire hospital bill", () => {
  const result = breakdown({ model: "co_payment" });
  assert.equal(result.copaymentPaise, 1800000);
  assert.equal(result.outsideAdmissiblePaise, 1000000);
  assert.equal(result.modeledInsurerPaise, 7200000);
  assert.equal(result.modeledPatientPaise, 2800000);
});

test("matching sub-limit caps only the eligible treatment portion and preserves other admissible expenses", () => {
  const result = breakdown({ model: "sub_limit" });
  assert.equal(result.aboveSubLimitPaise, 2000000);
  assert.equal(result.afterSubLimitPaise, 7000000);
  assert.equal(result.modeledInsurerPaise, 7000000);
  assert.equal(result.modeledPatientPaise, 3000000);
  assert.equal(result.copaymentPaise, 0);
});

test("sub-limit is non-applicable for another treatment and needs no eligible amount or confirmation", () => {
  const result = calculate({ model: "sub_limit", treatment: "Other treatment", treatmentEligiblePaise: null, confirmedFindingIds: [] });
  assert.equal(result.status, "illustrative");
  assert.equal(result.breakdown?.aboveSubLimitPaise, 0);
  assert.equal(result.decisions[0].outcome, "not_applicable");
});

test("an eligible amount below or equal to the cap creates no above-limit portion", () => {
  for (const eligible of [0, 2000000, 5000000]) assert.equal(breakdown({ treatmentEligiblePaise: eligible }).aboveSubLimitPaise, 0);
});

test("combined cap then co-payment avoids double-counting patient liability", () => {
  const b = breakdown();
  assert.equal(b.afterSubLimitPaise, 7000000);
  assert.equal(b.copaymentPaise, 1400000);
  assert.equal(b.modeledInsurerPaise, 5600000);
  assert.equal(b.modeledPatientPaise, 4400000);
  assert.equal(b.modeledInsurerPaise + b.modeledPatientPaise, b.hospitalBillPaise);
});

test("age boundary and missing age do not silently apply co-payment", () => {
  assert.equal(breakdown({ age: 59 }).copaymentPaise, 0);
  assert.equal(breakdown({ age: 60 }).copaymentPaise, 1400000);
  assert.equal(calculate({ age: null }).status, "incomplete");
  assert.equal(calculate({ age: 59, confirmedFindingIds: ["fixture-sublimit"] }).status, "illustrative");
});

test("missing bill, admissible base, matching-treatment amount and acknowledgments produce no totals", () => {
  for (const patch of [{ hospitalBillPaise: null }, { admissiblePaise: null }, { treatmentEligiblePaise: null }, { treatment: "" }, { scopeAcknowledged: false }, { confirmedFindingIds: [] }]) {
    const result = calculate(patch);
    assert.equal(result.status, "incomplete");
    assert.equal(result.breakdown, null);
  }
});

test("negative, fractional, unsafe and nonfinite input amounts are rejected", () => {
  for (const amount of [-1, 0.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
    for (const key of ["hospitalBillPaise", "admissiblePaise", "treatmentEligiblePaise"] as const) {
      assert.equal(calculate({ [key]: amount }).status, "invalid");
    }
  }
  for (const age of [-1, 60.5, Infinity, NaN]) assert.equal(calculate({ age }).status, "invalid");
});

test("admissible cannot exceed bill and eligible treatment cannot exceed admissible", () => {
  assert.equal(calculate({ admissiblePaise: 11000000 }).status, "invalid");
  assert.equal(calculate({ treatmentEligiblePaise: 9500000 }).status, "invalid");
});

test("missing, uncertain and contradictory evidence cannot be overridden by user acknowledgment", () => {
  for (const patch of [{ status: "uncertain" as const }, { status: "not_found_after_search" as const }, { status: "not_applicable" as const }, { verification_status: "needs_review" as const }, { verification_status: "conflicting" as const }, { verification_status: "insufficient_evidence" as const }, { source: null }, { applicability: null }, { rule: null }]) {
    const report = { ...mockFamilyReport, findings: mockFamilyReport.findings.map(finding => finding.condition_type === "co_payment" ? { ...finding, ...patch } : finding) };
    const result = calculate({}, report);
    assert.equal(result.status, "insufficient_evidence");
    assert.equal(result.breakdown, null);
  }
});

test("unknown bases, scope, calculation order and additional rule conditions fail closed", () => {
  for (const [kind, patch] of [
    ["co_payment", { basis: "hospital_bill" }], ["co_payment", { percent: -1 }], ["co_payment", { percent: 101 }], ["co_payment", { percent: 1.234 }],
    ["co_payment", { minimum_age: -1 }], ["co_payment", { maximum_age: 80 }], ["co_payment", { application_order: undefined }],
    ["sub_limit", { limit_scope: "annual" }], ["sub_limit", { amount_paise: -1 }], ["sub_limit", { basis: "entire_bill" }], ["sub_limit", { treatment_label: "" }],
  ] as const) assert.equal(calculate({}, changedRule(kind, patch)).status, "insufficient_evidence");
});

test("conflicting candidates, missing rules, wrong policies and unsupported categories yield no financial result", () => {
  assert.equal(calculate({}, { ...mockFamilyReport, findings: [] }).status, "insufficient_evidence");
  assert.equal(calculate({}, { ...mockFamilyReport, findings: [...mockFamilyReport.findings, { ...mockFamilyReport.findings[2], id: "another-copay" }] }).status, "insufficient_evidence");
  assert.equal(calculate({}, { ...mockFamilyReport, policy_id: "another-policy" }).status, "insufficient_evidence");
  assert.equal(calculateClaimImpact({ ...policy, category: "vehicle" }, mockFamilyReport, defaultScenario).status, "insufficient_evidence");
});

test("missing or invalid source pages prevent calculations", () => {
  const co = mockFamilyReport.findings.find(f => f.condition_type === "co_payment")!;
  for (const patch of [{ document_id: "unrelated" }, { page: 0 }, { page: 999 }, { quote: "" }]) {
    const report = { ...mockFamilyReport, findings: mockFamilyReport.findings.map(f => f === co ? { ...f, source: { ...f.source!, ...patch } } : f) };
    assert.equal(calculate({}, report).status, "insufficient_evidence");
  }
  const unknownPages = { ...policy, documents: policy.documents.map(doc => ({ ...doc, page_count: null })) };
  assert.equal(calculateClaimImpact(unknownPages, mockFamilyReport, defaultScenario).status, "insufficient_evidence");
});

test("rounding uses exact percentages and half-up to the nearest paise", () => {
  assert.equal(roundedPercentage(1, 50), 1);
  assert.equal(roundedPercentage(1, 49.99), 0);
  assert.equal(roundedPercentage(101, 12.5), 13);
  assert.equal(roundedPercentage(101, 0), 0);
  assert.equal(roundedPercentage(101, 100), 101);
  assert.equal(roundedPercentage(Number.MAX_SAFE_INTEGER, 100), Number.MAX_SAFE_INTEGER);
  assert.throws(() => roundedPercentage(10, 100.01));
  assert.throws(() => roundedPercentage(1.1, 10));
});

test("zero amounts, zero cap and maximum co-payment preserve bounded shares", () => {
  const empty = breakdown({ hospitalBillPaise: 0, admissiblePaise: 0, treatmentEligiblePaise: 0 });
  assert.equal(empty.modeledInsurerPaise + empty.modeledPatientPaise, 0);
  const noCapAllowance = breakdown({}, changedRule("sub_limit", { amount_paise: 0 }));
  assert.equal(noCapAllowance.aboveSubLimitPaise, 7000000);
  const fullShare = breakdown({}, changedRule("co_payment", { percent: 100 }));
  assert.equal(fullShare.modeledInsurerPaise, 0);
  assert.equal(fullShare.modeledPatientPaise, 10000000);
});

test("calculation invariants hold across a deterministic grid of fractional rupee cases", () => {
  for (const bill of [0, 1, 101, 9999, 10000001, Number.MAX_SAFE_INTEGER]) {
    for (const percent of [0, 0.01, 12.5, 20, 100]) {
      const admissible = Math.floor(bill * 0.8);
      const eligible = Math.floor(admissible * 0.7);
      const b = breakdown({ hospitalBillPaise: bill, admissiblePaise: admissible, treatmentEligiblePaise: eligible }, changedRule("co_payment", { percent }));
      assert.equal(b.modeledInsurerPaise + b.modeledPatientPaise, bill);
      assert.equal(b.outsideAdmissiblePaise + b.aboveSubLimitPaise + b.copaymentPaise, b.modeledPatientPaise);
      assert.ok(b.copaymentPaise <= b.afterSubLimitPaise);
      assert.ok(b.aboveSubLimitPaise <= eligible);
      for (const amount of [b.modeledInsurerPaise, b.modeledPatientPaise, b.copaymentPaise, b.aboveSubLimitPaise]) assert.ok(Number.isSafeInteger(amount) && amount >= 0 && amount <= bill);
    }
  }
});

test("INR input conversion is exact and accepts valid Indian or international grouping", () => {
  for (const [text, amount] of [["1,00,000.50", 10000050], ["100,000.50", 10000050], ["0.01", 1], ["12.5", 1250], ["0001.02", 102], [" 0 ", 0]] as const) assert.deepEqual(parseInr(text), { value: amount });
  assert.deepEqual(parseInr(""), { value: null });
  for (const text of ["-1", "1e3", "NaN", "Infinity", "1.001", "1,2", "1.2.3", "₹100", "9999999999999999", "1."]) assert.ok(parseInr(text).error, text);
});

test("calculation is deterministic and does not mutate policy, report or inputs", () => {
  const before = JSON.stringify([policy, mockFamilyReport, defaultScenario]);
  assert.deepEqual(calculate(), calculate());
  assert.equal(JSON.stringify([policy, mockFamilyReport, defaultScenario]), before);
});

test("result keeps outside-model conflicts and review assumptions visible and links applied rules", () => {
  const result = calculate();
  assert.equal(result.status, "illustrative");
  if (result.status !== "illustrative") return;
  const html = renderToStaticMarkup(<SimulationBreakdown result={result} />);
  assert.match(html, /Deductible references need reconciliation/);
  assert.match(html, /remains flagged for review/);
  assert.match(html, /#finding-fixture-copay/);
  assert.match(html, /illustrative PDF page/);
  assert.match(html, /Not an approved claim or a complete payout estimate/);
  assert.match(html, /<summary>Calculation and assumptions/);
  assert.match(html, /Illustrative insurer-paid amount/);
});

test("form has labeled native controls, keyboard-accessible actions and mobile input hints", () => {
  const html = renderToStaticMarkup(<ClaimSimulator policy={policy} report={mockFamilyReport} mode="mock" />);
  for (const id of ["claim-bill", "claim-admissible", "claim-model", "claim-treatment", "claim-member", "claim-age"]) {
    assert.ok(html.includes(`for="${id}"`));
    assert.ok(html.includes(`id="${id}"`));
  }
  assert.match(html, /inputMode="decimal"/);
  assert.match(html, /inputMode="numeric"/);
  assert.match(html, /type="checkbox"/);
  assert.match(html, /type="submit"/);
  assert.match(html, /<legend>/);
  assert.match(html, /aria-describedby="claim-admissible-help"/);
  assert.doesNotMatch(html, /tabindex="[1-9]/i);
});

test("empty and live-data modes do not silently run the local model", () => {
  assert.match(renderToStaticMarkup(<ClaimSimulator policy={policy} report={{ ...mockFamilyReport, findings: [] }} mode="mock" />), /No modelable findings/);
  const live = renderToStaticMarkup(<ClaimSimulator policy={policy} report={mockFamilyReport} mode="api" />);
  assert.match(live, /Live simulation is not connected/);
  assert.doesNotMatch(live, /Calculate illustrative impact/);
});

test("local adapter uses no network and supports cancellation", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => assert.fail("Local math must not call fetch or AI");
  try {
    assert.equal((await localSimulationClient.simulate(policy, mockFamilyReport, defaultScenario, new AbortController().signal)).status, "illustrative");
    const controller = new AbortController(); controller.abort();
    await assert.rejects(localSimulationClient.simulate(policy, mockFamilyReport, defaultScenario, controller.signal), { name: "AbortError" });
  } finally { globalThis.fetch = original; }
});

const serverRequest: SimulatorRequest = { insured_age: 65, estimated_admissible_expenses_paise: 9000000, treatment_label: "Cataract", room_rent_per_day_paise: null, room_days: null };
const serverResponse: SimulatorResponse = { policy_id: policy.id, status: "insufficient_evidence", scenario: serverRequest, results: [], missing_information: ["Rule not verified"], disclaimer: "Illustrative decision support; not an insurer claim decision." };

test("live adapter calls only the contracted endpoint and sends only v0.1 fields", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    assert.equal(url, "https://example.test/api/v1/policies/opaque%2Fid/simulate");
    assert.equal(init?.method, "POST");
    assert.deepEqual(init?.headers, { Authorization: "Bearer token", "Content-Type": "application/json" });
    assert.deepEqual(JSON.parse(String(init?.body)), serverRequest);
    return Response.json({ ...serverResponse, policy_id: "opaque/id" });
  };
  try {
    const result = await createApiSimulatorClient("https://example.test/", async () => "token").simulate("opaque/id", { ...serverRequest, hospitalBillPaise: 10000000 } as SimulatorRequest, new AbortController().signal);
    assert.equal(result.status, "insufficient_evidence");
    assert.deepEqual(result.results, []);
  } finally { globalThis.fetch = original; }
});

test("server response validation rejects cross-policy, negative and malformed numeric results", () => {
  assert.deepEqual(parseSimulatorResponse(serverResponse, policy.id), serverResponse);
  for (const patch of [{ policy_id: "wrong" }, { status: "approved" }, { scenario: { insured_age: -1 } }, { results: [{ condition_type: "co_payment", customer_share_paise: -1, calculation: "example", finding_id: "id" }] }, { missing_information: [null] }]) assert.throws(() => parseSimulatorResponse({ ...serverResponse, ...patch }, policy.id));
});

test("live authorization/validation errors do not fall back to fictional calculations", async () => {
  const original = globalThis.fetch;
  try {
    for (const status of [401, 403, 404, 422, 429, 500]) {
      globalThis.fetch = async () => new Response("private diagnostics", { status });
      await assert.rejects(createApiSimulatorClient("https://example.test", async () => "token").simulate(policy.id, serverRequest, new AbortController().signal));
    }
    globalThis.fetch = async () => assert.fail("No request without a token");
    await assert.rejects(createApiSimulatorClient("https://example.test", async () => "").simulate(policy.id, serverRequest, new AbortController().signal), /Sign in/);
  } finally { globalThis.fetch = original; }
});
