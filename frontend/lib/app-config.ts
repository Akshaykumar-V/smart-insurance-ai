export type AppConfig = { mode: "demo" } | LiveConfig;
export interface LiveConfig {
  mode: "live";
  supabaseUrl: string;
  supabasePublicKey: string;
  backendOrigin: string;
  policyReadsEnabled: boolean;
}

function origin(value: string | undefined, name: string, allowPrivateLan = false): string {
  try {
    const url = new URL(value ?? "");
    const octets = url.hostname.split(".").map(Number);
    const privateIp = octets.length === 4 && octets.every(part => Number.isInteger(part) && part >= 0 && part <= 255)
      && (octets[0] === 10 || (octets[0] === 192 && octets[1] === 168) || (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31));
    const local = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname) || (allowPrivateLan && privateIp);
    if ((url.protocol !== "https:" && !(local && url.protocol === "http:")) || url.username || url.password || url.search || url.hash || url.pathname !== "/") throw new Error();
    return url.origin;
  } catch { throw new Error(`${name} must be an HTTPS origin${allowPrivateLan ? " (HTTP is also allowed for localhost or private LAN development)" : " (HTTP is allowed for localhost)"}, without a path or credentials.`); }
}

// Configuration is public and baked into the browser bundle by Next.js.
export function parseAppConfig(env: Record<string, string | undefined>): AppConfig {
  const mode = env.NEXT_PUBLIC_APP_MODE?.trim().toLowerCase() || "demo";
  if (mode === "demo") return { mode: "demo" };
  if (mode !== "live") throw new Error("NEXT_PUBLIC_APP_MODE must be demo or live.");
  const supabaseUrl = origin(env.NEXT_PUBLIC_SUPABASE_URL, "NEXT_PUBLIC_SUPABASE_URL");
  const backendOrigin = origin(env.NEXT_PUBLIC_BACKEND_ORIGIN, "NEXT_PUBLIC_BACKEND_ORIGIN", true);
  const key = (env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "").trim();
  let publicKey = /^sb_publishable_[A-Za-z0-9_-]+$/.test(key);
  if (!publicKey) {
    try {
      const parts = key.split(".");
      const payload = JSON.parse(atob(parts[1].replace(/-/g, "+").replace(/_/g, "/")));
      publicKey = parts.length === 3 && payload.role === "anon";
    } catch { /* Reject unrecognized and secret keys without echoing them. */ }
  }
  if (!publicKey) throw new Error("Set a Supabase public publishable or legacy anon key. Secret and service-role keys must never be used in frontend configuration.");
  const reads = env.NEXT_PUBLIC_POLICY_READS_ENABLED || "false";
  if (!["true", "false"].includes(reads)) throw new Error("NEXT_PUBLIC_POLICY_READS_ENABLED must be true or false.");
  return { mode, supabaseUrl, supabasePublicKey: key, backendOrigin, policyReadsEnabled: reads === "true" };
}

export function readAppConfig(): AppConfig {
  // Keep literal property accesses: Next.js does not inline dynamic env lookups.
  return parseAppConfig({
    NEXT_PUBLIC_APP_MODE: process.env.NEXT_PUBLIC_APP_MODE,
    NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL,
    NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY,
    NEXT_PUBLIC_SUPABASE_ANON_KEY: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
    NEXT_PUBLIC_BACKEND_ORIGIN: process.env.NEXT_PUBLIC_BACKEND_ORIGIN,
    NEXT_PUBLIC_POLICY_READS_ENABLED: process.env.NEXT_PUBLIC_POLICY_READS_ENABLED,
  });
}
