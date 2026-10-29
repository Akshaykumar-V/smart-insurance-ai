import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ConditionResults, ConditionExtractionWorkspace } from "../components/condition-extraction-workspace";
import { ConditionError, ConditionSession, parseConditionRun, type ConditionClient, type ConditionExtractionResponse, type ConditionViewState } from "./condition-extraction";
import { conditionFixture, createMockConditionClient, demoDocumentId, demoJobId, demoPolicyId, type DemoConditionJob } from "./mock-condition-extraction";
const identity = (job = "success") => ({ policy_id: demoPolicyId, document_id: demoDocumentId, job_id: demoJobId(job) });
const signal = () => new AbortController().signal;
const markup = (run: ConditionExtractionResponse) => renderToStaticMarkup(<ConditionResults state={{ phase: "ready", identity: run, job: null, run, error: "" }} />);
async function terminal(session: ConditionSession, job: string) {
 for (let i=0; i<3; i++) await session.load(identity(job));
 return session.getSnapshot();
}

test("condition mock success transitions queued, processing, completed with no network", async () => {
 const original = globalThis.fetch; globalThis.fetch = async () => assert.fail("Mock must not access network");
 const session = new ConditionSession(createMockConditionClient("success", 0));
 try {
  await session.extract(demoPolicyId, { document_id: demoDocumentId });
  assert.equal(session.getSnapshot().job?.status, "queued");
  await session.load(identity()); assert.equal(session.getSnapshot().job?.status, "processing");
  await session.load(identity());
  const run=session.getSnapshot().run!;
  assert.equal(run.status,"completed"); assert.equal(run.conditions.length,6);
  const html=markup(run);
  for (const label of ["Co-payments","Deductibles","Treatment-specific sub-limits","Room-rent restrictions","Waiting periods","Exclusions"]) assert.ok(html.includes(label));
  assert.match(html,/Review required/); assert.match(html,/planned passages were processed/);
  for (const condition of run.conditions) {
   assert.ok(html.includes(condition.evidence[0].quote));
   assert.ok(html.includes(`PDF page ${condition.evidence[0].page}`));
  }
  assert.match(html,/Exceptions/); assert.match(html,/Dependencies/);
  assert.doesNotMatch(html,/Simulate Claim Impact|Calculate illustrative impact/);
 } finally { globalThis.fetch=original; session.dispose(); }
});

test("incomplete and empty runs retain warnings without claiming no restrictions", async () => {
 for (const job of ["incomplete","empty"] as const) {
  const session=new ConditionSession(createMockConditionClient(job,0));
  try {
   const state=await terminal(session,job); assert.equal(state.phase,"ready");
   assert.equal(state.run?.analysis_state,"incomplete");
   const html=markup(state.run!);
   assert.match(html,/Incomplete analysis/); assert.match(html,/planned passages could not all be processed/);
   assert.match(html,/does not mean the policy has no restrictions/);
   if(job === "empty") { assert.equal(state.run?.conditions.length,0); assert.match(html,/Restrictions may still exist/); }
   else assert.equal(state.run?.rejected_candidate_count,2);
  } finally { session.dispose(); }
 }
});

test("failed extraction is not confused with empty successful analysis", async () => {
 const session=new ConditionSession(createMockConditionClient("failure",0));
 try {
  const state=await terminal(session,"failure");
  assert.equal(state.run?.status,"failed"); assert.equal(state.run?.analysis_state,null);
  assert.match(markup(state.run!),/Results unavailable for this failed run/);
 } finally { session.dispose(); }
});

test("unauthorized extraction and foreign jobs publish no condition data", async () => {
 const session=new ConditionSession(createMockConditionClient("unauthorized",0));
 try {
  await session.extract(demoPolicyId,{document_id:demoDocumentId});
  assert.equal(session.getSnapshot().phase,"error"); assert.equal(session.getSnapshot().run,null);
  assert.match(session.getSnapshot().error,/Sign-in is required/);
  await session.load(identity("unauthorized")); assert.equal(session.getSnapshot().run,null);
  await session.load({...identity(),policy_id:"foreign-policy"});
  assert.match(session.getSnapshot().error,/unavailable or you do not have access/);
  assert.equal(session.getSnapshot().run,null);
 } finally { session.dispose(); }
});

test("explicit job selection rejects stale IDs and never substitutes newest job", async () => {
 const session=new ConditionSession(createMockConditionClient("success",0));
 try {
  await session.load(identity("stale"));
  assert.equal(session.getSnapshot().phase,"error"); assert.match(session.getSnapshot().error,/Stale or mismatched/);
  await session.load(identity("missing")); assert.equal(session.getSnapshot().run,null);
  await session.load({...identity(),job_id:""}); assert.match(session.getSnapshot().error,/explicit/);
 } finally { session.dispose(); }
});

test("late responses cannot overwrite the newly selected run", async () => {
 let release!: (value:ConditionExtractionResponse)=>void;
 let started!:()=>void; const ready=new Promise<void>(resolve=>{started=resolve;});
 const client:ConditionClient={ getJob: async value => ({ policy_id: value.policy_id, job_id: value.job_id, status: "completed", stage: "completed", message: null, error: null }), mode:"mock",extract:async()=>assert.fail("No extraction during selection"),getRun: async value => value.job_id==="demo-old" ? new Promise(resolve=>{release=resolve;started();}) : conditionFixture(value,"incomplete") };
 const session=new ConditionSession(client);
 try {
  const old=session.load(identity("old"));
  await ready;
  await session.load(identity("incomplete"));
  release(conditionFixture(identity("old"),"success")); await old;
  assert.equal(session.getSnapshot().run?.job_id,demoJobId("incomplete"));
  assert.equal(session.getSnapshot().run?.analysis_state,"incomplete");
 } finally { session.dispose(); }
});

test("duplicate extraction clicks produce only one request and cleanup cancels it", async () => {
 let calls=0; let requestSignal:AbortSignal|undefined;
 const client:ConditionClient={ getJob: async value => ({ policy_id: value.policy_id, job_id: value.job_id, status: "completed", stage: "completed", message: null, error: null }), mode:"mock",extract:async (_policy,_request,scope)=>{ calls++; requestSignal=scope; return new Promise((_resolve,reject)=>scope.addEventListener("abort",()=>reject(new DOMException("Aborted","AbortError")),{once:true})); },getRun:async()=>assert.fail("Not accepted") };
 const session=new ConditionSession(client);
 const first=session.extract(demoPolicyId,{document_id:demoDocumentId});
 await session.extract(demoPolicyId,{document_id:demoDocumentId});
 assert.equal(calls,1); session.clear(); await first;
 assert.equal(requestSignal?.aborted,true); assert.equal(session.getSnapshot().phase,"idle");
});

test("condition boundary rejects ambiguous identities, malformed evidence and unreported warnings", () => {
 const fixture=conditionFixture(identity(),"success");
 for(const patch of [{policy_id:"foreign"},{document_id:"foreign"},{job_id:"foreign"},{rejected_candidate_count:-1},{analysis_state:null},{conditions:[]},{status:"queued"}]) assert.throws(()=>parseConditionRun({...fixture,...patch},identity()));
 const first=fixture.conditions[0];
 for(const patch of [{job_id:"foreign"},{document_id:"foreign"},{source_verified:false},{review_required:false},{category:"motor"},{exceptions:null},{evidence:[]},{observed_value_mentions:["unsupported number"]}])
  assert.throws(()=>parseConditionRun({...fixture,conditions:[{...first,...patch}]},identity()));
 for(const patch of [{page:0},{start:-1},{end:0},{quote:""}]) assert.throws(()=>parseConditionRun({...fixture,conditions:[{...first,evidence:[{...first.evidence[0],...patch}]}]},identity()));
 assert.throws(()=>parseConditionRun({...fixture,conditions:[first,first]},identity()));
 const incomplete=conditionFixture(identity(),"incomplete");
 assert.throws(()=>parseConditionRun({...incomplete,warning:null},identity()));
});

test("quotations remain literal and escaped with explicit physical pages", () => {
 const fixture=conditionFixture(identity(),"success");
 fixture.conditions[0].evidence[0].quote="<script>fictional</script>  original\nquotation";
 fixture.conditions[0].observed_value_mentions=[];
 const html=markup(fixture);
 assert.match(html,/&lt;script&gt;fictional&lt;\/script&gt;  original\nquotation/);
 assert.doesNotMatch(html,/<script>/); assert.match(html,/physical, 1-indexed/);
});

test("preview has explicit job controls, extraction button and no live claim", () => {
 const html=renderToStaticMarkup(<ConditionExtractionWorkspace />);
 assert.match(html,/Extract Conditions/); assert.match(html,/Explicit job_id/);
 assert.match(html,/No newest-job fallback/); assert.match(html,/no live extraction/);
 assert.match(html,/Historical warning retrieval remains a separate integration/);
 assert.doesNotMatch(html,/Source checked by app|LIVE mode/);
});

test("401 and 403 hide stale data and render safe errors", async () => {
 for(const status of [401,403]) {
  const client:ConditionClient={ getJob: async value => ({ policy_id: value.policy_id, job_id: value.job_id, status: "completed", stage: "completed", message: null, error: null }),mode:"mock",extract:async()=>assert.fail("Read only"),getRun:async()=>{throw new ConditionError("private server detail",status);}};
  const session=new ConditionSession(client); await session.load(identity());
  const state=session.getSnapshot(); assert.equal(state.run,null);
  const html=renderToStaticMarkup(<ConditionResults state={state} />);
  assert.match(html,/role="alert"/); assert.doesNotMatch(html,/private server detail/);
  session.dispose();
 }
});
