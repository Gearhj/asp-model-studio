import {
  CheckCircle2,
  GitBranch,
  LoaderCircle,
  PauseCircle,
  Pencil,
  Scale,
  Send,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  DEFAULT_VIF_RESOLUTION_INPUTS,
  vifComparisonChartRows,
  type VifResolutionAction,
  type VifResolutionDecisionRequest,
  type VifResolutionInputs,
  type VifResolutionPlan,
} from "../../../lib/vifResolutionPlan";


type Props = {
  predictors: string[];
  lineageKey: string;
  onGenerate: (inputs: VifResolutionInputs) => Promise<VifResolutionPlan>;
  onDecision: (
    request: VifResolutionDecisionRequest,
  ) => Promise<{ status?: string; feature_recommendations?: unknown; evidence?: unknown }>;
};


const ACTIONS: Array<{ id: VifResolutionAction; label: string }> = [
  { id: "retain", label: "Retain" },
  { id: "exclude", label: "Exclude" },
  { id: "combine", label: "Combine" },
  { id: "defer", label: "Defer" },
];


const WEIGHT_LABELS: Array<{
  id: keyof VifResolutionInputs["preferenceWeights"];
  label: string;
}> = [
  { id: "signal", label: "Signal" },
  { id: "interpretability", label: "Interpretability" },
  { id: "data_quality", label: "Data quality" },
  { id: "special_value_burden", label: "Special-value burden" },
  { id: "production_availability", label: "Production availability" },
];


function number(value: number | null | undefined, digits = 2) {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString(undefined, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      })
    : "Not available";
}


function SummaryCard({
  label,
  summary,
  tone,
}: {
  label: string;
  summary: VifResolutionPlan["current"];
  tone: "current" | "proposed";
}) {
  return (
    <article
      className={`rounded-xl border p-4 ${
        tone === "proposed"
          ? "border-emerald-200 bg-emerald-50"
          : "border-slate-200 bg-white"
      }`}
    >
      <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">
        {label}
      </p>
      <p className="mt-1 text-2xl font-bold text-slate-950">
        {number(summary.maximum_vif)}
      </p>
      <p className="text-[11px] text-slate-600">Maximum VIF</p>
      <div className="mt-3 grid grid-cols-3 gap-2 text-[10px]">
        <span><strong>{summary.predictor_count}</strong><br />predictors</span>
        <span><strong>{summary.count_above_5}</strong><br />above 5</span>
        <span><strong>{summary.count_above_10}</strong><br />above 10</span>
      </div>
    </article>
  );
}


export default function VifResolutionPlanPanel({
  predictors,
  lineageKey,
  onGenerate,
  onDecision,
}: Props) {
  const [inputs, setInputs] = useState<VifResolutionInputs>(
    DEFAULT_VIF_RESOLUTION_INPUTS,
  );
  const [plan, setPlan] = useState<VifResolutionPlan | null>(null);
  const [selectedClusters, setSelectedClusters] = useState<string[]>([]);
  const [rationale, setRationale] = useState("");
  const [status, setStatus] = useState<
    "idle" | "generating" | "deciding" | "success" | "error"
  >("idle");
  const [message, setMessage] = useState("");
  const chartRows = useMemo(
    () => (plan ? vifComparisonChartRows(plan).slice(0, 12) : []),
    [plan],
  );
  const chartMaximum = Math.max(
    1,
    ...chartRows.flatMap((row) => [row.current_vif ?? 0, row.proposed_vif ?? 0]),
  );

  useEffect(() => {
    setInputs(DEFAULT_VIF_RESOLUTION_INPUTS);
    setPlan(null);
    setSelectedClusters([]);
    setRationale("");
    setStatus("idle");
    setMessage("");
  }, [lineageKey]);

  function toggleProtected(feature: string) {
    setInputs((current) => ({
      ...current,
      protectedPredictors: current.protectedPredictors.includes(feature)
        ? current.protectedPredictors.filter((value) => value !== feature)
        : [...current.protectedPredictors, feature],
    }));
  }

  function toggleAllowed(action: VifResolutionAction) {
    setInputs((current) => ({
      ...current,
      allowedActions: current.allowedActions.includes(action)
        ? current.allowedActions.filter((value) => value !== action)
        : [...current.allowedActions, action],
    }));
  }

  async function generate() {
    setStatus("generating");
    setMessage("Identifying correlated clusters and recalculating complete VIF paths…");
    try {
      const result = await onGenerate(inputs);
      setPlan(result);
      setSelectedClusters(result.clusters.map((cluster) => cluster.cluster_id));
      setStatus("success");
      setMessage(
        `Plan ${result.plan_id} generated. ${result.calculation_count.simulated_complete_vif_recalculations} simulated complete-VIF recalculations were compared.`,
      );
    } catch (cause) {
      setStatus("error");
      setMessage(
        cause instanceof Error ? cause.message : "The VIF resolution plan could not be generated.",
      );
    }
  }

  async function decide(request: VifResolutionDecisionRequest) {
    if (!plan) return;
    setStatus("deciding");
    setMessage("Recording the governed recommendation disposition…");
    try {
      const result = await onDecision({
        ...request,
        planId: plan.plan_id,
        rationale,
      });
      setPlan((current) =>
        current
          ? { ...current, status: result.status ?? current.status }
          : current,
      );
      setStatus("success");
      setMessage(
        result.status === "sent_to_feature_engineering"
          ? "Accepted proposals were sent to Feature Engineering as draft recommendations. No predictor or data value changed."
          : `Plan disposition recorded as ${String(result.status ?? "complete").replaceAll("_", " ")}. The governed feature set remains unchanged.`,
      );
    } catch (cause) {
      setStatus("error");
      setMessage(
        cause instanceof Error ? cause.message : "The VIF plan disposition could not be recorded.",
      );
    }
  }

  return (
    <section
      id="eda-relationships-resolution-plan"
      className="mt-5 rounded-xl border border-blue-200 bg-blue-50/40 p-4"
      data-testid="vif-resolution-plan"
      aria-labelledby="vif-resolution-plan-title"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-blue-700">
            Governed recommendation workflow
          </p>
          <h4 id="vif-resolution-plan-title" className="mt-1 text-base font-bold text-slate-950">
            Generate VIF Resolution Plan
          </h4>
          <p className="mt-1 max-w-3xl text-[11px] leading-5 text-slate-600">
            Groups correlated predictors, compares iterative single- and multi-variable paths,
            and creates recommendations only. The final holdout is never opened or used.
          </p>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-[10px] font-bold text-emerald-800">
          <ShieldCheck size={13} aria-hidden="true" /> Non-mutating
        </span>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <label className="text-[11px] font-semibold text-slate-700">
          Intended model family
          <select
            value={inputs.intendedModelFamily}
            onChange={(event) =>
              setInputs((current) => ({
                ...current,
                intendedModelFamily: event.target.value as VifResolutionInputs["intendedModelFamily"],
              }))
            }
            className="atlas-select mt-1 w-full"
          >
            <option value="linear_scorecard">Linear / scorecard</option>
            <option value="generalized_linear">Generalized linear</option>
            <option value="tree_ensemble">Tree ensemble</option>
            <option value="neural_network">Neural network</option>
            <option value="mixed_bench">Mixed model bench</option>
          </select>
        </label>
        <label className="text-[11px] font-semibold text-slate-700">
          Target VIF threshold
          <input
            type="number"
            min={1}
            max={100}
            step={0.5}
            value={inputs.targetVifThreshold}
            onChange={(event) =>
              setInputs((current) => ({
                ...current,
                targetVifThreshold: Number(event.target.value),
              }))
            }
            className="atlas-input mt-1 w-full"
          />
        </label>
        <label className="text-[11px] font-semibold text-slate-700">
          Resolution objective
          <select
            value={inputs.resolutionObjective}
            onChange={(event) =>
              setInputs((current) => ({
                ...current,
                resolutionObjective: event.target.value as VifResolutionInputs["resolutionObjective"],
              }))
            }
            className="atlas-select mt-1 w-full"
          >
            <option value="balanced">Balanced</option>
            <option value="minimize_exclusions">Minimize exclusions</option>
            <option value="reduce_max_vif">Reduce maximum VIF</option>
            <option value="preserve_signal">Preserve development signal</option>
            <option value="maximize_interpretability">Maximize interpretability</option>
          </select>
        </label>
        <label className="text-[11px] font-semibold text-slate-700">
          Correlation threshold
          <input
            type="number"
            min={0.5}
            max={0.999}
            step={0.01}
            value={inputs.correlationThreshold}
            onChange={(event) =>
              setInputs((current) => ({
                ...current,
                correlationThreshold: Number(event.target.value),
              }))
            }
            className="atlas-input mt-1 w-full"
          />
        </label>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-[1fr_1.35fr]">
        <div className="rounded-xl border border-slate-200 bg-white p-3">
          <p className="text-[11px] font-bold text-slate-800">Allowed actions</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {ACTIONS.map((action) => (
              <label key={action.id} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-2 text-[10px] font-semibold text-slate-700">
                <input
                  type="checkbox"
                  checked={inputs.allowedActions.includes(action.id)}
                  onChange={() => toggleAllowed(action.id)}
                />
                {action.label}
              </label>
            ))}
          </div>
          <p className="mt-3 text-[11px] font-bold text-slate-800">Protected predictors</p>
          <div className="mt-2 max-h-32 overflow-auto rounded-lg border border-slate-200 p-2">
            {predictors.map((feature) => (
              <label key={feature} className="flex items-center gap-2 py-1 text-[10px] text-slate-700">
                <input
                  type="checkbox"
                  checked={inputs.protectedPredictors.includes(feature)}
                  onChange={() => toggleProtected(feature)}
                />
                <span className="truncate">{feature}</span>
              </label>
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-3">
          <p className="text-[11px] font-bold text-slate-800">Preference weights</p>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {WEIGHT_LABELS.map((weight) => (
              <label key={weight.id} className="text-[10px] font-semibold text-slate-600">
                <span className="flex justify-between"><span>{weight.label}</span><span>{inputs.preferenceWeights[weight.id].toFixed(1)}</span></span>
                <input
                  type="range"
                  min={0}
                  max={5}
                  step={0.25}
                  value={inputs.preferenceWeights[weight.id]}
                  onChange={(event) =>
                    setInputs((current) => ({
                      ...current,
                      preferenceWeights: {
                        ...current.preferenceWeights,
                        [weight.id]: Number(event.target.value),
                      },
                    }))
                  }
                  className="mt-1 w-full accent-blue-700"
                />
              </label>
            ))}
          </div>
          <label className="mt-3 block text-[10px] font-semibold text-slate-600">
            Maximum iterative removals: {inputs.maximumRemovals}
            <input
              type="range"
              min={1}
              max={3}
              value={inputs.maximumRemovals}
              onChange={(event) =>
                setInputs((current) => ({
                  ...current,
                  maximumRemovals: Number(event.target.value),
                }))
              }
              className="mt-1 w-full accent-blue-700"
            />
          </label>
        </div>
      </div>

      <button
        type="button"
        onClick={() => void generate()}
        disabled={status === "generating" || status === "deciding" || !inputs.allowedActions.length}
        className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-700 px-4 py-3 text-xs font-bold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:bg-slate-300"
        data-testid="generate-vif-resolution-plan"
      >
        {status === "generating" ? <LoaderCircle size={15} className="animate-spin" /> : <GitBranch size={15} />}
        {status === "generating" ? "Generating complete comparison…" : "Generate VIF Resolution Plan"}
      </button>
      <p
        className={`mt-2 min-h-5 text-[11px] ${status === "error" ? "text-rose-700" : "text-slate-600"}`}
        role="status"
      >
        {message}
      </p>

      {plan ? (
        <div className="mt-5 space-y-4" data-testid="vif-resolution-result">
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-[11px] font-semibold text-emerald-900">
            {plan.explicit_statement} Development-only evidence used {plan.analysis_scope.development_rows.toLocaleString()} rows; {plan.analysis_scope.sealed_final_holdout_rows_excluded.toLocaleString()} sealed holdout rows were excluded.
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_1.2fr]">
            <SummaryCard label="Current governed set" summary={plan.current} tone="current" />
            <SummaryCard label="Proposed simulation" summary={plan.proposed} tone="proposed" />
            <article className="rounded-xl border border-slate-200 bg-white p-4 text-[11px] text-slate-700">
              <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">Calculation scope</p>
              <p className="mt-2"><strong>{plan.calculation_count.governed_feature_set_calculations}</strong> governed-set calculation</p>
              <p><strong>{plan.calculation_count.simulated_complete_vif_recalculations}</strong> simulated complete recalculations</p>
              <p><strong>{plan.calculation_count.governed_predictor_count}</strong> governed versus <strong>{plan.calculation_count.simulated_proposed_predictor_count}</strong> proposed predictors</p>
              <p className="mt-2 font-semibold text-blue-800">{plan.model_family.label}: {plan.model_family.implication}</p>
            </article>
          </div>

          <section className="rounded-xl border border-slate-200 bg-white p-4" data-testid="vif-before-after-chart">
            <div className="flex items-center gap-2"><Scale size={15} className="text-blue-700" /><h5 className="text-sm font-bold text-slate-950">Before-and-after VIF</h5></div>
            <div className="mt-3 space-y-2">
              {chartRows.map((row) => (
                <div key={row.feature} className="grid grid-cols-[minmax(120px,1fr)_2fr] items-center gap-3 text-[10px]">
                  <span className="truncate font-semibold text-slate-700" title={row.feature}>{row.feature}</span>
                  <div className="space-y-1">
                    <div className="flex items-center gap-2"><span className="w-12 text-right text-slate-500">Current</span><span className="h-2 rounded bg-slate-400" style={{ width: `${Math.max(1, ((row.current_vif ?? 0) / chartMaximum) * 100)}%` }} /><span>{number(row.current_vif)}</span></div>
                    <div className="flex items-center gap-2"><span className="w-12 text-right text-emerald-700">Proposed</span><span className="h-2 rounded bg-emerald-500" style={{ width: `${Math.max(row.proposed_vif === null ? 0 : 1, ((row.proposed_vif ?? 0) / chartMaximum) * 100)}%` }} /><span>{row.proposed_action === "exclude" ? "Excluded" : number(row.proposed_vif)}</span></div>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {plan.ties.length ? (
            <section className="rounded-xl border border-amber-300 bg-amber-50 p-4" data-testid="vif-tie-cases">
              <h5 className="text-sm font-bold text-amber-950">Equivalent alternatives require tie-breakers</h5>
              {plan.ties.map((tie) => (
                <div key={tie.cluster_id} className="mt-3 text-[11px] leading-5 text-amber-950">
                  <p className="font-bold">{tie.features.join(" versus ")}</p>
                  <p>{tie.message}</p>
                  <p><strong>Required tie-breakers:</strong> {tie.required_tie_breakers.join(", ")}.</p>
                </div>
              ))}
            </section>
          ) : null}

          <section className="rounded-xl border border-slate-200 bg-white p-4" data-testid="vif-cluster-recommendations">
            <h5 className="text-sm font-bold text-slate-950">Cluster-level recommendations</h5>
            <div className="mt-3 grid gap-3 lg:grid-cols-2">
              {plan.clusters.map((cluster) => (
                <article key={cluster.cluster_id} className="rounded-lg border border-slate-200 p-3">
                  <label className="flex items-start gap-2">
                    <input
                      type="checkbox"
                      checked={selectedClusters.includes(cluster.cluster_id)}
                      onChange={() => setSelectedClusters((current) => current.includes(cluster.cluster_id) ? current.filter((id) => id !== cluster.cluster_id) : [...current, cluster.cluster_id])}
                    />
                    <span><strong className="text-xs text-slate-900">{cluster.features.join(" · ")}</strong><span className="mt-1 block text-[10px] text-slate-500">|r| up to {number(cluster.maximum_correlation, 3)} · {cluster.recommended_action}</span></span>
                  </label>
                  <p className="mt-2 text-[10px] leading-4 text-slate-600">{cluster.rationale}</p>
                  {cluster.protected_features.length ? <p className="mt-2 text-[10px] font-semibold text-blue-800">Protected: {cluster.protected_features.join(", ")}</p> : null}
                </article>
              ))}
            </div>
          </section>

          <details className="rounded-xl border border-slate-200 bg-white" open>
            <summary className="cursor-pointer px-4 py-3 text-sm font-bold text-slate-950">Per-feature VIF delta table</summary>
            <div className="max-h-80 overflow-auto border-t border-slate-200">
              <table className="atlas-table min-w-[720px] text-[10px]">
                <thead><tr><th>Feature</th><th>Current VIF</th><th>Proposed VIF</th><th>Delta</th><th>Proposed action</th></tr></thead>
                <tbody>{plan.per_feature_vif_deltas.map((row) => <tr key={row.feature}><td className="font-semibold">{row.feature}</td><td>{number(row.current_vif)}</td><td>{row.proposed_action === "exclude" ? "Excluded" : number(row.proposed_vif)}</td><td>{number(row.delta)}</td><td>{row.proposed_action}</td></tr>)}</tbody>
              </table>
            </div>
          </details>

          <details className="rounded-xl border border-slate-200 bg-white">
            <summary className="cursor-pointer px-4 py-3 text-sm font-bold text-slate-950">Alternative resolution plans ({plan.alternatives.length})</summary>
            <div className="max-h-72 overflow-auto border-t border-slate-200">
              <table className="atlas-table min-w-[680px] text-[10px]"><thead><tr><th>Illustrative path</th><th>Max VIF</th><th>Above 5</th><th>Above 10</th><th>Predictors</th></tr></thead><tbody>{plan.alternatives.map((alternative, index) => <tr key={`${alternative.path.join("|")}-${index}`}><td>{alternative.path.join(" → ")}</td><td>{number(alternative.maximum_vif)}</td><td>{alternative.count_above_5}</td><td>{alternative.count_above_10}</td><td>{alternative.predictor_count}</td></tr>)}</tbody></table>
            </div>
          </details>

          <div className="grid gap-3 md:grid-cols-3 text-[10px]">
            <article className="rounded-lg border border-slate-200 bg-white p-3"><strong>Proposed exclusions</strong><p className="mt-1 text-slate-600">{plan.proposed_exclusions.length ? plan.proposed_exclusions.map((row) => `${row.feature} (${row.status})`).join(", ") : "None"}</p></article>
            <article className="rounded-lg border border-slate-200 bg-white p-3"><strong>Proposed combinations</strong><p className="mt-1 text-slate-600">{plan.proposed_combinations.length ? plan.proposed_combinations.map((row) => row.source_features.join(" + ")).join(", ") : "None"}</p></article>
            <article className="rounded-lg border border-slate-200 bg-white p-3"><strong>Unresolved clusters</strong><p className="mt-1 text-slate-600">{plan.remaining_unresolved_clusters.length ? plan.remaining_unresolved_clusters.map((row) => row.features.join(" · ")).join(", ") : "None"}</p></article>
          </div>

          <label className="block text-[11px] font-semibold text-slate-700">
            Reviewer rationale or modification note
            <textarea value={rationale} onChange={(event) => setRationale(event.target.value)} rows={3} className="atlas-input mt-1 w-full resize-y" placeholder="Document the decision basis, tie-breaker evidence, or requested modification." />
          </label>

          <div className="flex flex-wrap gap-2" data-testid="vif-plan-actions">
            <button type="button" className="atlas-primary-button" onClick={() => void decide({ planId: plan.plan_id, action: "accept_complete" })} disabled={status === "deciding"}><CheckCircle2 size={14} /> Accept complete plan</button>
            <button type="button" className="atlas-secondary-button" onClick={() => void decide({ planId: plan.plan_id, action: "accept_selected", selectedClusterIds: selectedClusters })} disabled={status === "deciding" || !selectedClusters.length}><CheckCircle2 size={14} /> Accept selected clusters</button>
            <button type="button" className="atlas-secondary-button" onClick={() => void decide({ planId: plan.plan_id, action: "modify", modifications: { reviewer_note: rationale } })} disabled={status === "deciding"}><Pencil size={14} /> Modify plan</button>
            <button type="button" className="atlas-secondary-button" onClick={() => void decide({ planId: plan.plan_id, action: "defer" })} disabled={status === "deciding"}><PauseCircle size={14} /> Defer</button>
            <button type="button" className="atlas-secondary-button" onClick={() => void decide({ planId: plan.plan_id, action: "reject" })} disabled={status === "deciding"}><XCircle size={14} /> Reject</button>
            <button type="button" className="atlas-secondary-button" onClick={() => void decide({ planId: plan.plan_id, action: "send_to_feature_engineering" })} disabled={status === "deciding" || !["accepted", "partially_accepted", "sent_to_feature_engineering"].includes(plan.status)}><Send size={14} /> Send accepted proposals to Feature Engineering</button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
