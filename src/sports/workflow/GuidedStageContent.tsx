// Embedded analytical workspaces for guided steps 4–11. Reuses the exact same content components
// as the standalone modules (no duplicated analytical logic, no iframes) so the user stays inside
// the MLB project shell. The workflow shell already provides the hero, project identity, progress,
// and Previous/Continue — these bodies render only the analytical content.
import { Link } from "react-router-dom";
import { ArrowRight, ExternalLink, CheckCircle2, Layers, CircleDot } from "lucide-react";
import type { ActiveSportsDataset } from "../sportsEvidenceApi";
import {
  PlayerTeamStateBody, ParticipationUsageBody, GameReplaySection, BaseOutTransitionSection,
  SimulationInputSection, WholeGameMonteCarloSection, Phase4SimulationStatus,
  Phase4ModelLaboratorySection, Phase4EvaluationSection, Phase4GraphSection, Phase4RegistrySection,
} from "../Phase4Surfaces";
import PaModelingCockpit from "../cockpit/PaModelingCockpit";
import type { StageResolution, ForecastContract } from "./workflowState";

function pct(v: number | undefined | null): string {
  if (v === undefined || v === null || Number.isNaN(v)) return "—";
  const p = v <= 1 ? v * 100 : v;
  return `${p.toFixed(1)}%`;
}

/** Player-state baseline summary (adopted Y−1 prior state) rendered above the optional research. */
function PlayerStateBaseline({ dataset }: { dataset: ActiveSportsDataset | null }) {
  const seasons = dataset?.featureAudit?.perSeasonRows ?? [];
  return (
    <section className="sports-panel p-5 sm:p-6">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-cyan-700"><Layers size={14} /> Adopted player-state baseline</div>
      <h3 className="mt-1 text-lg font-semibold text-slate-950">Bounded Y−1 batter &amp; pitcher prior state</h3>
      <p className="mt-1 text-sm text-slate-600">This is the leakage-safe player state the PA baseline uses: latest eligible prior-season batting and pitching priors plus explicit missing-history indicators.</p>
      {seasons.length > 0 ? (
        <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {seasons.map((s) => (
            <div key={s.season} className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm">
              <div className="font-semibold text-slate-900">{s.season}</div>
              <div className="mt-1 text-slate-600">Batter Y−1: <b>{pct(s.batterYMinus1JoinMatches / Math.max(1, s.batterYMinus1JoinDenominator))}</b></div>
              <div className="text-slate-600">Pitcher Y−1: <b>{pct(s.pitcherYMinus1JoinMatches / Math.max(1, s.pitcherYMinus1JoinDenominator))}</b></div>
            </div>
          ))}
        </div>
      ) : null}
      <div className="mt-4 rounded-xl border border-cyan-100 bg-cyan-50/50 px-4 py-3 text-sm text-slate-700">
        <b className="font-semibold text-slate-900">Optional / advanced research below.</b> Dynamic player state, E1 pitch-sequence features, and E2 interactions are shown with honest status — they are not required to proceed on the adopted baseline.
      </div>
    </section>
  );
}

/** Concise project context above the embedded cockpit (Step 6). */
function Step6Intro({ dataset, contract }: { dataset: ActiveSportsDataset | null; contract: ForecastContract | null }) {
  const facts: [string, string][] = [
    ["Target", contract?.target || "Plate-Appearance Outcome"],
    ["Development", contract ? `${contract.developmentSeasons[0]}–${contract.developmentSeasons.slice(-1)[0]}` : "2021–2023"],
    ["Validation", contract ? String(contract.validationSeason) : "2024"],
    ["Frozen", contract ? String(contract.frozenSeason) : "2025"],
    ["Champion", "D3 (candidate C4)"],
    ["Evidence mode", contract?.evidenceMode || "STRICT"],
  ];
  return (
    <section className="sports-panel p-5">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-cyan-700"><Layers size={14} /> Begin model development</div>
      <p className="mt-1 text-sm text-slate-600">The project context below is loaded automatically — you do not configure it again. Develop, tune, evaluate, and compare plate-appearance models in the cockpit.</p>
      <dl className="mt-3 grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-slate-200 bg-slate-200 sm:grid-cols-3 lg:grid-cols-6">
        {facts.map(([k, v]) => <div key={k} className="bg-white px-3 py-2"><dt className="text-[11px] font-semibold uppercase text-slate-400">{k}</dt><dd className="mt-0.5 text-sm font-semibold text-slate-900">{v}</dd></div>)}
      </dl>
    </section>
  );
}

/** Central analytical content for a guided step. Returns null for steps handled inline (1–3, 12). */
export function GuidedStageContent({ number, dataset, contract }: { number: number; dataset: ActiveSportsDataset | null; contract?: ForecastContract | null }) {
  const phase4 = dataset?.phase4;
  switch (number) {
    case 4:
      return <div className="space-y-4"><PlayerStateBaseline dataset={dataset} /><PlayerTeamStateBody study={phase4} /></div>;
    case 5:
      return <div className="space-y-4"><ParticipationUsageBody study={phase4} /></div>;
    case 6:
      return <div className="space-y-4"><Step6Intro dataset={dataset} contract={contract ?? null} /><PaModelingCockpit embedded /></div>;
    case 7:
      return (
        <div className="space-y-4">
          <Phase4SimulationStatus study={phase4} />
          <GameReplaySection replay={phase4?.gameReplay} />
          <BaseOutTransitionSection transition={phase4?.baseOutTransition} />
          <SimulationInputSection input={phase4?.simulationInput} />
          <WholeGameMonteCarloSection mc={phase4?.wholeGameMonteCarlo} />
        </div>
      );
    case 8:
      return <div className="space-y-4"><Phase4ModelLaboratorySection study={phase4} /></div>;
    case 9:
    case 10:
      return <div className="space-y-4"><Phase4EvaluationSection study={phase4} /></div>;
    case 11:
      return <div className="space-y-4"><Phase4GraphSection study={phase4} /><Phase4RegistrySection study={phase4} /></div>;
    default:
      return null;
  }
}

function OptionalRow({ label, enabled }: { label: string; enabled: boolean }) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm">
      <span className="text-slate-700">{label}</span>
      <span className={`inline-flex items-center gap-1.5 text-xs font-semibold ${enabled ? "text-emerald-700" : "text-slate-400"}`}>
        <span className={`h-1.5 w-1.5 rounded-full ${enabled ? "bg-emerald-500" : "bg-slate-300"}`} />{enabled ? "Enabled" : "Not enabled"}
      </span>
    </div>
  );
}

/** Compact foundation-ready view for auto-satisfied Steps 4 & 5 — no empty NOT_RUN panels dominate;
 *  optional/advanced research collapses under a disclosure. */
export function AutoSatisfiedFoundation({ focus, dataset }: { focus: StageResolution; dataset: ActiveSportsDataset | null }) {
  const p4 = dataset?.phase4;
  if (focus.number === 4) {
    return (
      <section className="space-y-4">
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5">
          <div className="flex items-center gap-2 text-emerald-800"><CheckCircle2 size={18} /><span className="text-lg font-semibold">Player-state foundation ready</span></div>
          <p className="mt-1 text-sm text-emerald-900">This project uses the bounded Y−1 batter/pitcher prior state, which is sufficient for PA modeling. {focus.requiredFor}.</p>
        </div>
        <PlayerStateBaseline dataset={dataset} />
        <section className="sports-panel p-5">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Optional / advanced player-state research</div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            <OptionalRow label="Dynamic player state" enabled={Boolean(p4?.components?.dynamicState)} />
            <OptionalRow label="E1 pitch-sequence features" enabled={Boolean(p4?.pitchSequenceFeatures)} />
            <OptionalRow label="E2 process interactions" enabled={Boolean(p4?.processInteractions)} />
            <OptionalRow label="Handedness / platoon" enabled={false} />
          </div>
          <details className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
            <summary className="cursor-pointer text-sm font-semibold text-slate-700">Explore advanced player-state research</summary>
            <div className="mt-3"><PlayerTeamStateBody study={p4} /></div>
          </details>
        </section>
      </section>
    );
  }
  // Step 5 — participation
  const parts = [
    { key: "lineup", label: "Lineup projection" },
    { key: "starterDuration", label: "Starter duration" },
    { key: "bullpenUsage", label: "Bullpen usage" },
  ] as const;
  return (
    <section className="space-y-4">
      <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5">
        <div className="flex items-center gap-2 text-emerald-800"><CheckCircle2 size={18} /><span className="text-lg font-semibold">Participation foundation sufficient for PA modeling</span></div>
        <p className="mt-1 text-sm text-emerald-900">Lineup, starter, and bullpen components are prerequisites for full-game simulation (Step 7). {focus.requiredFor}. You can develop the PA model now.</p>
      </div>
      <section className="sports-panel p-5">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Participation components</div>
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          {parts.map((p) => (
            <div key={p.key} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm">
              <div className="font-semibold text-slate-800">{p.label}</div>
              <div className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-500"><CircleDot size={11} className="text-cyan-600" />{p4?.components?.[p.key] ? "Existing research" : "Simulation dependency"}</div>
            </div>
          ))}
        </div>
        <details className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
          <summary className="cursor-pointer text-sm font-semibold text-slate-700">Customize participation &amp; usage</summary>
          <div className="mt-3"><ParticipationUsageBody study={p4} /></div>
        </details>
      </section>
    </section>
  );
}

/** Compact adopt/continue bar shown beneath embedded content for steps 4–11. */
export function AdoptBar({ focus, onAdopt }: { focus: StageResolution; onAdopt: () => void }) {
  const complete = focus.status === "COMPLETE";
  const route = focus.action.route || "/dashboard";
  const href = `${route}?from=mlb-workflow&step=${focus.number}`;
  const moduleLabel = focus.action.moduleLabel || "standalone workspace";
  const label = focus.number === 6 ? "Adopt Current PA Champion & Continue" : focus.action.kind === "inline_adopt" ? focus.action.label : "Accept & Continue";
  const secondaryLabel = focus.autoSatisfied ? `Customize (${moduleLabel})` : `Open full ${moduleLabel}`;
  return (
    <section className="sports-panel flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
      {complete ? (
        <div className="flex items-center gap-2 text-sm font-semibold text-emerald-700"><CheckCircle2 size={16} /> {focus.autoSatisfied ? "Foundation ready — no required decision. Use Continue to start modeling." : "Adopted by this project"}</div>
      ) : (
        <p className="text-sm text-slate-600">{focus.evidenceAvailable ? "Review the evidence above, then adopt it into this project to continue." : "This project has not yet adopted or materialized evidence for this stage."}</p>
      )}
      <div className="flex shrink-0 flex-wrap gap-2">
        <Link to={href} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">{secondaryLabel} <ExternalLink size={14} /></Link>
        {!complete && <button onClick={onAdopt} className="sports-primary-button">{label} <ArrowRight size={15} /></button>}
      </div>
    </section>
  );
}

/** Foundation checkpoint shown at the top of Step 6 — fast confirmation before modeling. */
export function FoundationSummary({ resolutions, onGoStep }: { resolutions: StageResolution[]; onGoStep: (n: number) => void }) {
  const items = resolutions.slice(0, 5);
  const allReady = items.every((r) => r.status === "COMPLETE");
  if (!allReady) return null;
  const labels: Record<number, string> = { 1: "Forecast contract", 2: "Registered MLB evidence", 3: "Identity & leakage checks", 4: "Player-state baseline", 5: "PA-modeling participation prerequisites" };
  return (
    <section className="rounded-2xl border border-emerald-200 bg-emerald-50/70 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-xs font-semibold uppercase tracking-[0.14em] text-emerald-700">Model foundation complete</div>
        <div className="flex gap-2">
          <button onClick={() => onGoStep(4)} className="rounded-lg border border-emerald-300 bg-white px-2.5 py-1 text-xs font-semibold text-emerald-800 hover:bg-emerald-50">Customize player state</button>
          <button onClick={() => onGoStep(5)} className="rounded-lg border border-emerald-300 bg-white px-2.5 py-1 text-xs font-semibold text-emerald-800 hover:bg-emerald-50">Customize participation</button>
        </div>
      </div>
      <div className="mt-3 grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((r) => <div key={r.number} className="flex items-center gap-2 text-sm text-slate-700"><CheckCircle2 size={15} className="shrink-0 text-emerald-600" />{labels[r.number]}</div>)}
      </div>
      <p className="mt-3 text-sm font-semibold text-slate-900">Foundation ready — begin plate-appearance model development below.</p>
    </section>
  );
}
