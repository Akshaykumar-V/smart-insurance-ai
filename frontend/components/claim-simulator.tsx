"use client";

import React, { useEffect, useRef, useState } from "react";
import { AlertCircle, ArrowUpRight, Calculator, Info, RefreshCw } from "lucide-react";
import { calculateClaimImpact, parseInr, ruleReadiness, type ClaimCalculation, type ClaimScenario, type ModelSelection } from "@/lib/claim-calculator";
import { formatMoney } from "@/lib/policies";
import { localSimulationClient } from "@/lib/simulation-client";
import type { FindingsResponse, PolicyDetails } from "@/lib/policy-intelligence";

export function SimulationBreakdown({ result }: { result: Extract<ClaimCalculation, { status: "illustrative" }> }) {
  const b = result.breakdown;
  return <div className="claim-result">
    <div className="claim-result-heading"><span className="eyebrow">DETERMINISTIC · FICTIONAL SCENARIO</span><h3>Illustrative impact of the selected rules</h3><p>Not an approved claim or a complete payout estimate. Other policy conditions remain unresolved.</p></div>
    <dl className="claim-breakdown">
      <div><dt>Estimated hospital bill</dt><dd>{formatMoney(b.hospitalBillPaise)}</dd></div>
      <div><dt>Estimated admissible expenses <small>Before the modeled sub-limit and co-payment</small></dt><dd>{formatMoney(b.admissiblePaise)}</dd></div>
      <div><dt>Outside your admissible estimate <small>Assumed non-admissible; not a confirmed exclusion</small></dt><dd>{formatMoney(b.outsideAdmissiblePaise)}</dd></div>
      <div><dt>Above the modeled treatment sub-limit</dt><dd>{formatMoney(b.aboveSubLimitPaise)}</dd></div>
      <div><dt>Admissible base after the modeled sub-limit</dt><dd>{formatMoney(b.afterSubLimitPaise)}</dd></div>
      <div><dt>Modeled co-payment</dt><dd>{formatMoney(b.copaymentPaise)}</dd></div>
    </dl>
    <div className="claim-shares"><div><span>Illustrative insurer-paid amount</span><strong>{formatMoney(b.modeledInsurerPaise)}</strong><small>Selected-rule model only</small></div><div><span>Illustrative patient-paid amount</span><strong>{formatMoney(b.modeledPatientPaise)}</strong><small>Selected-rule model only</small></div></div>
    <details className="claim-math" open><summary>Calculation and assumptions</summary>
      <ol>
        <li>Assumed non-admissible portion: {formatMoney(b.hospitalBillPaise)} − {formatMoney(b.admissiblePaise)} = {formatMoney(b.outsideAdmissiblePaise)}.</li>
        <li>{b.treatmentCapPaise === null ? "No treatment cap was applied in this scenario." : `Above-cap amount: max(${formatMoney(b.treatmentEligiblePaise)} − ${formatMoney(b.treatmentCapPaise)}, 0) = ${formatMoney(b.aboveSubLimitPaise)}. Only the eligible treatment portion is capped.`}</li>
        <li>Remaining base: {formatMoney(b.admissiblePaise)} − {formatMoney(b.aboveSubLimitPaise)} = {formatMoney(b.afterSubLimitPaise)}.</li>
        <li>{b.copaymentPercent === null ? "No co-payment was applied in this scenario." : `Co-payment: ${b.copaymentPercent}% × ${formatMoney(b.afterSubLimitPaise)} = ${formatMoney(b.copaymentPaise)} (rounded half-up to the nearest paise).`}</li>
        <li>Modeled insurer share: {formatMoney(b.afterSubLimitPaise)} − {formatMoney(b.copaymentPaise)} = {formatMoney(b.modeledInsurerPaise)}.</li>
        <li>Modeled patient share: {formatMoney(b.outsideAdmissiblePaise)} + {formatMoney(b.aboveSubLimitPaise)} + {formatMoney(b.copaymentPaise)} = {formatMoney(b.modeledPatientPaise)}. Each portion is counted once.</li>
      </ol>
    </details>
    <section className="claim-rule-decisions" aria-label="Rule applicability and source references">{result.decisions.map(decision => <div key={decision.findingId}><strong>{decision.title}</strong><span className="claim-rule-state">{decision.outcome === "applied" ? "Modeled with your assumption" : "Not applicable to supplied inputs"}</span><p>{decision.reason}</p><a className="text-action" href={`#finding-${decision.findingId}`}>Source finding · illustrative PDF page {decision.source.page} <ArrowUpRight size={14} /></a></div>)}</section>
    <div className="claim-warning"><Info size={18} /><ul>{result.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul></div>
  </div>;
}

export function ClaimSimulator({ policy, report, mode }: { policy: PolicyDetails; report: FindingsResponse; mode: "mock" | "api" }) {
  const heading = useRef<HTMLHeadingElement>(null);
  const outcomeRef = useRef<HTMLDivElement>(null);
  const operation = useRef<AbortController | null>(null);
  const [bill, setBill] = useState("");
  const [admissible, setAdmissible] = useState("");
  const [eligible, setEligible] = useState("");
  const [member, setMember] = useState("");
  const [age, setAge] = useState("");
  const [treatment, setTreatment] = useState("");
  const [model, setModel] = useState<ModelSelection>("combined");
  const [confirmed, setConfirmed] = useState<string[]>([]);
  const [acknowledged, setAcknowledged] = useState(false);
  const [result, setResult] = useState<ClaimCalculation | null>(null);
  const [inputErrors, setInputErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const candidates = report.findings.filter(finding => ["co_payment", "sub_limit"].includes(finding.condition_type));
  const selected = candidates.filter(finding => model === "combined" || finding.condition_type === model);
  const treatments = [...new Set(candidates.flatMap(finding => typeof finding.rule?.treatment_label === "string" ? [finding.rule.treatment_label] : []))];
  const matchingTreatment = selected.some(finding => finding.condition_type === "sub_limit" && typeof finding.rule?.treatment_label === "string" && finding.rule.treatment_label.trim().toLowerCase() === treatment.trim().toLowerCase());

  useEffect(() => { heading.current?.focus(); return () => { operation.current?.abort(); operation.current = null; }; }, []);
  useEffect(() => { if (result || error || Object.keys(inputErrors).length) outcomeRef.current?.focus(); }, [result, error, inputErrors]);

  function invalidate() {
    operation.current?.abort(); operation.current = null;
    setLoading(false); setResult(null); setError(""); setInputErrors({}); setConfirmed([]); setAcknowledged(false);
  }
  function changeMember(value: string) {
    invalidate(); setMember(value);
    const person = value === "" ? null : policy.insured_members[Number(value)];
    setAge(person?.age === null || person?.age === undefined ? "" : String(person.age));
  }
  function validateInputs(): ClaimScenario | null {
    const errors: Record<string, string> = {};
    const hospitalBill = parseInr(bill);
    const admissibleEstimate = parseInr(admissible);
    const treatmentExpenses = parseInr(eligible);
    if (hospitalBill.error || hospitalBill.value === null) errors.bill = hospitalBill.error ?? "Enter the estimated hospital bill.";
    if (admissibleEstimate.error || admissibleEstimate.value === null) errors.admissible = admissibleEstimate.error ?? "Enter a separate admissible estimate. If it is unknown, no financial result can be calculated.";
    if (treatmentExpenses.error) errors.eligible = treatmentExpenses.error;
    if (matchingTreatment && treatmentExpenses.value === null) errors.eligible = "Enter the eligible treatment portion already included in admissible expenses.";
    if (!treatment) errors.treatment = "Choose a treatment category.";
    if (age && (!/^\d+$/.test(age) || !Number.isSafeInteger(Number(age)))) errors.age = "Enter age as a non-negative whole number.";
    if (selected.some(finding => finding.condition_type === "co_payment" && finding.rule?.minimum_age !== undefined) && !age) errors.age = "Age is required for the selected age-linked rule.";
    if (Object.keys(errors).length) { setInputErrors(errors); return null; }
    return { hospitalBillPaise: hospitalBill.value, admissiblePaise: admissibleEstimate.value, treatmentEligiblePaise: treatmentExpenses.value,
      treatment, age: age === "" ? null : Number(age), model, confirmedFindingIds: confirmed, scopeAcknowledged: acknowledged };
  }
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (operation.current || mode !== "mock") return;
    setError(""); setInputErrors({}); setResult(null);
    const scenario = validateInputs();
    if (!scenario) return;
    // Evaluate incomplete/unsafe inputs synchronously before showing calculation activity.
    const preliminary = calculateClaimImpact(policy, report, scenario);
    if (preliminary.status !== "illustrative") { setResult(preliminary); return; }
    const controller = new AbortController(); operation.current = controller; setLoading(true);
    try {
      const next = await localSimulationClient.simulate(policy, report, scenario, controller.signal);
      if (!controller.signal.aborted) setResult(next);
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "This scenario could not be calculated. Try again.");
    } finally { if (operation.current === controller) { operation.current = null; setLoading(false); } }
  }
  const fieldError = (key: string) => inputErrors[key] ? <span id={`claim-${key}-error`} className="claim-field-error">{inputErrors[key]}</span> : null;

  return <section id="claim-simulator" className="claim-simulator" aria-labelledby="claim-title">
    <div className="claim-heading"><span className="policy-icon health"><Calculator size={23} /></span><div><span className="eyebrow">EXPLORE A HYPOTHETICAL SCENARIO</span><h2 id="claim-title" tabIndex={-1} ref={heading}>Claim Impact Simulator</h2></div></div>
    <p className="claim-description">See how a percentage co-payment and a treatment cap change the selected-rule model. Your inputs are estimates; nothing here is an insurer-approved claim.</p>
    {mode !== "mock" ? <div className="report-note"><Info size={18} /><p>Live simulation is not connected yet. Your policy report remains available. This fictional calculation mode is not used for live policy responses.</p></div> : <>
      <div className="report-demo-note"><Info size={18} /><div><strong>Fictional rules · calculated locally · no AI arithmetic</strong><p>Amounts and assumptions stay in this page session. Only the selected two rule types are modeled. Other findings in this report remain unresolved.</p></div></div>
      {!candidates.length ? <div className="panel-empty"><h3>No modelable findings were returned</h3><p>A missing co-payment or sub-limit does not mean it is absent from the policy. No financial result is available.</p></div> : <div className="claim-grid">
        <form className="claim-form" onSubmit={submit} noValidate aria-label="Hypothetical claim scenario">
          <fieldset disabled={loading}><legend>1. Estimated expenses</legend>
            <label htmlFor="claim-bill">Estimated hospital bill (INR)</label><input id="claim-bill" type="text" inputMode="decimal" maxLength={24} autoComplete="off" placeholder="e.g. 1,00,000" value={bill} onChange={event => { invalidate(); setBill(event.target.value); }} aria-invalid={!!inputErrors.bill} aria-describedby={inputErrors.bill ? "claim-bill-error" : undefined} />{fieldError("bill")}
            <label htmlFor="claim-admissible">Estimated admissible expenses (INR)</label><input id="claim-admissible" type="text" inputMode="decimal" maxLength={24} autoComplete="off" placeholder="Leave blank if unknown" value={admissible} onChange={event => { invalidate(); setAdmissible(event.target.value); }} aria-invalid={!!inputErrors.admissible} aria-describedby={`claim-admissible-help${inputErrors.admissible ? " claim-admissible-error" : ""}`} /><small id="claim-admissible-help">Your estimate before the modeled cap and co-payment. We never treat the full bill as automatically admissible.</small>{fieldError("admissible")}
          </fieldset>
          <fieldset disabled={loading}><legend>2. Hypothetical context</legend>
            <label htmlFor="claim-model">Rules to model</label><select id="claim-model" value={model} onChange={event => { invalidate(); setModel(event.target.value as ModelSelection); setEligible(""); }}><option value="combined">Sub-limit, then co-payment</option><option value="co_payment">Co-payment only</option><option value="sub_limit">Treatment sub-limit only</option></select>
            <label htmlFor="claim-treatment">Treatment category</label><select id="claim-treatment" value={treatment} onChange={event => { invalidate(); setTreatment(event.target.value); setEligible(""); }} aria-invalid={!!inputErrors.treatment} aria-describedby={inputErrors.treatment ? "claim-treatment-error" : undefined}><option value="">Choose a category</option>{treatments.map(item => <option key={item} value={item}>{item}</option>)}<option value="Other treatment">Other treatment (none of the listed categories)</option></select>{fieldError("treatment")}
            {matchingTreatment && <><label htmlFor="claim-eligible">Eligible expenses for this treatment (INR)</label><input id="claim-eligible" type="text" inputMode="decimal" maxLength={24} autoComplete="off" value={eligible} onChange={event => { invalidate(); setEligible(event.target.value); }} aria-invalid={!!inputErrors.eligible} aria-describedby={`claim-eligible-help${inputErrors.eligible ? " claim-eligible-error" : ""}`} /><small id="claim-eligible-help">A portion of the admissible estimate above, not an additional expense. Other admissible expenses are not capped by this treatment rule.</small>{fieldError("eligible")}</>}
            <label htmlFor="claim-member">Insured member (optional)</label><select id="claim-member" value={member} onChange={event => changeMember(event.target.value)}><option value="">Use a hypothetical age</option>{policy.insured_members.map((person, index) => <option key={index} value={index}>{person.name || `Unnamed member ${index + 1}`} · {person.age === null ? "age unknown" : `age ${person.age}`}</option>)}</select>
            <label htmlFor="claim-age">Applicable age for this scenario</label><input id="claim-age" type="text" inputMode="numeric" maxLength={3} autoComplete="off" value={age} onChange={event => { invalidate(); setAge(event.target.value); }} aria-invalid={!!inputErrors.age} aria-describedby={`claim-age-help${inputErrors.age ? " claim-age-error" : ""}`} /><small id="claim-age-help">You may edit a member’s age for a hypothetical scenario. Policy/member records are not changed.</small>{fieldError("age")}
          </fieldset>
          <fieldset disabled={loading}><legend>3. Scope and exception assumptions</legend>
            {selected.map(finding => {
              const problem = ruleReadiness(finding, policy);
              return <div className="claim-assumption" key={finding.id}><strong>{finding.title}</strong><p>{finding.applicability || "Applicability not established."}</p><p>{finding.exceptions.length ? finding.exceptions.join(" ") : "No exception details were returned; this does not establish that no exceptions exist."}</p>
                {problem ? <p className="claim-blocked">Cannot model: {problem}</p> : <label className="claim-checkbox"><input type="checkbox" checked={confirmed.includes(finding.id)} onChange={event => { setResult(null); setError(""); setConfirmed(ids => event.target.checked ? [...ids, finding.id] : ids.filter(id => id !== finding.id)); }} />For this hypothetical scenario, assume its scope is satisfied and no exception changes this rule. Needed only if the age/treatment condition matches.</label>}
                <a className="text-action" href={`#finding-${finding.id}`}>Read source finding <ArrowUpRight size={13} /></a></div>;
            })}
            <label className="claim-checkbox claim-scope-check"><input type="checkbox" checked={acknowledged} onChange={event => { setResult(null); setError(""); setAcknowledged(event.target.checked); }} />I understand these are shares under selected fictional rules only. Other policy conditions are unresolved; this is not a full payout estimate.</label>
          </fieldset>
          <button className="button primary claim-submit" type="submit" disabled={loading}>{loading ? "Calculating locally…" : error ? "Retry illustrative calculation" : "Calculate illustrative impact"}<Calculator size={16} /></button>
        </form>
        <div className="claim-output" ref={outcomeRef} tabIndex={-1} aria-label="Simulation result" aria-busy={loading}>
          {loading ? <div className="claim-placeholder" role="status"><RefreshCw size={27} /><h3>Calculating your fictional scenario</h3><p>Applying the selected rules with deterministic arithmetic.</p></div> : Object.keys(inputErrors).length ? <div className="claim-warning" role="alert"><AlertCircle size={19} /><div><h3>Check the scenario inputs</h3><ul>{Object.entries(inputErrors).map(([key, message]) => <li key={key}><a href={`#claim-${key}`}>{message}</a></li>)}</ul></div></div> : error ? <div className="claim-warning" role="alert"><AlertCircle size={19} /><p>{error} Your inputs are retained; use Retry illustrative calculation.</p></div> : result?.status === "illustrative" ? <SimulationBreakdown result={result} /> : result ? <div className="claim-warning" role="alert"><AlertCircle size={19} /><div><h3>{result.status === "insufficient_evidence" ? "Evidence is not sufficient for this model" : "More information is needed"}</h3><ul>{result.issues.map(issue => <li key={issue}>{issue}</li>)}</ul><p>No financial result has been calculated.</p></div></div> : <div className="claim-placeholder"><Calculator size={30} /><h3>Your scenario, explained</h3><p>Enter separate bill and admissible estimates, select the context and confirm the hypothetical assumptions. The breakdown will appear here.</p><small>Unknown admissible expenses? Leave the amount blank to see what is needed.</small></div>}
        </div>
      </div>}
    </>}
  </section>;
}
