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
  "Can a current, leakage-safe plate-appearance model improve the calibration and accuracy of simulated MLB game-score distributions relative to Core Gold-48, historical Direct Gold, and AISP_BASELINE?";

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
  predictionUnit: "Plate appearance.",
  targetDefinition:
    "Eight-class PA outcome: STRIKEOUT, WALK_HBP_CI, HOME_RUN, SINGLE, DOUBLE, TRIPLE, BIP_OUT, OTHER_REACH",
  downstreamUse:
    "Feed calibrated plate-appearance probabilities into the Monte Carlo game simulator to estimate the joint home/away score distribution, home-win probability, run differential, total runs, moneyline probability, run-line probability, and totals probability.",
  primaryMetric: "Multiclass log loss under five chronological expanding-window folds.",
  secondaryMetrics:
    "Multiclass Brier score; calibration error; class-level calibration; rare-class stability; game-level moneyline log loss; expected home/away score MAE; run-differential MAE; total-runs MAE.",
  comparisonBenchmarks:
    "Core Gold-48 baseline; historical Direct Gold reference; AISP_BASELINE",
  forecastRestrictions:
    "Sportsbook prices are not model predictors. No target-game outcome or future actual game state. No global preprocessing, validation/OOT-derived preprocessing, or final-OOT information during model selection. The simulator supplies inning, top/bottom, outs, bases, and score differential at forecast time.",
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

export function ProjectBoundStage3ProfileShell({
  state,
  children,
}: {
  state: CurrentGoldReviewState;
  children: ReactNode;
}) {
  return (
    <ReviewGate state={state}>{(review) => {
      const candidateCount = review.contextualFeaturePack?.totalFeatureCount ?? review.matrix.predictorCount;
      const identityIssues =
        review.identity.unresolvedPlayerIdentities
        + review.identity.ambiguousPlayerIdentities
        + review.identity.unresolvedGameIdentities
        + review.identity.ambiguousGameIdentities
        + review.identity.duplicateCanonicalPaIdentities
        + review.identity.duplicatePlateAppearanceIdentities
        + review.identity.nullIdentityRows;

      return (
        <div className="space-y-4" data-testid="stage3-project-bound-profile-shell">
          <section className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm" data-testid="stage3-eda-persistent-summary">
            <div className="flex flex-wrap items-center gap-2 px-1 pb-2">
              <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-700"><Layers size={13} /> Analysis summary</div>
              <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-800">DEVELOPMENT ONLY</span>
              <span className="ml-auto text-[10px] text-slate-500">Project-bound authority · {shortSha(review.reviewDigest)}</span>
            </div>
            <dl className="grid gap-px overflow-hidden rounded-xl border border-slate-200 bg-slate-200 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
              <SummaryDatum label="Development rows" value={int(review.matrix.development.rows)} />
              <SummaryDatum label="Target classes" value={int(review.targetTaxonomy.classOrder.length)} />
              <SummaryDatum label="Candidate predictors" value={int(candidateCount)} />
              <SummaryDatum
                label="Cold-start prevalence"
                value={review.modelingTreatment.coldStartPercent === undefined
                  ? review.modelingTreatment.coldStartRows
                  : `${review.modelingTreatment.coldStartPercent.toFixed(1)}% · ${int(review.modelingTreatment.coldStartRowCount ?? 0)} rows`}
              />
              <SummaryDatum label="Final OOT rows" value={`${int(review.matrix.finalOot.rows)} · LOCKED`} accent />
              <SummaryDatum label="Identity" value={identityIssues === 0 ? "PASS" : `${int(identityIssues)} ISSUES`} accent={identityIssues > 0} />
              <SummaryDatum label="Point in time" value={review.pointInTimeReview.status} accent={review.pointInTimeReview.status !== "PASS"} />
              <SummaryDatum label="Leakage" value={review.leakageGate.status} accent={review.leakageGate.status !== "PASS"} />
            </dl>
          </section>

          {children}
        </div>
      );
    }}</ReviewGate>
  );
}

function SummaryDatum({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return <div className={accent ? "bg-amber-50 px-3 py-2" : "bg-white px-3 py-2"}><dt className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</dt><dd className={`mt-0.5 break-words text-xs font-semibold tabular-nums ${accent ? "text-amber-900" : "text-slate-900"}`}>{value}</dd></div>;
}

export function ProjectBoundPopulation({ state, go }: { state: CurrentGoldReviewState; go?: (id: string) => void }) {
  const { markSaved, savedSteps } = useCockpitStore();
  return (
    <ReviewGate state={state}>{(review) => {
      const context = review.contextualFeaturePack;
      const reconciliation = review.populationReconciliation;
      const reasonRows = Object.entries(reconciliation.exclusionReasonCounts);
      const membership = reconciliation.membershipEvidence;
      const adopt = () => {
        markSaved("population");
        go?.("profile");
      };
      return (
        <div className="space-y-5" data-testid="stage3-project-bound-population">
          <section className="overflow-hidden rounded-2xl border border-emerald-300 bg-gradient-to-br from-emerald-50 via-white to-cyan-50 shadow-sm" data-testid="stage3-population-recommendation">
            <div className="grid gap-5 p-5 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-end">
              <div>
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-emerald-800"><ShieldCheck size={16} /> Population readiness · ready</div>
                <h3 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">Use Project-Bound Current Gold Population — Recommended</h3>
                <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-700">The registered project binding controls the matrix below. Confirming it continues the workflow; it does not select, copy, or rebuild a dataset.</p>
                <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                  <RecommendationFact label="Total rows" value={int(review.goldAuthority.rowCount)} />
                  <RecommendationFact label="Development" value={int(review.matrix.development.rows)} />
                  <RecommendationFact label="Final OOT · locked" value={int(review.matrix.finalOot.rows)} />
                  <RecommendationFact label="Feature library" value={`${review.matrix.predictorCount} + ${context?.addedFeatureCount || 0} = ${context?.totalFeatureCount || review.matrix.predictorCount}`} />
                </div>
              </div>
              <button type="button" onClick={adopt} className="inline-flex items-center justify-center gap-2 rounded-xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white shadow-sm hover:bg-slate-800">
                <CheckCircle2 size={17} className="text-emerald-300" /> {savedSteps.population ? "POPULATION CONFIRMED · CONTINUE" : "ADOPT POPULATION AND CONTINUE"}
              </button>
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-5">
            <div className="flex flex-wrap items-center justify-between gap-2"><div><div className="text-xs font-semibold uppercase tracking-[0.14em] text-cyan-700">Decision status</div><h3 className="mt-1 text-lg font-semibold text-slate-950">Is there any reason not to proceed?</h3></div><span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-800">READY · CONDITIONS DOCUMENTED</span></div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <DecisionStatus label="Project/source identity" status="PASS" detail={`${review.sourceAuthority.datasetId} → ${review.goldAuthority.datasetId}`} />
              <DecisionStatus label="Row reconciliation" status={membership ? "PASS" : "CONDITION"} detail={`${int(reconciliation.sourceRows)} − ${int(reconciliation.goldRows)} = ${int(reconciliation.excludedRows)}; exact membership and construction stage are ${membership ? "independently reconciled" : "known by season only"}; finer source-side causes are not recorded.`} />
              <DecisionStatus label="Player/game identity" status="PASS" detail={`${review.identity.unresolvedPlayerIdentities + review.identity.ambiguousPlayerIdentities + review.identity.unresolvedGameIdentities + review.identity.ambiguousGameIdentities} unresolved or ambiguous identities`} />
              <DecisionStatus label="Point-in-time review" status={review.pointInTimeReview.status === "PASS" ? "PASS" : review.pointInTimeReview.status === "PASS_WITH_CONDITIONS" ? "CONDITION" : "BLOCKED"} detail={review.pointInTimeReview.detail} />
              <DecisionStatus label="Leakage gate" status={review.leakageGate.status === "PASS" ? "PASS" : review.leakageGate.status === "PASS_WITH_CONDITIONS" ? "CONDITION" : "BLOCKED"} detail={review.leakageGate.detail} />
              <DecisionStatus label="Final OOT lock" status="PASS" detail={`${int(review.matrix.finalOot.rows)} rows excluded from development EDA and model selection`} />
              <DecisionStatus label="Zero model activity" status="PASS" detail={`${review.goldAuthority.modelsFitted} fits; no score, calibration, selection, or promotion`} />
              <DecisionStatus label="Feature library" status={context?.verified ? "PASS" : "BLOCKED"} detail={`${review.matrix.predictorCount} Core + ${context?.addedFeatureCount || 0} contextual candidates; eight governed target classes`} />
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-5" data-testid="stage3-population-reconciliation">
            <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-600">Row reconciliation</div><h3 className="mt-1 text-lg font-semibold text-slate-950">Every source-to-modeling row is accounted for</h3></div><span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-[11px] font-semibold text-amber-900">CONSTRUCTION STAGE EXACT · FINER CAUSE NOT RECORDED</span></div>
            <div className="mt-4 grid items-center gap-2 text-center sm:grid-cols-[1fr_auto_1fr_auto_1fr]">
              <EquationValue label="Accepted source PAs" value={reconciliation.sourceRows} />
              <span className="text-2xl text-slate-300">−</span>
              <EquationValue label="Model-ready PAs" value={reconciliation.goldRows} />
              <span className="text-2xl text-slate-300">=</span>
              <EquationValue label="Excluded source PAs" value={reconciliation.excludedRows} accent />
            </div>
            <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(280px,.7fr)]">
              <div className="overflow-auto rounded-xl border border-slate-200"><table className="w-full min-w-[560px] text-left text-xs"><thead className="bg-slate-50"><tr>{["Season", "Source rows", "Gold rows", "Excluded", "Share of exclusions"].map((name) => <th key={name} className="border-b border-slate-200 px-3 py-2 text-slate-500">{name}</th>)}</tr></thead><tbody>{reconciliation.bySeason.map((row) => <tr key={row.season}><td className="border-b border-slate-100 px-3 py-2 font-semibold">{row.season}</td><td className="border-b border-slate-100 px-3 py-2 tabular-nums">{int(row.sourceRows)}</td><td className="border-b border-slate-100 px-3 py-2 tabular-nums">{int(row.goldRows)}</td><td className="border-b border-slate-100 px-3 py-2 tabular-nums">{int(row.excludedRows)}</td><td className="border-b border-slate-100 px-3 py-2 tabular-nums">{reconciliation.excludedRows ? `${((row.excludedRows / reconciliation.excludedRows) * 100).toFixed(2)}%` : "0.00%"}</td></tr>)}</tbody></table></div>
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs leading-5 text-amber-950">
                <b>Exact exclusion-stage status: {reconciliation.exclusionReasonStatus}.</b>
                {reasonRows.length ? <><div className="mt-2">{reasonRows.map(([name, count]) => `${name}: ${int(count)}`).join(" · ")}</div><p className="mt-2">All 4,597 rows were outside the frozen Gold V1 bridge matched set before feature construction; feature assembly lost 0 rows. The finer source-side bridge cause was not recorded, so no identity, key, or target-side cause is invented.</p></> : <><p className="mt-2">The registered Gold authority contains no causal exclusion codes. This page does not invent bridge, identity, or feature-construction causes.</p>{membership ? <p className="mt-2">A read-only canonical-PA anti-join independently proves <b>{int(reconciliation.excludedRows)}</b> excluded identities. Identity-set SHA: <span className="break-all font-mono">{membership.identitySetSha256}</span>.</p> : <p className="mt-2">Exact causal and descriptive concentration evidence is not available in this response.</p>}</>}
              </div>
            </div>
            {membership ? <details className="mt-4 rounded-xl border border-cyan-200 bg-cyan-50/30 p-4" data-testid="stage3-exclusion-membership-evidence"><summary className="cursor-pointer text-sm font-semibold text-cyan-900">Exact excluded-membership concentrations · independently derived from verified identities</summary><p className="mt-2 text-xs leading-5 text-cyan-950">These are descriptive cuts of the exact 4,597-row identity-set difference, not finer causal reasons. The 823 source targets that lack a governed mapping remain explicitly unmapped.</p><div className="mt-3 grid gap-3 xl:grid-cols-3"><CompactCountTable title="By month" label="Month" rows={membership.byMonth.map((row) => [row.month, row.excludedRows] as [string, number])} /><CompactCountTable title="By batting team" label="Team" rows={membership.byBattingTeam.map((row) => [row.team, row.excludedRows] as [string, number])} /><CompactCountTable title="By governed target or unmapped" label="Target" rows={membership.byGovernedTargetOrUnmapped.map((row) => [row.target, row.excludedRows] as [string, number])} /></div><div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">{Object.entries(membership.identityConditions).map(([name, count]) => <Metric key={name} label={name.replaceAll(/([A-Z])/g, " $1")} value={int(count)} detail="exact membership evidence" />)}<Metric label="Final OOT exclusions" value={int(membership.finalOotExcludedRows)} detail="locked period" />{Object.entries(membership.featureConstructionConditionCounts).map(([name, count]) => <Metric key={name} label={name.replaceAll("_", " ")} value={int(count)} detail="exact construction-stage evidence" />)}</div></details> : null}
          </section>

          <section className="grid gap-4 xl:grid-cols-[1.2fr_.8fr]">
            <div className="rounded-2xl border border-slate-200 bg-white p-5"><div className="text-xs font-semibold uppercase tracking-[0.14em] text-cyan-700"><Layers size={15} className="mr-1.5 inline" /> Modeling population policy</div><ul className="mt-3 grid gap-2 text-sm text-slate-700 sm:grid-cols-2">{[
              "Use all eligible development rows.",
              "Retain legitimate cold-start rows.",
              "Retain missingness and insufficient-history indicators.",
              "No random split and no random oversampling by default.",
              "Group observations by canonical game.",
              "Configure exact chronological folds later.",
              "Use training-fold-only preprocessing and imputation.",
              "Keep the final OOT locked.",
            ].map((item) => <li key={item} className="flex gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2"><CheckCircle2 size={14} className="mt-0.5 shrink-0 text-emerald-600" />{item}</li>)}</ul></div>
            <div className="rounded-2xl border border-cyan-200 bg-cyan-50/40 p-5"><div className="text-xs font-semibold uppercase tracking-[0.14em] text-cyan-800"><Target size={15} className="mr-1.5 inline" /> Governed target</div><div className="mt-3 grid gap-2 sm:grid-cols-2">{review.targetTaxonomy.classOrder.map((name, index) => <div key={name} className="rounded-lg border border-cyan-200 bg-white px-3 py-2 font-mono text-xs font-semibold text-slate-800"><span className="mr-2 text-slate-400">{index + 1}</span>{name}</div>)}</div><p className="mt-2 text-xs text-cyan-900">No final-OOT outcome counts are exposed.</p></div>
          </section>

          <details className="rounded-2xl border border-slate-300 bg-slate-50 p-5" data-testid="stage3-advanced-authority-details">
            <summary className="cursor-pointer text-sm font-semibold text-slate-700">Advanced authority, manifests, hashes, and identity details</summary>
            <div className="mt-4 rounded-2xl border border-slate-800 bg-slate-950 p-5 text-white"><div className="text-xs font-semibold uppercase tracking-[0.14em] text-cyan-300"><Database size={15} className="mr-1.5 inline" /> Automatic Stage 2 → Stage 3 authority handoff</div><div className="mt-3 grid gap-3 lg:grid-cols-3"><Authority label="Registered source" value={review.sourceAuthority.datasetId} detail={`${review.sourceAuthority.datasetVersionId} · ${shortSha(review.sourceAuthority.manifestSha)}`} /><Authority label="Active modeling population" value={review.goldAuthority.datasetId} detail={`${shortSha(review.goldAuthority.manifestSha)} · independently verified`} /><Authority label="Contextual feature library" value={context?.datasetId || "UNAVAILABLE"} detail={context ? `${shortSha(context.manifestSha256)} · attached, review-only` : "The project-bound contextual authority is missing."} /></div></div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><Status label="Duplicate PA identities" value={int(review.identity.duplicateCanonicalPaIdentities + review.identity.duplicatePlateAppearanceIdentities)} detail="canonical + public keys" /><Status label="Unresolved players" value={int(review.identity.unresolvedPlayerIdentities)} detail="included-population issue count; observed totals redacted here" /><Status label="Ambiguous players" value={int(review.identity.ambiguousPlayerIdentities)} detail="included-population issue count" /><Status label="Game identity issues" value={int(review.identity.unresolvedGameIdentities + review.identity.ambiguousGameIdentities)} detail="unresolved + ambiguous" /></div>
            <p className="mt-3 text-xs text-slate-600">Changing this inherited population requires returning to the project dataset and Stage 2 contract and recording a versioned change.</p>
          </details>
        </div>
      );
    }}</ReviewGate>
  );
}

function RecommendationFact({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border border-emerald-200 bg-white/85 px-3 py-2"><div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-0.5 text-lg font-semibold tabular-nums text-slate-950">{value}</div></div>;
}

function DecisionStatus({ label, status, detail }: { label: string; status: "PASS" | "CONDITION" | "BLOCKED"; detail: string }) {
  const tone = status === "PASS" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : status === "CONDITION" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-rose-200 bg-rose-50 text-rose-900";
  return <div className={`rounded-xl border p-3 ${tone}`}><div className="flex items-center justify-between gap-2"><span className="text-[10px] font-semibold uppercase tracking-wide opacity-75">{label}</span><span className="rounded-full border border-current/20 bg-white/60 px-2 py-0.5 text-[10px] font-bold">{status}</span></div><p className="mt-2 text-xs leading-5">{detail}</p></div>;
}

function EquationValue({ label, value, accent = false }: { label: string; value: number; accent?: boolean }) {
  return <div className={`rounded-xl border p-4 ${accent ? "border-amber-200 bg-amber-50" : "border-slate-200 bg-slate-50"}`}><div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-1 text-2xl font-semibold tabular-nums text-slate-950">{int(value)}</div></div>;
}

function CompactCountTable({ title, label, rows }: { title: string; label: string; rows: [string, number][] }) {
  return <div className="max-h-80 overflow-auto rounded-lg border border-cyan-100 bg-white"><div className="sticky top-0 border-b border-cyan-100 bg-cyan-50 px-3 py-2 text-xs font-semibold text-cyan-900">{title}</div><table className="w-full text-xs"><thead><tr className="text-left text-slate-500"><th className="px-3 py-1.5">{label}</th><th className="px-3 py-1.5 text-right">Excluded</th></tr></thead><tbody>{rows.map(([name, count]) => <tr key={name}><td className="border-t border-slate-100 px-3 py-1.5 font-mono">{name}</td><td className="border-t border-slate-100 px-3 py-1.5 text-right tabular-nums">{int(count)}</td></tr>)}</tbody></table></div>;
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
  const { notes } = useCockpitStore();
  let handoff: null | {
    destination?: string;
    selectedVariables?: string[];
    bookmarkedVariables?: string[];
    filters?: Record<string, unknown>;
    authorityKey?: string;
    sourceTab?: string;
    createdAt?: string;
  } = null;
  try {
    handoff = notes["stage3.eda.handoff"] ? JSON.parse(notes["stage3.eda.handoff"]) : null;
  } catch {
    handoff = null;
  }
  const expectedDestination = stepLabel === "Outliers" ? "outliers" : stepLabel === "Missing Values" ? "missing" : stepLabel === "Feature Engineering" ? "features" : null;
  return (
    <ReviewGate state={state}>{(review) => {
      const authorityKey = [review.sourceAuthority.manifestSha, review.goldAuthority.manifestSha, review.contextualFeaturePack?.manifestSha256 ?? "no-context", review.reviewDigest].join(":");
      const acceptedHandoff = expectedDestination && handoff?.destination === expectedDestination && handoff.authorityKey === authorityKey ? handoff : null;
      return (
      <section
        className="rounded-2xl border border-amber-200 bg-amber-50 p-6"
        data-testid="stage3-project-bound-later-step-gate"
      >
        <div className="flex items-center gap-2 font-semibold text-amber-950">
          <Lock size={18} /> {stepLabel} · project-bound analytical handoff
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
        {acceptedHandoff ? (
          <div className="mt-4 rounded-xl border border-cyan-200 bg-white p-3 text-xs text-slate-700" data-testid="stage3-eda-handoff-acknowledgment">
            <div className="font-semibold text-cyan-900">Data Profile handoff acknowledged</div>
            <p className="mt-1">
              {int(acceptedHandoff.selectedVariables?.length ?? 0)} selected variable(s), {int(acceptedHandoff.bookmarkedVariables?.length ?? 0)} bookmarked variable(s), and {int(Object.keys(acceptedHandoff.filters ?? {}).length)} active filter(s) are preserved from {acceptedHandoff.sourceTab?.replaceAll("_", " ") ?? "Data Profile"}.
              Authority <span className="font-mono">{review.reviewDigest.slice(0, 14)}…</span> matches the current project binding.
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">{(acceptedHandoff.selectedVariables ?? []).map((name) => <span key={name} className="rounded-full border border-cyan-200 bg-cyan-50 px-2 py-1 font-mono text-[10px] text-cyan-900">{name}</span>)}</div>
            {(acceptedHandoff.bookmarkedVariables ?? []).length ? <div className="mt-2 flex flex-wrap gap-1.5">{(acceptedHandoff.bookmarkedVariables ?? []).map((name) => <span key={name} className="rounded-full border border-amber-200 bg-amber-50 px-2 py-1 font-mono text-[10px] text-amber-900">★ {name}</span>)}</div> : null}
            {Object.keys(acceptedHandoff.filters ?? {}).length ? <pre className="mt-2 max-h-36 overflow-auto rounded-lg bg-slate-950 p-2 font-mono text-[10px] leading-4 text-slate-200">{JSON.stringify(acceptedHandoff.filters, null, 2)}</pre> : null}
            <p className="mt-1 text-[11px] text-slate-500">The handoff is a bookmark only. This downstream step remains held closed and makes no analytical or model request.</p>
          </div>
        ) : null}
        <p className="mt-4 text-xs leading-5 text-amber-800">
          This implementation activates the project-bound Data Profile only. A later, separately
          authorized implementation must make this downstream step consume the same project-bound
          contract before it can run.
        </p>
      </section>
      );
    }}</ReviewGate>
  );
}
