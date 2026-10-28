import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { FindingCard } from "../components/finding-card";
import { PolicyDetailsContent } from "../components/policy-details";
import { mockFamilyReport, mockPolicyDetails } from "./mock-intelligence";
import { createApiPolicyClient, mockPolicyClient } from "./policy-client";
import { conditionGroups, findingCautions, findingsAvailability, missingInformation, parseFindings, parsePolicyDetails, PolicyDataError, reportAvailability, sourceReference, type Finding } from "./policy-intelligence";

const family = mockPolicyDetails.find(policy => policy.id === "demo-health-family")!;
const individual = mockPolicyDetails.find(policy => policy.id === "demo-health-individual")!;
const finding = mockFamilyReport.findings[0];
const signal = () => new AbortController().signal;

test("all mock details match v0.1 and the report covers all six categories", () => {
  for (const policy of mockPolicyDetails) assert.deepEqual(parsePolicyDetails(policy, policy.id), policy);
  assert.deepEqual(parseFindings(mockFamilyReport, family.id), mockFamilyReport);
  assert.deepEqual(new Set(mockFamilyReport.findings.map(item => item.condition_type)), new Set(conditionGroups.map(group => group.type)));
  assert.equal(family.insured_members[1].age, null);
  assert.equal(individual.sum_insured_paise, null);
  assert.ok(mockFamilyReport.findings.every(item => item.source === null || item.source.quote.startsWith("Fictional UI fixture:")));
});

test("details boundary rejects mismatched policies, invalid members, document pages and duplicate IDs", () => {
  assert.throws(() => parsePolicyDetails(family, "another-policy"), /different policy/);
  for (const patch of [{ uin: 123 }, { insured_members: [{ name: null, age: -1 }] }, { insured_members: [{ name: "Demo", age: 3.5 }] }, { insured_members: null }, { documents: [{ ...family.documents[0], page_count: 0 }] }, { documents: [{ ...family.documents[0], type: "pdf" }] }, { documents: [family.documents[0], family.documents[0]] }]) {
    assert.throws(() => parsePolicyDetails({ ...family, ...patch }, family.id));
  }
});

test("finding boundary rejects malformed and ambiguous data, including zero-indexed pages", () => {
  assert.throws(() => parseFindings(mockFamilyReport, "another-policy"), /different policy/);
  for (const patch of [{ status: "covered" }, { condition_type: "motor" }, { verification_status: "guaranteed" }, { rule: [] }, { rule: undefined }, { exceptions: null }, { exceptions: [7] }, { applicability: 2 }, { review_required: "yes" }, { source: { ...finding.source, page: 0 } }, { source: { ...finding.source, page: 1.5 } }, { source: { ...finding.source, quote: "" } }]) {
    assert.throws(() => parseFindings({ ...mockFamilyReport, findings: [{ ...finding, ...patch }] }, family.id));
  }
  assert.throws(() => parseFindings({ ...mockFamilyReport, findings: [finding, finding] }, family.id), /ambiguous/);
});

test("unknown rule keys and null sources are preserved without doing calculations", () => {
  const rule = { future_backend_field: { basis: "unresolved" }, percent: 20 };
  const result = parseFindings({ ...mockFamilyReport, findings: [{ ...finding, rule, source: null }] }, family.id);
  assert.deepEqual(result.findings[0].rule, rule);
  assert.equal(result.findings[0].source, null);
});

test("missing schedule, dates, amount, members and processing issues remain explicit", () => {
  const warnings = missingInformation(individual).join(" ");
  assert.match(warnings, /No policy schedule/);
  assert.match(warnings, /Sum insured is not available/);
  assert.match(warnings, /policy period is not available/);
  assert.match(warnings, /member information is not available/);
  assert.match(missingInformation(family).join(" "), /ages are missing/);
  assert.match(missingInformation(family).join(" "), /require review/);
});

test("report eligibility blocks wallet-only, unknown types and nonterminal analysis", () => {
  assert.equal(reportAvailability(family).available, true);
  assert.equal(reportAvailability({ ...family, analysis_status: "needs_review" }).available, true);
  for (const patch of [{ category: "life" as const }, { category: "vehicle" as const }, { policy_type: "unknown" as const }, { policy_type: "other" as const }, ...(["not_started", "processing", "failed", "unsupported"] as const).map(analysis_status => ({ analysis_status }))]) {
    assert.equal(reportAvailability({ ...family, ...patch }).available, false);
  }
});

test("unclassified live policy can read review-required evidence without becoming analysis-eligible", () => {
  const placeholder = { ...family, category: "other" as const, policy_type: "unknown" as const, analysis_status: "needs_review" as const };
  assert.equal(reportAvailability(placeholder).available, false);
  assert.deepEqual(findingsAvailability(placeholder, "api"), {
    available: true,
    reviewOnly: true,
    title: "Extracted evidence available for review",
    message: "Policy category and type are unconfirmed. Any extracted findings shown here need review and do not establish eligibility for specialized analysis.",
  });
  assert.equal(findingsAvailability(placeholder, "mock").available, false);
  for (const patch of [{ category: "life" as const }, { category: "vehicle" as const }, { policy_type: "other" as const }, { analysis_status: "unsupported" as const }, { analysis_status: "processing" as const }, { analysis_status: "failed" as const }]) {
    assert.equal(findingsAvailability({ ...placeholder, ...patch }, "api").available, false);
  }
});

test("source references require a matching policy document and an in-range page", () => {
  assert.equal(sourceReference(finding, family.documents).available, true);
  assert.equal(sourceReference({ ...finding, source: null }, family.documents).available, false);
  assert.equal(sourceReference(finding, []).available, false);
  assert.equal(sourceReference({ ...finding, source: { ...finding.source!, page: 99 } }, family.documents).available, false);
  assert.equal(sourceReference(finding, [{ ...family.documents[0], page_count: null }]).available, true);
});

test("finding cards explain not-found and absent exceptions without guaranteeing coverage", () => {
  const notFound = mockFamilyReport.findings.find(item => item.status === "not_found_after_search")!;
  const html = renderToStaticMarkup(<FindingCard finding={notFound} documents={family.documents} mode="mock" />);
  assert.match(html, /Not found in the searched material does not mean covered/);
  assert.match(html, /No exceptions were returned/);
  assert.match(html, /No source quote or page was returned/);
  assert.match(html, /Fictional AI interpretation/);
  assert.doesNotMatch(html, /Inspect source reference/);
});

test("live finding cards display backend rule values, applicability, source attribution and review status", () => {
  const copay: Finding = {
    ...finding,
    id: "live-copay",
    condition_type: "co_payment",
    verification_status: "needs_review",
    review_required: true,
    rule: { percent: 20, basis: "admissible expenses" },
    applicability: "Age 60 and above.",
    source: { document_id: family.documents[0].id, page: 1, quote: "A co-payment of 20% applies to admissible expenses." },
  };
  const copayHtml = renderToStaticMarkup(<FindingCard finding={copay} documents={family.documents} mode="api" />);
  assert.match(copayHtml, /Condition/);
  assert.match(copayHtml, /Co-payment/);
  assert.match(copayHtml, /20%/);
  assert.match(copayHtml, /When this may apply/);
  assert.match(copayHtml, /Age 60 and above/);
  assert.match(copayHtml, /A co-payment of 20% applies to admissible expenses/);
  assert.match(copayHtml, /PDF page 1/);
  assert.match(copayHtml, /Needs review/);
  assert.match(copayHtml, /flagged for review/);

  const subLimit: Finding = {
    ...copay,
    id: "live-cataract",
    condition_type: "sub_limit",
    rule: { amount_paise: 4_000_000, treatment: "Cataract", basis: "per policy year" },
    applicability: "Cataract treatment only.",
    source: { document_id: family.documents[0].id, page: 2, quote: "Cataract treatment is limited to INR 40,000." },
  };
  const subLimitHtml = renderToStaticMarkup(<FindingCard finding={subLimit} documents={family.documents} mode="api" />);
  assert.match(subLimitHtml, /Treatment sub-limit/);
  assert.match(subLimitHtml, /Cataract: ₹40,000/);
  assert.match(subLimitHtml, /PDF page 2/);
  assert.match(subLimitHtml, /Needs review/);
});

test("conflicting and verified-but-review-required findings retain their cautions", () => {
  const conflict = mockFamilyReport.findings.find(item => item.verification_status === "conflicting")!;
  assert.match(renderToStaticMarkup(<FindingCard finding={conflict} documents={family.documents} mode="mock" />), /evidence conflicts/);
  const verifiedReview = { ...finding, review_required: true };
  const html = renderToStaticMarkup(<FindingCard finding={verifiedReview} documents={family.documents} mode="api" />);
  assert.match(html, /Source checked by app/);
  assert.match(html, /flagged for review/);
  assert.match(html, /not insurer certification/);
});

test("unmatched evidence is not displayed as an original quote even if verification says verified", () => {
  const html = renderToStaticMarkup(<FindingCard finding={finding} documents={[]} mode="api" />);
  assert.match(html, /could not be matched/);
  assert.doesNotMatch(html, /Fictional UI fixture:/);
  assert.doesNotMatch(html, /Inspect source reference/);
});

test("source text is escaped and separated from interpretation", () => {
  const unsafe: Finding = { ...finding, source: { ...finding.source!, quote: "<script>alert('fixture')</script>" } };
  const html = renderToStaticMarkup(<FindingCard finding={unsafe} documents={family.documents} mode="api" />);
  assert.match(html, /AI interpretation/);
  assert.match(html, /Original policy evidence/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /PDF page/);
});

test("reported non-applicability is explicitly limited to supplied context", () => {
  assert.match(findingCautions({ ...finding, status: "not_applicable" }).join(" "), /not a coverage guarantee/);
});

test("details render unknowns and fictional members without inventing ages or dates", () => {
  const sparse = renderToStaticMarkup(<PolicyDetailsContent policy={individual} mode="mock" />);
  assert.match(sparse, /Member details are not available/);
  assert.match(sparse, /Page count unknown/);
  assert.match(sparse, /Not available/);
  const full = renderToStaticMarkup(<PolicyDetailsContent policy={family} mode="mock" />);
  assert.match(full, /Age not available/);
  assert.match(full, /fictional member/);
  assert.match(full, /\/policies\/demo-health-family\/findings/);
});

test("API adapter uses only documented endpoints, bearer tokens and encoded IDs", async () => {
  const original = globalThis.fetch;
  const paths: string[] = [];
  const id = "opaque/policy?1";
  globalThis.fetch = async (input, init) => {
    paths.push(String(input));
    assert.deepEqual(init?.headers, { Authorization: "Bearer fixture-token" });
    assert.equal(init?.cache, "no-store");
    return Response.json(String(input).endsWith("/findings") ? { ...mockFamilyReport, policy_id: id } : { ...family, id });
  };
  try {
    const client = createApiPolicyClient("https://example.test/", async () => "fixture-token");
    await client.getPolicy(id, signal());
    await client.getFindings(id, signal());
    assert.deepEqual(paths, ["https://example.test/api/v1/policies/opaque%2Fpolicy%3F1", "https://example.test/api/v1/policies/opaque%2Fpolicy%3F1/findings"]);
  } finally { globalThis.fetch = original; }
});

test("API adapter handles unauthorized, forbidden, missing and unavailable reports", async () => {
  const original = globalThis.fetch;
  try {
    for (const status of [401, 403, 404, 429, 500]) {
      globalThis.fetch = async () => new Response("private server details", { status });
      await assert.rejects(createApiPolicyClient("https://example.test", async () => "token").getFindings(family.id, signal()), error => {
        assert.ok(error instanceof PolicyDataError);
        assert.equal(error.status, status);
        assert.doesNotMatch(error.message, /private server details/);
        return true;
      });
    }
  } finally { globalThis.fetch = original; }
});

test("API adapter rejects malformed and cross-policy responses", async () => {
  const original = globalThis.fetch;
  const client = createApiPolicyClient("https://example.test", async () => "token");
  try {
    globalThis.fetch = async () => new Response("not-json");
    await assert.rejects(client.getPolicy(family.id, signal()), /unreadable/);
    globalThis.fetch = async () => Response.json({ ...family, id: "other" });
    await assert.rejects(client.getPolicy(family.id, signal()), /different policy/);
    globalThis.fetch = async () => Response.json({ ...mockFamilyReport, policy_id: "other" });
    await assert.rejects(client.getFindings(family.id, signal()), /different policy/);
  } finally { globalThis.fetch = original; }
});

test("missing token and cancelled requests never reach fetch", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => assert.fail("Network should not be called");
  try {
    const client = createApiPolicyClient("https://example.test", async () => "");
    await assert.rejects(client.getPolicy(family.id, signal()), /Sign in/);
    const controller = new AbortController(); controller.abort();
    await assert.rejects(client.getFindings(family.id, controller.signal), { name: "AbortError" });
  } finally { globalThis.fetch = original; }
});

test("mock adapter returns isolated fixtures and explicit not-found errors without network access", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => assert.fail("Mocks must not use the network");
  try {
    const policy = await mockPolicyClient.getPolicy(family.id, signal());
    policy.documents.length = 0;
    assert.ok(family.documents.length > 0);
    assert.equal((await mockPolicyClient.getFindings(family.id, signal())).findings.length, 6);
    assert.equal((await mockPolicyClient.getFindings(individual.id, signal())).findings.length, 0);
    await assert.rejects(mockPolicyClient.getPolicy("missing", signal()), error => error instanceof PolicyDataError && error.status === 404);
    const controller = new AbortController(); controller.abort();
    await assert.rejects(mockPolicyClient.getPolicy(family.id, controller.signal), { name: "AbortError" });
  } finally { globalThis.fetch = original; }
});
