"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { WorkspaceShell } from "@/components/workspace-shell";
import { ArrowRight, Car, Check, FileText, Heart, House, Info, LayoutGrid, Leaf, Plus, Search, ShieldCheck, Sparkles, WalletCards } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { formatDate, formatMoney, type InsuranceCategory, type PolicyCard as Policy } from "@/lib/policies";
import { mockWalletClient, type WalletClient } from "@/lib/wallet-client";
import { UploadDialog } from "@/components/upload-dialog";
import type { UploadClient } from "@/lib/upload-contract";
const categories: { id: InsuranceCategory | "all"; label: string; icon: LucideIcon }[] = [{ id: "all", label: "All policies", icon: LayoutGrid }, { id: "health", label: "Health", icon: Heart }, { id: "life", label: "Life", icon: Leaf }, { id: "vehicle", label: "Vehicle", icon: Car }, { id: "animal", label: "Animal", icon: ShieldCheck }, { id: "property", label: "Property", icon: House }, { id: "other", label: "Other", icon: FileText }];
const statusLabels = { not_started: "Not analyzed", processing: "Processing documents", ready: "Analysis available", needs_review: "Review needed", failed: "Processing failed", unsupported: "Wallet only" };
function PolicyCard({ policy }: { policy: Policy }) {
 const Icon = categories.find(c => c.id === policy.category)!.icon;
 const health = policy.category === "health";
 return <article className={`policy-card ${health ? "health-card" : ""}`}>
  <div className="card-top"><span className={`policy-icon ${policy.category}`}><Icon size={23} /></span><span className={`status ${policy.analysis_status}`}><span />{statusLabels[policy.analysis_status]}</span></div>
  <p className="insurer">{policy.insurer ?? "Insurer not available"}</p><h3>{policy.product_name ?? "Untitled policy"}</h3>
  <p className="policy-type">{policy.category} <span>•</span> {policy.policy_type === "family_floater" ? "Family floater" : policy.policy_type === "individual" ? "Individual" : "Policy"}</p>
  <div className="policy-amount"><span>Sum insured</span><strong>{formatMoney(policy.sum_insured_paise)}</strong></div>
  <div className="policy-date"><span>Policy end date</span><b>{formatDate(policy.end_date)}</b></div>
  <div className="card-foot">{health ? <><FileText size={15} /><span>{policy.needs_review ? "Schedule & applicability need review" : "Extracting policy information"}</span></> : <><Info size={15} /><span>Specialized analysis unavailable</span></>}</div>
  <Link className="wallet-details-link" href={`/policies/${encodeURIComponent(policy.id)}`} aria-label={`View details for ${policy.product_name ?? "untitled policy"}`}>View policy details <ArrowRight size={15} /></Link>
 </article>;
}
export function Wallet({ client = mockWalletClient, uploadClient }: { client?: WalletClient; uploadClient?: UploadClient }) {
 const [policies, setPolicies] = useState<Policy[]>([]);
 const [loading, setLoading] = useState(true);
 const [error, setError] = useState("");
 const [attempt, setAttempt] = useState(0);
 const [category, setCategory] = useState<InsuranceCategory | "all">("all");
 const [query, setQuery] = useState("");
 const [upload, setUpload] = useState(false);
 useEffect(() => { const controller = new AbortController(); setLoading(true); setError(""); client.listPolicies(controller.signal).then(data => { setPolicies(data.items); }).catch((err: unknown) => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Unable to load policies."); }).finally(() => { if (!controller.signal.aborted) setLoading(false); }); return () => controller.abort(); }, [client, attempt]);
 const visible = policies.filter(p => (category === "all" || p.category === category) && `${p.product_name ?? ""} ${p.insurer ?? ""}`.toLowerCase().includes(query.toLowerCase().trim()));
 return <><WorkspaceShell><div className="page-heading"><div><div className="eyebrow">YOUR POLICIES, IN ONE PLACE</div><h1>Insurance wallet</h1><p>A little more organized. A lot more peace of mind.</p></div><button className="button primary" onClick={() => setUpload(true)}><Plus size={18} />Add policy</button></div>
 <section className="hero" aria-labelledby="hero-title"><div className="hero-copy"><span className="hero-tag"><Sparkles size={14} />A CLEARER VIEW OF YOUR COVER</span><h2 id="hero-title">Life has enough paperwork.<br />Let’s simplify your insurance.</h2><p>Bring your policies together, see what’s available,<br className="desktop-break" /> and take the next step toward understanding your cover.</p><button className="hero-link" onClick={() => setUpload(true)}>Add your first policy document <ArrowRight size={17} /></button></div><div className="hero-art" aria-hidden="true"><div className="art-orbit" /><div className="art-card back" /><div className="art-card front"><ShieldCheck size={35} /><span>YOUR INSURANCE</span><div /><div /><b>In good order.</b></div><span className="art-check"><Check size={22} /></span></div></section>
 <section className="stats" aria-label="Wallet overview"><div><span className="stat-icon"><WalletCards size={20} /></span><div><span>Policies in wallet</span><strong>{loading || error ? "—" : policies.length.toString().padStart(2, "0")}</strong></div></div><div><span className="stat-icon mint"><Heart size={20} /></span><div><span>Health policies</span><strong>{loading || error ? "—" : policies.filter(p => p.category === "health").length.toString().padStart(2, "0")}</strong></div></div><div><span className="stat-icon amber"><FileText size={20} /></span><div><span>Flagged for review</span><strong>{loading || error ? "—" : policies.filter(p => p.needs_review).length.toString().padStart(2, "0")}</strong></div></div></section>
 <section aria-labelledby="policies-title" className="policies-section"><div className="section-heading"><h2 id="policies-title">Your policies <span>{loading || error ? "—" : policies.length}</span></h2><label className="search"><Search size={17} /><input aria-label="Search policies by name or insurer" placeholder="Search policies…" value={query} onChange={e => setQuery(e.target.value)} /></label></div><div className="filters" role="group" aria-label="Filter policies by category">{categories.map(c => <button key={c.id} aria-pressed={category === c.id} className={category === c.id ? "active" : ""} onClick={() => setCategory(c.id)}><c.icon size={15} />{c.label}</button>)}</div>
 {loading ? <div className="policy-grid" role="status" aria-label="Loading policies">{[1, 2, 3].map(n => <div className="skeleton" key={n}><div /><div /><div /><div /></div>)}<span className="sr-only">Loading policies</span></div> : error ? <div className="empty-state" role="alert"><Info /><h3>We couldn’t load your wallet</h3><p>{error}</p><button className="button primary" onClick={() => setAttempt(a => a + 1)}>Try again</button></div> : visible.length === 0 ? <div className="empty-state"><WalletCards size={32} /><h3>{query ? "No matching policies" : "A little room for peace of mind"}</h3><p>{query ? "Try a different policy name or insurer." : "No policies in this category yet. Add a policy to get started."}</p><button className="button secondary" onClick={() => { setQuery(""); setCategory("all"); }}>Show all policies</button><button className="button primary" onClick={() => setUpload(true)}><Plus size={16} />Add policy</button></div> : <div className="policy-grid">{visible.map(p => <PolicyCard key={p.id} policy={p} />)}<button className="add-card" onClick={() => setUpload(true)}><span><Plus size={24} /></span><strong>Make room for your next policy</strong><p>Keep every policy within reach.</p><b>Add policy <ArrowRight size={15} /></b></button></div>}</section>
 </WorkspaceShell><UploadDialog open={upload} close={() => setUpload(false)} policies={policies} client={uploadClient} /></>;
}
