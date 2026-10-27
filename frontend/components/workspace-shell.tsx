import Link from "next/link";
import { ChevronRight, Info, LifeBuoy, ShieldCheck, Sparkles, WalletCards } from "lucide-react";
import type { ReactNode } from "react";

export function WorkspaceShell({ children, section = "Insurance wallet", mode = "mock" }: { children: ReactNode; section?: string; mode?: "mock" | "api" }) {
  const demo = mode === "mock";
  return <div className="app-shell">
    <a className="skip-link" href="#main">Skip to content</a>
    <aside className="sidebar">
      <Link className="brand" href="/"><span className="brand-mark"><ShieldCheck size={24} /></span>coverly<span className="brand-dot">.</span></Link>
      <div className="workspace-label">YOUR WORKSPACE</div>
      <nav aria-label="Main navigation">
        <Link className="nav-item selected" href="/" aria-current={section === "Insurance wallet" ? "page" : undefined}><WalletCards size={19} />Insurance wallet<span className="nav-dot" /></Link>
        <div className="nav-item upcoming"><Sparkles size={19} /><span>Claim simulator<small>In health policy reports</small></span></div>
      </nav>
      <div className="sidebar-bottom">
        <div className="sidebar-tip"><span className="tip-icon"><ShieldCheck size={22} /></span><h3>Clarity starts with cover.</h3><p>Keep your policies together.<br />Understand the details that matter.</p></div>
        <a className="help-link" href="#scope"><LifeBuoy size={18} />About this prototype <ChevronRight size={16} /></a>
        <div className="demo-profile"><span>{demo ? "DW" : "PW"}</span><div>{demo ? "Demo workspace" : "Policy workspace"}<small>{demo ? "Fictional policy collection" : "Connected policy service"}</small></div></div>
      </div>
    </aside>
    <div className="main-shell">
      <header className="topbar"><span>Workspace <ChevronRight size={14} /><b>{section}</b></span><span className="demo-pill"><span />{demo ? "Demo mode" : "API mode"}</span></header>
      <main id="main">
        {children}
        <section className="scope-note" id="scope"><Info size={19} /><div><h3>Built for clarity. Grounded in your documents.</h3><p>Advanced AI claim analysis supports only individual and family-floater indemnity health insurance. Other categories are wallet-only. Analysis availability does not verify coverage or claim applicability.</p></div></section>
        <footer><span><ShieldCheck size={14} />Smart Insurance Wallet · Hackathon proof-of-concept</span><span>{demo ? "All policies and amounts shown are fictional demo data." : "Decision support, not an insurer claim decision."}</span></footer>
      </main>
    </div>
  </div>;
}
