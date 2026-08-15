import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  FileClock,
  GitBranch,
  ShieldCheck,
} from "lucide-react";
import {
  getPreparationDocumentation,
  type PreparationDocumentationState,
} from "../../lib/preparationGovernance";
import { loadLocalDataset } from "../../lib/localDataset";
import { requireLocalDatasetCanonicalIdentity } from "../../lib/datasetIdentity";

export default function PreparationDocumentationLiveLink({
  projectId,
}: {
  projectId: string;
}) {
  const [state, setState] = useState<PreparationDocumentationState | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!projectId) return;
    const controller = new AbortController();
    let identity: ReturnType<typeof requireLocalDatasetCanonicalIdentity>;
    try {
      identity = requireLocalDatasetCanonicalIdentity(
        projectId,
        loadLocalDataset(),
        "Preparation documentation dataset identity",
      );
    } catch (cause) {
      setState(null);
      setError(
        cause instanceof Error
          ? cause.message
          : "Preparation documentation requires an exact Dataset Library version.",
      );
      return () => controller.abort();
    }
    getPreparationDocumentation(identity, controller.signal)
      .then((payload) => {
        setState(payload);
        setError("");
      })
      .catch((cause) => {
        if (controller.signal.aborted) return;
        setError(
          cause instanceof Error
            ? cause.message
            : "Preparation documentation is unavailable.",
        );
      });
    return () => controller.abort();
  }, [projectId]);

  if (error) {
    return (
      <section className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
        <div className="flex items-start gap-2">
          <AlertTriangle size={17} className="mt-0.5 shrink-0" />
          <div>
            <div className="font-semibold">
              Preparation documentation link is unavailable
            </div>
            <div className="mt-1">{error}</div>
          </div>
        </div>
      </section>
    );
  }
  if (!state) return null;

  const stages = [
    {
      label: "Outliers",
      status:
        state.outliers.status === "current"
          ? "confirmed"
          : state.outliers.status.startsWith("stale")
            ? "stale"
            : "draft",
      detail: state.outliers.application
        ? `${Number(state.outliers.application.changed_values ?? 0).toLocaleString()} values changed`
        : "Decision not applied",
    },
    {
      label: "Missing Values",
      status:
        state.missing_values.status === "current"
          ? "confirmed"
          : state.missing_values.status.startsWith("stale")
            ? "stale"
            : "draft",
      detail: state.missing_values.validation
        ? "Validated, no treatment required"
        : state.missing_values.application
          ? `${Number(state.missing_values.application.development_missing_after ?? 0).toLocaleString()} Development nulls remain`
          : "Decision not recorded",
    },
    {
      label: "Feature Engineering",
      status: state.feature_engineering.status,
      detail: `${state.feature_engineering.accepted_features.length.toLocaleString()} accepted / ${state.feature_engineering.materialized_features.length.toLocaleString()} materialized · ${state.feature_engineering.confirmation_status ?? "confirmation pending"}`,
    },
    {
      label: "Validation Design",
      status: state.validation_design.status,
      detail: state.validation_design.design_version
        ? `${validationStrategyLabel(state.validation_design.strategy)} · ${state.validation_design.design_version}`
        : "Governed design not approved",
    },
    {
      label: "Model Training",
      status: state.model_training.status,
      detail: state.model_training.training_job_id
        ? `${state.model_training.completed_models?.length ?? 0} persisted model(s) · ${state.model_training.model_selection_decision ? "proposal recorded" : "decision pending"}`
        : "Governed training not completed",
    },
  ] as const;

  return (
    <section
      className="rounded-xl border border-cyan-200 bg-gradient-to-br from-cyan-50 to-white p-4 shadow-sm"
      data-testid="preparation-documentation-live-link"
    >
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-cyan-950">
            <GitBranch size={18} />
            <h2 className="text-sm font-semibold">
              Preparation Decision Record
            </h2>
          </div>
          <p className="mt-1 max-w-4xl text-xs leading-5 text-cyan-900/80">
            Live backend lineage from preparation through Validation Design and
            governed Model Training. Confirmed records become stale
            automatically when a bound dataset, manifest, split, or decision
            changes.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <StatusPill status={state.status} />
          <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-1 text-[11px] font-semibold text-emerald-800">
            <ShieldCheck size={13} /> Backend enforced
          </span>
        </div>
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-5">
        {stages.map((stage) => (
          <div
            key={stage.label}
            className="rounded-lg border border-cyan-100 bg-white px-3 py-2.5"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-semibold text-slate-950">
                {stage.label}
              </span>
              <StatusPill status={stage.status} compact />
            </div>
            <div className="mt-1 text-[11px] text-slate-600">
              {stage.detail}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 border-t border-cyan-100 pt-3 text-[11px] text-slate-600">
        <span>
          Dataset <strong>{state.dataset_version}</strong>
        </span>
        <span>
          Target <strong>{state.target || "Not set"}</strong>
        </span>
        <span>
          Manifest{" "}
          <strong>{state.feature_engineering.manifest_hash || state.predictor_manifest_id || "Pending"}</strong>
        </span>
        <span>
          Validation{" "}
          <strong>{state.validation_design.design_version || "Pending"}</strong>
        </span>
        <span>
          Training job{" "}
          <strong>{state.model_training.training_job_id || "Pending"}</strong>
        </span>
        <span>
          Target-source exclusions{" "}
          <strong>
            {state.governance.target_source_excluded.join(", ") || "None"}
          </strong>
        </span>
        <span>
          Record <strong>{state.documentation_version}</strong>
        </span>
      </div>
    </section>
  );
}

function validationStrategyLabel(value: string | null) {
  if (!value) return "Validation strategy pending";
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");
}

function StatusPill({
  status,
  compact = false,
}: {
  status: "draft" | "confirmed" | "stale";
  compact?: boolean;
}) {
  const Icon =
    status === "confirmed"
      ? CheckCircle2
      : status === "stale"
        ? AlertTriangle
        : FileClock;
  const style =
    status === "confirmed"
      ? "border-emerald-200 bg-emerald-50 text-emerald-800"
      : status === "stale"
        ? "border-amber-200 bg-amber-50 text-amber-800"
        : "border-slate-200 bg-slate-50 text-slate-700";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border font-semibold ${style} ${
        compact ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-1 text-[11px]"
      }`}
    >
      <Icon size={compact ? 11 : 13} />
      {status === "confirmed"
        ? "Confirmed"
        : status === "stale"
          ? "Stale"
          : "Draft"}
    </span>
  );
}
