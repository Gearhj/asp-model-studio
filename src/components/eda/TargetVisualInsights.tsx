import { Activity, AlertTriangle, CheckCircle2, Eye, ShieldCheck } from "lucide-react";
import { formatEventRate } from "../../lib/dataAcquisitionLifecycle";
import {
  formatCount,
  formatRatio,
  type ConfidenceInterval,
  type TargetClassBalance,
} from "../../lib/targetIntelligence";
import { safeArray } from "../../lib/workflowSafety";

export type TargetPredictorPreviewGroup = {
  label: string;
  count: number;
  event_count: number;
  event_rate: number | null;
};

export type TargetPredictorPreviewRow = {
  feature: string;
  kind: "numeric" | "categorical";
  iv: number | null;
  monotonicity: string;
  event_rate_spread: number | null;
  groups: TargetPredictorPreviewGroup[];
};

export type TargetPredictorPreviewPayload = {
  scope?: string;
  population_rows?: number;
  analysis_population_id?: string;
  split_id?: string;
  final_holdout_accessed?: boolean;
  predictor_limit?: number;
  shape_limit?: number;
  candidate_count?: number;
  returned_predictors?: number;
  request_mode?: string;
  server_authorized_predictors_only?: boolean;
  target_excluded?: boolean;
  raw_observations_included?: boolean;
  predictors?: TargetPredictorPreviewRow[];
};

function finiteRate(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(0, Math.min(1, parsed)) : null;
}

export function TargetBalanceConfidenceVisual({
  balance,
  interval,
  reducedMotion,
}: {
  balance: TargetClassBalance | null;
  interval: ConfidenceInterval | null;
  reducedMotion: boolean;
}) {
  if (!balance) {
    return (
      <div
        className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-5 text-sm text-slate-600"
        data-testid="target-balance-confidence-empty"
      >
        Target balance is unavailable until the exact Development Population profile resolves.
      </div>
    );
  }

  const eventRate = finiteRate(balance.eventRate) ?? 0;
  const nonEventRate = finiteRate(balance.nonEventRate) ?? Math.max(0, 1 - eventRate);
  const lower = finiteRate(interval?.lowerBound);
  const upper = finiteRate(interval?.upperBound);
  const point = finiteRate(interval?.pointEstimate) ?? eventRate;
  const intervalWidth =
    lower !== null && upper !== null ? Math.max((upper - lower) * 100, 0.5) : 0;

  return (
    <div
      className="rounded-xl border border-blue-200 bg-white p-4 shadow-sm"
      data-testid="target-balance-confidence"
      data-scope="development-population"
      data-reduced-motion={reducedMotion ? "true" : "false"}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-bold text-slate-950">
            <Activity size={16} className="text-blue-700" aria-hidden="true" />
            Target balance and confidence
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-600">
            How common the configured event is, and how precisely prevalence is measured across the Development Population.
          </p>
        </div>
        <span
          className="rounded-full bg-blue-50 px-2.5 py-1 text-[11px] font-semibold text-blue-800"
          data-testid="target-total-population"
        >
          {formatCount(balance.totalModelingPopulation)} modeled rows
        </span>
      </div>

      <div
        className="mt-4 overflow-hidden rounded-full bg-slate-100"
        role="img"
        aria-label={`Target balance: ${formatCount(balance.eventCount)} events at ${formatEventRate(eventRate)} and ${formatCount(balance.nonEventCount)} non-events at ${formatEventRate(nonEventRate)} across the Development Population.`}
        data-testid="target-balance-bar"
      >
        <div className="flex h-10 w-full">
          <div
            className={`grid min-w-[5.25rem] place-items-center bg-rose-700 px-2 text-xs font-bold text-white ${
              reducedMotion ? "" : "transition-[width] duration-300"
            }`}
            style={{ width: `${eventRate * 100}%` }}
          >
            Bad = 1 · <span data-testid="target-event-rate">{formatEventRate(eventRate)}</span>
          </div>
          <div
            className={`grid min-w-[5.25rem] place-items-center bg-blue-700 px-2 text-xs font-bold text-white ${
              reducedMotion ? "" : "transition-[width] duration-300"
            }`}
            style={{ width: `${nonEventRate * 100}%` }}
          >
            Good = 0 · {formatEventRate(nonEventRate)}
          </div>
        </div>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <div className="rounded-lg border border-rose-100 bg-rose-50 px-3 py-2">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-rose-700">Configured event</div>
          <div className="mt-1 text-sm font-bold tabular-nums text-rose-950" data-testid="target-event-count">
            {formatCount(balance.eventCount)} Bad / 1
          </div>
        </div>
        <div className="rounded-lg border border-blue-100 bg-blue-50 px-3 py-2">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-blue-700">Non-event</div>
          <div className="mt-1 text-sm font-bold tabular-nums text-blue-950" data-testid="target-non-event-count">
            {formatCount(balance.nonEventCount)} Good / 0
          </div>
        </div>
      </div>
      <p className="mt-2 text-right text-[11px] font-semibold text-slate-600">
        Imbalance ratio:{" "}
        <span className="tabular-nums text-slate-900" data-testid="target-imbalance-ratio">
          {formatRatio(balance.imbalanceRatio)}
        </span>
      </p>

      <div
        className="mt-4"
        data-testid="target-confidence-interval"
      >
        <div className="flex items-center justify-between gap-3 text-xs">
          <span className="font-semibold text-slate-800" data-testid="ci-method">
            {interval ? `${Math.round(interval.confidenceLevel * 100)}% Wilson confidence interval` : "Wilson confidence interval"}
          </span>
          <span className="tabular-nums text-slate-600" data-testid="ci-confidence-level">
            {lower === null || upper === null
              ? "Not available"
              : `${formatEventRate(lower)} – ${formatEventRate(upper)}`}
          </span>
        </div>
        <div
          className="relative mt-2 h-7 rounded-lg border border-slate-200 bg-gradient-to-r from-blue-50 via-white to-rose-50"
          data-testid="target-wilson-confidence-band"
          role="img"
          aria-label={
            lower === null || upper === null
              ? "Wilson confidence interval is not available."
              : `Wilson confidence interval from ${formatEventRate(lower)} to ${formatEventRate(upper)}, with point estimate ${formatEventRate(point)}.`
          }
        >
          {lower !== null && upper !== null ? (
            <>
              <div
                className="absolute top-2 h-3 rounded-full bg-teal-500/60"
                style={{ left: `${lower * 100}%`, width: `${intervalWidth}%` }}
              />
              <div
                className="absolute top-0 h-full w-0.5 bg-slate-950"
                style={{ left: `${point * 100}%` }}
                aria-hidden="true"
              />
            </>
          ) : null}
        </div>
        <div className="mt-1 flex justify-between gap-3 text-[10px] font-semibold tabular-nums text-slate-500">
          <span data-testid="ci-lower-bound">{formatEventRate(lower)}</span>
          <span data-testid="ci-point-estimate">{formatEventRate(point)}</span>
          <span data-testid="ci-upper-bound">{formatEventRate(upper)}</span>
        </div>
        <p className="mt-2 text-[11px] leading-4 text-slate-500" data-testid="ci-explanation">
          The band quantifies measurement uncertainty on the Development Population; it is not a forecast interval.
        </p>
      </div>
    </div>
  );
}

export function TargetQualityDiagnostic({
  quality,
  identity,
  targetSourceExcluded,
}: {
  quality: Record<string, any>;
  identity: Record<string, any>;
  targetSourceExcluded: string[];
}) {
  const invalidCount = safeArray<any>(quality.invalid_target_values).reduce(
    (sum, item) => sum + (Number(item.count) || 0),
    0,
  );
  const diagnostics = [
    {
      label: "Missing target",
      value: Number(quality.missing_target_count ?? identity.missing_target_count ?? 0),
      concern: Number(quality.missing_target_count ?? identity.missing_target_count ?? 0) > 0,
    },
    { label: "Invalid values", value: invalidCount, concern: invalidCount > 0 },
    {
      label: "Unexpected values",
      value: safeArray(quality.unexpected_target_values).length,
      concern: safeArray(quality.unexpected_target_values).length > 0,
    },
    {
      label: "Duplicate target-bearing rows",
      value: Number(quality.duplicate_target_bearing_rows ?? 0),
      concern: Number(quality.duplicate_target_bearing_rows ?? 0) > 0,
    },
    {
      label: "Target-derived candidates",
      value: safeArray(quality.target_derived_candidates).length,
      concern: safeArray(quality.target_derived_candidates).length > 0,
    },
    {
      label: "Post-outcome candidates",
      value: safeArray(quality.post_outcome_candidates).length,
      concern: safeArray(quality.post_outcome_candidates).length > 0,
    },
  ];
  const concernCount = diagnostics.filter((item) => item.concern).length;

  return (
    <section
      className={`rounded-xl border p-4 ${
        concernCount ? "border-amber-300 bg-amber-50/70" : "border-teal-200 bg-teal-50/60"
      }`}
      data-testid="target-quality-diagnostic"
      data-diagnostic-status={concernCount ? "review" : "clear"}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-bold text-slate-950">
            {concernCount ? (
              <AlertTriangle size={16} className="text-amber-700" aria-hidden="true" />
            ) : (
              <ShieldCheck size={16} className="text-teal-700" aria-hidden="true" />
            )}
            Target quality diagnostic
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-600">
            Missingness, unexpected values, duplicate-row checks, and leakage review
            use the exact Development Population with the sealed final holdout excluded.
          </p>
        </div>
        <span
          className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${
            concernCount ? "bg-amber-100 text-amber-900" : "bg-teal-100 text-teal-900"
          }`}
        >
          {concernCount ? `${concernCount} review area${concernCount === 1 ? "" : "s"}` : "No quality exceptions"}
        </span>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {diagnostics.map((item) => (
          <div
            key={item.label}
            className="flex items-center justify-between gap-3 rounded-lg border border-white/90 bg-white px-3 py-2 shadow-sm"
            data-quality-diagnostic={item.label}
          >
            <span className="text-xs font-semibold text-slate-700">{item.label}</span>
            <span className={`flex items-center gap-1 text-sm font-bold tabular-nums ${item.concern ? "text-amber-800" : "text-teal-800"}`}>
              {item.concern ? <AlertTriangle size={13} aria-hidden="true" /> : <CheckCircle2 size={13} aria-hidden="true" />}
              {formatCount(item.value)}
            </span>
          </div>
        ))}
      </div>

      <p className="mt-3 text-xs text-slate-700" data-testid="target-source-exclusion-diagnostic">
        <strong>Deterministic target source excluded:</strong>{" "}
        {targetSourceExcluded.length ? targetSourceExcluded.join(", ") : "No deterministic target source was identified."}
      </p>
    </section>
  );
}

export function TargetPredictorPreview({
  preview,
  target,
  targetSourceExcluded,
  reducedMotion,
  onInspect,
}: {
  preview: TargetPredictorPreviewPayload | null;
  target: string;
  targetSourceExcluded: string[];
  reducedMotion: boolean;
  onInspect: (row: TargetPredictorPreviewRow) => void;
}) {
  const excluded = new Set([target, ...targetSourceExcluded]);
  const rows = safeArray<TargetPredictorPreviewRow>(preview?.predictors)
    .filter((row) => row.feature && !excluded.has(row.feature))
    .slice(0, 5);

  return (
    <section
      className="rounded-xl border border-indigo-200 bg-indigo-50/50 p-4"
      data-testid="target-event-rate-predictor-preview"
      data-scope={preview?.scope ?? "unavailable"}
      data-request-mode={preview?.request_mode ?? "unavailable"}
      data-reduced-motion={reducedMotion ? "true" : "false"}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-bold text-slate-950">
            <Eye size={16} className="text-indigo-700" aria-hidden="true" />
            Event-rate by predictor preview
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-600">
            Top five server-authorized predictors by IV from the Development Population.
            Target-directed IV, event rates, and shape summaries exclude the sealed final holdout.
          </p>
        </div>
        <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-semibold text-indigo-800">
          Development Population · {formatCount(preview?.population_rows)} rows
        </span>
      </div>

      {rows.length ? (
        <div className="mt-4 grid gap-3 xl:grid-cols-5">
          {rows.map((row) => (
            <article
              key={row.feature}
              className={`rounded-xl border border-indigo-100 bg-white p-3 shadow-sm ${
                reducedMotion ? "" : "transition hover:-translate-y-0.5 hover:shadow-md"
              }`}
              data-testid="target-predictor-preview-card"
              data-predictor={row.feature}
            >
              <div className="min-h-10 break-words text-xs font-bold leading-4 text-slate-900" title={row.feature}>
                {row.feature}
              </div>
              <PredictorSparkline row={row} />
              <dl className="mt-2 space-y-1 text-[11px]">
                <div className="flex justify-between gap-2">
                  <dt className="text-slate-500">IV</dt>
                  <dd className="font-bold tabular-nums text-indigo-900">
                    {row.iv === null || row.iv === undefined ? "N/A" : row.iv.toFixed(3)}
                  </dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-slate-500">Spread</dt>
                  <dd className="font-semibold tabular-nums text-slate-800">{formatEventRate(row.event_rate_spread)}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-slate-500">Shape</dt>
                  <dd className="max-w-[8rem] text-right font-semibold text-slate-800">{row.monotonicity || "Not available"}</dd>
                </div>
              </dl>
              <button
                type="button"
                className="mt-3 w-full rounded-lg border border-indigo-200 bg-indigo-50 px-2 py-1.5 text-[11px] font-bold text-indigo-900 hover:bg-indigo-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-700"
                data-testid="inspect-target-predictor"
                onClick={() => onInspect(row)}
              >
                Inspect detailed analysis
              </button>
            </article>
          ))}
        </div>
      ) : (
        <div
          className="mt-4 rounded-lg border border-dashed border-indigo-200 bg-white px-4 py-5 text-sm text-slate-600"
          data-testid="target-predictor-preview-empty"
        >
          No authorized predictor has enough governed target information for an event-rate preview.
        </div>
      )}

      <p className="mt-3 text-[11px] leading-4 text-slate-500">
        Development-only signal; final holdout accessed: {preview?.final_holdout_accessed ? "yes" : "no"}.
        High IV is a review signal, not automatic leakage. {targetSourceExcluded.length ? `${targetSourceExcluded.join(", ")} remains excluded as a deterministic target source.` : ""}
      </p>
    </section>
  );
}

function PredictorSparkline({ row }: { row: TargetPredictorPreviewRow }) {
  const rates = safeArray<TargetPredictorPreviewGroup>(row.groups)
    .map((group) => finiteRate(group.event_rate))
    .filter((value): value is number => value !== null);
  const width = 160;
  const height = 46;
  const pad = 5;
  const min = rates.length ? Math.min(...rates) : 0;
  const max = rates.length ? Math.max(...rates) : 1;
  const span = Math.max(max - min, 0.000001);
  const points = rates.map((rate, index) => {
    const x = rates.length === 1 ? width / 2 : pad + (index / (rates.length - 1)) * (width - pad * 2);
    const y = height - pad - ((rate - min) / span) * (height - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  return (
    <svg
      className="mt-2 h-12 w-full overflow-visible"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`${row.feature} event-rate shape across ${rates.length} governed groups; spread ${formatEventRate(row.event_rate_spread)}; ${row.monotonicity}.`}
      data-testid="target-predictor-sparkline"
    >
      <line x1={pad} x2={width - pad} y1={height / 2} y2={height / 2} stroke="#e2e8f0" strokeDasharray="3 3" />
      {points.length > 1 ? (
        <polyline points={points.join(" ")} fill="none" stroke="#4f46e5" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
      ) : null}
      {points.map((point, index) => {
        const [cx, cy] = point.split(",");
        return <circle key={`${point}-${index}`} cx={cx} cy={cy} r="2.5" fill="#be123c" />;
      })}
    </svg>
  );
}
