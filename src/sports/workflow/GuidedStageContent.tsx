// Embedded analytical workspaces for guided steps 4–11. Reuses the exact same content components
// as the standalone modules (no duplicated analytical logic, no iframes) so the user stays inside
// the MLB project shell. The workflow shell already provides the hero, project identity, progress,
// and Previous/Continue — these bodies render only the analytical content.
import { Link } from "react-router-dom";
import { ArrowRight, ExternalLink, CheckCircle2, Layers } from "lucide-react";
import type { ActiveSportsDataset } from "../sportsEvidenceApi";
import {
  PlayerTeamStateBody, ParticipationUsageBody, GameReplaySection, BaseOutTransitionSection,
  SimulationInputSection, WholeGameMonteCarloSection, Phase4SimulationStatus,
  Phase4ModelLaboratorySection, Phase4EvaluationSection, Phase4GraphSection, Phase4RegistrySection,
} from "../Phase4Surfaces";
import PaModelingCockpit from "../cockpit/PaModelingCockpit";
import type { StageResolution } from "./workflowState";

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

/** Central analytical content for a guided step. Returns null for steps handled inline (1–3, 12). */
export function GuidedStageContent({ number, dataset }: { number: number; dataset: ActiveSportsDataset | null }) {
  const phase4 = dataset?.phase4;
  switch (number) {
    case 4:
      return <div className="space-y-4"><PlayerStateBaseline dataset={dataset} /><PlayerTeamStateBody study={phase4} /></div>;
    case 5:
      return <div className="space-y-4"><ParticipationUsageBody study={phase4} /></div>;
    case 6:
      return <PaModelingCockpit embedded />;
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

/** Compact adopt/continue bar shown beneath embedded content for steps 4–11. */
export function AdoptBar({ focus, onAdopt }: { focus: StageResolution; onAdopt: () => void }) {
  const complete = focus.status === "COMPLETE";
  const route = focus.action.route || "/dashboard";
  const href = `${route}?from=mlb-workflow&step=${focus.number}`;
  const moduleLabel = focus.action.moduleLabel || "standalone workspace";
  const label = focus.number === 6 ? "Adopt Current PA Champion & Continue" : focus.action.kind === "inline_adopt" ? focus.action.label : "Accept & Continue";
  return (
    <section className="sports-panel flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
      {complete ? (
        <div className="flex items-center gap-2 text-sm font-semibold text-emerald-700"><CheckCircle2 size={16} /> Adopted by this project</div>
      ) : (
        <p className="text-sm text-slate-600">{focus.evidenceAvailable ? "Review the evidence above, then adopt it into this project to continue." : "This project has not yet adopted or materialized evidence for this stage."}</p>
      )}
      <div className="flex shrink-0 flex-wrap gap-2">
        <Link to={href} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">Open full {moduleLabel} <ExternalLink size={14} /></Link>
        {!complete && <button onClick={onAdopt} className="sports-primary-button">{label} <ArrowRight size={15} /></button>}
      </div>
    </section>
  );
}
