"use client";
import { ConditionExtractionWorkspace } from "./condition-extraction-workspace";

import React, { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { readAppConfig, type LiveConfig } from "@/lib/app-config";
import { AuthSessionController } from "@/lib/auth-session";
import { getBrowserSupabase } from "@/lib/supabase-browser";
import { WorkspaceShell } from "./workspace-shell";
import { Wallet } from "./wallet";
import { PolicyWorkspace } from "./policy-workspace";
import { LiveWorkspace } from "./live-workspace";

export interface PolicyRoute { policyId: string; view: "details" | "findings" }

export function AppEntry({ route, conditionExtraction = false }: { route?: PolicyRoute; conditionExtraction?: boolean }) {
  const settings = useMemo(() => {
    try { return { config: readAppConfig(), error: "" }; }
    catch (error) { return { config: null, error: error instanceof Error ? error.message : "Live configuration is invalid." }; }
  }, []);
  if (!settings.config) return <WorkspaceShell mode="api" section="Configuration"><div className="empty-state" role="alert"><h1>Live configuration is incomplete</h1><p>{settings.error}</p><p>Supply the public settings in your local environment, then restart or rebuild the frontend.</p></div></WorkspaceShell>;
  if (settings.config.mode === "demo") return conditionExtraction ? <ConditionExtractionWorkspace /> : route ? <PolicyWorkspace key={route.policyId} {...route} /> : <Wallet />;
  return <LiveBoundary config={settings.config} route={route} conditionExtraction={conditionExtraction} />;
}

function LiveBoundary({ config, route, conditionExtraction }: { config: LiveConfig; route?: PolicyRoute; conditionExtraction?: boolean }) {
  const [auth, setAuth] = useState<AuthSessionController | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    let controller: AuthSessionController | undefined;
    getBrowserSupabase(config).then(client => {
      if (cancelled) return;
      controller = new AuthSessionController(client.auth);
      setAuth(controller);
      void controller.start();
    }).catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; controller?.dispose(); };
  }, [config]);
  if (auth) return <AuthGate auth={auth} config={config} route={route} conditionExtraction={conditionExtraction} />;
  return <WorkspaceShell mode="api" section="Sign in"><div className="empty-state" role={failed ? "alert" : "status"}>{failed ? "Authentication could not initialize. Check public configuration and reload." : "Loading authentication…"}</div></WorkspaceShell>;
}

function AuthGate({ auth, config, route, conditionExtraction }: { auth: AuthSessionController; config: LiveConfig; route?: PolicyRoute; conditionExtraction?: boolean }) {
  const state = useSyncExternalStore(auth.subscribe, auth.getSnapshot, auth.getSnapshot);
  if (state.status === "signed_in") return <LiveWorkspace key={state.user.id} auth={auth} user={state.user} config={config} route={route} conditionExtraction={conditionExtraction} />;
  return <WorkspaceShell mode="api" section="Sign in">{state.status === "loading" ? <p role="status">Checking your session…</p> : <SignInForm auth={auth} message={state.message} />}</WorkspaceShell>;
}

export function SignInForm({ auth, message }: { auth: AuthSessionController; message: string }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    try { await auth.signIn(email, password); }
    finally { setPassword(""); setBusy(false); }
  }
  return <section className="live-panel"><h1>Sign in to your live workspace</h1><p>Use an existing Supabase email/password account. This hackathon prototype accepts public or fictional PDFs.</p><p role="status">{message}</p>
    <form className="live-auth-form" onSubmit={submit}><label htmlFor="auth-email">Email</label><input id="auth-email" type="email" autoComplete="username" value={email} onChange={event => setEmail(event.target.value)} required disabled={busy} />
      <label htmlFor="auth-password">Password</label><input id="auth-password" type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} required disabled={busy} />
      <button className="button primary" type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button></form>
    <button className="button secondary" disabled={busy} onClick={async () => { setBusy(true); try { await auth.signOut(); } finally { setBusy(false); } }}>Clear this session / retry sign-out</button>
  </section>;
}
