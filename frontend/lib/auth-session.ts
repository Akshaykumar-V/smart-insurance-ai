export interface AuthSession {
  access_token: string;
  expires_at?: number;
  user: { id: string; email?: string };
}
type SessionResult = { data: { session: AuthSession | null }; error: unknown };
export interface AuthPort {
  getSession(): Promise<SessionResult>;
  refreshSession(): Promise<SessionResult>;
  signInWithPassword(input: { email: string; password: string }): Promise<SessionResult>;
  signOut(options: { scope: "local" }): Promise<{ error: unknown }>;
  onAuthStateChange(callback: (event: string, session: AuthSession | null) => void): { data: { subscription: { unsubscribe(): void } } };
}
export type AuthState = { status: "loading" } | { status: "signed_out"; message: string } | { status: "signed_in"; user: AuthSession["user"] };
export class AuthRequiredError extends Error {
  constructor() { super("Your session is unavailable or expired. Sign in again before continuing."); this.name = "AuthRequiredError"; }
}

// Stores UI identity only. Supabase owns token storage/rotation; getAccessToken
// reads a fresh session for every request instead of closing over an old JWT.
export class AuthSessionController {
  private state: AuthState = { status: "loading" };
  private listeners = new Set<() => void>();
  private scope = new AbortController();
  private revision = 0;
  private blocked = false;
  private unsubscribe?: () => void;
  private refresh?: Promise<SessionResult>;
  private logout?: Promise<void>;
  constructor(private readonly auth: AuthPort, private readonly now = () => Date.now() / 1000) {}
  getSnapshot = (): AuthState => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private publish(next: AuthState) { this.state = next; this.listeners.forEach(listener => listener()); }
  private adopt(session: AuthSession | null) {
    const oldId = this.state.status === "signed_in" ? this.state.user.id : null;
    if (oldId !== (session?.user.id ?? null)) { this.scope.abort(); this.scope = new AbortController(); this.refresh = undefined; this.revision++; }
    this.publish(session ? { status: "signed_in", user: session.user } : { status: "signed_out", message: "Sign in to upload a public or fictional policy PDF." });
  }
  async start() {
    this.unsubscribe = this.auth.onAuthStateChange((_event, session) => {
      if (!this.blocked) { this.revision++; this.adopt(session); }
    }).data.subscription.unsubscribe;
    const revision = this.revision;
    try {
      const { data, error } = await this.auth.getSession();
      if (revision !== this.revision || this.blocked) return;
      if (error) this.expire(); else this.adopt(data.session);
    } catch { if (revision === this.revision) this.expire(); }
  }
  dispose() { this.unsubscribe?.(); this.scope.abort(); this.blocked = true; this.revision++; }
  expire = () => {
    this.blocked = true; this.revision++; this.scope.abort(); this.refresh = undefined;
    this.publish({ status: "signed_out", message: "Your session could not be confirmed. Sign in again. Any interrupted upload may still exist on the server; do not blindly resend it." });
  };
  async signIn(email: string, password: string) {
    // The sign-in form mounts immediately after the workspace locks. Let any
    // pending SDK sign-out finish before creating a replacement session.
    if (this.logout) await this.logout;
    this.blocked = true; this.scope.abort(); const revision = ++this.revision;
    try {
      const { data, error } = await this.auth.signInWithPassword({ email: email.trim(), password });
      if (revision !== this.revision) return;
      if (error || !data.session) throw new Error();
      this.blocked = false; this.scope = new AbortController(); this.adopt(data.session);
    } catch {
      if (revision === this.revision) this.publish({ status: "signed_out", message: "Sign-in failed. Check your email/password and connection, and confirm that the account is enabled." });
    }
  }
  signOut(): Promise<void> {
    if (this.logout) return this.logout;
    this.expire(); // Immediately abort requests and remove private UI, even offline.
    this.logout = (async () => {
      try {
        const { error } = await this.auth.signOut({ scope: "local" });
        if (error) throw new Error();
        this.publish({ status: "signed_out", message: "Signed out of this browser session." });
      } catch {
        this.publish({ status: "signed_out", message: "The workspace is locked, but remote sign-out could not be confirmed. Retry sign-out when connected." });
      }
    })().finally(() => { this.logout = undefined; });
    return this.logout;
  }
  requestSignal(ownerId: string, signal: AbortSignal): AbortSignal {
    if (this.blocked || this.state.status !== "signed_in" || this.state.user.id !== ownerId) throw new AuthRequiredError();
    return AbortSignal.any([signal, this.scope.signal]);
  }
  async getAccessToken(ownerId: string): Promise<string> {
    const scope = this.scope;
    const stillOwner = () => !this.blocked && !scope.signal.aborted && this.state.status === "signed_in" && this.state.user.id === ownerId;
    if (!stillOwner()) throw new AuthRequiredError();
    try {
      let result = await this.auth.getSession();
      if (!stillOwner()) throw new AuthRequiredError();
      if (result.error || !result.data.session || result.data.session.user.id !== ownerId) throw new AuthRequiredError();
      if ((result.data.session.expires_at ?? 0) <= this.now() + 60) {
        if (!this.refresh) {
          const pending = this.auth.refreshSession().finally(() => { if (this.refresh === pending) this.refresh = undefined; });
          this.refresh = pending;
        }
        result = await this.refresh;
      }
      if (!stillOwner()) throw new AuthRequiredError();
      const session = result.data.session;
      if (result.error || !session?.access_token || session.user.id !== ownerId || (session.expires_at ?? 0) <= this.now()) throw new AuthRequiredError();
      return session.access_token;
    } catch {
      if (stillOwner()) this.expire();
      throw new AuthRequiredError();
    }
  }
}
