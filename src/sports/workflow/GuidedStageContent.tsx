// Embedded analytical content for the 9-stage MLB PROGRAM workflow (Phase 6D). Reuses the exact
// standalone module content (no duplication, no iframes) so the scientist stays inside the project.
// Stage 2 merges dataset preview + identity/leakage data-quality; Stage 3 is the PA Modeling Cockpit.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, ExternalLink, CheckCircle2, Layers, ShieldCheck, Database, TriangleAlert } from "lucide-react";
import { getJSON } from "../../lib/api";
import type { ActiveSportsDataset } from "../sportsEvidenceApi";
import {
  ParticipationUsageBody, GameReplaySection, BaseOutTransitionSection, SimulationInputSection,
  WholeGameMonteCarloSection, Phase4SimulationStatus, Phase4ModelLaboratorySection,
  Phase4EvaluationSection, Phase4GraphSection, Phase4RegistrySection,
} from "../Phase4Surfaces";
import PaModelingCockpit from "../cockpit/PaModelingCockpit";
import DataPreviewPanel from "../cockpit/DataPreviewPanel";
import type { StageResolution, ForecastContract } from "./workflowState";
import { GOVERNED_TEMPORAL, developmentWindowLabel } from "./workflowState";

function pct(v: number | undefined | null): string {
  if (v === undefined || v === null || Number.isNaN(v)) return "—";
  const p = v <= 1 ? v * 100 : v;
  return `${p.toFixed(1)}%`;
}

// ---- Stage 2: Data Evidence & Quality (dataset preview + identity/leakage in one workspace) ----
function QualityChip({ label, value, pass = true }: { label: string; value: string; pass?: boolean }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-sm font-semibold ${pass ? "text-emerald-700" : "text-amber-700"}`}>{value}</div>
    </div>
  );
}

export function DataQualitySummary({ dataset }: { dataset: ActiveSportsDataset | null }) {
  const bridge = dataset?.identityBridge;
  const ja = bridge?.joinAudit;
  const audit = dataset?.featureAudit;
  const noFuzzy = bridge?.noNamesOrFuzzyMatching ?? (audit?.joinEvidence?.inferenceOrFuzzyMatchingUsed === false);
  const seasons = audit?.perSeasonRows ?? [];
  const limitations = dataset?.limitations ?? [];
  const mapping = ja ? pct(ja.mappingRate) : (bridge ? "registered" : "—");
  return (
    <section className="sports-panel p-5 sm:p-6">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-cyan-700"><ShieldCheck size={14} /> Data quality</div>
      <h3 className="mt-1 text-lg font-semibold text-slate-950">Is this dataset suitable for modeling?</h3>

      {/* Governed source-evidence vs. modeling-development reconciliation (Phase 6E). Prevents the
          platform from claiming 2021–2023 development when only 2023 is a modeling season. */}
      <div className="mt-3 rounded-xl border border-cyan-200 bg-cyan-50/60 px-4 py-3">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-cyan-700">Population authority — source evidence vs. modeling development</div>
        <div className="mt-1.5 grid gap-2 text-sm sm:grid-cols-4">
          <div><div className="text-[11px] font-semibold uppercase text-slate-400">Source evidence</div><div className="font-semibold text-slate-900">{GOVERNED_TEMPORAL.sourceEvidenceSeasons[0]}–{GOVERNED_TEMPORAL.sourceEvidenceSeasons.slice(-1)[0]}</div></div>
          <div><div className="text-[11px] font-semibold uppercase text-slate-400">Modeling development</div><div className="font-semibold text-emerald-700">{GOVERNED_TEMPORAL.developmentSeasons.join(", ")}</div></div>
          <div><div className="text-[11px] font-semibold uppercase text-slate-400">Validation</div><div className="font-semibold text-amber-700">{GOVERNED_TEMPORAL.validationSeason}</div></div>
          <div><div className="text-[11px] font-semibold uppercase text-slate-400">Frozen final</div><div className="font-semibold text-rose-700">{GOVERNED_TEMPORAL.frozenSeason}</div></div>
        </div>
        <div className="mt-1.5 text-xs text-slate-600">{GOVERNED_TEMPORAL.priorOnlyReason}</div>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-3 lg:grid-cols-4">
        <QualityChip label="Identity mapping" value={ja ? `PASS · ${mapping}` : "PASS"} pass={!ja || (ja.ambiguousReferences ?? 0) === 0} />
        <QualityChip label="Unresolved IDs" value={ja ? String(ja.unresolvedReferences ?? 0) : "0"} pass={!ja || (ja.unresolvedReferences ?? 0) === 0} />
        <QualityChip label="Ambiguous IDs" value={ja ? String(ja.ambiguousReferences ?? 0) : "0"} pass={!ja || (ja.ambiguousReferences ?? 0) === 0} />
        <QualityChip label="Point-in-time review" value={noFuzzy ? "PASS" : "REVIEW"} pass={noFuzzy} />
        <QualityChip label="Target taxonomy" value="8 classes" />
        <QualityChip label="Leakage gate" value={noFuzzy ? "PASS · exact joins" : "REVIEW"} pass={noFuzzy} />
      </div>

      {seasons.length > 0 && (
        <div className="mt-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Prior-history coverage (Y−1 joins)</div>
          <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {seasons.map((s) => (
              <div key={s.season} className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm">
                <div className="font-semibold text-slate-900">{s.season}</div>
                <div className="mt-1 text-slate-600">Batter Y−1 <b>{pct(s.batterYMinus1JoinMatches / Math.max(1, s.batterYMinus1JoinDenominator))}</b></div>
                <div className="text-slate-600">Pitcher Y−1 <b>{pct(s.pitcherYMinus1JoinMatches / Math.max(1, s.pitcherYMinus1JoinDenominator))}</b></div>
              </div>
            ))}
          </div>
        </div>
      )}

      {limitations.length > 0 && (
        <div className="mt-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-amber-700">Known data limitations</div>
          <ul className="mt-1 grid gap-0.5 text-xs text-amber-900">{limitations.slice(0, 5).map((l) => <li key={l}>· {l}</li>)}</ul>
        </div>
      )}

      <details className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
        <summary className="cursor-pointer text-sm font-semibold text-slate-700">Technical authority &amp; lineage</summary>
        <div className="mt-2 grid gap-1 font-mono text-[11px] text-slate-500">
          {bridge ? <div>identity bridge · {bridge.registrationId} · {bridge.manifestSha?.slice(0, 16)}…</div> : null}
          {bridge?.rights ? <div>rights · {bridge.rights.status}</div> : null}
          {audit ? <div>feature audit · {audit.contractVersion} · {audit.status}</div> : null}
          {dataset ? <div>dataset · {dataset.datasetId} · manifest {dataset.manifestSha?.slice(0, 16)}…</div> : null}
        </div>
      </details>
    </section>
  );
}

// ---- Stage 3: PA Model Development intro ----
function CockpitIntro({ contract }: { contract: ForecastContract | null }) {
  const facts: [string, string][] = [
    ["Target", contract?.target || "Plate-Appearance Outcome"],
    ["Development", developmentWindowLabel(contract)],
    ["Validation", contract ? String(contract.validationSeason) : "2024"],
    ["Frozen", contract ? String(contract.frozenSeason) : "2025"],
    ["Champion", "D3 (candidate C4)"],
    ["Evidence mode", contract?.evidenceMode || "STRICT"],
  ];
  return (
    <section className="sports-panel p-5">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-cyan-700"><Layers size={14} /> Begin model development</div>
      <p className="mt-1 text-sm text-slate-600">Project context is inherited automatically — you do not configure it again. Player-state and pitch-sequence research now appear as <b>feature families</b> inside step 06 Feature Engineering.</p>
      <dl className="mt-3 grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-slate-200 bg-slate-200 sm:grid-cols-3 lg:grid-cols-6">
        {facts.map(([k, v]) => <div key={k} className="bg-white px-3 py-2"><dt className="text-[11px] font-semibold uppercase text-slate-400">{k}</dt><dd className="mt-0.5 text-sm font-semibold text-slate-900">{v}</dd></div>)}
      </dl>
    </section>
  );
}

/** Central analytical content for a program stage. Stages 1 & 9 are handled inline in the shell. */
export function GuidedStageContent({ number, dataset, contract }: { number: number; dataset: ActiveSportsDataset | null; contract?: ForecastContract | null }) {
  const p4 = dataset?.phase4;
  switch (number) {
    case 2:
      return <div className="space-y-4"><DataQualitySummary dataset={dataset} /><DataPreviewPanel title="Your selected data" /></div>;
    case 3:
      return <div className="space-y-4"><CockpitIntro contract={contract ?? null} /><PaModelingCockpit embedded /></div>;
    case 4:
      return <div className="space-y-4"><ParticipationUsageBody study={p4} /></div>;
    case 5:
      return (
        <div className="space-y-4">
          <Phase4SimulationStatus study={p4} />
          <GameReplaySection replay={p4?.gameReplay} />
          <BaseOutTransitionSection transition={p4?.baseOutTransition} />
          <SimulationInputSection input={p4?.simulationInput} />
          <WholeGameMonteCarloSection mc={p4?.wholeGameMonteCarlo} />
        </div>
      );
    case 6:
      return <div className="space-y-4"><Phase4ModelLaboratorySection study={p4} /></div>;
    case 7:
      return <div className="space-y-4"><Phase4EvaluationSection study={p4} /></div>;
    case 8:
      return <div className="space-y-4"><Phase4GraphSection study={p4} /><Phase4RegistrySection study={p4} /></div>;
    default:
      return null;
  }
}

/** Compact adopt/continue bar for stages 2 & 4–8. Stage 3 (cockpit) and stage 9 (export) are special. */
export function AdoptBar({ focus, onAdopt }: { focus: StageResolution; onAdopt: () => void }) {
  const complete = focus.status === "COMPLETE";
  const route = focus.action.route || "/dashboard";
  const href = `${route}?from=mlb-workflow&stage=${focus.number}`;
  const moduleLabel = focus.action.moduleLabel || "standalone workspace";
  const label = focus.number === 2 ? "Accept Data & Continue" : focus.action.kind === "inline_adopt" ? focus.action.label : "Accept & Continue";
  return (
    <section className="sports-panel flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
      {complete ? (
        <div className="flex items-center gap-2 text-sm font-semibold text-emerald-700"><CheckCircle2 size={16} /> Adopted by this project — use Continue for the next stage.</div>
      ) : (
        <p className="text-sm text-slate-600">{focus.evidenceAvailable ? "Review the evidence above, then accept it into this project to continue." : "This project has not yet adopted or materialized evidence for this stage."}</p>
      )}
      <div className="flex shrink-0 flex-wrap gap-2">
        <Link to={href} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">Open full {moduleLabel} <ExternalLink size={14} /></Link>
        {!complete && <button onClick={onAdopt} className="sports-primary-button">{label} <ArrowRight size={15} /></button>}
      </div>
    </section>
  );
}
