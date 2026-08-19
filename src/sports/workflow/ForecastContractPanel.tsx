// Stage 1 — Project & Forecast Contract. Prefilled from project creation; the scientist reviews
// and formalizes the target, temporal policy, and evidence mode, then registers a versioned
// forecast contract. The 2025 frozen season is visually distinct and never used for selection.
import { useState } from "react";
import { ShieldCheck, Sparkles } from "lucide-react";
import type { SportsProjectMetadata } from "../sportsConfig";
import { TARGETS_BY_WORKFLOW, FORECAST_LIFECYCLES } from "../sportsConfig";
import { DEFAULT_TEMPORAL, GOVERNED_TEMPORAL, MODELING_START_SEASON, governedDevelopmentSeasons, saveContract, type ForecastContract } from "./workflowState";

const YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026];
// Development targets are restricted to the governed PRIMARY_GEN2_MODELING seasons (≥2023). 2021–2022
// are PRIOR_ONLY_HISTORY (source evidence for Y−1 priors), never selectable as development targets.
const DEV_YEARS = YEARS.filter((y) => y >= MODELING_START_SEASON);

export function ForecastContractPanel({
  projectId, metadata, existing, onSaved,
}: {
  projectId: string;
  metadata: SportsProjectMetadata | null;
  existing: ForecastContract | null;
  onSaved: () => void;
}) {
  const targets = TARGETS_BY_WORKFLOW["mlb-forecasting"];
  const [target, setTarget] = useState(existing?.target || metadata?.primaryTarget || "Plate-Appearance Outcome");
  const [lifecycle, setLifecycle] = useState(existing?.lifecycle || metadata?.lifecycle || "Pregame — Final");
  // Clamp any legacy development window to the governed modeling seasons (drops 2021–2022 prior-only).
  const govDev = governedDevelopmentSeasons(existing?.developmentSeasons ?? DEFAULT_TEMPORAL.developmentSeasons);
  const [devStart, setDevStart] = useState(govDev[0]);
  const [devEnd, setDevEnd] = useState(govDev[govDev.length - 1]);
  const [valSeason, setValSeason] = useState(existing?.validationSeason ?? DEFAULT_TEMPORAL.validationSeason);
  const [frozenSeason, setFrozenSeason] = useState(existing?.frozenSeason ?? DEFAULT_TEMPORAL.frozenSeason);
  const [prospective, setProspective] = useState<number | null>(existing?.prospectiveSeason ?? DEFAULT_TEMPORAL.prospectiveSeason);
  const [evidenceMode, setEvidenceMode] = useState<"STRICT" | "ENHANCED">(existing?.evidenceMode || "ENHANCED");
  const [purpose, setPurpose] = useState(existing?.researchPurpose || metadata?.researchPurpose || "");
  const [notes, setNotes] = useState(existing?.notes || metadata?.description || "");
  const devSeasons = YEARS.filter((y) => y >= devStart && y <= devEnd);
  const valid = devSeasons.length > 0 && devEnd < valSeason && valSeason < frozenSeason;

  // Save and advance immediately — no interstitial confirmation screen.
  const save = () => {
    if (!valid) return;
    const contract: ForecastContract = {
      projectId,
      version: (existing?.version ?? 0) + 1,
      target,
      lifecycle,
      developmentSeasons: devSeasons,
      validationSeason: valSeason,
      frozenSeason,
      prospectiveSeason: prospective,
      evidenceMode,
      intendedOutputs: metadata?.secondaryTargets?.length ? [metadata.primaryTarget, ...metadata.secondaryTargets] : [target],
      researchPurpose: purpose.trim(),
      notes: notes.trim(),
      savedAt: new Date().toISOString(),
    };
    saveContract(contract);
    onSaved();
  };

  return (
    <section className="sports-panel p-5 sm:p-6">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-cyan-700"><Sparkles size={14} /> Prefilled from your project — review and formalize</div>

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <Field label="Forecast target">
          <select value={target} onChange={(e) => setTarget(e.target.value)} className="wf-input">{targets.map((t) => <option key={t}>{t}</option>)}</select>
        </Field>
        <Field label="Forecast lifecycle">
          <select value={lifecycle} onChange={(e) => setLifecycle(e.target.value)} className="wf-input">{FORECAST_LIFECYCLES.map((t) => <option key={t}>{t}</option>)}</select>
        </Field>
      </div>

      {/* Temporal policy */}
      <div className="mt-6">
        <div className="text-sm font-semibold text-slate-900">Temporal policy</div>
        <p className="mt-1 text-xs text-slate-500">Development trains the model, validation selects it, and the frozen season is held out — never used for model selection.</p>
        <div className="mt-3 grid gap-4 sm:grid-cols-4">
          <Field label="Development start"><select value={devStart} onChange={(e) => setDevStart(Number(e.target.value))} className="wf-input">{DEV_YEARS.filter((y) => y <= devEnd).map((y) => <option key={y}>{y}</option>)}</select></Field>
          <Field label="Development end"><select value={devEnd} onChange={(e) => setDevEnd(Number(e.target.value))} className="wf-input">{DEV_YEARS.filter((y) => y >= devStart && y < valSeason).map((y) => <option key={y}>{y}</option>)}</select></Field>
          <Field label="Validation"><select value={valSeason} onChange={(e) => setValSeason(Number(e.target.value))} className="wf-input">{YEARS.filter((y) => y > devEnd && y < frozenSeason).map((y) => <option key={y}>{y}</option>)}</select></Field>
          <Field label="Frozen final"><select value={frozenSeason} onChange={(e) => setFrozenSeason(Number(e.target.value))} className="wf-input">{YEARS.filter((y) => y > valSeason).map((y) => <option key={y}>{y}</option>)}</select></Field>
        </div>
        <TemporalTimeline devSeasons={devSeasons} valSeason={valSeason} frozenSeason={frozenSeason} prospective={prospective} />
        <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-600">
          <div className="font-semibold uppercase tracking-wide text-slate-500">Governed source evidence vs. modeling development</div>
          <div className="mt-1"><b>Source evidence:</b> {GOVERNED_TEMPORAL.sourceEvidenceSeasons[0]}–{GOVERNED_TEMPORAL.sourceEvidenceSeasons.slice(-1)[0]} · <b>Modeling development:</b> {devSeasons[0] ?? "—"}{devSeasons.length > 1 ? `–${devSeasons.slice(-1)[0]}` : ""} · <b>Validation:</b> {valSeason} · <b>Frozen:</b> {frozenSeason}</div>
          <div className="mt-1 text-slate-500">{GOVERNED_TEMPORAL.priorOnlyReason}</div>
        </div>
        {!valid && <p className="mt-2 text-xs font-semibold text-amber-700">Development must end before validation, and validation before the frozen season.</p>}
      </div>

      {/* Evidence mode */}
      <div className="mt-6">
        <div className="text-sm font-semibold text-slate-900">Evidence mode</div>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {(["ENHANCED", "STRICT"] as const).map((m) => (
            <button key={m} type="button" onClick={() => setEvidenceMode(m)}
              className={`rounded-xl border px-4 py-3 text-left text-sm ${evidenceMode === m ? "border-cyan-500 bg-cyan-50" : "border-slate-200 bg-white hover:border-slate-300"}`}>
              <div className="flex items-center gap-2 font-semibold text-slate-900"><ShieldCheck size={15} className={evidenceMode === m ? "text-cyan-600" : "text-slate-400"} /> {m === "ENHANCED" ? "Enhanced research" : "Strict pregame"}</div>
              <div className="mt-1 text-xs text-slate-500">{m === "ENHANCED" ? "All governed research families (player state, usage, weather)." : "Only strictly pregame-available evidence."}</div>
            </button>
          ))}
        </div>
      </div>

      <div className="mt-6 grid gap-4">
        <Field label="Research purpose"><input value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="Establish a leakage-safe game simulation baseline" className="wf-input" /></Field>
        <Field label="Notes"><textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} placeholder="Scope, decision context, known limitations." className="wf-input" /></Field>
      </div>

      <button onClick={save} disabled={!valid} className="sports-primary-button mt-6 disabled:cursor-not-allowed disabled:opacity-50">
        <ShieldCheck size={16} /> Save &amp; Register Forecast Contract
      </button>
    </section>
  );
}

function TemporalTimeline({ devSeasons, valSeason, frozenSeason, prospective }: { devSeasons: number[]; valSeason: number; frozenSeason: number; prospective: number | null }) {
  const segs: { label: string; role: string; cls: string }[] = [
    ...devSeasons.map((y) => ({ label: String(y), role: "DEV", cls: "bg-emerald-500" })),
    { label: String(valSeason), role: "VAL", cls: "bg-amber-500" },
    { label: String(frozenSeason), role: "FROZEN", cls: "bg-rose-500 ring-2 ring-rose-300" },
    ...(prospective ? [{ label: String(prospective), role: "FUTURE", cls: "bg-slate-400" }] : []),
  ];
  return (
    <div className="mt-4">
      <div className="flex gap-1">
        {segs.map((s, i) => (
          <div key={i} className="flex-1 text-center">
            <div className={`h-8 rounded ${s.cls} flex items-center justify-center text-xs font-bold text-white`}>{s.label}</div>
            <div className={`mt-1 text-[10px] font-semibold uppercase ${s.role === "FROZEN" ? "text-rose-600" : "text-slate-500"}`}>{s.role}</div>
          </div>
        ))}
      </div>
      <div className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-rose-200 bg-rose-50 px-2 py-1 text-[11px] font-semibold text-rose-700">
        <ShieldCheck size={12} /> {frozenSeason} FROZEN — not used for model selection
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="flex flex-col gap-1.5"><span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span>{children}</label>;
}
