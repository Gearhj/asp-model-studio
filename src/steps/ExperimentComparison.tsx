import { useEffect, useMemo, useState } from "react";
import { Download, FlaskConical, Trophy } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import {
  exportExperimentsCsv,
  loadExperiments,
  promoteExperimentToChampion,
  updateExperimentNotes,
  type ExperimentRecord,
} from "../lib/experimentTracking";

type SortMetric =
  | "auc"
  | "pr_auc"
  | "precision"
  | "recall"
  | "f1"
  | "ks"
  | "lift"
  | "calibration"
  | "interpretability"
  | "runtime";

const sortOptions: { key: SortMetric; label: string }[] = [
  { key: "auc", label: "AUC" },
  { key: "pr_auc", label: "PR-AUC" },
  { key: "precision", label: "Precision" },
  { key: "recall", label: "Recall" },
  { key: "f1", label: "F1" },
  { key: "ks", label: "KS" },
  { key: "lift", label: "Lift" },
  { key: "calibration", label: "Calibration" },
  { key: "interpretability", label: "Interpretability" },
  { key: "runtime", label: "Runtime" },
];

function metricValue(experiment: ExperimentRecord, metric: SortMetric) {
  if (metric === "interpretability") return experiment.interpretability;
  if (metric === "runtime") return experiment.runtimeMs;
  if (metric === "calibration") return experiment.calibrationStatus === "calibrated" ? 1 : 0;
  return Number(experiment.metrics[metric] ?? Number.NaN);
}

function formatMetric(value: unknown, digits = 4) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(digits) : "-";
}

function downloadText(filename: string, text: string, type = "text/csv") {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function ExperimentComparison() {
  const [experiments, setExperiments] = useState<ExperimentRecord[]>(() => loadExperiments());
  const [sortMetric, setSortMetric] = useState<SortMetric>("auc");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string>("");

  useEffect(() => {
    const refresh = () => setExperiments(loadExperiments());
    window.addEventListener("experiment-tracking-updated", refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener("experiment-tracking-updated", refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);

  const sorted = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rows = q
      ? experiments.filter((experiment) =>
          [experiment.experimentId, experiment.dataset_version_id, experiment.modelType, experiment.modelKey, experiment.notes]
            .join(" ")
            .toLowerCase()
            .includes(q)
        )
      : experiments;
    return rows.slice().sort((a, b) => {
      const aValue = metricValue(a, sortMetric);
      const bValue = metricValue(b, sortMetric);
      if (sortMetric === "runtime") return (aValue || Number.POSITIVE_INFINITY) - (bValue || Number.POSITIVE_INFINITY);
      return (Number.isFinite(bValue) ? bValue : Number.NEGATIVE_INFINITY) - (Number.isFinite(aValue) ? aValue : Number.NEGATIVE_INFINITY);
    });
  }, [experiments, query, sortMetric]);

  const selected = experiments.find((experiment) => experiment.experimentId === selectedId) ?? sorted[0] ?? null;
  const champion = experiments.find((experiment) => experiment.champion) ?? null;

  const promote = (experimentId: string) => {
    const next = promoteExperimentToChampion(experimentId);
    setExperiments(next);
  };

  const updateNotes = (experimentId: string, notes: string) => {
    const next = updateExperimentNotes(experimentId, notes);
    setExperiments(next);
  };

  return (
    <div className="w-full space-y-5">
      <div className="flex flex-col gap-3 pt-2 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <BrandLogo size="md" variant="light" showSubtitle className="mb-3" />
          <div className="flex items-center gap-2">
            <FlaskConical size={20} className="text-slate-800" />
            <h1 className="text-xl font-semibold text-slate-950">Experiment Comparison</h1>
          </div>
          <p className="mt-1 text-sm text-slate-600">
            Lightweight MLflow-style run history for model comparison, champion promotion, and validation evidence.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            className="w-64 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter experiments..."
          />
          <select
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm"
            value={sortMetric}
            onChange={(event) => setSortMetric(event.target.value as SortMetric)}
          >
            {sortOptions.map((option) => (
              <option key={option.key} value={option.key}>
                Sort by {option.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
            onClick={() => downloadText("experiment-comparison.csv", exportExperimentsCsv(experiments))}
          >
            <Download size={15} />
            Export CSV
          </button>
        </div>
      </div>

      <section className="grid gap-4 md:grid-cols-4">
        <Stat label="Experiments" value={experiments.length || "-"} />
        <Stat label="Champion" value={champion?.modelType ?? "None"} />
        <Stat
          label="Datasets"
          value={
            new Set(
              experiments.map(
                (experiment) =>
                  `${experiment.project_id}:${experiment.dataset_id}:${experiment.dataset_version_id}`,
              ),
            ).size || "-"
          }
        />
        <Stat label="Models" value={new Set(experiments.map((experiment) => experiment.modelKey)).size || "-"} />
      </section>

      <section className="grid gap-5 2xl:grid-cols-[minmax(0,1.35fr)_minmax(420px,0.65fr)]">
        <div className="overflow-hidden rounded-lg border border-slate-200/80 bg-white/90 shadow-sm">
          <div className="border-b border-slate-200 px-4 py-3">
            <h2 className="text-sm font-semibold text-slate-950">Runs</h2>
            <p className="mt-1 text-xs text-slate-500">Click a run to inspect settings, diagnostics, and notes.</p>
          </div>
          <div className="overflow-auto">
            <table className="min-w-[1220px] w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-2">Champion</th>
                  <th className="px-3 py-2">Timestamp</th>
                  <th className="px-3 py-2">Model</th>
                  <th className="px-3 py-2">AUC</th>
                  <th className="px-3 py-2">PR-AUC</th>
                  <th className="px-3 py-2">Precision</th>
                  <th className="px-3 py-2">Recall</th>
                  <th className="px-3 py-2">F1</th>
                  <th className="px-3 py-2">KS</th>
                  <th className="px-3 py-2">Lift</th>
                  <th className="px-3 py-2">Calibration</th>
                  <th className="px-3 py-2">Interpretability</th>
                  <th className="px-3 py-2">Runtime</th>
                  <th className="px-3 py-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((experiment) => (
                  <tr
                    key={experiment.experimentId}
                    className={`cursor-pointer border-t ${selected?.experimentId === experiment.experimentId ? "bg-indigo-50" : "hover:bg-slate-50"}`}
                    onClick={() => setSelectedId(experiment.experimentId)}
                  >
                    <td className="px-3 py-2">
                      {experiment.champion ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700">
                          <Trophy size={12} />
                          Champion
                        </span>
                      ) : (
                        "-"
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-600">{new Date(experiment.timestamp).toLocaleString()}</td>
                    <td className="px-3 py-2 font-medium text-slate-950">{experiment.modelType}</td>
                    <td className="px-3 py-2">{formatMetric(experiment.metrics.auc)}</td>
                    <td className="px-3 py-2">{formatMetric(experiment.metrics.pr_auc)}</td>
                    <td className="px-3 py-2">{formatMetric(experiment.metrics.precision)}</td>
                    <td className="px-3 py-2">{formatMetric(experiment.metrics.recall)}</td>
                    <td className="px-3 py-2">{formatMetric(experiment.metrics.f1)}</td>
                    <td className="px-3 py-2">{formatMetric(experiment.metrics.ks)}</td>
                    <td className="px-3 py-2">{formatMetric(experiment.metrics.lift, 2)}</td>
                    <td className="px-3 py-2">{experiment.calibrationStatus}</td>
                    <td className="px-3 py-2">{experiment.interpretability}</td>
                    <td className="px-3 py-2">{Math.round(experiment.runtimeMs / 1000)}s</td>
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        className="rounded-lg bg-slate-950 px-2 py-1 text-xs font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
                        disabled={experiment.champion}
                        onClick={(event) => {
                          event.stopPropagation();
                          promote(experiment.experimentId);
                        }}
                      >
                        Promote
                      </button>
                    </td>
                  </tr>
                ))}
                {!sorted.length && (
                  <tr>
                    <td className="px-3 py-6 text-sm text-slate-500" colSpan={14}>
                      No experiment records yet. Train models in Step 7 to create experiment records automatically.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <ExperimentDetail experiment={selected} onPromote={promote} onNotesChange={updateNotes} />
      </section>
    </div>
  );
}

function ExperimentDetail({
  experiment,
  onPromote,
  onNotesChange,
}: {
  experiment: ExperimentRecord | null;
  onPromote: (experimentId: string) => void;
  onNotesChange: (experimentId: string, notes: string) => void;
}) {
  if (!experiment) {
    return (
      <aside className="rounded-lg border border-slate-200/80 bg-white/90 p-4 text-sm text-slate-500 shadow-sm">
        Select an experiment to review details.
      </aside>
    );
  }

  const topFeatures = experiment.featureImportance?.slice(0, 8) ?? [];

  return (
    <aside className="rounded-lg border border-slate-200/80 bg-white/90 p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-950">{experiment.modelType}</h2>
          <p className="mt-1 break-all text-xs text-slate-500">{experiment.experimentId}</p>
        </div>
        <button
          type="button"
          className="rounded-lg bg-slate-950 px-3 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
          disabled={experiment.champion}
          onClick={() => onPromote(experiment.experimentId)}
        >
          {experiment.champion ? "Champion" : "Promote"}
        </button>
      </div>

      <div className="mt-4 grid gap-2">
        <Detail label="Project ID" value={experiment.project_id} />
        <Detail label="Dataset ID" value={experiment.dataset_id} />
        <Detail label="Dataset Version" value={experiment.dataset_version_id} />
        <Detail label="Selected Features" value={String(experiment.selectedFeatures.length)} />
        <Detail label="Balancing" value={experiment.balancingMethod} />
        <Detail label="Split Strategy" value={experiment.splitStrategy} />
        <Detail label="Calibration" value={experiment.calibrationStatus} />
        <Detail label="Runtime" value={`${Math.round(experiment.runtimeMs / 1000)} seconds`} />
      </div>

      <div className="mt-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Hyperparameters</h3>
        <pre className="mt-2 max-h-28 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-100">
          {JSON.stringify(experiment.hyperparameters ?? {}, null, 2)}
        </pre>
      </div>

      <div className="mt-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Top Feature Importance</h3>
        <div className="mt-2 grid gap-2">
          {topFeatures.length ? (
            topFeatures.map((row) => (
              <div key={row.feature} className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs">
                <span className="truncate font-medium text-slate-800">{row.feature}</span>
                <span className="text-slate-600">{formatMetric(row.importance)}</span>
              </div>
            ))
          ) : (
            <div className="text-sm text-slate-500">No feature importance captured.</div>
          )}
        </div>
      </div>

      <label className="mt-4 grid gap-1">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Notes</span>
        <textarea
          className="min-h-24 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm"
          value={experiment.notes}
          onChange={(event) => onNotesChange(experiment.experimentId, event.target.value)}
          placeholder="Document why this experiment should or should not be promoted."
        />
      </label>
    </aside>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-slate-200/80 bg-white/90 p-4 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 truncate text-xl font-semibold text-slate-950" title={String(value)}>
        {value}
      </div>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 break-words text-xs font-semibold text-slate-800">{value}</div>
    </div>
  );
}
