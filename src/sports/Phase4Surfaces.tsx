import type { ReactNode } from "react";
import {
  Activity,
  CircleDashed,
  GitBranch,
  Layers3,
  ShieldCheck,
  Users,
} from "lucide-react";
import {
  useActiveSportsDataset,
  type SportsCatcherReadiness,
  type SportsPhase4Component,
  type SportsPhase4EvidenceRecord,
  type SportsPhase4Study,
  type SportsPitchSequenceFeatures,
  type SportsProcessInteractions,
  type SportsIncrementalSignalStudy,
  type SportsSevereMissForensics,
  type SportsGameReplay,
  type SportsBaseOutTransition,
  type SportsSimulationInput,
  type SportsWholeGameMonteCarlo,
  type SportsParticipationAblation,
  type SportsStarterIdentity,
} from "./sportsEvidenceApi";

function record(value: unknown): SportsPhase4EvidenceRecord {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as SportsPhase4EvidenceRecord
    : {};
}

function text(value: unknown, fallback = "—") {
  return typeof value === "string" && value ? value : fallback;
}

function number(value: unknown) {
  const result = Number(value);
  return Number.isFinite(result) ? result : undefined;
}

function metric(value: unknown, digits = 5) {
  const result = number(value);
  return result === undefined
    ? "—"
    : result.toLocaleString("en-US", { maximumFractionDigits: digits });
}

function integer(value: unknown) {
  const result = number(value);
  return result === undefined ? "—" : Math.round(result).toLocaleString("en-US");
}

function statusClass(status: string) {
  if (/CHALLENGER|COMPONENT/.test(status)) return "border-violet-200 bg-violet-50 text-violet-800";
  if (/BASELINE/.test(status)) return "border-cyan-200 bg-cyan-50 text-cyan-800";
  if (/REJECTED|BLOCKED/.test(status)) return "border-amber-200 bg-amber-50 text-amber-800";
  return "border-slate-200 bg-slate-50 text-slate-700";
}

function Status({ value }: { value: string }) {
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${statusClass(value)}`}>{value}</span>;
}

function SurfaceFrame({
  eyebrow,
  title,
  description,
  status,
  facts,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  status: string;
  facts: Array<{ label: string; value: string }>;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0 space-y-5 pb-10">
      <header className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 px-5 py-6 text-white shadow-xl sm:px-7">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-200">{eyebrow}</span>
          <Status value={status} />
        </div>
        <h1 className="mt-4 text-3xl font-semibold tracking-tight sm:text-4xl">{title}</h1>
        <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-300 sm:text-base">{description}</p>
        <dl className="mt-6 grid gap-px overflow-hidden rounded-xl border border-white/10 bg-white/10 sm:grid-cols-3">
          {facts.map((fact) => (
            <div key={fact.label} className="bg-slate-950/75 px-4 py-3">
              <dt className="text-xs text-slate-400">{fact.label}</dt>
              <dd className="mt-1 break-words text-sm font-semibold tabular-nums text-white">{fact.value}</dd>
            </div>
          ))}
        </dl>
      </header>
      {children}
    </div>
  );
}

function Card({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-100 px-5 py-4 sm:px-6">
        <h2 className="text-lg font-semibold text-slate-950">{title}</h2>
        {description ? <p className="mt-1 text-sm leading-6 text-slate-600">{description}</p> : null}
      </div>
      <div className="p-5 sm:p-6">{children}</div>
    </section>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-sm text-slate-600">
      <CircleDashed className="mx-auto mb-2 text-slate-400" size={22} aria-hidden="true" />
      {children}
    </div>
  );
}

function EvidenceGrid({ evidence }: { evidence: SportsPhase4EvidenceRecord }) {
  const entries = Object.entries(evidence).filter(([, value]) => (
    typeof value === "string" || typeof value === "number" || typeof value === "boolean"
  ));
  if (!entries.length) return <Empty>No bounded summary evidence was registered.</Empty>;
  return (
    <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {entries.map(([key, value]) => (
        <div key={key} className="min-w-0 rounded-xl border border-slate-200 bg-slate-50 p-3">
          <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{key.replaceAll(/([A-Z])/g, " $1")}</dt>
          <dd className="mt-1 break-words text-sm font-semibold tabular-nums text-slate-900">
            {typeof value === "number" ? metric(value) : typeof value === "boolean" ? value ? "Yes" : "No" : String(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function candidateId(value: SportsPhase4EvidenceRecord) {
  return text(value.candidateId ?? value.id, "candidate");
}

function foldRows(component: SportsPhase4Component) {
  return component.folds.map((fold) => {
    const metrics = record(fold.metrics ?? fold.rawMetrics);
    return {
      candidateId: text(fold.candidateId),
      foldId: text(fold.foldId),
      season: number(fold.validationSeason),
      metrics,
    };
  });
}

function candidateFold(component: SportsPhase4Component, id: string, season: number) {
  return foldRows(component).find((fold) => fold.candidateId === id && fold.season === season)?.metrics ?? {};
}

function metricValue(metrics: SportsPhase4EvidenceRecord, key: string) {
  const aliases: Record<string, string[]> = {
    logLoss: ["logLoss", "binaryLogLoss"],
    topNineRecall: ["topNineRecall", "top9Recall"],
    topThreeRecall: ["topThreeRecall", "top3Recall"],
    topFiveRecall: ["topFiveRecall", "top5Recall"],
  };
  for (const candidate of aliases[key] ?? [key]) {
    const value = number(metrics[candidate]);
    if (value !== undefined) return value;
  }
  if (key === "topLabelEce") {
    const calibration = record(metrics.topLabelCalibration);
    return number(calibration.expectedCalibrationError);
  }
  return undefined;
}

function CandidateTable({ component, metricKeys }: { component: SportsPhase4Component; metricKeys: string[] }) {
  if (!component.candidates.length) return <Empty>No governed candidate rows were registered.</Empty>;
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200">
      <table className="w-full min-w-[900px] text-left text-xs">
        <thead className="bg-slate-900 text-slate-200">
          <tr>
            <th className="px-3 py-3">Candidate</th>
            <th className="px-3 py-3">Configuration</th>
            {metricKeys.flatMap((key) => [2024, 2025].map((season) => (
              <th key={`${key}-${season}`} className="px-3 py-3">{season} {key}</th>
            )))}
            <th className="px-3 py-3">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {component.candidates.map((candidate) => {
            const id = candidateId(candidate);
            const config = record(candidate.config ?? candidate.hyperparameters);
            return (
              <tr key={id}>
                <td className="px-3 py-3 font-semibold text-slate-950">{id}<div className="mt-0.5 font-normal text-slate-500">{text(candidate.displayName ?? candidate.name, "")}</div></td>
                <td className="max-w-[260px] px-3 py-3 text-slate-600">{Object.keys(config).length ? JSON.stringify(config) : "Frozen policy"}</td>
                {metricKeys.flatMap((key) => [2024, 2025].map((season) => (
                  <td key={`${id}-${key}-${season}`} className="px-3 py-3 tabular-nums text-slate-700">{metric(metricValue(candidateFold(component, id, season), key))}</td>
                )))}
                <td className="px-3 py-3"><Status value={text(candidate.status, candidate.eligible === false ? "REJECTED" : "RECORDED")} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function FoldMetricChart({ component, metricKey }: { component: SportsPhase4Component; metricKey?: string }) {
  const selectedMetric = metricKey ?? (component.componentType === "STARTER_DURATION"
    ? "bfpMae"
    : component.componentType === "LINEUP_PROJECTION"
      ? "topNineRecall"
      : component.componentType === "BULLPEN_USAGE" ? "brierScore" : "logLoss");
  const rows = foldRows(component).flatMap((fold) => {
    const value = metricValue(fold.metrics, selectedMetric);
    return value === undefined ? [] : [{ ...fold, value }];
  });
  if (!rows.length) return <Empty>No fold-level {selectedMetric} observations were supplied.</Empty>;
  const maximum = Math.max(...rows.map((row) => row.value), Number.EPSILON);
  return (
    <figure aria-label={`${component.contractName} ${selectedMetric} by candidate and fold`}>
      <figcaption className="text-xs font-semibold uppercase tracking-wide text-slate-500">{selectedMetric} · supplied fold evidence</figcaption>
      <div className="mt-3 space-y-2">
        {rows.map((row, index) => (
          <div key={`${row.candidateId}-${row.foldId}-${index}`} className="grid grid-cols-[minmax(110px,.42fr)_minmax(120px,1fr)_72px] items-center gap-2 text-xs">
            <span className="truncate font-medium text-slate-700">{row.candidateId} · {row.season ?? row.foldId}</span>
            <span className="h-3 overflow-hidden rounded-full bg-slate-200"><span className="block h-full rounded-full bg-gradient-to-r from-cyan-500 to-blue-500" style={{ width: `${Math.max(1.5, row.value / maximum * 100)}%` }} /></span>
            <span className="text-right font-semibold tabular-nums text-slate-900">{metric(row.value)}</span>
          </div>
        ))}
      </div>
    </figure>
  );
}

function CalibrationChart({ component }: { component: SportsPhase4Component }) {
  const selectedId = text(component.selected?.candidateId, "");
  const rows = foldRows(component).filter((fold) => fold.candidateId === selectedId).flatMap((fold) => {
    const dynamicBins = Array.isArray(fold.metrics.topLabelReliability)
      ? fold.metrics.topLabelReliability
      : [];
    const binaryCalibration = record(fold.metrics.calibration ?? fold.metrics.topLabelCalibration);
    const binaryBins = Array.isArray(binaryCalibration.bins) ? binaryCalibration.bins : [];
    const bins = dynamicBins.length ? dynamicBins : binaryBins;
    return bins.flatMap((item) => {
      const bin = record(item);
      const predicted = number(bin.meanConfidence ?? bin.meanProbability);
      const observed = number(bin.accuracy ?? bin.observedRate);
      const count = number(bin.count);
      return predicted === undefined || observed === undefined || count === undefined
        ? []
        : [{ season: fold.season, bin: number(bin.binIndex) ?? 0, predicted, observed, count }];
    });
  });
  if (!rows.length) return <Empty>No selected-candidate calibration bins were supplied.</Empty>;
  return (
    <figure aria-label={`${component.contractName} selected-candidate calibration`}>
      <figcaption className="text-xs font-semibold uppercase tracking-wide text-slate-500">Calibration · predicted versus observed</figcaption>
      <div className="mt-3 grid gap-4 lg:grid-cols-2">
        {[2024, 2025].map((season) => {
          const seasonRows = rows.filter((row) => row.season === season);
          return (
            <div key={season} className="rounded-lg border border-slate-200 bg-white p-3">
              <div className="text-xs font-semibold text-slate-700">{season}</div>
              <div className="mt-2 space-y-1.5">
                {seasonRows.map((row) => (
                  <div key={row.bin} className="grid grid-cols-[28px_1fr_48px] items-center gap-2 text-[10px]">
                    <span className="text-slate-500">B{row.bin + 1}</span>
                    <span className="relative block h-3 rounded bg-slate-100" title={`n=${row.count}; predicted=${row.predicted}; observed=${row.observed}`}>
                      <span className="absolute inset-y-0 left-0 rounded bg-cyan-300" style={{ width: `${Math.max(1, row.predicted * 100)}%` }} />
                      <span className="absolute inset-y-0 left-0 border-r-2 border-violet-700" style={{ width: `${Math.max(1, row.observed * 100)}%` }} />
                    </span>
                    <span className="text-right tabular-nums text-slate-600">n={integer(row.count)}</span>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
      <p className="mt-2 text-[11px] text-slate-500">Cyan bar: mean predicted confidence/probability · violet marker: observed rate.</p>
    </figure>
  );
}

function EffectiveSampleSizeChart({ component }: { component: SportsPhase4Component }) {
  const groups = Array.isArray(component.coverage.subgroups)
    ? component.coverage.subgroups.flatMap((item) => {
        const row = record(item);
        const finalMetrics = record(row.finalMetrics);
        const value = number(finalMetrics.logLoss);
        const count = number(row.rowCount);
        return value === undefined || count === undefined ? [] : [{
          season: number(row.validationSeason),
          subgroup: text(row.subgroup),
          value,
          count,
        }];
      })
    : [];
  if (!groups.length) return <Empty>No effective-sample-size subgroup metrics were supplied.</Empty>;
  const maximum = Math.max(...groups.map((row) => row.value), Number.EPSILON);
  return (
    <figure aria-label="Dynamic-state log loss by effective-sample-size group">
      <figcaption className="text-xs font-semibold uppercase tracking-wide text-slate-500">History coverage · final log loss by ESS band</figcaption>
      <div className="mt-3 space-y-2">
        {groups.map((row) => (
          <div key={`${row.season}-${row.subgroup}`} className="grid grid-cols-[minmax(150px,.55fr)_1fr_72px] items-center gap-2 text-xs">
            <span className="truncate text-slate-600">{row.season} · {row.subgroup} · n={integer(row.count)}</span>
            <span className="h-3 rounded-full bg-slate-200"><span className="block h-full rounded-full bg-violet-500" style={{ width: `${Math.max(1.5, row.value / maximum * 100)}%` }} /></span>
            <span className="text-right font-semibold tabular-nums text-slate-900">{metric(row.value)}</span>
          </div>
        ))}
      </div>
    </figure>
  );
}

function Limitations({ values }: { values: string[] }) {
  return (
    <ul className="space-y-2 text-sm leading-6 text-slate-600">
      {values.map((value) => <li key={value} className="flex gap-2"><ShieldCheck className="mt-1 shrink-0 text-amber-600" size={15} aria-hidden="true" /><span>{value}</span></li>)}
    </ul>
  );
}

function readinessChipClass(v: string) {
  if (v === "AVAILABLE") return "border-emerald-200 bg-emerald-50 text-emerald-800";
  if (v === "PARTIAL") return "border-amber-200 bg-amber-50 text-amber-800";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

// E1 free pitch-sequence PROCESS features — a leakage-safe feature materialization,
// NOT a model. Renders honest NOT_RUN until materialized; never shows model metrics
// or any "E1 improved log loss" claim (no model is trained).
export function PitchSequenceProcessSection({ features }: { features?: SportsPitchSequenceFeatures }) {
  const strikeout = features ? record(features.strikeoutWalkReadiness.strikeout) : {};
  const walk = features ? record(features.strikeoutWalkReadiness.walk) : {};
  const parse = features ? record(features.parseQuality) : {};
  return (
    <Card
      title="E1 · free pitch-sequence process features"
      description="Leakage-safe batter and pitcher plate-discipline process features from the free Retrosheet pitch-sequence encoding. This is a feature-readiness materialization, not a model; no predictive improvement is claimed."
    >
      {!features ? (
        <Empty>MLB_PITCH_SEQUENCE_PROCESS_FEATURES_V1 has not been materialized. Feature readiness is NOT_RUN until the governed materialization is executed.</Empty>
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Status value={features.terminalStatus} />
            <span className="text-sm text-slate-600">Parser {features.parserVersion} · materialization {features.materializationId}</span>
          </div>
          <EvidenceGrid evidence={{
            parseSuccessRate: number(parse.parseSuccessRate),
            unknownSymbols: number(parse.unknownSymbols),
            seasons: features.seasons.join(", "),
            trailingWindowDays: features.trailingWindowDays,
            batterFeatures: features.batterFeatureCount,
            pitcherFeatures: features.pitcherFeatureCount,
            totalFeatures: features.totalFeatureCount,
            rowsRead: features.rowsRead,
            rowsMaterialized: features.rowsMaterialized,
          }} />
          <div className="grid gap-5 xl:grid-cols-2">
            <div className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">STRIKEOUT-relevant feature availability</h3>
              <div className="flex flex-wrap gap-2">{Object.entries(strikeout).map(([k, v]) => (
                <span key={k} className={`inline-flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs ${readinessChipClass(String(v))}`}>{k.replaceAll("_", " ")}<span className="font-semibold">{String(v)}</span></span>
              ))}</div>
            </div>
            <div className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">WALK / HBP-relevant feature availability</h3>
              <div className="flex flex-wrap gap-2">{Object.entries(walk).map(([k, v]) => (
                <span key={k} className={`inline-flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs ${readinessChipClass(String(v))}`}>{k.replaceAll("_", " ")}<span className="font-semibold">{String(v)}</span></span>
              ))}</div>
            </div>
          </div>
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Feature coverage (by season)</h3>
            <EvidenceGrid evidence={record(features.coverage)} />
          </div>
          {features.rareOutcomeLimitations.length ? <Limitations values={features.rareOutcomeLimitations} /> : null}
        </div>
      )}
    </Card>
  );
}

// E2 batter × pitcher process interactions — a bounded, leakage-safe feature
// materialization derived from E1. Renders honest NOT_RUN until materialized; never
// shows model metrics or a predictive-improvement claim (no model is trained).
export function ProcessInteractionsSection({ interactions }: { interactions?: SportsProcessInteractions }) {
  const families = interactions ? record(interactions.interactionFamilies) : {};
  const redundancy = interactions ? record(interactions.redundancy) : {};
  const strikeout = interactions ? record(interactions.strikeoutWalkReadiness.strikeout) : {};
  const walk = interactions ? record(interactions.strikeoutWalkReadiness.walk) : {};
  const highCorr = Array.isArray(redundancy.highCorrelationPairs) ? redundancy.highCorrelationPairs : [];
  const parent = interactions ? record(interactions.parentE1) : {};
  return (
    <Card
      title="E2 · batter × pitcher process interactions"
      description="Bounded, leakage-safe matchup interaction features derived from the E1 batter and pitcher process states. This is a feature materialization, not a model; no predictive improvement is claimed."
    >
      {!interactions ? (
        <Empty>MLB_BATTER_PITCHER_PROCESS_INTERACTIONS_V1 has not been materialized. Interaction readiness is NOT_RUN until E1 is materialized and E2 is executed.</Empty>
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Status value={interactions.terminalStatus} />
            <span className="text-sm text-slate-600">Parent E1 {text(parent.materializationId)} · materialization {interactions.materializationId}</span>
          </div>
          <EvidenceGrid evidence={{
            featureCount: interactions.featureCount,
            featureHardMax: interactions.featureHardMax,
            seasons: interactions.seasons.join(", "),
            rowsRead: interactions.rowsRead,
            rowsMaterialized: interactions.rowsMaterialized,
            exactDuplicateGroups: Array.isArray(redundancy.exactDuplicateGroups) ? redundancy.exactDuplicateGroups.length : 0,
            nearConstantFeatures: Array.isArray(redundancy.nearConstantFeatures) ? redundancy.nearConstantFeatures.length : 0,
            highCorrelationPairs: highCorr.length,
          }} />
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Interaction families</h3>
            <div className="flex flex-wrap gap-2">{Object.entries(families).map(([fam, list]) => (
              <span key={fam} className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs"><span className="font-medium text-slate-800">{fam.replaceAll("_", " ")}</span><span className="rounded-full bg-slate-200 px-2 py-0.5 text-[10px] font-semibold text-slate-600">{Array.isArray(list) ? list.length : 0}</span></span>
            ))}</div>
          </div>
          <div className="grid gap-5 xl:grid-cols-2">
            <div className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">STRIKEOUT interaction readiness</h3>
              <div className="flex flex-wrap gap-2">{Object.entries(strikeout).map(([k, v]) => (
                <span key={k} className={`inline-flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs ${readinessChipClass(String(v))}`}>{k.replaceAll("_", " ")}<span className="font-semibold">{String(v)}</span></span>
              ))}</div>
            </div>
            <div className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">WALK interaction readiness</h3>
              <div className="flex flex-wrap gap-2">{Object.entries(walk).map(([k, v]) => (
                <span key={k} className={`inline-flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs ${readinessChipClass(String(v))}`}>{k.replaceAll("_", " ")}<span className="font-semibold">{String(v)}</span></span>
              ))}</div>
            </div>
          </div>
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Coverage & redundancy (by season)</h3>
            <EvidenceGrid evidence={record(interactions.coverage)} />
            {highCorr.length ? <p className="text-xs text-amber-700">High-correlation pairs flagged for fold-local handling: {highCorr.map((p) => `${text(record(p).a)}~${text(record(p).b)} (${text(record(p).pearson)})`).join(" · ")}</p> : null}
          </div>
          {interactions.limitations.length ? <Limitations values={interactions.limitations} /> : null}
        </div>
      )}
    </Card>
  );
}

function verdictChipClass(v: string) {
  if (/_CONFIRMED$/.test(v)) return "border-violet-200 bg-violet-50 text-violet-800";
  if (/_MARGINAL$/.test(v)) return "border-cyan-200 bg-cyan-50 text-cyan-800";
  if (/_NEGATIVE$/.test(v)) return "border-amber-200 bg-amber-50 text-amber-800";
  return "border-slate-200 bg-slate-50 text-slate-700";
}

export function IncrementalSignalStudySection({ study }: { study?: SportsIncrementalSignalStudy }) {
  const decision = study ? record(study.decision) : {};
  const e1 = record(decision.e1);
  const e2 = record(decision.e2);
  const nextStep = study ? record(study.nextStep) : {};
  const counts = study ? record(study.branchFeatureCounts) : {};
  const anchor = study ? record(study.anchor) : {};
  const strikeout = study ? record(study.strikeout) : {};
  const soSeasons = record(strikeout.seasons);
  return (
    <Card
      title="E1/E2 · controlled incremental-signal study (D3 vs D3+E1 vs D3+E1+E2)"
      description="Feature ablation only: one fixed model family, fixed C=0.05, identical 549,479-PA population, no grid search, no algorithm tournament. Research study — never a promoted model."
    >
      {!study ? (
        <Empty>MLB_E1_E2_INCREMENTAL_SIGNAL_STUDY_V1 has not been run. The A/B/C feature-value verdict is NOT_RUN until the study executes.</Empty>
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`inline-flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs ${verdictChipClass(text(e1.decision))}`}>E1<span className="font-semibold">{text(e1.decision)}</span></span>
            <span className={`inline-flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs ${verdictChipClass(text(e2.decision))}`}>E2<span className="font-semibold">{text(e2.decision)}</span></span>
            <span className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-600">research only · not promoted · champion unchanged</span>
          </div>
          <EvidenceGrid evidence={{
            branchFeaturesABC: `${integer(counts.A)} / ${integer(counts.B)} / ${integer(counts.C)}`,
            fixedC: 0.05,
            gridSearch: false,
            anchorReproduced: anchor.reproducedBothFolds === true,
          }} />
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Out-of-time log loss (A = D3, B = +E1, C = +E1+E2)</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-slate-500"><tr><th className="py-1 pr-4">Season</th><th className="py-1 pr-4">A</th><th className="py-1 pr-4">B</th><th className="py-1 pr-4">C</th><th className="py-1 pr-4">B−A</th><th className="py-1 pr-4">C−B</th><th className="py-1 pr-4">C−A band</th></tr></thead>
                <tbody>{study.incrementalRows.map((r) => {
                  const row = record(r); const ll = record(row.logLoss); const d = record(row.deltas);
                  const ba = record(d.B_minus_A); const cb = record(d.C_minus_B); const bands = record(row.practicalBands);
                  return (
                    <tr key={String(row.validationSeason)} className="border-t border-slate-100">
                      <td className="py-1 pr-4 font-medium text-slate-700">{integer(row.validationSeason)}</td>
                      <td className="py-1 pr-4">{metric(ll.A, 6)}</td>
                      <td className="py-1 pr-4">{metric(ll.B, 6)}</td>
                      <td className="py-1 pr-4">{metric(ll.C, 6)}</td>
                      <td className="py-1 pr-4">{metric(ba.logLoss, 6)}</td>
                      <td className="py-1 pr-4">{metric(cb.logLoss, 6)}</td>
                      <td className="py-1 pr-4">{text(bands.C_minus_A_logLoss)}</td>
                    </tr>
                  );
                })}</tbody>
              </table>
            </div>
          </div>
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">STRIKEOUT class-conditional log-loss change (E1: B−A / E2: C−B)</h3>
            <div className="flex flex-wrap gap-2">{["2024", "2025"].map((s) => {
              const season = record(soSeasons[s]); const dl = record(season.classConditionalLogLossDelta);
              return <span key={s} className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-700">{s}<span className="font-semibold">E1 {metric(dl.B_minus_A, 5)}</span><span className="font-semibold">E2 {metric(dl.C_minus_B, 5)}</span></span>;
            })}</div>
          </div>
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Recommended next experiment</h3>
            <p className="mt-1 text-sm font-semibold text-slate-800">{text(nextStep.recommendedPath)} — {text(nextStep.summary)}</p>
            <EvidenceGrid evidence={{
              e6ShouldProceed: nextStep.e6ShouldProceed,
              archetypesShouldProceed: nextStep.archetypesShouldProceed,
              algorithmTournamentShouldProceed: nextStep.algorithmTournamentShouldProceed,
              premiumDataPriorityRaised: nextStep.premiumDataPriorityRaised,
            }} />
          </div>
          {study.limitations.length ? <Limitations values={study.limitations} /> : null}
        </div>
      )}
    </Card>
  );
}

export function SevereMissForensicsSection({ forensics }: { forensics?: SportsSevereMissForensics }) {
  const rand = forensics ? record(forensics.randomness) : {};
  const clf = forensics ? record(forensics.severeMissClassifier) : {};
  const oi = forensics ? record(forensics.overIndex2025) : {};
  const oiRows = Array.isArray(oi.rows) ? oi.rows.map(record) : [];
  const topOi = oiRows.filter((r) => typeof r.overIndex === "number").sort((a, b) => Number(b.overIndex) - Number(a.overIndex))[0] ?? {};
  const worst1 = (forensics?.pareto2025 ?? []).map(record).find((r) => Number(r.worstFraction) === 0.01) ?? {};
  const worst5 = (forensics?.pareto2025 ?? []).map(record).find((r) => Number(r.worstFraction) === 0.05) ?? {};
  const ts = forensics ? record(forensics.tailSensitivity2025) : {};
  return (
    <Card
      title="Severe-miss forensics (Phase 4F) — where D3 error concentrates"
      description="Forensic analysis of individual PA losses. Analysis only: the official population is never trimmed and individual loss is never clipped; tail-sensitivity numbers are diagnostic, not a performance claim."
    >
      {!forensics ? (
        <Empty>MLB_PA_SEVERE_MISS_FORENSIC_STUDY_V1 has not been run. Severe-miss forensics are NOT_RUN.</Empty>
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-2 rounded-lg border border-violet-200 bg-violet-50 px-2.5 py-1.5 text-xs text-violet-800">{text(rand.primaryCategory)}</span>
            <span className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-600">official population preserved · analysis only</span>
          </div>
          <EvidenceGrid evidence={{
            worst1pctLossShare2025: worst1.lossShare,
            worst5pctLossShare2025: worst5.lossShare,
            severeMissClassifierAuc: clf.rocAuc,
            severeMissClassifierPrAuc: clf.prAuc,
            topOverIndexClass: `${text(topOi.class)} (${metric(topOi.overIndex, 2)}×)`,
          }} />
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Top confusion pairs in the worst 5% (2025)</h3>
            <div className="flex flex-wrap gap-2">{(forensics.confusionPairs2025 ?? []).map(record).slice(0, 6).map((p, i) => (
              <span key={i} className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-700">{text(p.actual)} → {text(p.predicted)}<span className="font-semibold">{integer(p.count)}</span></span>
            ))}</div>
          </div>
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Top corrective opportunities</h3>
            <ol className="mt-1 space-y-1 text-sm text-slate-800">{(forensics.topThreePatterns ?? []).map(record).map((p, i) => (
              <li key={i} className="flex items-center justify-between gap-3"><span>{i + 1}. {text(p.pattern)}</span><span className="text-[11px] font-semibold uppercase text-slate-500">{text(p.proposedCorrection)}</span></li>
            ))}</ol>
            <p className="mt-2 text-sm font-semibold text-slate-800">Recommended next: {text(forensics.recommendedNextStep)}</p>
          </div>
          {Array.isArray(ts.rows) ? (
            <p className="text-xs text-amber-700">Tail sensitivity (diagnostic only, not a performance claim): official 2025 D3 log loss {metric(ts.officialAggregateLogLoss, 6)}; removing worst 1% → {metric(record((ts.rows as unknown[]).map(record).find((r) => Number(r.removedWorstFraction) === 0.01) ?? {}).aggregateLogLossOnRemainder, 6)}.</p>
          ) : null}
          {forensics.limitations.length ? <Limitations values={forensics.limitations} /> : null}
        </div>
      )}
    </Card>
  );
}

export function PlayerTeamStatePage() {
  const evidence = useActiveSportsDataset();
  const study = evidence.status === "ready" ? evidence.data.phase4 : undefined;
  const component = study?.components.dynamicState;
  const descriptor = component?.descriptor ?? {};
  const selected = component?.selected ?? {};
  const status = component?.status ?? "NOT CONFIGURED";
  return (
    <SurfaceFrame
      eyebrow="Phase 4 · governed component research"
      title="Player & Team State"
      description="Point-in-time batter and pitcher state built only from completed plate appearances on dates before the target game. Canonical identity is used for exact joins and lineage, never as a memorization feature."
      status={status}
      facts={[
        { label: "State snapshots", value: integer(descriptor.snapshotCount ?? descriptor.rowCount) },
        { label: "Selected policy", value: text(descriptor.selectedPolicyId ?? selected.policyId) },
        { label: "Phase 3 comparator", value: "D0 · frozen raw C4" },
      ]}
    >
      {!component ? (
        <Empty>MLB_DYNAMIC_PLAYER_STATE_V1 has not been registered. Phase 3 remains the active static research baseline.</Empty>
      ) : (
        <>
          <Card title="Dynamic-state coverage" description="Missing history, effective sample size, and uncertainty remain explicit in the governed summary."><EvidenceGrid evidence={component.coverage} /></Card>
          <Card title="D0–D4 temporal comparison" description="Candidate selection uses 2024 only; the 2025 rows are frozen retrospective evaluation evidence."><CandidateTable component={component} metricKeys={["logLoss", "brierScore", "topLabelEce"]} /></Card>
          <Card title="History-coverage performance"><EffectiveSampleSizeChart component={component} /></Card>
          <div className="grid gap-5 xl:grid-cols-2">
            <Card title="Recency and shrinkage selection"><EvidenceGrid evidence={descriptor} /></Card>
            <Card title="Calibration and bootstrap"><EvidenceGrid evidence={{ ...record(component.calibration), bootstrapComparisons: component.bootstrap.length }} /></Card>
          </div>
          <Card title="Decision limitations"><Limitations values={component.limitations} /></Card>
        </>
      )}
      <PitchSequenceProcessSection features={study?.pitchSequenceFeatures} />
      <ProcessInteractionsSection interactions={study?.processInteractions} />
      <IncrementalSignalStudySection study={study?.incrementalSignalStudy} />
      <SevereMissForensicsSection forensics={study?.severeMissForensics} />
    </SurfaceFrame>
  );
}

const PARTICIPATION_DEFINITIONS: Array<{
  key: "lineup" | "starterDuration" | "bullpenUsage";
  title: string;
  distinction: string;
  metrics: string[];
}> = [
  { key: "lineup", title: "Lineup projection", distinction: "Actual historical lineup and batting order are retrospective targets only.", metrics: ["logLoss", "brierScore", "topNineRecall", "topNineF1"] },
  { key: "starterDuration", title: "Starter duration", distinction: "CONDITIONAL_ON_HISTORICAL_STARTER_IDENTITY · announcement timing is not claimed.", metrics: ["bfpMae", "bfpRmse", "outsMae"] },
  { key: "bullpenUsage", title: "Bullpen availability and usage", distinction: "Actual target-game relievers and sequence are targets only and are never injected into the candidate pool.", metrics: ["logLoss", "brierScore", "topThreeRecall", "topFiveRecall"] },
];

function LabelChips({ rows, primary, secondary }: { rows: SportsPhase4EvidenceRecord[]; primary: string; secondary: string }) {
  if (!rows.length) return <Empty>No inventory rows were registered.</Empty>;
  return (
    <div className="flex flex-wrap gap-2">
      {rows.map((row, index) => (
        <span key={`${text(row[primary], String(index))}`} className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs">
          <span className="font-medium text-slate-800">{text(row[primary])}</span>
          <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600">{text(row[secondary])}</span>
        </span>
      ))}
    </div>
  );
}

function pct(value: unknown) {
  const n = number(value);
  return n === undefined ? "—" : `${(n * 100).toLocaleString("en-US", { maximumFractionDigits: 1 })}%`;
}

function CatcherCoverageTable({ starting, pa }: { starting: SportsPhase4EvidenceRecord; pa: SportsPhase4EvidenceRecord }) {
  const seasons = Array.from(new Set([...Object.keys(starting), ...Object.keys(pa)])).sort();
  if (!seasons.length) return <Empty>No seasonal coverage was registered.</Empty>;
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200">
      <table className="w-full min-w-[640px] text-left text-xs">
        <thead className="bg-slate-900 text-slate-200"><tr>
          <th className="px-3 py-2">Season</th><th className="px-3 py-2">Team-games</th><th className="px-3 py-2">Starting-catcher coverage</th>
          <th className="px-3 py-2">Plate appearances</th><th className="px-3 py-2">PA catcher coverage</th><th className="px-3 py-2">Ambiguous</th><th className="px-3 py-2">Unique catchers</th>
        </tr></thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {seasons.map((season) => {
            const s = record(starting[season]); const p = record(pa[season]);
            return (
              <tr key={season}>
                <td className="px-3 py-2 font-semibold text-slate-950">{season}</td>
                <td className="px-3 py-2 tabular-nums">{integer(s.teamGames)}</td>
                <td className="px-3 py-2 tabular-nums font-semibold text-emerald-700">{pct(s.startingCatcherCoverageRate)}</td>
                <td className="px-3 py-2 tabular-nums">{integer(p.plateAppearances)}</td>
                <td className="px-3 py-2 tabular-nums font-semibold text-cyan-700">{pct(p.paCatcherAssignmentCoverageRate)}</td>
                <td className="px-3 py-2 tabular-nums text-amber-700">{integer(p.ambiguous)}</td>
                <td className="px-3 py-2 tabular-nums">{integer(p.uniqueCatchers)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SampleBandBars({ bySeason, label }: { bySeason: SportsPhase4EvidenceRecord; label: string }) {
  const seasons = Object.keys(bySeason).sort();
  if (!seasons.length) return <Empty>No {label} distribution was registered.</Empty>;
  const bandOrder = ["0", "1-9", "10-24", "25-49", "50-99", "100-249", "250+"];
  return (
    <div className="space-y-4">
      {seasons.map((season) => {
        const dist = record(bySeason[season]);
        const bands = record(dist.bands);
        const population = number(dist.population) || 0;
        return (
          <div key={season}>
            <div className="flex items-center justify-between text-xs text-slate-500">
              <span className="font-semibold text-slate-700">{season}</span>
              <span>n={integer(dist.population)} · unique pairs {integer(dist.uniquePairs)} · median {metric(dist.medianPriorSamples, 0)}</span>
            </div>
            <div className="mt-2 space-y-1">
              {bandOrder.map((band) => {
                const cell = record(bands[band]);
                const count = number(cell.count) || 0;
                const share = population ? count / population : 0;
                return (
                  <div key={band} className="grid grid-cols-[64px_1fr_88px] items-center gap-2 text-[11px]">
                    <span className="text-slate-500">{band}</span>
                    <span className="h-3 rounded-full bg-slate-200"><span className="block h-full rounded-full bg-gradient-to-r from-cyan-500 to-violet-500" style={{ width: `${Math.max(share * 100, count ? 1.5 : 0)}%` }} /></span>
                    <span className="text-right tabular-nums text-slate-700">{integer(count)} · {pct(share)}</span>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Catcher Influence Readiness is a DATA-AVAILABILITY AUDIT, not a catcher model.
// It renders honest NOT_RUN until governed audit evidence exists, and never shows a
// catcher score, ranking, or model-performance metric. All values below are the
// registered runtime audit evidence (no fabricated numbers).
export function CatcherInfluenceReadinessSection({ readiness }: { readiness?: SportsCatcherReadiness }) {
  const battery = readiness ? record(readiness.batterySampleDistribution.bySeason) : {};
  const catcherBatter = readiness ? record(readiness.catcherBatterSampleDistribution.bySeason) : {};
  return (
    <Card
      title="Starting catcher & catcher influence readiness"
      description="Data-availability audit of CATCHER_ASSOCIATED_EFFECT and PITCHER_CATCHER_BATTERY_EFFECT evidence. This is not a catcher model, score, or ranking; it measures how reliably catcher identity is reconstructable and how sparse battery / catcher-batter history is."
    >
      {!readiness ? (
        <Empty>MLB_CATCHER_INFLUENCE_READINESS_V1 has not been run. Catcher/battery evidence coverage is NOT_RUN until the governed audit is executed.</Empty>
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Status value={readiness.terminalStatus} />
            <span className="max-w-3xl text-sm text-slate-600">{readiness.rationale}</span>
          </div>
          <div className="space-y-2"><h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Seasonal catcher-assignment coverage</h3><CatcherCoverageTable starting={readiness.startingCatcherCoverage} pa={readiness.paCatcherAssignmentCoverage} /></div>
          <div className="grid gap-5 xl:grid-cols-2">
            <div className="space-y-2"><h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Pitcher-catcher battery prior-sample distribution</h3><SampleBandBars bySeason={battery} label="battery" /></div>
            <div className="space-y-2"><h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Catcher × batter prior-sample distribution</h3><SampleBandBars bySeason={catcherBatter} label="catcher-batter" /></div>
          </div>
          <div className="grid gap-5 xl:grid-cols-2">
            <div className="space-y-2"><h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Free feature families</h3><LabelChips rows={readiness.freeFeatureInventory} primary="field" secondary="label" /></div>
            <div className="space-y-2"><h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Premium / tracking gaps (unavailable in free data)</h3><LabelChips rows={readiness.premiumDataGaps} primary="field" secondary="classification" /></div>
          </div>
          {readiness.limitations.length ? <Limitations values={readiness.limitations} /> : null}
        </div>
      )}
    </Card>
  );
}

export function ParticipationUsagePage() {
  const evidence = useActiveSportsDataset();
  const study = evidence.status === "ready" ? evidence.data.phase4 : undefined;
  const completed = PARTICIPATION_DEFINITIONS.filter(({ key }) => study?.components[key]).length;
  const statuses = PARTICIPATION_DEFINITIONS.map(({ key }) => study?.components[key]?.status).filter(Boolean);
  const status = completed === 0 ? "NOT CONFIGURED" : completed === 3 ? "RESEARCH EVIDENCE REGISTERED" : "PARTIAL RESEARCH EVIDENCE";
  return (
    <SurfaceFrame
      eyebrow="Phase 4 · participation and usage"
      title="Participation & Usage"
      description="Lineup, starter-duration, and bullpen components are evaluated retrospectively from strictly prior-date evidence. Candidate-pool misses remain measured limitations; no roster, injury, transaction, or announcement feed is inferred."
      status={status}
      facts={[
        { label: "Components recorded", value: `${completed} / 3` },
        { label: "Component decisions", value: statuses.length ? statuses.join(" · ") : "None" },
        { label: "Simulator status", value: "NOT CONFIGURED" },
      ]}
    >
      {PARTICIPATION_DEFINITIONS.map(({ key, title, distinction, metrics }) => {
        const component = study?.components[key];
        return (
          <Card key={key} title={title} description={distinction}>
            {!component ? <Empty>{title} evidence has not been registered.</Empty> : (
              <div className="space-y-5">
                <div className="flex flex-wrap items-center justify-between gap-3"><Status value={component.status} /><span className="text-sm text-slate-600">{component.decisionReason}</span></div>
                <EvidenceGrid evidence={component.coverage} />
                <CandidateTable component={component} metricKeys={metrics.slice(0, 2)} />
                <Limitations values={component.limitations} />
              </div>
            )}
          </Card>
        );
      })}
      <CatcherInfluenceReadinessSection readiness={study?.catcherReadiness} />
    </SurfaceFrame>
  );
}

export function Phase4ModelLaboratorySection({ study }: { study?: SportsPhase4Study }) {
  const components = study ? Object.values(study.components).filter(Boolean) as SportsPhase4Component[] : [];
  if (!components.length) return null;
  return (
    <Card title="Phase 4 component candidates" description="Dynamic-state and participation candidates are research evidence; none authorizes simulation, export, or deployment.">
      <div className="space-y-6">
        {components.map((component) => (
          <div key={component.componentId} className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold text-slate-950">{component.contractName}</h3><Status value={component.status} /></div>
            <CandidateTable component={component} metricKeys={component.componentType === "STARTER_DURATION" ? ["bfpMae", "bfpRmse"] : ["logLoss", "brierScore"]} />
          </div>
        ))}
      </div>
    </Card>
  );
}

export function Phase4EvaluationSection({ study }: { study?: SportsPhase4Study }) {
  const components = study ? Object.values(study.components).filter(Boolean) as SportsPhase4Component[] : [];
  if (!components.length) return null;
  return (
    <Card title="Phase 4 evaluation & calibration" description="Every value below is a bounded registered summary from the rolling-origin 2024/2025 evaluation.">
      <div className="grid gap-4 xl:grid-cols-2">
        {components.map((component) => (
          <article key={component.componentId} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div className="flex items-start justify-between gap-3"><div><h3 className="font-semibold text-slate-950">{component.contractName}</h3><p className="mt-1 text-xs text-slate-500">{component.decisionReason}</p></div><Status value={component.status} /></div>
            <div className="mt-4 space-y-4">
              <FoldMetricChart component={component} />
              <FoldMetricChart component={component} metricKey={component.componentType === "STARTER_DURATION" ? "bfpRmse" : component.componentType === "LINEUP_PROJECTION" ? "brierScore" : component.componentType === "BULLPEN_USAGE" ? "topLabelEce" : "brierScore"} />
              {component.componentType === "LINEUP_PROJECTION" || component.componentType === "BULLPEN_USAGE" || component.componentType === "DYNAMIC_PLAYER_STATE" ? <CalibrationChart component={component} /> : null}
              <EvidenceGrid evidence={component.metrics} />
            </div>
          </article>
        ))}
      </div>
    </Card>
  );
}

export function Phase4GraphSection({ study }: { study?: SportsPhase4Study }) {
  if (!study?.graph) return null;
  return (
    <Card title="Phase 4 parent-linked research graph" description="This graph extends the immutable Phase 3 lineage and keeps simulator, bundle, and prospective-feed nodes not configured.">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {study.graph.nodes.map((node, index) => (
          <article key={text(node.nodeId, String(index))} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
            <div className="flex items-start justify-between gap-3"><GitBranch className="mt-0.5 text-cyan-700" size={16} aria-hidden="true" /><Status value={text(node.status, "NOT_CONFIGURED")} /></div>
            <div className="mt-3 text-sm font-semibold text-slate-950">{text(node.label, text(node.nodeId))}</div>
          </article>
        ))}
      </div>
      <p className="mt-4 text-xs text-slate-500">{study.graph.edges.length.toLocaleString("en-US")} governed dependency edges · graph ID {text(study.graph.graphId, "recorded")}</p>
    </Card>
  );
}

export function Phase4RegistrySection({ study }: { study?: SportsPhase4Study }) {
  if (!study) return null;
  return (
    <Card title="Phase 4 research registry" description="Metadata and logical artifact references only; fitted model and prediction bytes remain in ignored runtime storage.">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <EvidenceGrid evidence={{ studyId: study.studyId, studySha: study.studySha, registeredAt: study.registeredAt, artifactCount: study.artifacts.length }} />
      </div>
      <div className="mt-5 overflow-x-auto rounded-xl border border-slate-200">
        <table className="w-full min-w-[760px] text-left text-xs"><thead className="bg-slate-900 text-slate-200"><tr><th className="px-3 py-3">Artifact type</th><th className="px-3 py-3">Artifact ID</th><th className="px-3 py-3">Bytes</th><th className="px-3 py-3">Logical URI</th></tr></thead><tbody className="divide-y divide-slate-100">{study.artifacts.map((artifact) => <tr key={artifact.artifactId}><td className="px-3 py-3 font-semibold">{artifact.artifactType}</td><td className="px-3 py-3 font-mono">{artifact.artifactId}</td><td className="px-3 py-3 tabular-nums">{integer(artifact.byteCount)}</td><td className="max-w-[360px] break-all px-3 py-3 font-mono text-slate-600">{artifact.logicalUri}</td></tr>)}</tbody></table>
      </div>
    </Card>
  );
}

export function Phase4SimulationStatus({ study }: { study?: SportsPhase4Study }) {
  if (!study) return null;
  const available = Object.values(study.components).filter(Boolean).map((component) => component!.contractName);
  return (
    <Card title="Phase 4 simulator readiness" description="Research components are inputs for future integration, not a game forecast.">
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-cyan-200 bg-cyan-50 p-4"><div className="flex items-center gap-2 font-semibold text-cyan-950"><Layers3 size={17} />Available research evidence</div><ul className="mt-3 space-y-1 text-sm text-cyan-900">{available.map((item) => <li key={item}>{item}</li>)}</ul></div>
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4"><div className="flex items-center gap-2 font-semibold text-amber-950"><Activity size={17} />Still not configured</div><p className="mt-3 text-sm leading-6 text-amber-900">Confirmed-lineup and probable-starter feeds, injuries and transactions, platoon state, base-out transitions, the game simulator, residual model, bundle export, and forward monitoring.</p></div>
      </div>
    </Card>
  );
}

export function GameReplaySection({ replay }: { replay?: SportsGameReplay }) {
  const counts = replay ? record(replay.classificationCounts) : {};
  const forensics = replay?.mismatchForensics ?? [];
  return (
    <Card
      title="Phase 5 · deterministic historical game replay"
      description="Before predicting a game, prove the kernel can replay a real one. Mechanical validator only — no probabilistic simulation, Monte Carlo, or betting logic."
    >
      {!replay ? (
        <Empty>MLB_GAME_REPLAY_ENGINE_V1 has not been run. Replay readiness is NOT_RUN.</Empty>
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`inline-flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs ${readinessChipClass(replay.readinessStatus.includes("READY") && !replay.readinessStatus.includes("PARTIALLY") && !replay.readinessStatus.includes("BLOCKED") ? "AVAILABLE" : replay.readinessStatus.includes("PARTIALLY") ? "PARTIAL" : "BLOCKED")}`}>{text(replay.readinessStatus)}</span>
            <span className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-600">deterministic replay · no probabilistic simulation</span>
          </div>
          <EvidenceGrid evidence={{
            source: replay.sourceFamily,
            seasons: replay.seasons.join(", "),
            gamesReplayed: replay.gamesAttempted,
            exactReplayRate: replay.exactReplayRate,
            finalScoreExactRate: replay.finalScoreExactRate,
            inningSequenceExactRate: replay.inningSequenceExactRate,
            baseOutContinuityRate: replay.zeroContinuityRate,
          }} />
          <div className="grid gap-2 sm:grid-cols-4">
            {["EXACT_REPLAY", "PARTIAL_REPLAY", "REPLAY_MISMATCH", "SOURCE_INSUFFICIENT"].map((k) => (
              <div key={k} className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5"><span className="text-xs font-semibold text-slate-700">{k.replaceAll("_", " ")}</span><span className="text-sm font-semibold text-slate-900">{integer(counts[k])}</span></div>
            ))}
          </div>
          {forensics.length ? (
            <div className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Mismatch forensics (honest, not hidden)</h3>
              <div className="flex flex-wrap gap-2">{forensics.slice(0, 6).map(record).map((f, i) => (
                <span key={i} className="inline-flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-xs text-amber-800">{text(f.category)}{f.paOutcome ? ` · ${text(f.paOutcome)}` : ""}<span className="font-semibold">{integer(f.count)}</span></span>
              ))}</div>
            </div>
          ) : <p className="text-xs text-emerald-700">No unexplained mismatches beyond documented source quirks.</p>}
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4"><p className="text-sm text-amber-900">Next simulator milestone: a base-out transition distribution and a probabilistic PA-outcome provider that swaps actual events for sampled events. Game Simulator, Monte Carlo, residual layer, and ASP export remain NOT_CONFIGURED.</p></div>
          {replay.limitations.length ? <Limitations values={replay.limitations} /> : null}
        </div>
      )}
    </Card>
  );
}

export function BaseOutTransitionSection({ transition }: { transition?: SportsBaseOutTransition }) {
  const v = transition ? record(transition.validation2024) : {};
  const f = transition ? record(transition.frozen2025) : {};
  const stress = transition ? record(transition.stochasticStressTest) : {};
  const fb = record(v.fallbackUsage);
  const perOutcome = record(v.perOutcome);
  const ready = transition?.readinessStatus === "BASE_OUT_TRANSITION_MODEL_READY";
  return (
    <Card
      title="Phase 5B · base-out / runner-advancement transition model"
      description="The simulation bridge from a sampled PA outcome to the deterministic kernel. Mechanical + empirical, legality-guaranteed. No Monte Carlo, win/run-line/total probabilities, or betting logic."
    >
      {!transition ? (
        <Empty>MLB_BASE_OUT_TRANSITION_MODEL_V1 has not been run. Transition readiness is NOT_RUN.</Empty>
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`inline-flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs ${readinessChipClass(ready ? "AVAILABLE" : transition.readinessStatus.includes("PARTIALLY") ? "PARTIAL" : "BLOCKED")}`}>{text(transition.readinessStatus)}</span>
            <span className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-600">policy {text(transition.retainedPolicy)} · parent {text(record(transition.parentReplayAuthority).contractName)}</span>
          </div>
          <EvidenceGrid evidence={{
            devSeasons: transition.devSeasons.join(", "),
            primaryStateCells: transition.primaryStateCells,
            sparseCells: transition.sparseCellCount,
            illegalProbabilityMass: transition.illegalProbabilityMass,
            stressIllegalStates: stress.illegalStateCount,
            sampledTransitions: stress.totalSampledTransitions,
          }} />
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">One-step transition backtest (2024 validation / 2025 frozen)</h3>
            <div className="overflow-x-auto"><table className="w-full text-left text-xs">
              <thead className="text-slate-500"><tr><th className="py-1 pr-4">Metric</th><th className="py-1 pr-4">2024</th><th className="py-1 pr-4">2025</th></tr></thead>
              <tbody>{[["transition log loss", "logLoss", 4], ["summed Brier", "brier", 4], ["top-1 accuracy", "top1Accuracy", 4], ["top-2 coverage", "top2Coverage", 4], ["base-mask-after accuracy", "baseMaskAfterAccuracy", 4], ["outs-added accuracy", "outsAddedAccuracy", 4], ["inning-ending accuracy", "inningEndingAccuracy", 4], ["runs-scored MAE", "runsScoredMae", 4]].map(([label, key]) => (
                <tr key={String(key)} className="border-t border-slate-100"><td className="py-1 pr-4 text-slate-700">{label}</td><td className="py-1 pr-4">{metric(v[key as string], 4)}</td><td className="py-1 pr-4">{metric(f[key as string], 4)}</td></tr>
              ))}</tbody>
            </table></div>
          </div>
          <EvidenceGrid evidence={{
            fallbackL0Exact: fb.L0_EXACT, fallbackHomeRunDeterministic: fb.DETERMINISTIC_HOME_RUN,
            fallbackLegalPrior: fb.L3_LEGAL_PRIOR ?? 0,
            reproducibleSameSeed: record(transition.reproducibility).sameSeedIdentical,
            modelArtifactFormat: record(transition.modelArtifact).format,
          }} />
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Highest-uncertainty PA outcomes (2024 transition log loss)</h3>
            <div className="flex flex-wrap gap-2">{Object.entries(perOutcome).map(([o, m]) => ({ o, ll: Number(record(m).logLoss) })).sort((a, b) => b.ll - a.ll).slice(0, 5).map(({ o, ll }) => (
              <span key={o} className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-700">{o.replaceAll("_", " ")}<span className="font-semibold">{ll.toFixed(3)}</span></span>
            ))}</div>
          </div>
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4"><p className="text-sm text-amber-900">Next launch-critical step: a D3 probabilistic PA-outcome provider adapter, then a first whole-game Monte Carlo on this identical kernel. Monte Carlo, game-level calibration, residual layer, and ASP export remain NOT_CONFIGURED.</p></div>
          {transition.limitations.length ? <Limitations values={transition.limitations} /> : null}
        </div>
      )}
    </Card>
  );
}

export function SimulationInputSection({ input }: { input?: SportsSimulationInput }) {
  const readiness = input ? record(input.readiness) : {};
  const pa = input ? record(input.paProvider) : {};
  const repro = record(pa.reproduction);
  const logLoss = record(repro.logLoss);
  const coverage = input ? record(record(input.participantProvider).coverage) : {};
  const eligible = input ? record(record(input.eligiblePopulation).bySeason) : {};
  const seq = input ? record(input.shortSequenceIntegration) : {};
  const perf = input ? record(input.monteCarloPerformanceEstimate) : {};
  const passed = input?.monteCarloEntryDecision === "MONTE_CARLO_ENTRY_GATES_PASSED";
  const gateLabels: Array<[string, string]> = [
    ["replayEngine", "Replay Engine"],
    ["baseOutTransition", "Base-Out Transition"],
    ["d3ProbabilisticPaProvider", "D3 PA Provider"],
    ["historicalParticipantReplay", "Historical Participant Replay"],
    ["gameInitialization", "Game Initialization"],
    ["wholeGameMonteCarlo", "Whole-Game Monte Carlo"],
  ];
  return (
    <Card
      title="Phase 5C · simulation input layer (Monte-Carlo entry gates)"
      description="The final entry gates before the first whole-game Monte Carlo: faithful D3 PA-outcome invocation, historical participants, and game initialization. Interface correctness only — no Monte Carlo, win/run-line/total probabilities, or betting logic."
    >
      {!input ? (
        <Empty>MLB_SIMULATION_INPUT_LAYER_V1 has not been run. Simulation-input readiness is NOT_RUN.</Empty>
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`inline-flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs ${readinessChipClass(passed ? "AVAILABLE" : input.monteCarloEntryDecision.includes("PARTIAL") ? "PARTIAL" : "BLOCKED")}`}>{text(input.monteCarloEntryDecision)}</span>
            <span className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-600">interface correctness · no Monte Carlo</span>
          </div>
          <div className="grid gap-2 sm:grid-cols-3">
            {gateLabels.map(([key, label]) => {
              const status = text(readiness[key]);
              const tone = status === "READY" ? "AVAILABLE" : status === "LOCKED" ? "BLOCKED" : "PARTIAL";
              return (
                <div key={key} className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5">
                  <span className="text-xs font-semibold text-slate-700">{label}</span>
                  <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px] ${readinessChipClass(tone)}`}>{status}</span>
                </div>
              );
            })}
          </div>
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">D3 historical reproduction (frozen raw_D3, bit-exact)</h3>
            <EvidenceGrid evidence={{
              exactReproduction: repro.exactReproduction,
              rowsCompared: repro.rowsCompared,
              maxAbsProbabilityDiff: repro.maxAbsProbabilityDiff,
              mismatchCount: repro.mismatchCount,
              logLoss2024: logLoss["2024"],
              logLoss2025: logLoss["2025"],
              throughputPasPerSec: pa.throughputPasPerSecond,
            }} />
          </div>
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Historical participant coverage &amp; Monte-Carlo eligible games</h3>
            <div className="overflow-x-auto"><table className="w-full text-left text-xs">
              <thead className="text-slate-500"><tr><th className="py-1 pr-4">Season</th><th className="py-1 pr-4">Games</th><th className="py-1 pr-4">Complete replay</th><th className="py-1 pr-4">Batter/pitcher resolved</th><th className="py-1 pr-4">Eligible</th></tr></thead>
              <tbody>{["2024", "2025"].map((s) => {
                const c = record(coverage[s]);
                const e = record(eligible[s]);
                return (
                  <tr key={s} className="border-t border-slate-100">
                    <td className="py-1 pr-4 text-slate-700">{s}</td>
                    <td className="py-1 pr-4">{integer(c.games)}</td>
                    <td className="py-1 pr-4">{integer(c.completeReplayGames)}</td>
                    <td className="py-1 pr-4">{metric(c.activeBatterResolutionRate, 4)} / {metric(c.activePitcherResolutionRate, 4)}</td>
                    <td className="py-1 pr-4 font-semibold text-slate-900">{integer(e.eligible)}</td>
                  </tr>
                );
              })}</tbody>
            </table></div>
          </div>
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Short-sequence stochastic integration (bounded — not a game forecast)</h3>
            <EvidenceGrid evidence={{
              sequences: seq.sequences,
              sampledPlateAppearances: seq.totalPlateAppearances,
              illegalStates: seq.illegalStates,
              duplicatedOrLostRunners: (Number(seq.duplicatedRunners) || 0) + (Number(seq.lostRunners) || 0),
              sameSeedReproducible: seq.sameSeedReproducible,
              differentSeedDivergent: seq.differentSeedDivergent,
            }} />
          </div>
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4"><p className="text-sm text-amber-900">Estimated Monte-Carlo cost (no simulation executed): one game × 1,000 sims ≈ {metric(record(perf.oneGame1000Sims).seconds, 1)}s · 15-game slate × 1,000 sims ≈ {metric(record(perf.slate15Games1000Sims).seconds, 1)}s at {integer(perf.measuredPasPerSecond)} PA/s. Next launch-critical step: the first whole-game Monte Carlo and a historical game-level backtest on this identical kernel + providers. Whole-Game Monte Carlo, game calibration, residual layer, prospective feed, and ASP export remain NOT_CONFIGURED.</p></div>
          {input.limitations.length ? <Limitations values={input.limitations} /> : null}
        </div>
      )}
    </Card>
  );
}

export function WholeGameMonteCarloSection({ mc }: { mc?: SportsWholeGameMonteCarlo }) {
  const s2024 = mc ? record(record(mc.bySeason)["2024"]) : {};
  const s2025 = mc ? record(record(mc.bySeason)["2025"]) : {};
  const ready = mc?.simulatorReadiness?.includes("RESEARCH_BASELINE_READY");
  const covLabels: Array<[string, string]> = [["50", "50%"], ["80", "80%"], ["90", "90%"], ["95", "95%"]];
  const scoreRows: Array<[string, string]> = [
    ["actual runs/team", "actualMeanTotal"], ["sim runs/team", "simulatedMeanTotal"],
    ["total-run bias", "totalBias"], ["total-run MAE", "totalMae"], ["total-run RMSE", "totalRmse"],
    ["total-run CRPS", "crpsTotal"], ["run-diff MAE", "runDiffMae"],
  ];
  return (
    <Card
      title="Phase 5D · whole-game Monte Carlo research baseline"
      description="First game-level probabilistic validation under actual historical participants (oracle). Research diagnostic — NOT a production forecast, betting model, or market comparison. No win/run-line/total odds."
    >
      {!mc ? (
        <Empty>MLB_WHOLE_GAME_MONTE_CARLO_V1 has not been run. Simulator readiness is NOT_RUN.</Empty>
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`inline-flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs ${readinessChipClass(ready ? "AVAILABLE" : mc.simulatorReadiness.includes("PARTIALLY") ? "PARTIAL" : "BLOCKED")}`}>{text(mc.simulatorReadiness)}</span>
            <span className="inline-flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-xs text-amber-800">{text(mc.participantMode)} · oracle upper bound, not prospective</span>
            <span className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-600">{integer(mc.simulationsPerGame)} sims/game</span>
          </div>
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Actual vs simulated scoring (per season)</h3>
            <div className="overflow-x-auto"><table className="w-full text-left text-xs">
              <thead className="text-slate-500"><tr><th className="py-1 pr-4">Metric</th><th className="py-1 pr-4">2024</th><th className="py-1 pr-4">2025</th></tr></thead>
              <tbody>{scoreRows.map(([label, key]) => (
                <tr key={key} className="border-t border-slate-100"><td className="py-1 pr-4 text-slate-700">{label}</td><td className="py-1 pr-4">{metric(s2024[key], 3)}</td><td className="py-1 pr-4">{metric(s2025[key], 3)}</td></tr>
              ))}</tbody>
            </table></div>
          </div>
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Prediction-interval coverage — total runs (nominal vs observed 2024)</h3>
            <div className="grid gap-2 sm:grid-cols-4">{covLabels.map(([k, lbl]) => {
              const obs = Number(record(s2024.coverageTotal)[k]);
              const nominal = Number(k) / 100;
              const good = Math.abs(obs - nominal) <= 0.05;
              return (
                <div key={k} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5">
                  <div className="flex items-center justify-between text-xs"><span className="font-semibold text-slate-700">{lbl} interval</span><span className={good ? "text-emerald-700" : "text-amber-700"}>{Number.isFinite(obs) ? (obs * 100).toFixed(1) : "—"}%</span></div>
                  <div className="mt-1.5 h-1.5 w-full rounded-full bg-slate-200"><div className={`h-1.5 rounded-full ${good ? "bg-emerald-500" : "bg-amber-500"}`} style={{ width: `${Math.min(100, Math.max(0, obs * 100))}%` }} /></div>
                </div>
              );
            })}</div>
          </div>
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Diagnostic winner probability &amp; calibration (no market comparison)</h3>
            <div className="overflow-x-auto"><table className="w-full text-left text-xs">
              <thead className="text-slate-500"><tr><th className="py-1 pr-4">Metric</th><th className="py-1 pr-4">2024</th><th className="py-1 pr-4">2025</th></tr></thead>
              <tbody>
                <tr className="border-t border-slate-100"><td className="py-1 pr-4 text-slate-700">home-win Brier</td><td className="py-1 pr-4">{metric(record(s2024.winner).brier, 4)}</td><td className="py-1 pr-4">{metric(record(s2025.winner).brier, 4)}</td></tr>
                <tr className="border-t border-slate-100"><td className="py-1 pr-4 text-slate-700">home-win log loss</td><td className="py-1 pr-4">{metric(record(s2024.winner).logLoss, 4)}</td><td className="py-1 pr-4">{metric(record(s2025.winner).logLoss, 4)}</td></tr>
                <tr className="border-t border-slate-100"><td className="py-1 pr-4 text-slate-700">calibration ECE</td><td className="py-1 pr-4">{metric(s2024.calibrationEce, 4)}</td><td className="py-1 pr-4">{metric(s2025.calibrationEce, 4)}</td></tr>
                <tr className="border-t border-slate-100"><td className="py-1 pr-4 text-slate-700">actual home-win rate</td><td className="py-1 pr-4">{metric(s2024.actualHomeWinRate, 4)}</td><td className="py-1 pr-4">{metric(s2025.actualHomeWinRate, 4)}</td></tr>
                <tr className="border-t border-slate-100"><td className="py-1 pr-4 text-slate-700">mean sim home-win prob</td><td className="py-1 pr-4">{metric(s2024.meanSimulatedHomeWinProb, 4)}</td><td className="py-1 pr-4">{metric(s2025.meanSimulatedHomeWinProb, 4)}</td></tr>
              </tbody>
            </table></div>
          </div>
          <EvidenceGrid evidence={{
            d3GameLevelValue: mc.d3GameLevelValue,
            contactQualityPriority: mc.contactQualityPriority,
            participationAblation: mc.participationAblationDecision,
            illegalStates: record(mc.legality).totalIllegalStates,
            nonterminated: record(mc.legality).totalNonterminated,
          }} />
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4"><p className="text-sm text-amber-900">Oracle participants remove lineup/starter/bullpen prediction uncertainty — this is an optimistic upper bound, not a deployable pregame forecast. Next realism step follows the participation-ablation and contact-quality decisions above. Projected participation, prospective feed, residual layer, premium contact-quality, and ASP export remain NOT_CONFIGURED.</p></div>
          {mc.limitations.length ? <Limitations values={mc.limitations} /> : null}
        </div>
      )}
    </Card>
  );
}

export function ParticipationAblationSection({ ablation }: { ablation?: SportsParticipationAblation }) {
  const s2024 = ablation ? record(record(ablation.bySeason)["2024"]) : {};
  const branches2024 = record(s2024.branches);
  const preserved = ablation?.overallDecision?.includes("VALUE_PRESERVED") || ablation?.overallDecision?.includes("ACCEPTABLE");
  const branchOrder: Array<[string, string]> = [["P0", "Oracle"], ["P1", "+Lineup"], ["P2", "+Starter dur."], ["P3", "+Bullpen"]];
  const p3d = record(record(s2024.deltas)["P3_vs_P0"]);
  const impactTone = (v?: string) => v?.includes("ACCEPTABLE") ? "AVAILABLE" : v?.includes("MATERIAL") ? "PARTIAL" : "BLOCKED";
  return (
    <Card
      title="Phase 5E · projected-participation ablation (P0→P3)"
      description="How much game-level value survives when ASP substitutes its own lineup/starter/bullpen models for the historical oracle. Research diagnostic — no forecasts, odds, edge, or ROI."
    >
      {!ablation ? (
        <Empty>MLB_PROJECTED_PARTICIPATION_ABLATION_V1 has not been run. Ablation status is NOT_RUN.</Empty>
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`inline-flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs ${readinessChipClass(preserved ? "AVAILABLE" : ablation.overallDecision.includes("MATERIAL") ? "PARTIAL" : "BLOCKED")}`}>{text(ablation.overallDecision)}</span>
            <span className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-600">{integer(ablation.simulationsPerGame)} sims/game · starter identity oracle</span>
          </div>
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Branch comparison — 2024 (increasing participation realism →)</h3>
            <div className="overflow-x-auto"><table className="w-full text-left text-xs">
              <thead className="text-slate-500"><tr><th className="py-1 pr-4">Metric</th>{branchOrder.map(([b, l]) => <th key={b} className="py-1 pr-4">{b} · {l}</th>)}</tr></thead>
              <tbody>
                <tr className="border-t border-slate-100"><td className="py-1 pr-4 text-slate-700">home-win Brier</td>{branchOrder.map(([b]) => <td key={b} className="py-1 pr-4">{metric(record(record(branches2024[b]).winner).brier, 4)}</td>)}</tr>
                <tr className="border-t border-slate-100"><td className="py-1 pr-4 text-slate-700">total-run CRPS</td>{branchOrder.map(([b]) => <td key={b} className="py-1 pr-4">{metric(record(branches2024[b]).totalCrps, 3)}</td>)}</tr>
                <tr className="border-t border-slate-100"><td className="py-1 pr-4 text-slate-700">total-run bias</td>{branchOrder.map(([b]) => <td key={b} className="py-1 pr-4">{metric(record(branches2024[b]).totalBias, 3)}</td>)}</tr>
                <tr className="border-t border-slate-100"><td className="py-1 pr-4 text-slate-700">90% coverage</td>{branchOrder.map(([b]) => <td key={b} className="py-1 pr-4">{metric(record(branches2024[b]).cov90Total, 3)}</td>)}</tr>
              </tbody>
            </table></div>
          </div>
          <div className="grid gap-2 sm:grid-cols-3">
            {[["Lineup", ablation.lineupGameImpact], ["Starter duration", ablation.starterDurationGameImpact], ["Bullpen", ablation.bullpenGameImpact]].map(([label, val]) => (
              <div key={label} className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5">
                <span className="text-xs font-semibold text-slate-700">{label}</span>
                <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px] ${readinessChipClass(impactTone(text(val)))}`}>{text(val).replace(/^.*_GAME_IMPACT_/, "")}</span>
              </div>
            ))}
          </div>
          <EvidenceGrid evidence={{
            p3VsP0BrierRelPct: record(p3d.winnerBrier).relPct,
            p3VsP0CrpsRelPct: record(p3d.totalCrps).relPct,
            meanLineupRecall2024: record(ablation.meanLineupRecall)["2024"],
            priorStateFallbackRate: record(ablation.stateFallback).priorStateRate,
            leagueFallbackRate: record(ablation.stateFallback).leagueFallbackRate,
          }} />
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4"><p className="text-sm text-amber-900">P3 is <strong>PROJECTED_PARTICIPATION_RESEARCH_MODE</strong>: it still uses the actual starter identity (S2 is conditional on it) and a historical population — not a live pregame forecast. Remaining oracle dependencies: starter identity (CRITICAL), schedule/teams/date and injury/scratch feed (MODERATE). Prospective feed, starter-identity projection, premium data, and the interactive Model Studio cockpit remain NOT_CONFIGURED.</p></div>
          {ablation.limitations.length ? <Limitations values={ablation.limitations} /> : null}
        </div>
      )}
    </Card>
  );
}

export function StarterIdentitySection({ starter }: { starter?: SportsStarterIdentity }) {
  const e2024 = starter ? record(record(starter.starterEvaluation)["2024"]) : {};
  const e2025 = starter ? record(record(starter.starterEvaluation)["2025"]) : {};
  const sim2024 = starter ? record(record(starter.bySeason)["2024"]) : {};
  const q0 = record(sim2024.Q0); const q1 = record(sim2024.Q1); const delta = record(sim2024.delta);
  const acceptable = starter?.simulatorDecision?.includes("ACCEPTABLE");
  const isComponent = starter?.modelDecision === "STARTER_IDENTITY_RESEARCH_COMPONENT";
  return (
    <Card
      title="Phase 5F · starter-identity projection (last participation oracle)"
      description="Predict who starts from prior-date rotation cadence only, then measure the game-level cost of dropping the oracle starter. Research diagnostic — no forecasts, odds, edge, or ROI."
    >
      {!starter ? (
        <Empty>MLB_STARTER_IDENTITY_PROJECTION_V1 has not been run. Starter-identity status is NOT_RUN.</Empty>
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`inline-flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs ${readinessChipClass(isComponent ? "AVAILABLE" : "PARTIAL")}`}>{text(starter.modelDecision)}</span>
            <span className={`inline-flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs ${readinessChipClass(acceptable ? "AVAILABLE" : starter.simulatorDecision.includes("MATERIAL") ? "PARTIAL" : "BLOCKED")}`}>{text(starter.simulatorDecision)}</span>
            <span className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-600">{text(starter.pregameSimulatorReadiness)}</span>
          </div>
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Starter identity accuracy (2024 val / 2025 frozen)</h3>
            <div className="overflow-x-auto"><table className="w-full text-left text-xs">
              <thead className="text-slate-500"><tr><th className="py-1 pr-4">Metric</th><th className="py-1 pr-4">2024</th><th className="py-1 pr-4">2025</th></tr></thead>
              <tbody>{[["candidate-pool coverage", "candidatePoolCoverage", 3], ["top-1 accuracy", "top1Accuracy", 3], ["top-2 accuracy", "top2Accuracy", 3], ["top-3 accuracy", "top3Accuracy", 3], ["MRR", "mrr", 3], ["mean candidates", "meanCandidateCount", 1]].map(([label, key, dp]) => (
                <tr key={String(key)} className="border-t border-slate-100"><td className="py-1 pr-4 text-slate-700">{label}</td><td className="py-1 pr-4">{metric(e2024[key as string], dp as number)}</td><td className="py-1 pr-4">{metric(e2025[key as string], dp as number)}</td></tr>
              ))}</tbody>
            </table></div>
          </div>
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Simulator cost — oracle (Q0) vs projected starter (Q1), 2024</h3>
            <div className="overflow-x-auto"><table className="w-full text-left text-xs">
              <thead className="text-slate-500"><tr><th className="py-1 pr-4">Metric</th><th className="py-1 pr-4">Q0 oracle</th><th className="py-1 pr-4">Q1 projected</th><th className="py-1 pr-4">Δ rel</th></tr></thead>
              <tbody>
                <tr className="border-t border-slate-100"><td className="py-1 pr-4 text-slate-700">home-win Brier</td><td className="py-1 pr-4">{metric(record(q0.winner).brier, 4)}</td><td className="py-1 pr-4">{metric(record(q1.winner).brier, 4)}</td><td className="py-1 pr-4">{metric(record(delta.winnerBrier).relPct, 2)}%</td></tr>
                <tr className="border-t border-slate-100"><td className="py-1 pr-4 text-slate-700">total-run CRPS</td><td className="py-1 pr-4">{metric(q0.totalCrps, 3)}</td><td className="py-1 pr-4">{metric(q1.totalCrps, 3)}</td><td className="py-1 pr-4">{metric(record(delta.totalCrps).relPct, 2)}%</td></tr>
                <tr className="border-t border-slate-100"><td className="py-1 pr-4 text-slate-700">90% coverage</td><td className="py-1 pr-4">{metric(q0.cov90Total, 3)}</td><td className="py-1 pr-4">{metric(q1.cov90Total, 3)}</td><td className="py-1 pr-4">{metric(record(delta.cov90).abs, 3)}</td></tr>
              </tbody>
            </table></div>
          </div>
          <EvidenceGrid evidence={{
            starterCorrectRate2024: sim2024.starterCorrectRate,
            bullpenPriority: record(starter.priorities).bullpen,
            prospectiveFeed: record(starter.priorities).prospectiveFeed,
            modelStudioCockpit: record(starter.priorities).modelStudioCockpit,
          }} />
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4"><p className="text-sm text-amber-900">With starter identity projected, all four participation layers (lineup, starter identity, starter duration, bullpen) are now projected. Remaining oracle: schedule/teams/date and no injury/scratch feed (MODERATE) — a historical population, not a live pregame forecast. Next: {text(record(starter.priorities).bullpen).includes("HIGH") ? "bullpen reliever-selection improvement or the interactive Model Studio cockpit" : "prospective feed integration"}.</p></div>
          {starter.limitations.length ? <Limitations values={starter.limitations} /> : null}
        </div>
      )}
    </Card>
  );
}

export function Phase4SummaryTiles({ study }: { study?: SportsPhase4Study }) {
  if (!study) return null;
  const components = Object.values(study.components).filter(Boolean) as SportsPhase4Component[];
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {components.map((component) => (
        <article key={component.componentId} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-center justify-between gap-3"><Users className="text-cyan-700" size={18} /><Status value={component.status} /></div>
          <div className="mt-3 text-sm font-semibold text-slate-950">{component.contractName}</div>
          <div className="mt-1 text-xs text-slate-500">{component.candidates.length} candidates · {component.artifacts.length} artifacts</div>
        </article>
      ))}
    </div>
  );
}
