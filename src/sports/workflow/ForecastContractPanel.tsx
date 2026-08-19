// Stage 1 — Project & Forecast Contract. Prefilled from project creation; the scientist reviews
// and formalizes the target, temporal policy, and evidence mode, then registers a versioned
// forecast contract. The 2025 frozen season is visually distinct and never used for selection.
import { useState } from "react";
import { ShieldCheck, Sparkles, FlaskConical, TriangleAlert } from "lucide-react";
import type { SportsProjectMetadata } from "../sportsConfig";
import { TARGETS_BY_WORKFLOW, FORECAST_LIFECYCLES } from "../sportsConfig";
import {
  DEFAULT_TEMPORAL, GOVERNED_TEMPORAL, governedDevelopmentSeasons, isEligibleDevelopmentStart,
  SEASON_ROLE_POLICY, saveContract, saveTemporalDraft, type ForecastContract,
} from "./workflowState";

const YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026];
// Development START may be inspected for any registered candidate season (2021–2023). Only 2023 is
// eligible under the current Gen-2 policy; selecting 2021/2022 creates a separate RESEARCH DRAFT and
// never overwrites the registered contract (see save handlers below).
const DEV_START_CANDIDATES = [2021, 2022, 2023];
const SOURCE_TIMELINE = [2021, 2022, 2023, 2024, 2025, 2026];

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
  const [excludePriorFamilies, setExcludePriorFamilies] = useState(false);
  const [draftSaved, setDraftSaved] = useState(false);
  const devSeasons = YEARS.filter((y) => y >= devStart && y <= devEnd);
  const valid = devSeasons.length > 0 && devEnd < valSeason && valSeason < frozenSeason;
  // Selecting an earlier development start is a REVISED research spec, not the governed Gen-2 contract.
  const isRevised = !isEligibleDevelopmentStart(devStart);
  const noPriorSeason = devStart <= 2021;  // 2021 has no <=2020 registered prior for Y-1 features

  // Save the GOVERNED contract — only when the development window is eligible (2023 start).
  const save = () => {
    if (!valid || isRevised) return;
    const contract: ForecastContract = {
      projectId,
      version: (existing?.version ?? 0) + 1,
      target,
      lifecycle,
      developmentSeasons: governedDevelopmentSeasons(devSeasons),
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

  // Save a REVISED TEMPORAL EXPERIMENT — a separate research draft that never mutates the registered
  // Gen-2 contract. This is what an earlier development start produces.
  const saveRevised = () => {
    if (!valid) return;
    saveTemporalDraft({
      projectId,
      developmentSeasons: devSeasons,
      validationSeason: valSeason,
      frozenSeason,
      excludePriorFamilies,
      rationale: purpose.trim() || notes.trim(),
      savedAt: new Date().toISOString(),
    });
    setDraftSaved(true);
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
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-sm font-semibold text-slate-900">Temporal policy</div>
          <div className="text-[11px] font-semibold text-slate-500">Source evidence {GOVERNED_TEMPORAL.sourceEvidenceSeasons[0]}–{GOVERNED_TEMPORAL.sourceEvidenceSeasons.slice(-1)[0]}</div>
        </div>
        <p className="mt-1 text-xs text-slate-500">Development trains, validation selects, and the frozen season is held out — never used for model selection. <b>Every registered season exists</b>; earlier seasons carry another governed role, they are not missing data.</p>

        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Source evidence</div>
            <div className="mt-0.5 text-lg font-semibold text-slate-900">2021–2025</div>
            <div className="text-xs text-slate-500">all registered FD1 seasons</div>
          </div>
          <div className="rounded-xl border border-cyan-200 bg-cyan-50/60 p-3">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-cyan-700">Current Gen-2 model policy</div>
            <div className="mt-0.5 text-sm font-semibold text-slate-900">Dev 2023 · Val 2024 · Frozen 2025</div>
            <div className="text-xs text-slate-500">2021–2022 = prior-history evidence</div>
          </div>
        </div>

        <div className="mt-3 grid gap-4 sm:grid-cols-4">
          <Field label="Development start"><select value={devStart} onChange={(e) => setDevStart(Number(e.target.value))} className="wf-input">{DEV_START_CANDIDATES.filter((y) => y <= devEnd).map((y) => <option key={y} value={y}>{y}{isEligibleDevelopmentStart(y) ? "" : " — not eligible"}</option>)}</select></Field>
          <Field label="Development end"><select value={devEnd} onChange={(e) => setDevEnd(Number(e.target.value))} className="wf-input">{YEARS.filter((y) => y >= devStart && y < valSeason && y <= 2023).map((y) => <option key={y}>{y}</option>)}</select></Field>
          <Field label="Validation"><select value={valSeason} onChange={(e) => setValSeason(Number(e.target.value))} className="wf-input">{YEARS.filter((y) => y > devEnd && y < frozenSeason).map((y) => <option key={y}>{y}</option>)}</select></Field>
          <Field label="Frozen final"><select value={frozenSeason} onChange={(e) => setFrozenSeason(Number(e.target.value))} className="wf-input">{YEARS.filter((y) => y > valSeason).map((y) => <option key={y}>{y}</option>)}</select></Field>
        </div>

        <SourceEvidenceTimeline devSeasons={devSeasons} valSeason={valSeason} frozenSeason={frozenSeason} isRevised={isRevised} />

        <div className="mt-3 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
          <b>{devStart} — {SEASON_ROLE_POLICY[devStart]?.role}:</b> {SEASON_ROLE_POLICY[devStart]?.reason}
        </div>

        {isRevised && (
          <div className="mt-3 rounded-xl border border-amber-300 bg-amber-50 p-4">
            <div className="flex items-center gap-2 text-sm font-semibold text-amber-900"><TriangleAlert size={15} /> Revised temporal experiment — research draft</div>
            <p className="mt-1 text-xs text-amber-900">A development start of <b>{devStart}</b> is <b>not part of the registered Gen-2 policy</b>. Saving here creates a separate research draft — it will <b>not overwrite</b> the governed contract (Dev 2023 · Val 2024 · Frozen 2025).</p>
            {noPriorSeason && (
              <div className="mt-2 rounded-lg border border-amber-200 bg-white p-3 text-xs">
                <div className="font-semibold text-slate-900">2021 feasibility assessment</div>
                <ul className="mt-1 space-y-0.5 text-slate-600">
                  <li>· Target rows available: <b className="text-emerald-700">YES</b></li>
                  <li>· Y−1 player-state features: <b className="text-rose-700">NOT AVAILABLE</b> — no pre-2021 registered history (2020 data does not exist here)</li>
                </ul>
                <label className="mt-2 flex items-center gap-2 font-semibold text-slate-700"><input type="checkbox" checked={excludePriorFamilies} onChange={(e) => setExcludePriorFamilies(e.target.checked)} className="h-4 w-4 rounded border-slate-300" /> Exclude prior-history feature families for this experiment</label>
                <p className="mt-1 text-[11px] text-slate-500">Explicit alternatives: (A) exclude prior-history families above, (B) begin development in 2022, or (C) retain the current 2023 Gen-2 policy. This tool does not choose for you and never fabricates 2020 data.</p>
              </div>
            )}
            {draftSaved && <div className="mt-2 rounded-md bg-emerald-100 px-2 py-1 text-[11px] font-semibold text-emerald-800">Revised temporal experiment saved as a research draft — the registered Gen-2 contract is unchanged.</div>}
          </div>
        )}

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

      {isRevised ? (
        <button onClick={saveRevised} disabled={!valid} className="sports-primary-button mt-6 disabled:cursor-not-allowed disabled:opacity-50">
          <FlaskConical size={16} /> Create revised temporal experiment
        </button>
      ) : (
        <button onClick={save} disabled={!valid} className="sports-primary-button mt-6 disabled:cursor-not-allowed disabled:opacity-50">
          <ShieldCheck size={16} /> Save &amp; Register Forecast Contract
        </button>
      )}
    </section>
  );
}

// Full source-evidence timeline (2021–2026) with each season's governed role. When a revised research
// spec proposes an earlier development window, those seasons show a distinct "DEV?" draft overlay. The
// frozen season is never presented as tunable/selectable.
function SourceEvidenceTimeline({ devSeasons, valSeason, frozenSeason, isRevised }: { devSeasons: number[]; valSeason: number; frozenSeason: number; isRevised: boolean }) {
  const roleOf = (y: number): { label: string; cls: string; textCls: string } => {
    if (isRevised && devSeasons.includes(y)) return { label: "DEV?", cls: "bg-violet-500 ring-2 ring-violet-300", textCls: "text-violet-600" };
    if (!isRevised && devSeasons.includes(y)) return { label: "DEV", cls: "bg-emerald-500", textCls: "text-emerald-600" };
    if (y === valSeason) return { label: "VAL", cls: "bg-amber-500", textCls: "text-amber-600" };
    if (y === frozenSeason) return { label: "FROZEN", cls: "bg-rose-500 ring-2 ring-rose-300", textCls: "text-rose-600" };
    if (SEASON_ROLE_POLICY[y]?.role === "PRIOR HISTORY") return { label: "PRIOR", cls: "bg-slate-400", textCls: "text-slate-500" };
    return { label: "FUTURE", cls: "bg-slate-300", textCls: "text-slate-400" };
  };
  return (
    <div className="mt-4">
      <div className="flex gap-1">
        {SOURCE_TIMELINE.map((y) => {
          const r = roleOf(y);
          return (
            <div key={y} className="flex-1 text-center">
              <div className={`flex h-8 items-center justify-center rounded text-xs font-bold text-white ${r.cls}`}>{y}</div>
              <div className={`mt-1 text-[10px] font-semibold uppercase ${r.textCls}`}>{r.label}</div>
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        <span className="inline-flex items-center gap-1.5 rounded-md border border-rose-200 bg-rose-50 px-2 py-1 text-[11px] font-semibold text-rose-700"><ShieldCheck size={12} /> {frozenSeason} FROZEN — never used for model selection</span>
        {isRevised && <span className="inline-flex items-center gap-1.5 rounded-md border border-violet-200 bg-violet-50 px-2 py-1 text-[11px] font-semibold text-violet-700">DEV? — proposed research draft, not registered</span>}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="flex flex-col gap-1.5"><span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span>{children}</label>;
}
