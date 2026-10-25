import type { PolicyCard } from "../../frontend_api_types";
export type { PolicyCard, InsuranceCategory } from "../../frontend_api_types";
export interface PolicyList { items: PolicyCard[]; next_cursor: string | null }
const categories = ["health", "life", "vehicle", "animal", "property", "other"];
const types = ["individual", "family_floater", "other", "unknown"];
const statuses = ["not_started", "processing", "ready", "needs_review", "failed", "unsupported"];
function nullableString(value: unknown): boolean { return value === null || typeof value === "string"; }
function date(value: unknown): boolean { return value === null || (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value))); }
export function parsePolicyList(value: unknown): PolicyList {
  if (!value || typeof value !== "object") throw new Error("Invalid policy response.");
  const data = value as Record<string, unknown>;
  if (!Array.isArray(data.items) || !nullableString(data.next_cursor)) throw new Error("Invalid policy list.");
  for (const item of data.items) {
    if (!item || typeof item !== "object") throw new Error("Invalid policy.");
    const p = item as Record<string, unknown>;
    if (typeof p.id !== "string" || !p.id || !categories.includes(p.category as string) || !types.includes(p.policy_type as string) || !statuses.includes(p.analysis_status as string) || !nullableString(p.insurer) || !nullableString(p.product_name) || !date(p.start_date) || !date(p.end_date) || typeof p.needs_review !== "boolean" || !(p.sum_insured_paise === null || (typeof p.sum_insured_paise === "number" && Number.isSafeInteger(p.sum_insured_paise) && p.sum_insured_paise >= 0))) throw new Error("Policy data did not match API contract v0.1.");
  }
  return data as unknown as PolicyList;
}
export function formatMoney(paise: number | null): string { return paise === null ? "Not available" : new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(paise / 100); }
export function formatDate(value: string | null): string { return value ? new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(new Date(value)) : "Schedule not provided"; }

