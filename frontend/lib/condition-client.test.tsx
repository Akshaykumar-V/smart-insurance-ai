import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createApiConditionClient } from "./condition-client";
import { ConditionError, ConditionSession, parseConditionRun } from "./condition-extraction";
import { conditionFixture, demoPolicyId, demoDocumentId, demoJobId } from "./mock-condition-extraction";
import { ConditionExtractionWorkspace, ConditionResults } from "../components/condition-extraction-workspace";
const identity = { policy_id: demoPolicyId, document_id: demoDocumentId, job_id: demoJobId("success") };
const signal = () => new AbortController().signal;
const receipt = { ...identity, status: "queued" as const };
const job = { policy_id: identity.policy_id, job_id: identity.job_id, status: "completed" as const, stage: "completed" as const, message: "Analysis context retained.", error: null };

test("API adapter sends only agreed methods, JSON and explicit job IDs with fresh tokens", async () => {
 const original = globalThis.fetch; const calls: string[] = []; let token = "first-fictional-token";
 globalThis.fetch = async (url, init) => {
  const path = String(url); calls.push(path);
  assert.equal((init?.headers as Record<string,string>).Authorization, `Bearer ${token}`);
  assert.equal(init?.cache,"no-store");
  if(init?.method === "POST") {
   assert.equal((init.headers as Record<string,string>)["Content-Type"],"application/json");
   assert.deepEqual(JSON.parse(String(init.body)),{document_id:identity.document_id});
   return Response.json({...receipt,status:"completed"},{status:202});
  }
  return Response.json(path.includes("/jobs/") ? job : conditionFixture(identity,"success"));
 };
 try {
  const client=createApiConditionClient("https://example.test/",async()=>token);
  assert.equal((await client.extract(identity.policy_id,{document_id:identity.document_id},signal())).status,"completed");
  token="rotated-fictional-token"; assert.deepEqual(await client.getJob(identity,signal()),job);
  assert.equal((await client.getRun(identity,signal())).conditions.length,6);
  assert.deepEqual(calls,[`https://example.test/api/v1/policies/${identity.policy_id}/condition-extractions`,`https://example.test/api/v1/jobs/${identity.job_id}`,`https://example.test/api/v1/policies/${identity.policy_id}/conditions?job_id=${identity.job_id}`]);
 } finally { globalThis.fetch=original; }
});

test("every duplicate-start JobStatus is accepted without issuing a second POST", async () => {
 const original=globalThis.fetch; let calls=0;
 try {
  const client=createApiConditionClient("https://example.test",async()=>"fictional-token");
  for(const status of ["queued","processing","completed","failed","needs_review"] as const) {
   globalThis.fetch=async()=>{calls++;return Response.json({...receipt,status},{status:202});};
   assert.equal((await client.extract(identity.policy_id,{document_id:identity.document_id},signal())).status,status);
  }
  assert.equal(calls,5);
 } finally {globalThis.fetch=original;}
});

test("API HTTP failures never expose server text or fall back to fictional results", async () => {
 const original=globalThis.fetch;
 try {
  const client=createApiConditionClient("https://example.test",async()=>"fictional-token");
  for(const status of [401,403,404,429,500]) {
   globalThis.fetch=async()=>new Response("private server text",{status});
   for(const request of [()=>client.extract(identity.policy_id,{document_id:identity.document_id},signal()),()=>client.getJob(identity,signal()),()=>client.getRun(identity,signal())]) {
    await assert.rejects(request(),e=>{ assert.ok(e instanceof Error); assert.equal((e as {status?:number}).status,status); assert.doesNotMatch(e.message,/private server text/);return true; });
   }
  }
 } finally {globalThis.fetch=original;}
});

test("network failure leaves extraction acceptance unknown and never retries POST", async () => {
 const original=globalThis.fetch; let calls=0;
 globalThis.fetch=async()=>{calls++;throw new TypeError("private network diagnostics");};
 try {
  const session=new ConditionSession(createApiConditionClient("https://example.test",async()=>"fictional-token"));
  await session.extract(identity.policy_id,{document_id:identity.document_id});
  assert.equal(calls,1); assert.equal(session.getSnapshot().run,null);
  assert.match(session.getSnapshot().error,/acceptance is unconfirmed/);
  assert.doesNotMatch(session.getSnapshot().error,/private network diagnostics/); session.dispose();
 } finally {globalThis.fetch=original;}
});

test("invalid IDs, missing tokens and cancellation during token acquisition send zero requests", async () => {
 const original=globalThis.fetch; globalThis.fetch=async()=>assert.fail("Must not fetch");
 try {
  const client=createApiConditionClient("https://example.test",async()=>"");
  await assert.rejects(client.getRun({...identity,job_id:""},signal()),/UUIDs/);
  await assert.rejects(client.getRun(identity,signal()),/Sign in/);
  const controller=new AbortController();
  const cancelled=createApiConditionClient("https://example.test",async()=>{controller.abort();return "fictional-token";});
  await assert.rejects(cancelled.extract(identity.policy_id,{document_id:identity.document_id},controller.signal),{name:"AbortError"});
 } finally {globalThis.fetch=original;}
});

test("API validates malformed and wrong-run responses instead of replacing them", async () => {
 const original=globalThis.fetch;
 try {
  const client=createApiConditionClient("https://example.test",async()=>"fictional-token");
  globalThis.fetch=async()=>new Response("not JSON"); await assert.rejects(client.getRun(identity,signal()),/unreadable/);
  globalThis.fetch=async()=>Response.json({...job,job_id:demoJobId("failure")}); await assert.rejects(client.getJob(identity,signal()),/mismatched/);
  globalThis.fetch=async()=>Response.json(conditionFixture({...identity,job_id:demoJobId("failure")},"success")); await assert.rejects(client.getRun(identity,signal()),/mismatched/);
  globalThis.fetch=async()=>Response.json(receipt); await assert.rejects(client.extract(identity.policy_id,{document_id:identity.document_id},signal()),/unexpected response status/);
  globalThis.fetch=async()=>Response.json({...receipt,document_id:demoPolicyId},{status:202}); await assert.rejects(client.extract(identity.policy_id,{document_id:identity.document_id},signal()),/Acceptance is unconfirmed/);
 } finally {globalThis.fetch=original;}
});

test("final schema normalizes omitted dependency labels and rejects unknown keys", () => {
 const fixture=conditionFixture(identity,"success");
 const raw=structuredClone(fixture) as unknown as {conditions:{dependencies:unknown[]}[]};
 raw.conditions[0].dependencies=[{kind:"endorsement"}];
 assert.deepEqual(parseConditionRun(raw,identity).conditions[0].dependencies,[{kind:"endorsement",label:null}]);
 for(const dependency of [{kind:"invented",label:null},{kind:"policy_schedule",label:4},{kind:"other_clause",label:null,extra:"bad"},"schedule"]) {
  raw.conditions[0].dependencies=[dependency]; assert.throws(()=>parseConditionRun(raw,identity),ConditionError);
 }
});

test("final evidence and status invariants match backend limits", () => {
 const fixture=conditionFixture(identity,"success"); const first=fixture.conditions[0];
 for(const kind of ["benefit","restriction","condition","definition","procedural_requirement","other"]) assert.doesNotThrow(()=>parseConditionRun({...fixture,conditions:[{...first,kind}]},identity));
 assert.throws(()=>parseConditionRun({...fixture,conditions:[{...first,kind:"fictional_clause"}]},identity));
 for(const evidence of [Array(7).fill(first.evidence[0]),[{...first.evidence[0],page:201}],[{...first.evidence[0],quote:"short"}]]) assert.throws(()=>parseConditionRun({...fixture,conditions:[{...first,evidence}]},identity));
 const failed=conditionFixture(identity,"failure"); assert.equal(parseConditionRun(failed,identity).analysis_state,null);
 assert.throws(()=>parseConditionRun({...failed,warning:null},identity));
 for(const status of ["queued","processing"]) assert.doesNotThrow(()=>parseConditionRun({...fixture,status,analysis_state:null,conditions:[]},identity));
});

test("session polls job status and retains warnings before loading only terminal conditions", async () => {
 const original=globalThis.fetch; const paths:string[]=[]; let reads=0;
 globalThis.fetch=async url=>{
  const path=String(url); paths.push(path);
  return Response.json(path.includes("/jobs/") ? {...job,status:reads++ ? "needs_review" : "processing",message:"Incomplete evidence needs review."} : conditionFixture(identity,"incomplete"));
 };
 try {
  const session=new ConditionSession(createApiConditionClient("https://example.test",async()=>"fictional-token"));
  await session.load(identity); assert.equal(session.getSnapshot().job?.status,"processing"); assert.equal(paths.length,1);
  assert.match(renderToStaticMarkup(<ConditionResults state={session.getSnapshot()} mode="api" />),/Incomplete evidence needs review/);
  await session.load(identity); assert.equal(session.getSnapshot().run?.analysis_state,"incomplete");
  assert.equal(paths.length,3);
  const html=renderToStaticMarkup(<ConditionResults state={session.getSnapshot()} mode="api" />);
  assert.match(html,/Incomplete analysis/); assert.doesNotMatch(html,/fictional fixture/);
  session.dispose();
 } finally {globalThis.fetch=original;}
});

test("live workspace never offers fixture scenarios or fictional IDs", () => {
 const client=createApiConditionClient("https://example.test",async()=>"fictional-token");
 const html=renderToStaticMarkup(<ConditionExtractionWorkspace client={client} />);
 assert.match(html,/LIVE mode/); assert.match(html,/Policy ID \(UUID\)/);
 assert.doesNotMatch(html,/Fictional extraction outcome|<datalist|fictional fixtures|fictional-passage|Typed mock preview/);
});

test("local cancellation can resume reads without resending extraction", async () => {
 const original=globalThis.fetch; let calls=0;
 globalThis.fetch=async (_url,init)=>{calls++;return new Promise<Response>((_resolve,reject)=>init?.signal?.addEventListener("abort",()=>reject(new DOMException("Aborted","AbortError")),{once:true}));};
 try {
  const session=new ConditionSession(createApiConditionClient("https://example.test",async()=>"fictional-token"));
  const load=session.load(identity); await new Promise(resolve=>setTimeout(resolve,0)); session.pause(); await load;
  assert.equal(session.getSnapshot().phase,"ready"); assert.equal(session.getSnapshot().run,null);
  const resumedMethods: string[]=[];
  globalThis.fetch=async(url,init)=>{resumedMethods.push(init?.method ?? "GET");return Response.json(String(url).includes("/jobs/") ? job : conditionFixture(identity,"success"));};
  await session.load(identity); assert.equal(calls,1);
  assert.deepEqual(resumedMethods,["GET","GET"]);
  assert.equal(session.getSnapshot().run?.conditions.length,6); session.dispose();
 } finally {globalThis.fetch=original;}
});

test("POST timeout aborts once, keeps acceptance unknown and cleans up", async t => {
 const original=globalThis.fetch; let started!:()=>void; let calls=0;
 const ready=new Promise<void>(resolve=>{started=resolve;});
 t.mock.timers.enable({apis:["setTimeout"]});
 globalThis.fetch=async(_url,init)=>new Promise<Response>((_resolve,reject)=>{calls++;init?.signal?.addEventListener("abort",()=>reject(new DOMException("Aborted","AbortError")),{once:true});started();});
 try {
  const client=createApiConditionClient("https://example.test",async()=>"fictional-token");
  const rejected=assert.rejects(client.extract(identity.policy_id,{document_id:identity.document_id},signal()),/acceptance is unconfirmed/);
  await ready;t.mock.timers.tick(30_000);await rejected;assert.equal(calls,1);
 } finally {globalThis.fetch=original;t.mock.timers.reset();}
});


test("evidence quote minimum is measured in Unicode code points without rewriting text", () => {
 const fixture=conditionFixture(identity,"success");
 const condition=fixture.conditions[0];condition.observed_value_mentions=[];
 condition.evidence[0].quote=String.fromCodePoint(0x1F600).repeat(6);
 assert.throws(()=>parseConditionRun(fixture,identity),/evidence offsets/);
 condition.evidence[0].quote=String.fromCodePoint(0x1F600).repeat(12);
 condition.evidence[0].end=12;
 assert.equal(parseConditionRun(fixture,identity).conditions[0].evidence[0].quote,condition.evidence[0].quote);
});

test("unreadable acceptance cannot be retried implicitly and later GET failure clears old results", async () => {
 const original=globalThis.fetch;let calls=0;
 try {
  const client=createApiConditionClient("https://example.test",async()=>"fictional-token");
  globalThis.fetch=async()=>{calls++;return Response.json({...receipt,job_id:"not-a-job-uuid"},{status:202});};
  await assert.rejects(client.extract(identity.policy_id,{document_id:identity.document_id},signal()),/Acceptance is unconfirmed/);assert.equal(calls,1);
  const session=new ConditionSession(client);
  globalThis.fetch=async url=>Response.json(String(url).includes("/jobs/")?job:conditionFixture(identity,"success"));
  await session.load(identity);assert.equal(session.getSnapshot().run?.conditions.length,6);
  globalThis.fetch=async()=>{throw new TypeError("offline");};
  await session.load(identity);assert.equal(session.getSnapshot().run,null);assert.equal(session.getSnapshot().phase,"error");
  session.dispose();
 } finally {globalThis.fetch=original;}
});
