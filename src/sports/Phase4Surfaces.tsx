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
