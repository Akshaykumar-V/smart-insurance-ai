import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { parseAppConfig, type LiveConfig } from "./app-config";
import { AuthSessionController, AuthRequiredError, type AuthPort, type AuthSession } from "./auth-session";
import { createLiveClients } from "./live-clients";
import { pollJob } from "./poll-job";
import { SignInForm } from "../components/app-entry";
import { LiveWorkspace } from "../components/live-workspace";
import { mockPolicyDetails, mockFamilyReport } from "./mock-intelligence";
import { createClient } from "@supabase/supabase-js";

const env = { NEXT_PUBLIC_APP_MODE: "live", NEXT_PUBLIC_SUPABASE_URL: "https://project.supabase.co", NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "sb_publishable_test_only", NEXT_PUBLIC_BACKEND_ORIGIN: "http://192.168.1.40:8000" };
const config = parseAppConfig(env) as LiveConfig;
const session = (id = "owner-a", token = "fictional-token", expires = 2000): AuthSession => ({ user: { id, email: "fictional@example.test" }, access_token: token, expires_at: expires });
function fakeAuth(initial: AuthSession | null = session()) {
  let current = initial;
  let listener: ((event: string, session: AuthSession | null) => void) | undefined;
  const counters = { refresh: 0, unsubscribe: 0 };
  const auth: AuthPort = {
    getSession: async () => ({ data: { session: current }, error: null }),
    refreshSession: async () => { counters.refresh++; current = session(current?.user.id, "refreshed-token"); return { data: { session: current }, error: null }; },
    signInWithPassword: async input => { assert.equal(input.email, "fictional@example.test"); current = session(); return { data: { session: current }, error: null }; },
    signOut: async options => { assert.equal(options.scope, "local"); current = null; listener?.("SIGNED_OUT", null); return { error: null }; },
    onAuthStateChange: callback => { listener = callback; return { data: { subscription: { unsubscribe: () => { counters.unsubscribe++; listener = undefined; } } } }; },
  };
  const controller = new AuthSessionController(auth, () => 1000);
  return { auth, controller, counters, emit(value: AuthSession | null) { current = value; listener?.(value ? "SIGNED_IN" : "SIGNED_OUT", value); } };
}
const signal = () => new AbortController().signal;
const receipt = { policy_id: "opaque/policy", document_id: "doc-a", job_id: "job-a", status: "queued" as const };
const pdf = () => new File(["%PDF-1.7\nfictional"], "fictional.pdf", { type: "application/pdf" });

test("demo is default and ignores incomplete live configuration; misspelled mode fails closed", () => {
  assert.deepEqual(parseAppConfig({}), { mode: "demo" });
  assert.deepEqual(parseAppConfig({ ...env, NEXT_PUBLIC_APP_MODE: "DEMO", NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "" }), { mode: "demo" });
  assert.throws(() => parseAppConfig({ ...env, NEXT_PUBLIC_APP_MODE: "lve" }), /demo or live/);
});

test("live configuration requires public settings and supports explicit Laptop 1 private LAN origins", () => {
  assert.equal(config.backendOrigin, "http://192.168.1.40:8000");
  assert.equal(config.policyReadsEnabled, false);
  for (const key of ["NEXT_PUBLIC_SUPABASE_URL", "NEXT_PUBLIC_BACKEND_ORIGIN", "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY"]) assert.throws(() => parseAppConfig({ ...env, [key]: "" }));
  for (const origin of ["http://10.0.0.9:8000", "http://172.16.0.4:8000", "http://127.0.0.1:8000", "https://api.example.test"]) assert.equal((parseAppConfig({ ...env, NEXT_PUBLIC_BACKEND_ORIGIN: origin }) as LiveConfig).backendOrigin, origin);
  for (const origin of ["http://192.168.example.test", "https://user:password@example.test", "https://api.example.test/api/v1", "https://api.example.test?token=x", "http://api.example.test", "http://172.32.0.1:8000"]) assert.throws(() => parseAppConfig({ ...env, NEXT_PUBLIC_BACKEND_ORIGIN: origin }));
});

test("configuration accepts legacy anon keys and rejects service-role/secret keys without echoing them", () => {
  const jwt = (role: string) => `e30.${Buffer.from(JSON.stringify({ role })).toString("base64url")}.test-signature`;
  assert.ok(parseAppConfig({ ...env, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "", NEXT_PUBLIC_SUPABASE_ANON_KEY: jwt("anon") }));
  for (const key of [jwt("service_role"), "sb_secret_sensitive_test_value", "arbitrary-key"]) {
    assert.throws(() => parseAppConfig({ ...env, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: key }), error => error instanceof Error && !error.message.includes(key));
  }
  assert.throws(() => parseAppConfig({ ...env, NEXT_PUBLIC_POLICY_READS_ENABLED: "yes" }));
});

test("auth restores a session and returns the current token, not a captured token", async () => {
  const f = fakeAuth(); await f.controller.start();
  assert.equal(f.controller.getSnapshot().status, "signed_in");
  assert.equal(await f.controller.getAccessToken("owner-a"), "fictional-token");
  f.emit(session("owner-a", "rotated-token"));
  assert.equal(await f.controller.getAccessToken("owner-a"), "rotated-token");
  f.controller.dispose(); assert.equal(f.counters.unsubscribe, 1);
});

test("concurrent token requests share refresh and reject already expired refresh results", async () => {
  const f = fakeAuth(session("owner-a", "old-token", 1020)); await f.controller.start();
  const tokens = await Promise.all([f.controller.getAccessToken("owner-a"), f.controller.getAccessToken("owner-a")]);
  assert.deepEqual(tokens, ["refreshed-token", "refreshed-token"]); assert.equal(f.counters.refresh, 1);
  const failed = fakeAuth(session("owner-a", "old-token", 900)); await failed.controller.start();
  failed.auth.refreshSession = async () => ({ data: { session: session("owner-a", "still-expired", 900) }, error: null });
  await assert.rejects(failed.controller.getAccessToken("owner-a"), AuthRequiredError);
  assert.equal(failed.controller.getSnapshot().status, "signed_out");
});

test("missing sessions and failed refresh stop requests and require reauthentication", async () => {
  const missing = fakeAuth(null); await missing.controller.start();
  await assert.rejects(missing.controller.getAccessToken("owner-a"), AuthRequiredError);
  const f = fakeAuth(session("owner-a", "old", 900)); await f.controller.start();
  f.auth.refreshSession = async () => { throw new Error("private auth diagnostics"); };
  await assert.rejects(f.controller.getAccessToken("owner-a"), error => error instanceof AuthRequiredError && !error.message.includes("private"));
  assert.equal(f.controller.getSnapshot().status, "signed_out");
  f.emit(session()); assert.equal(f.controller.getSnapshot().status, "signed_out", "background events cannot bypass required sign-in");
  await f.controller.signIn(" fictional@example.test ", "test-password");
  assert.equal(f.controller.getSnapshot().status, "signed_in");
});

test("sign-in errors are safe and sign-out aborts active scopes before awaiting remote logout", async () => {
  const f = fakeAuth(null); await f.controller.start();
  f.auth.signInWithPassword = async () => ({ data: { session: null }, error: new Error("private user information") });
  await f.controller.signIn("fictional@example.test", "test-password");
  assert.doesNotMatch(JSON.stringify(f.controller.getSnapshot()), /private user information|test-password/);
  const g = fakeAuth(); await g.controller.start();
  const scope = g.controller.requestSignal("owner-a", signal());
  let finish!: () => void;
  g.auth.signOut = () => new Promise(resolve => { finish = () => resolve({ error: null }); });
  const logout = g.controller.signOut();
  assert.equal(scope.aborted, true); assert.equal(g.controller.getSnapshot().status, "signed_out");
  await assert.rejects(g.controller.getAccessToken("owner-a"), AuthRequiredError);
  finish(); await logout;
  assert.match(JSON.stringify(g.controller.getSnapshot()), /Signed out/);
});

test("failed remote sign-out locks the workspace and reports unconfirmed logout", async () => {
  const f = fakeAuth(); await f.controller.start();
  f.auth.signOut = async () => ({ error: new Error("network failure") });
  await f.controller.signOut();
  assert.equal(f.controller.getSnapshot().status, "signed_out");
  assert.match(JSON.stringify(f.controller.getSnapshot()), /remote sign-out could not be confirmed/);
});

test("a replacement sign-in waits for pending sign-out instead of being cleared by late logout", async () => {
  const f = fakeAuth(); await f.controller.start();
  let finish!: () => void; let signIns = 0;
  f.auth.signOut = () => new Promise(resolve => { finish = () => resolve({ error: null }); });
  f.auth.signInWithPassword = async () => { signIns++; return { data: { session: session() }, error: null }; };
  const logout = f.controller.signOut();
  const login = f.controller.signIn("fictional@example.test", "test-only");
  assert.equal(signIns, 0); finish(); await logout; await login;
  assert.equal(signIns, 1); assert.equal(f.controller.getSnapshot().status, "signed_in");
});

test("an old owner's pending refresh cannot replace or clear the new owner's refresh", async () => {
  const f = fakeAuth(session("owner-a", "old", 900)); await f.controller.start();
  const resolvers: Array<(value: Awaited<ReturnType<AuthPort["refreshSession"]>>) => void> = [];
  f.auth.refreshSession = () => new Promise(resolve => { resolvers.push(resolve); });
  const old = f.controller.getAccessToken("owner-a"); await Promise.resolve();
  const rejected = assert.rejects(old, AuthRequiredError);
  f.emit(session("owner-b", "new-old", 900));
  const next = f.controller.getAccessToken("owner-b"); await Promise.resolve();
  assert.equal(resolvers.length, 2);
  resolvers[0]({ data: { session: session("owner-a", "old-refreshed") }, error: null }); await rejected;
  resolvers[1]({ data: { session: session("owner-b", "new-refreshed") }, error: null });
  assert.equal(await next, "new-refreshed"); assert.equal(f.controller.getSnapshot().status, "signed_in");
});

test("account changes abort old requests and cannot send a new owner's token to an old client", async () => {
  const f = fakeAuth(); await f.controller.start();
  const scope = f.controller.requestSignal("owner-a", signal());
  let release!: (value: Awaited<ReturnType<AuthPort["getSession"]>>) => void;
  f.auth.getSession = () => new Promise(resolve => { release = resolve; });
  const pending = f.controller.getAccessToken("owner-a");
  f.emit(session("owner-b", "other-owner-token"));
  release({ data: { session: session("owner-b", "other-owner-token") }, error: null });
  await assert.rejects(pending, AuthRequiredError);
  assert.equal(scope.aborted, true);
  assert.equal(f.controller.getSnapshot().status, "signed_in", "old request cannot sign out the new owner");
});

test("an initial session read cannot restore a stale identity after a newer signed-out event", async () => {
  const f = fakeAuth();
  let release!: (value: Awaited<ReturnType<AuthPort["getSession"]>>) => void;
  f.auth.getSession = () => new Promise(resolve => { release = resolve; });
  const start = f.controller.start(); f.emit(null);
  release({ data: { session: session() }, error: null }); await start;
  assert.equal(f.controller.getSnapshot().status, "signed_out");
});

test("live upload plus polling calls only contracted endpoints and retains actual receipt IDs", async () => {
  const f = fakeAuth(); await f.controller.start();
  const { uploadClient } = createLiveClients(config, f.controller, "owner-a");
  const original = globalThis.fetch; const paths: string[] = [];
  globalThis.fetch = async (url, init) => {
    paths.push(String(url)); assert.equal((init?.headers as Record<string, string>).Authorization, "Bearer fictional-token");
    if (String(url).endsWith("/policies/upload")) { assert.equal(init?.method, "POST"); assert.ok(init?.body instanceof FormData); return Response.json(receipt, { status: 202 }); }
    return Response.json({ job_id: receipt.job_id, policy_id: receipt.policy_id, status: "needs_review", stage: "extracting", message: "Text extracted; AI not verified", error: null });
  };
  try {
    const accepted = await uploadClient.upload({ file: pdf() }, signal());
    assert.deepEqual(accepted, receipt);
    const job = await pollJob(uploadClient, accepted, signal(), () => {}, () => {}, { wait: async () => {} });
    assert.equal(job.status, "needs_review");
    assert.deepEqual(paths, [`${config.backendOrigin}/api/v1/policies/upload`, `${config.backendOrigin}/api/v1/jobs/job-a`]);
  } finally { globalThis.fetch = original; }
});

test("backend 401 expires authentication without replaying an upload; 403 does not log the user out", async () => {
  const original = globalThis.fetch;
  try {
    for (const status of [401, 403]) {
      const f = fakeAuth(); await f.controller.start(); const { uploadClient } = createLiveClients(config, f.controller, "owner-a");
      let calls = 0;
      globalThis.fetch = async () => { calls++; return Response.json({ error: { code: "TOKEN_REJECTED", message: "untrusted details" } }, { status }); };
      await assert.rejects(uploadClient.upload({ file: pdf() }, signal()));
      assert.equal(calls, 1); assert.equal(f.controller.getSnapshot().status, status === 401 ? "signed_out" : "signed_in");
    }
  } finally { globalThis.fetch = original; }
});

test("sign-out cancels in-flight backend requests and prevents additional polling", async () => {
  const f = fakeAuth(); await f.controller.start(); const { uploadClient } = createLiveClients(config, f.controller, "owner-a");
  const original = globalThis.fetch; let started!: () => void;
  const start = new Promise<void>(resolve => { started = resolve; });
  globalThis.fetch = async (_url, init) => new Promise((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true }); started();
  });
  try {
    const request = uploadClient.getJob(receipt.job_id, signal());
    const rejected = assert.rejects(request, { name: "AbortError" });
    await start; await f.controller.signOut(); await rejected;
    await assert.rejects(uploadClient.getJob(receipt.job_id, signal()), AuthRequiredError);
  } finally { globalThis.fetch = original; }
});

test("missing policy endpoints are gated with zero fetch calls and no synthetic responses", async () => {
  const f = fakeAuth(); await f.controller.start(); const clients = createLiveClients(config, f.controller, "owner-a");
  const original = globalThis.fetch; globalThis.fetch = async () => assert.fail("Missing endpoints must not be called");
  try {
    await assert.rejects(clients.policyClient.getPolicy(receipt.policy_id, signal()), /not enabled/);
    await assert.rejects(clients.policyClient.getFindings(receipt.policy_id, signal()), /not enabled/);
    assert.equal("walletClient" in clients, false); assert.equal("simulationClient" in clients, false);
  } finally { globalThis.fetch = original; }
});

test("future explicitly enabled policy reads validate real responses and never fall back to fixtures", async () => {
  const f = fakeAuth(); await f.controller.start();
  const clients = createLiveClients({ ...config, policyReadsEnabled: true }, f.controller, "owner-a");
  const original = globalThis.fetch; const policy = mockPolicyDetails.find(item => item.id === mockFamilyReport.policy_id)!;
  try {
    globalThis.fetch = async () => Response.json({ id: policy.id });
    await assert.rejects(clients.policyClient.getPolicy(policy.id, signal()));
    globalThis.fetch = async () => new Response("missing", { status: 404 });
    await assert.rejects(clients.policyClient.getPolicy(policy.id, signal()), /not be found/);
    globalThis.fetch = async () => Response.json(policy); // Explicit fixture transport, never live evidence.
    assert.deepEqual(await clients.policyClient.getPolicy(policy.id, signal()), policy);
  } finally { globalThis.fetch = original; }
});

test("sign-in and live route markup label mode and never display fictional policy reports", async () => {
  const f = fakeAuth(); await f.controller.start();
  const form = renderToStaticMarkup(<SignInForm auth={f.controller} message="Sign in" />);
  assert.match(form, /type="password"/); assert.match(form, /autoComplete="current-password"/); assert.match(form, /for="auth-email"/);
  const home = renderToStaticMarkup(<LiveWorkspace config={config} auth={f.controller} user={session().user} />);
  const route = renderToStaticMarkup(<LiveWorkspace config={config} auth={f.controller} user={session().user} route={{ policyId: "opaque/id", view: "findings" }} />);
  assert.match(home, /LIVE mode/); assert.match(home, /live wallet list is not connected/);
  assert.match(route, /Policy report is not connected/); assert.match(route, /opaque\/id/);
  for (const html of [home, route]) assert.doesNotMatch(html, /Family Health Plus|fixture-copay|Calculate illustrative impact/);
});

test("official Supabase SDK signs in and signs out through stubbed Auth HTTP with no backend or secrets logging", async () => {
  const calls: string[] = [];
  const payload = { sub: "00000000-0000-4000-8000-000000000001", exp: Math.floor(Date.now() / 1000) + 3600 };
  const token = `${Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url")}.${Buffer.from(JSON.stringify(payload)).toString("base64url")}.fictional-signature`;
  const client = createClient("https://auth.example.test", "sb_publishable_test_only", {
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
    global: { fetch: async (url, init) => {
      calls.push(String(url));
      if (String(url).endsWith("/token?grant_type=password")) {
        const body = JSON.parse(String(init?.body)); assert.equal(body.email, "fictional@example.test"); assert.equal(body.password, "test-only-password");
        return Response.json({ access_token: token, refresh_token: "fictional-refresh-token", expires_in: 3600, token_type: "bearer", user: { id: payload.sub, email: body.email, aud: "authenticated", role: "authenticated", app_metadata: {}, user_metadata: {}, created_at: "2026-10-27T00:00:00Z" } });
      }
      assert.match(String(url), /\/logout\?scope=local$/);
      return new Response(null, { status: 204 });
    } },
  });
  const auth = new AuthSessionController(client.auth);
  try {
    await auth.start(); assert.equal(auth.getSnapshot().status, "signed_out");
    await auth.signIn("fictional@example.test", "test-only-password");
    assert.equal(auth.getSnapshot().status, "signed_in"); assert.equal(await auth.getAccessToken(payload.sub), token);
    await auth.signOut(); assert.equal(auth.getSnapshot().status, "signed_out");
    assert.deepEqual(calls, ["https://auth.example.test/auth/v1/token?grant_type=password", "https://auth.example.test/auth/v1/logout?scope=local"]);
  } finally { auth.dispose(); client.auth.stopAutoRefresh(); }
});
