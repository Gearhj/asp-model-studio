import type { ReactNode } from "react";
import {
  Archive,
  CheckCircle2,
  Database,
  Layers,
  Lock,
  RefreshCw,
  ShieldCheck,
  Target,
  TriangleAlert,
} from "lucide-react";
import { useCockpitStore } from "./cockpitApi";
import type {
  CurrentGoldDataReview,
  CurrentGoldReviewState,
} from "../workflow/currentGoldDataReview";

export const PROJECT_MODELING_QUESTION =
  "Estimate calibrated probabilities for the governed eight plate-appearance outcomes using current, leakage-safe pregame evidence and simulator-generated game state. Feed those probabilities into the Monte Carlo game simulator to estimate the joint home/away score distribution, home-win probability, run differential and total runs. Compare candidate models with the Core Gold-48 baseline, the historical Direct Gold reference and AISP_BASELINE using chronological validation.";

export const GOVERNED_PA_CLASSES = [
  "STRIKEOUT",
  "WALK_HBP_CI",
  "HOME_RUN",
  "SINGLE",
  "DOUBLE",
  "TRIPLE",
  "BIP_OUT",
  "OTHER_REACH",
] as const;

const DEFAULT_CHARTER = {
  predictionUnit: "Governed plate appearance",
  targetDefinition:
    "Eight-class PA outcome: STRIKEOUT, WALK_HBP_CI, HOME_RUN, SINGLE, DOUBLE, TRIPLE, BIP_OUT, OTHER_REACH",
  downstreamUse:
    "Feed conditional PA probabilities into the Monte Carlo game simulator for joint score, win-probability, run-differential, and total-runs distributions.",
  primaryMetric: "multiclass log loss",
  secondaryMetrics:
    "Brier score; calibration; class stability; game moneyline log loss; expected-score MAE; run-differential MAE; total-runs MAE",
  comparisonBenchmarks:
    "Core Gold-48 baseline; historical Direct Gold reference; AISP_BASELINE",
  forecastRestrictions:
    "Pregame-known evidence only. Conditional inning, half, outs, base-mask, and batting-score differential are supplied by the simulator at forecast time. No future actual game state, random split, global imputation, or validation/final-OOT-derived preprocessing.",
  deploymentIntent:
    "Research challenger for prospective simulation evaluation. No champion, promotion, export, or live-control authority is granted by this charter.",
};

function int(value: number) {
  return Math.round(value).toLocaleString();
}

function shortSha(value: string) {
  return value ? `${value.slice(0, 12)}…${value.slice(-8)}` : "—";
}

function ReviewGate({ state, children }: { state: CurrentGoldReviewState; children: (review: CurrentGoldDataReview) => ReactNode }) {
  if (state.status === "loading" || state.status === "idle") {
    return (
      <section className="rounded-2xl border border-slate-200 bg-white p-6" role="status">
        <div className="flex items-center gap-3 text-sm text-slate-600">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-cyan-600" />
          Inheriting the accepted project-bound Current Gold authority from Stage 2…
        </div>
      </section>
    );
  }
  if (state.status === "error" || !state.review) {
    return (
      <section className="rounded-2xl border border-rose-200 bg-rose-50 p-6" role="alert">
        <div className="flex items-center gap-2 font-semibold text-rose-900"><TriangleAlert size={18} /> Stage 3 population handoff unavailable</div>
        <p className="mt-1 text-sm text-rose-800">{state.error || "The accepted Stage 2 authority could not be resolved."}</p>
        <button type="button" onClick={() => void state.refresh()} className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-rose-300 bg-white px-3 py-2 text-sm font-semibold text-rose-800"><RefreshCw size={14} /> Retry project-bound handoff</button>
      </section>
    );
  }
  return <>{children(state.review)}</>;
}

function CharterField({
  label,
  value,
  onChange,
  rows = 2,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
}) {
  return (
    <label className="block rounded-xl border border-slate-200 bg-slate-50 p-3">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</span>
      <textarea
        value={value}
        rows={rows}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 w-full resize-y rounded-lg border border-slate-300 bg-white p-2.5 text-sm leading-6 text-slate-800 focus:border-cyan-500 focus:outline-none"
      />
    </label>
  );
}

export function ProjectBoundModelingCharter({ state }: { state: CurrentGoldReviewState }) {
  const { notes, setNote, markSaved, savedSteps } = useCockpitStore();
  const value = (name: keyof typeof DEFAULT_CHARTER | "modelingQuestion", fallback: string) =>
    notes[`stage3.charter.${name}`] ?? fallback;
  const change = (name: keyof typeof DEFAULT_CHARTER | "modelingQuestion") => (next: string) =>
    setNote(`stage3.charter.${name}`, next);

  return (
    <ReviewGate state={state}>{(review) => {
      const classOrderExact = review.targetTaxonomy.classOrder.join("|") === GOVERNED_PA_CLASSES.join("|");
      return (
        <div className="space-y-5" data-testid="stage3-project-bound-modeling-charter">
          <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5">
            <div className="flex flex-wrap items-center gap-2 text-sm text-emerald-900">
              <CheckCircle2 size={17} />
              <b>Modeling Charter inherited from accepted Stages 1 and 2</b>
              <span className="ml-auto rounded-full border border-emerald-300 bg-white px-2.5 py-1 text-[10px] font-semibold uppercase">Project-bound authority</span>
            </div>
            <p className="mt-2 text-sm leading-6 text-emerald-900">Review and refine the project’s scientific intent here. Editing this charter changes only the project draft; it does not alter the registered dataset, temporal contract, final OOT, or any model.</p>
          </section>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Metric label="Prediction unit" value="Plate appearance" detail={`${int(review.goldAuthority.rowCount)} governed rows`} />
            <Metric label="Target" value="Eight-class PA outcome" detail={classOrderExact ? "Exact governed order" : "CONTRACT MISMATCH"} />
            <Metric label="Primary metric" value="Multiclass log loss" detail="chronological validation" />
            <Metric label="Project champion" value="None yet" detail="legacy artifacts are benchmarks only" />
          </div>

          <section className="rounded-2xl border border-slate-200 bg-white p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div><div className="text-xs font-semibold uppercase tracking-[0.14em] text-cyan-700"><Target size={15} className="mr-1.5 inline" /> Modeling Charter</div><h3 className="mt-1 text-lg font-semibold text-slate-950">Project objective and evaluation intent</h3></div>
              <button type="button" onClick={() => markSaved("objective")} className="rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white">{savedSteps.objective ? "Charter saved ✓" : "Save charter"}</button>
            </div>
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              <div className="lg:col-span-2"><CharterField label="Modeling question" rows={5} value={value("modelingQuestion", PROJECT_MODELING_QUESTION)} onChange={change("modelingQuestion")} /></div>
              <CharterField label="Prediction unit" value={value("predictionUnit", DEFAULT_CHARTER.predictionUnit)} onChange={change("predictionUnit")} />
              <CharterField label="Eight-class PA target (charter statement)" rows={3} value={value("targetDefinition", DEFAULT_CHARTER.targetDefinition)} onChange={change("targetDefinition")} />
              <CharterField label="Downstream game-simulation use" rows={3} value={value("downstreamUse", DEFAULT_CHARTER.downstreamUse)} onChange={change("downstreamUse")} />
              <CharterField label="Primary model-selection metric" value={value("primaryMetric", DEFAULT_CHARTER.primaryMetric)} onChange={change("primaryMetric")} />
              <CharterField label="Secondary metrics" rows={3} value={value("secondaryMetrics", DEFAULT_CHARTER.secondaryMetrics)} onChange={change("secondaryMetrics")} />
              <CharterField label="Comparison benchmarks" rows={3} value={value("comparisonBenchmarks", DEFAULT_CHARTER.comparisonBenchmarks)} onChange={change("comparisonBenchmarks")} />
              <CharterField label="Forecast-time restrictions" rows={4} value={value("forecastRestrictions", DEFAULT_CHARTER.forecastRestrictions)} onChange={change("forecastRestrictions")} />
              <div className="lg:col-span-2"><CharterField label="Deployment intent" rows={3} value={value("deploymentIntent", DEFAULT_CHARTER.deploymentIntent)} onChange={change("deploymentIntent")} /></div>
            </div>
          </section>

          <section className="rounded-2xl border border-cyan-200 bg-cyan-50/50 p-5">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-cyan-800"><Lock size={15} /> Governed target taxonomy · inherited and locked</div>
            <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">{GOVERNED_PA_CLASSES.map((name, index) => <div key={name} className="rounded-lg border border-cyan-200 bg-white px-3 py-2 font-mono text-xs font-semibold text-slate-800"><span className="mr-2 text-slate-400">{index + 1}</span>{name}</div>)}</div>
            <p className="mt-2 text-xs text-cyan-900">A target-taxonomy change is not a charter edit. It requires returning to the registered Stage 1/Stage 2 contract and creating a versioned change.</p>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-5">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-600"><Archive size={15} className="mr-1.5 inline" /> Read-only comparison benchmarks</div>
            <div className="mt-3 grid gap-2 lg:grid-cols-2">
              {[
                ["Core Gold-48 baseline", review.goldAuthority.datasetId, "Project-bound baseline specification; no project champion has been selected."],
                ["Historical Direct Gold reference", "Historical Gold V1 research lineage", "Reference evidence only; it does not control this project."],
                ["AISP_BASELINE", "AI Sports Predictor operational lineage", "External comparison benchmark; it is not fitted or promoted here."],
                ["Base-22 / A2 Logistic and Historical HGB", "Legacy FD1 research lineage", "Sealed/read-only historical benchmarks; incompatible as this project’s active population."],
              ].map(([name, lineage, detail]) => <div key={name} className="rounded-xl border border-slate-200 bg-slate-50 p-3"><div className="font-semibold text-slate-900">{name}</div><div className="mt-1 font-mono text-[11px] text-slate-500">{lineage}</div><p className="mt-1 text-xs leading-5 text-slate-600">{detail}</p></div>)}
            </div>
          </section>
        </div>
      );
    }}</ReviewGate>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="rounded-xl border border-slate-200 bg-white p-3"><div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-1 text-lg font-semibold tabular-nums text-slate-950">{value}</div><div className="mt-0.5 text-[11px] text-slate-500">{detail}</div></div>;
}

const LEGACY_REFERENCES = [
  { name: "MLB_PA_V1 / Base-22", reasons: "Wrong date coverage · wrong feature contract · wrong temporal policy" },
  { name: "FD1 / Gen-2 feature view", reasons: "Wrong date coverage · historical benchmark only" },
  { name: "Gen-3 feature views", reasons: "Sealed evidence · incompatible project lineage · historical benchmark only" },
];

export function ProjectBoundPopulation({ state }: { state: CurrentGoldReviewState }) {
  return (
    <ReviewGate state={state}>{(review) => {
      const context = review.contextualFeaturePack;
      const reconciliation = review.populationReconciliation;
      const reasonRows = Object.entries(reconciliation.exclusionReasonCounts);
      return (
        <div className="space-y-5" data-testid="stage3-project-bound-population">
          <section className="rounded-2xl border border-emerald-300 bg-emerald-50 p-5" data-testid="stage3-population-recommendation">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-emerald-800"><ShieldCheck size={16} /> Use Project-Bound Current Gold Population — Recommended</div>
            <p className="mt-2 text-sm leading-6 text-emerald-950">This population matches the registered project contract, is current through 2026-08-27, has verified identity and point-in-time evidence, supports Core Gold and contextual feature-family comparisons, and leaves the final OOT locked.</p>
          </section>

          <section className="rounded-2xl border border-slate-800 bg-slate-950 p-5 text-white">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-cyan-300"><Database size={15} className="mr-1.5 inline" /> Automatic Stage 2 → Stage 3 authority handoff</div>
            <div className="mt-3 grid gap-3 lg:grid-cols-3">
              <Authority label="Registered source" value={review.sourceAuthority.datasetId} detail={`${review.sourceAuthority.datasetVersionId} · ${shortSha(review.sourceAuthority.manifestSha)}`} />
              <Authority label="Active modeling population" value={review.goldAuthority.datasetId} detail={`${shortSha(review.goldAuthority.manifestSha)} · independently verified`} />
              <Authority label="Contextual feature library" value={context?.datasetId || "UNAVAILABLE"} detail={context ? `${shortSha(context.manifestSha256)} · attached, review-only` : "The project-bound contextual authority is missing."} />
            </div>
            <p className="mt-3 text-xs text-slate-300">The accepted project binding controls this matrix. Changing the population requires returning to the project dataset and Stage 2 contract and recording a versioned change.</p>
          </section>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
            <Metric label="Modeling rows" value={int(review.goldAuthority.rowCount)} detail="one row per governed PA" />
            <Metric label="Development" value={int(review.matrix.development.rows)} detail={`through ${review.matrix.development.endDate}`} />
            <Metric label="Final OOT" value={int(review.matrix.finalOot.rows)} detail={`${review.matrix.finalOot.startDate}–${review.matrix.finalOot.endDate}`} />
            <Metric label="Seasons" value={review.matrix.seasons.join("–")} detail="required coverage" />
            <Metric label="Core predictors" value={int(review.matrix.predictorCount)} detail="exact ordered Gold-48" />
            <Metric label="Context candidates" value={int(context?.addedFeatureCount || 0)} detail="not automatically included" />
            <Metric label="Candidate library" value={int(context?.totalFeatureCount || review.matrix.predictorCount)} detail="Core + contextual" />
            <Metric label="Target classes" value={String(review.targetTaxonomy.classOrder.length)} detail="governed taxonomy" />
          </div>

          <section className="grid gap-4 xl:grid-cols-2">
            <div className="rounded-2xl border border-slate-200 bg-white p-5">
              <div className="text-xs font-semibold uppercase tracking-[0.14em] text-cyan-700">Point-in-time and final-OOT locks</div>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                <Status label="Point-in-time review" value={review.pointInTimeReview.status} detail={review.pointInTimeReview.detail} />
                <Status label="Leakage gate" value={review.leakageGate.status} detail={review.leakageGate.detail} />
                <Status label="Final OOT" value="LOCKED" detail={`${int(review.matrix.finalOot.rows)} rows are reporting-only; no outcome distribution is exposed here.`} />
                <Status label="Model activity" value="ZERO FITS" detail="No fit, score, calibration, selection, or promotion occurs in this handoff." />
              </div>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-white p-5">
              <div className="text-xs font-semibold uppercase tracking-[0.14em] text-cyan-700">Identity reconciliation</div>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                <Status label="Duplicate PA identities" value={int(review.identity.duplicateCanonicalPaIdentities + review.identity.duplicatePlateAppearanceIdentities)} detail="canonical + public keys" />
                <Status label="Unresolved players" value={int(review.identity.unresolvedPlayerIdentities)} detail={`${int(review.identity.matchedExactPlayerCount)} exact players`} />
                <Status label="Ambiguous players" value={int(review.identity.ambiguousPlayerIdentities)} detail="included population" />
                <Status label="Game identity issues" value={int(review.identity.unresolvedGameIdentities + review.identity.ambiguousGameIdentities)} detail="unresolved + ambiguous" />
              </div>
            </div>
          </section>

          <section className="rounded-2xl border border-cyan-200 bg-cyan-50/40 p-5">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-cyan-800"><Target size={15} className="mr-1.5 inline" /> Exact governed target taxonomy</div>
            <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">{review.targetTaxonomy.classOrder.map((name, index) => <div key={name} className="rounded-lg border border-cyan-200 bg-white px-3 py-2 font-mono text-xs font-semibold text-slate-800"><span className="mr-2 text-slate-400">{index + 1}</span>{name}</div>)}</div>
            <p className="mt-2 text-xs text-cyan-900">Class labels are displayed without final-OOT outcome counts or distribution-derived recommendations.</p>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-5">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-600">Source-to-Gold population reconciliation</div>
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <Metric label="Registered source rows" value={int(reconciliation.sourceRows)} detail={review.sourceAuthority.datasetId} />
              <Metric label="Current Gold rows" value={int(reconciliation.goldRows)} detail={review.goldAuthority.datasetId} />
              <Metric label="Source-to-Gold exclusions" value={int(reconciliation.excludedRows)} detail="explicit population difference" />
            </div>
            <div className="mt-3 overflow-auto rounded-xl border border-slate-200"><table className="w-full min-w-[560px] text-left text-xs"><thead className="bg-slate-50"><tr>{["Season", "Source rows", "Gold rows", "Excluded"].map((name) => <th key={name} className="border-b border-slate-200 px-3 py-2 text-slate-500">{name}</th>)}</tr></thead><tbody>{reconciliation.bySeason.map((row) => <tr key={row.season}><td className="border-b border-slate-100 px-3 py-2 font-semibold">{row.season}</td><td className="border-b border-slate-100 px-3 py-2 tabular-nums">{int(row.sourceRows)}</td><td className="border-b border-slate-100 px-3 py-2 tabular-nums">{int(row.goldRows)}</td><td className="border-b border-slate-100 px-3 py-2 tabular-nums">{int(row.excludedRows)}</td></tr>)}</tbody></table></div>
            {reasonRows.length ? <div className="mt-3 text-xs text-slate-600"><b>Exact registered reasons:</b> {reasonRows.map(([name, count]) => `${name} ${int(count)}`).join(" · ")}</div> : <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900"><b>Reason ledger status: {reconciliation.exclusionReasonStatus}.</b> Stage 2 provides exact source, Gold, total, and per-season counts but no reconciling reason-code ledger; this page does not invent categories.</div>}
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-5">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-cyan-700"><Layers size={15} className="mr-1.5 inline" /> Recommended population policy</div>
            <ul className="mt-3 grid gap-2 text-sm text-slate-700 lg:grid-cols-2">{[
              "Use all eligible development rows.",
              "Retain legitimate cold-start rows.",
              "Retain missingness and insufficient-history indicators.",
              "No random split and no random oversampling by default.",
              "Group observations by canonical game.",
              "Configure exact chronological folds later.",
              "Use training-fold-only preprocessing and imputation.",
              "Keep the final OOT locked.",
            ].map((item) => <li key={item} className="flex gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2"><CheckCircle2 size={14} className="mt-0.5 shrink-0 text-emerald-600" />{item}</li>)}</ul>
          </section>

          <details className="rounded-2xl border border-slate-300 bg-slate-50 p-5" data-testid="stage3-legacy-reference-datasets">
            <summary className="cursor-pointer text-sm font-semibold text-slate-700">Show legacy/reference datasets</summary>
            <p className="mt-2 text-xs text-slate-600">These records remain visible for lineage and historical comparison only. None can become this project’s active modeling population.</p>
            <div className="mt-3 grid gap-2 lg:grid-cols-3">{LEGACY_REFERENCES.map((item) => <div key={item.name} className="rounded-xl border border-slate-200 bg-white p-3"><div className="font-semibold text-slate-900">{item.name}</div><span className="mt-2 inline-flex rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-[10px] font-semibold text-rose-800">INCOMPATIBLE_WITH_CURRENT_PROJECT_CONTRACT</span><p className="mt-2 text-xs leading-5 text-slate-600">{item.reasons}</p></div>)}</div>
          </details>
        </div>
      );
    }}</ReviewGate>
  );
}

function Authority({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="rounded-xl border border-white/15 bg-white/5 p-3"><div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</div><div className="mt-1 break-all font-semibold text-white">{value}</div><div className="mt-1 break-all font-mono text-[10px] text-slate-400">{detail}</div></div>;
}

function Status({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="rounded-xl border border-slate-200 bg-slate-50 p-3"><div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-1 font-semibold text-emerald-700">{value.replaceAll("_", " ")}</div><p className="mt-1 text-[11px] leading-5 text-slate-600">{detail}</p></div>;
}

export function ProjectBoundStage3Intro({ state }: { state: CurrentGoldReviewState }) {
  return (
    <ReviewGate state={state}>{(review) => (
      <section className="sports-panel p-5" data-testid="stage3-project-bound-intro">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-cyan-700"><Layers size={14} /> Project-bound model development</div>
        <p className="mt-1 text-sm text-slate-600">The accepted Stage 2 Current Gold authority and contextual feature library are inherited automatically. No dataset re-selection, model fit, or champion adoption occurs in this handoff.</p>
        <dl className="mt-3 grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-slate-200 bg-slate-200 sm:grid-cols-3 lg:grid-cols-6">
          {[
            ["Active population", review.goldAuthority.datasetId],
            ["Rows", int(review.goldAuthority.rowCount)],
            ["Development", `${int(review.matrix.development.rows)} · through ${review.matrix.development.endDate}`],
            ["Final OOT", `${int(review.matrix.finalOot.rows)} · LOCKED`],
            ["Candidate library", `${review.contextualFeaturePack?.totalFeatureCount || review.matrix.predictorCount} features`],
            ["Project champion", "None yet"],
          ].map(([label, value]) => <div key={label} className="bg-white px-3 py-2"><dt className="text-[11px] font-semibold uppercase text-slate-400">{label}</dt><dd className="mt-0.5 break-words text-sm font-semibold text-slate-900">{value}</dd></div>)}
        </dl>
      </section>
    )}</ReviewGate>
  );
}

export function ProjectBoundLaterStepGate({
  state,
  stepLabel,
}: {
  state: CurrentGoldReviewState;
  stepLabel: string;
}) {
  return (
    <ReviewGate state={state}>{(review) => (
      <section
        className="rounded-2xl border border-amber-200 bg-amber-50 p-6"
        data-testid="stage3-project-bound-later-step-gate"
      >
        <div className="flex items-center gap-2 font-semibold text-amber-950">
          <Lock size={18} /> {stepLabel} is not activated by this population handoff
        </div>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-amber-900">
          Stage 3 is bound to <b>{review.goldAuthority.datasetId}</b> and its verified contextual
          feature library. The existing implementation for this step is tied to the legacy global
          matrix, so it is held closed rather than silently substituting an incompatible population.
        </p>
        <div className="mt-4 grid gap-2 text-xs sm:grid-cols-3">
          <Status label="Active rows" value={int(review.goldAuthority.rowCount)} detail="Project-bound Current Gold" />
          <Status label="Final OOT" value="LOCKED" detail={`${int(review.matrix.finalOot.rows)} reporting-only rows`} />
          <Status label="Model activity" value="ZERO FITS" detail="No fit, score, tune, calibration, or promotion" />
        </div>
        <p className="mt-4 text-xs leading-5 text-amber-800">
          This correction establishes the modeling charter and population authority only. A later,
          separately authorized implementation must make this step consume the same project-bound
          contract before it can run.
        </p>
      </section>
    )}</ReviewGate>
  );
}
