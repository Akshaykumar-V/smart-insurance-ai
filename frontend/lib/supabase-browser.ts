import type { SupabaseClient } from "@supabase/supabase-js";
import type { LiveConfig } from "./app-config";

let browserClient: SupabaseClient | undefined;

export async function getBrowserSupabase(config: LiveConfig) {
  if (typeof window === "undefined") throw new Error("Authentication must initialize in the browser.");
  const { createClient } = await import("@supabase/supabase-js");
  browserClient ??= createClient(config.supabaseUrl, config.supabasePublicKey, {
    auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false },
  });
  return browserClient;
}
