import { useEffect, useMemo, useRef, useState } from "react";
import {
  Braces,
  Calculator,
  CalendarDays,
  ChevronDown,
  Columns3,
  Eye,
  GitCompareArrows,
  LoaderCircle,
  Plus,
  Save,
  Settings2,
  Trash2,
} from "lucide-react";
import StepShell from "../components/StepShell";
import {
  AtlasAttentionPanel,
  AtlasDataScopeBadge,
  AtlasExecutionStatus,
  AtlasWorkflowSection,
  type AtlasWorkflowMetric,
} from "../components/ui/AtlasWorkflow";
import {
  getFeatureManifest,
  materializeFeatureManifest,
  previewFeaturePlan,
  removeFeature,
  saveFeatureManifest,
  type FeatureDraft,
  type FeatureManifest,
  type FeatureManifestRow,
  type FeatureOrigin,
  type FeaturePreview,
  type PipelineStep,
} from "../lib/featureManifest";
import { createEvidence } from "../lib/evidenceGraph";
import { logDecision } from "../lib/decisionJournal";
import { useWorkflowStore } from "../state/useWorkflowStore";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

type BuilderType = "interaction" | "numeric_bin" | "categorical_rule" | "polynomial" | "arithmetic" | "date-derived";

type VifRow = {
  feature: string;
  vif: number | null;
  status: string;
};

const PREVIEW_ROW_LIMITS = [10, 25, 50, 100] as const;
const VIF_AUTO_EXCLUDE_THRESHOLD = 10;

const builderOptions: Array<{ id: BuilderType; label: string; icon: typeof Plus; description: string }> = [
  { id: "interaction", label: "Interaction", icon: GitCompareArrows, description: "Multiply two governed numeric predictors." },
  { id: "numeric_bin", label: "Numeric Bin", icon: Columns3, description: "Create fixed reviewer-defined cut points." },
  { id: "categorical_rule", label: "Rule Category", icon: Braces, description: "Create a deterministic category from explicit rules." },
  { id: "polynomial", label: "Polynomial", icon: Calculator, description: "Create one named squared or cubed term." },
  { id: "arithmetic", label: "Arithmetic", icon: Calculator, description: "Add, subtract, multiply, or divide two predictors." },
  { id: "date-derived", label: "Date Derived", icon: CalendarDays, description: "Extract a governed date component." },
];

function toDraft(row: Partial<FeatureManifestRow>): FeatureDraft {
  const featureName = row.feature_name?.trim() || row.feature_id || "unnamed_feature";
  const origin = row.origin ?? "other";
  return {
    feature_id: row.feature_id,
    feature_name: featureName,
    display_name: row.display_name?.trim() || featureName,
    origin,
    source_features: Array.isArray(row.source_features) ? row.source_features.filter(Boolean) : [],
    transformation_type: row.transformation_type || origin,
    formula_or_rule: row.formula_or_rule || "Metadata requires review",
    output_datatype: row.output_datatype || "unknown",
    selected: row.selected !== false,
    exclusion_reason: row.exclusion_reason || "",
    user_rationale: row.user_rationale || "",
    config: row.config ?? {},
  };
}

function parseList(value: string) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function parseNumbers(value: string) {
  return Array.from(new Set(parseList(value).map(Number).filter(Number.isFinite))).sort((left, right) => left - right);
}

export default function Step05FeatureEngineering() {
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const getNextStepPath = useWorkflowStore((state) => state.getNextStepPath);
  const [manifest, setManifest] = useState<FeatureManifest | null>(null);
  const [drafts, setDrafts] = useState<FeatureDraft[]>([]);
  const [pipelineSteps, setPipelineSteps] = useState<PipelineStep[]>([]);
  const [builderType, setBuilderType] = useState<BuilderType>("interaction");
  const [form, setForm] = useState<Record<string, string>>({});
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [materializing, setMaterializing] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [previewRowLimit, setPreviewRowLimit] = useState(10);
  const [preview, setPreview] = useState<FeaturePreview | null>(null);
  const [vifRows, setVifRows] = useState<VifRow[] | null>(null);
  const [vifLoading, setVifLoading] = useState(false);
  const [vifSaving, setVifSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const previewController = useRef<AbortController | null>(null);

  async function loadManifest() {
    setLoading(true);
    setError("");
    try {
      const payload = await getFeatureManifest();
      setManifest(payload);
      setDrafts(payload.features.filter((feature) => feature.origin !== "original").map(toDraft));
      setPipelineSteps(payload.pipeline_steps ?? []);
      setDirty(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Feature manifest is unavailable.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadManifest();
  }, []);

  const originals = manifest?.features.filter((feature) => feature.origin === "original") ?? [];
  const eligibleOriginals = originals.filter((feature) => feature.eligibility_status === "eligible");
  const numericOriginals = eligibleOriginals.filter((feature) => /int|float|double|numeric|number/i.test(feature.output_datatype));
  const categoricalOriginals = eligibleOriginals.filter((feature) => !numericOriginals.includes(feature));
  const availableNames = useMemo(() => [...eligibleOriginals.map((feature) => feature.feature_name), ...drafts.map((feature) => feature.feature_name)], [drafts, eligibleOriginals]);
  const numericNames = useMemo(() => [...numericOriginals.map((feature) => feature.feature_name), ...drafts.filter((feature) => feature.output_datatype === "numeric").map((feature) => feature.feature_name)], [drafts, numericOriginals]);
  const vifCandidateNames = useMemo(() => (manifest?.features ?? [])
    .filter((feature) => feature.selected
      && feature.eligibility_status === "eligible"
      && /int|float|double|numeric|number/i.test(feature.output_datatype)
      && (feature.origin === "original" || feature.materialization_status === "materialized"))
    .map((feature) => feature.feature_name), [manifest]);
  const selectedByFeature = useMemo(() => new Map((manifest?.features ?? []).map((feature) => [feature.feature_name, feature.selected])), [manifest]);
  const materializedCount = manifest?.features.filter((feature) => feature.origin !== "original" && feature.materialization_status === "materialized").length ?? 0;
  const planReady = !dirty && drafts.every((draft) => manifest?.features.some((feature) => feature.feature_id === draft.feature_id && feature.materialization_status === "materialized"));

  function field(name: string) {
    return form[name] ?? "";
  }

  function updateField(name: string, value: string) {
    setForm((current) => ({ ...current, [name]: value }));
  }

  function addFeature() {
    setError("");
    const name = field("name").trim();
    if (!name) {
      setError("Enter a unique feature name before adding the transformation.");
      return;
    }
    if (availableNames.includes(name)) {
      setError(`Feature name '${name}' already exists.`);
      return;
    }
    const target = manifest?.features.find((feature) => feature.eligibility_status === "excluded" && /target/i.test(feature.exclusion_reason))?.feature_name;
    let draft: FeatureDraft;
    if (builderType === "interaction") {
      const left = field("left");
      const right = field("right");
      if (!left || !right || left === right) {
        setError("Select two different numeric source predictors.");
        return;
      }
      draft = makeDraft(name, builderType, [left, right], `${left} * ${right}`, "numeric", {});
    } else if (builderType === "numeric_bin") {
      const source = field("source");
      const cutPoints = parseNumbers(field("cutPoints"));
      const labels = parseList(field("labels"));
      if (!source || !cutPoints.length) {
        setError("Select a numeric source and enter at least one fixed cut point.");
        return;
      }
      if (labels.length && labels.length !== cutPoints.length + 1) {
        setError("Bin labels must contain one more value than cut points.");
        return;
      }
      draft = makeDraft(name, builderType, [source], `cut(${source}; ${cutPoints.join(", ")})`, "categorical", { cut_points: cutPoints, labels, missing_label: field("missingLabel") || "Missing" });
    } else if (builderType === "categorical_rule") {
      const source = field("source");
      const operator = field("operator") || "equals";
      if (!source || (operator !== "is_missing" && !field("value"))) {
        setError("Select a source and provide a rule value.");
        return;
      }
      const rule = { op: operator, value: field("value"), then_label: field("thenLabel") || "Matched" };
      draft = makeDraft(name, builderType, [source], `${source} ${operator} ${field("value")}`, "categorical", { rules: [rule], else_label: field("elseLabel") || "Other" });
    } else if (builderType === "polynomial") {
      const source = field("source");
      const degree = Number(field("degree") || 2);
      if (!source || ![2, 3].includes(degree)) {
        setError("Select one numeric source and degree 2 or 3.");
        return;
      }
      draft = makeDraft(name, builderType, [source], `${source} ^ ${degree}`, "numeric", { degree });
    } else if (builderType === "arithmetic") {
      const left = field("left");
      const right = field("right");
      const operation = field("operation") || "add";
      if (!left || !right) {
        setError("Select two numeric source predictors.");
        return;
      }
      draft = makeDraft(name, builderType, [left, right], `${left} ${operation} ${right}`, "numeric", { operation });
    } else {
      const source = field("source");
      const component = field("component") || "year";
      if (!source) {
        setError("Select a valid date source.");
        return;
      }
      draft = makeDraft(name, builderType, [source], `${component}(${source})`, "numeric", { component });
    }
    if (target && draft.source_features.includes(target)) {
      setError("The target cannot be used to create a predictor.");
      return;
    }
    setDrafts((current) => [...current, draft]);
    setDirty(true);
    setPreview(null);
    setForm({});
    setMessage(`${name} added to the transformation plan. Save and materialize the plan to make it available downstream.`);
  }

  async function savePlan() {
    setSaving(true);
    setError("");
    try {
      const payload = await saveFeatureManifest(drafts, pipelineSteps, manifest?.dataset_version ?? "");
      setManifest(payload);
      setDrafts(payload.features.filter((feature) => feature.origin !== "original").map(toDraft));
      setPipelineSteps(payload.pipeline_steps ?? []);
      setDirty(false);
      setMessage(`Feature manifest ${payload.manifest_version} saved. Deterministic features are ready to materialize.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The feature plan could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  async function runPreview() {
    previewController.current?.abort();
    const controller = new AbortController();
    previewController.current = controller;
    setPreviewing(true);
    setError("");
    try {
      const payload = await previewFeaturePlan(drafts, previewRowLimit, controller.signal);
      setPreview(payload);
      setMessage(`Preview generated from ${payload.preview_row_count} bounded rows. No full-data materialization occurred.`);
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "AbortError") return;
      setError(cause instanceof Error ? cause.message : "Feature preview failed.");
    } finally {
      if (!controller.signal.aborted) setPreviewing(false);
    }
  }

  async function materialize() {
    if (dirty) {
      setError("Save the current transformation plan before materializing features.");
      return;
    }
    if (!manifest) return;
    setMaterializing(true);
    setError("");
    try {
      const payload = await materializeFeatureManifest(manifest.manifest_version);
      await loadManifest();
      setMessage(`${payload.engineered_feature_count} engineered features materialized across ${payload.row_count.toLocaleString()} backend rows in ${payload.duration_ms.toLocaleString()} ms.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Feature materialization failed.");
    } finally {
      setMaterializing(false);
    }
  }

  async function deleteDraft(draft: FeatureDraft) {
    if (draft.feature_id && manifest?.features.some((feature) => feature.feature_id === draft.feature_id)) {
      try {
        const payload = await removeFeature(draft.feature_id);
        setManifest(payload);
        setDrafts(payload.features.filter((feature) => feature.origin !== "original").map(toDraft));
        setDirty(false);
        setMessage(`${draft.feature_name} removed from the manifest. Re-materialize to update the backend feature set.`);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "The feature could not be removed.");
      }
    } else {
      setDrafts((current) => current.filter((item) => item !== draft));
      setDirty(true);
    }
  }

  async function runVif() {
    if (dirty) {
      setError("Save and materialize the current feature plan before running VIF diagnostics.");
      return;
    }
    if (vifCandidateNames.length < 2) {
      setError("At least two selected numeric predictors are required for VIF diagnostics.");
      return;
    }
    setVifLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/eda/workspace/relationships`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ selected_features: vifCandidateNames }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok || !payload?.ok) throw new Error(payload?.detail ?? "VIF analysis failed.");
      setVifRows(payload.vif ?? []);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "VIF analysis failed.");
    } finally {
      setVifLoading(false);
    }
  }

  async function persistVifSelection(updates: Record<string, boolean>) {
    if (!manifest) return;
    setVifSaving(true);
    setError("");
    try {
      const draftByName = new Map(drafts.map((draft) => [draft.feature_name, draft]));
      const featureUpdates = manifest.features.map((feature) => {
        const draft = draftByName.get(feature.feature_name) ?? toDraft(feature);
        const selected = updates[feature.feature_name];
        if (selected === undefined || feature.eligibility_status !== "eligible") return draft;
        return {
          ...draft,
          selected,
          exclusion_reason: selected ? "" : "Excluded after VIF review",
        };
      });
      const payload = await saveFeatureManifest(featureUpdates, pipelineSteps, manifest.dataset_version);
      setManifest(payload);
      setDrafts(payload.features.filter((feature) => feature.origin !== "original").map(toDraft));
      setPipelineSteps(payload.pipeline_steps ?? []);
      setDirty(false);
      setPreview(null);
      const excludedCount = Object.values(updates).filter((selected) => !selected).length;
      setMessage(excludedCount
        ? `${excludedCount.toLocaleString()} predictor${excludedCount === 1 ? "" : "s"} excluded after VIF review. Any existing split is now stale.`
        : "Predictor restored to the governed Feature Manifest. Any existing split is now stale.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The VIF selection could not be saved.");
    } finally {
      setVifSaving(false);
    }
  }

  async function excludeHighVifFeatures() {
    const updates = Object.fromEntries((vifRows ?? [])
      .filter((row) => typeof row.vif === "number" && Number.isFinite(row.vif) && row.vif >= VIF_AUTO_EXCLUDE_THRESHOLD)
      .map((row) => [row.feature, false]));
    if (!Object.keys(updates).length) {
      setMessage(`No predictors have VIF greater than or equal to ${VIF_AUTO_EXCLUDE_THRESHOLD}.`);
      return;
    }
    await persistVifSelection(updates);
  }

  function updatePipeline(type: "scaler" | "encoding", value: string) {
    setPipelineSteps((current) => {
      const remaining = current.filter((step) => step.transformation_type !== type);
      return value === "None" ? remaining : [...remaining, { transformation_type: type, selected_features: [], config: { method: value }, enabled: true }];
    });
    setDirty(true);
  }

  function pipelineValue(type: "scaler" | "encoding") {
    const step = pipelineSteps.find((item) => item.transformation_type === type && item.enabled);
    return String(step?.config?.method ?? "None");
  }

  async function completeStep() {
    if (!manifest) return false;
    await createEvidence({
      projectId,
      projectName,
      evidenceType: "feature_engineering",
      title: "Governed Feature Manifest",
      summary: `${drafts.length} deterministic engineered features and ${pipelineSteps.length} training-only pipeline steps were recorded in manifest ${manifest.manifest_version}.`,
      sourcePage: "Feature Engineering",
      sourceRoute: "/step05",
      datasetIds: [manifest.dataset_version],
      modelIds: [],
      documentIds: [],
      notebookIds: [],
      supportsSections: ["Feature Engineering", "Candidate Models"],
      tags: ["predictive_modeling", "feature_manifest", "lineage"],
      status: planReady ? "ready" : "needs_review",
      importance: "high",
      lineage: { datasetVersion: manifest.dataset_version, manifestVersion: manifest.manifest_version },
      payload: { features: manifest.features, pipelineSteps: manifest.pipeline_steps },
    });
    return true;
  }

  const heroMetrics: AtlasWorkflowMetric[] = [
    { label: "Source Predictors", value: eligibleOriginals.length.toLocaleString() },
    { label: "Engineered Plan", value: drafts.length.toLocaleString() },
    { label: "Materialized", value: materializedCount.toLocaleString(), tone: materializedCount === drafts.length ? "success" : drafts.length ? "warning" : "neutral" },
    { label: "Pipeline Steps", value: pipelineSteps.length.toLocaleString() },
    { label: "Manifest", value: manifest?.manifest_version ?? "Loading" },
    { label: "Readiness", value: planReady ? "Current" : "Action required", tone: planReady ? "success" : "warning" },
  ];

  if (loading) {
    return <StepShell title="Step 5: Feature Engineering" subtitle="Build governed, traceable predictors without moving full-data transformations into the browser." variant="preparation" heroMetrics={heroMetrics} nextDisabled><div className="atlas-workflow-section flex min-h-56 items-center justify-center"><LoaderCircle size={28} className="animate-spin text-blue-600" /></div></StepShell>;
  }

  return (
    <StepShell
      title="Step 5: Feature Engineering"
      subtitle="Create named deterministic predictors, define training-only preprocessing, inspect bounded previews, and materialize the governed feature set with complete lineage."
      variant="preparation"
      heroMetrics={heroMetrics}
      nextPath={getNextStepPath("step05")}
      nextDisabled={!!error || dirty || !planReady}
      nextDisabledReason={dirty ? "Save the transformation plan before continuing." : !planReady ? "Materialize all deterministic engineered features before continuing." : error || undefined}
      onNext={completeStep}
      nextStatusLine="The current feature manifest and materialized predictors will move to Final Predictor Review."
    >
      <div className="space-y-4">
        {error ? <AtlasAttentionPanel title="Feature plan requires attention" tone="danger">{error}</AtlasAttentionPanel> : null}
        {message ? <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">{message}</div> : null}

        <AtlasWorkflowSection eyebrow="Authoritative contract" title="Transformation Plan" description="Every explicit feature appears here immediately. Training uses only features recorded in this manifest." tone="info" action={manifest ? <span className="text-xs font-semibold text-slate-600">{manifest.manifest_version}</span> : null}>
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <StatusMetric label="Original features" value={eligibleOriginals.length} />
            <StatusMetric label="Planned features" value={drafts.length} />
            <StatusMetric label="Materialized features" value={materializedCount} />
            <StatusMetric label="Split status" value={manifest?.split_status?.replace(/_/g, " ") ?? "not created"} warning={manifest?.split_status === "stale"} />
          </div>
          <div className="mt-4 overflow-auto rounded-lg border border-slate-200">
            <table className="atlas-table min-w-[980px]">
              <thead><tr><th>Feature</th><th>Type</th><th>Formula or rule</th><th>Source variables</th><th>Output</th><th>Leakage</th><th>Creation</th><th>Materialization</th><th /></tr></thead>
              <tbody>
                {drafts.map((draft) => {
                  const saved = manifest?.features.find((feature) => feature.feature_id === draft.feature_id || feature.feature_name === draft.feature_name);
                  return (
                    <tr key={draft.feature_id ?? draft.feature_name}>
                      <td className="font-semibold">{draft.feature_name}</td>
                      <td>{originLabel(draft.origin)}</td>
                      <td className="font-mono text-xs">{draft.formula_or_rule}</td>
                      <td>{draft.source_features.join(", ")}</td>
                      <td>{draft.output_datatype}</td>
                      <td><span className="font-semibold text-emerald-700">Target excluded</span></td>
                      <td>{saved?.creation_status ?? "Draft"}</td>
                      <td>{saved?.materialization_status?.replace(/_/g, " ") ?? "Not saved"}</td>
                      <td><button type="button" className="atlas-icon-button" title={`Remove ${draft.feature_name}`} onClick={() => void deleteDraft(draft)}><Trash2 size={15} /></button></td>
                    </tr>
                  );
                })}
                {!drafts.length ? <tr><td colSpan={9} className="py-8 text-center text-sm text-slate-500">No engineered features have been created. All transformations default to None.</td></tr> : null}
              </tbody>
            </table>
          </div>
        </AtlasWorkflowSection>

        <AtlasWorkflowSection eyebrow="Deterministic feature builder" title="Create an Engineered Predictor" description="Choose one transformation type. ATLAS validates names, lineage, source availability, and target exclusion before saving." tone="neutral">
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
            {builderOptions.map((option) => {
              const Icon = option.icon;
              const selected = builderType === option.id;
              return <button key={option.id} type="button" className={selected ? "rounded-lg border border-blue-600 bg-blue-50 p-3 text-left" : "rounded-lg border border-slate-200 bg-white p-3 text-left hover:border-blue-300"} onClick={() => { setBuilderType(option.id); setForm({}); }}><Icon size={17} className={selected ? "text-blue-700" : "text-slate-500"} /><div className="mt-2 text-sm font-semibold text-slate-950">{option.label}</div><div className="mt-1 text-xs text-slate-500">{option.description}</div></button>;
            })}
          </div>
          <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
            <BuilderForm type={builderType} form={form} update={updateField} allNames={availableNames} numericNames={numericNames} categoricalNames={categoricalOriginals.map((feature) => feature.feature_name)} />
            <div className="mt-4 flex justify-end"><button type="button" className="atlas-primary-button" onClick={addFeature}><Plus size={15} /> Add to transformation plan</button></div>
          </div>
        </AtlasWorkflowSection>

        <AtlasWorkflowSection eyebrow="Training-only preprocessing" title="Pipeline Transformations" description="Learned transformations are fitted on training data only. They do not appear as created predictor rows." tone="neutral">
          <div className="grid gap-4 lg:grid-cols-2">
            <SelectField label="Numeric scaling" value={pipelineValue("scaler")} onChange={(value) => updatePipeline("scaler", value)} options={["None", "StandardScaler", "MinMaxScaler"]} helper="Use None for tree-only modeling. Scaling is fitted after the validation split." />
            <SelectField label="Categorical encoding" value={pipelineValue("encoding")} onChange={(value) => updatePipeline("encoding", value)} options={["None", "OneHotEncoder"]} helper="Encoding is fitted on training categories with unknown-level handling." />
          </div>
        </AtlasWorkflowSection>

        <AtlasWorkflowSection eyebrow="Execution" title="Preview and Materialization" description="Preview returns bounded rows for inspection. Materialization executes deterministic features across the backend working dataset." tone="info">
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 text-xs font-semibold text-slate-700">
              Preview rows
              <select className="atlas-input w-24" value={previewRowLimit} onChange={(event) => setPreviewRowLimit(Number(event.target.value))} disabled={previewing}>
                {PREVIEW_ROW_LIMITS.map((limit) => <option key={limit} value={limit}>{limit}</option>)}
              </select>
            </label>
            <button type="button" className="atlas-secondary-button" onClick={() => void runPreview()} disabled={previewing || !drafts.length}>{previewing ? <LoaderCircle size={15} className="animate-spin" /> : <Eye size={15} />} Preview first {previewRowLimit} rows</button>
            <button type="button" className="atlas-secondary-button" onClick={() => void savePlan()} disabled={saving || !dirty}>{saving ? <LoaderCircle size={15} className="animate-spin" /> : <Save size={15} />} Save manifest</button>
            <button type="button" className="atlas-primary-button" onClick={() => void materialize()} disabled={materializing || dirty || !manifest}>{materializing ? <LoaderCircle size={15} className="animate-spin" /> : <Settings2 size={15} />} Materialize full dataset</button>
            {materializing ? <AtlasExecutionStatus state="running" label="Materializing features" detail="Backend execution is in progress." /> : planReady ? <AtlasExecutionStatus state="complete" label="Feature set current" detail="Materialized predictors match the saved manifest." /> : <AtlasExecutionStatus state="idle" label="Materialization required" detail="Save and execute the current plan." />}
          </div>
          {preview ? <FeaturePreviewTable preview={preview} /> : null}
        </AtlasWorkflowSection>

        <details className="atlas-workflow-section">
          <summary className="flex cursor-pointer list-none items-center justify-between"><span><span className="block text-sm font-semibold text-slate-950">Predictor Redundancy Check</span><span className="mt-1 block text-xs text-slate-600">VIF is intentionally lazy and never runs during page render.</span></span><ChevronDown size={17} /></summary>
          <div className="mt-4 border-t border-slate-200 pt-4">
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" className="atlas-secondary-button" onClick={() => void runVif()} disabled={vifLoading || vifSaving || dirty}>{vifLoading ? <LoaderCircle size={15} className="animate-spin" /> : <GitCompareArrows size={15} />} Run VIF diagnostics</button>
              {vifRows ? <button type="button" className="atlas-secondary-button" onClick={() => void excludeHighVifFeatures()} disabled={vifLoading || vifSaving}>{vifSaving ? <LoaderCircle size={15} className="animate-spin" /> : <Settings2 size={15} />} Uncheck VIF &gt;= {VIF_AUTO_EXCLUDE_THRESHOLD}</button> : null}
            </div>
            <p className="mt-2 text-xs leading-5 text-slate-600">VIF values at or above {VIF_AUTO_EXCLUDE_THRESHOLD} indicate severe multicollinearity. Exclusions are saved to the Feature Manifest and flow into Final Predictor Review and Model Training.</p>
            {vifRows ? <div className="mt-3 overflow-auto rounded-lg border border-slate-200"><table className="atlas-table"><thead><tr><th>Use in model</th><th>Feature</th><th>VIF</th><th>Status</th></tr></thead><tbody>{vifRows.map((row) => <tr key={row.feature}><td><label className="inline-flex items-center gap-2 text-xs font-semibold text-slate-700"><input type="checkbox" checked={selectedByFeature.get(row.feature) ?? true} onChange={(event) => void persistVifSelection({ [row.feature]: event.target.checked })} disabled={vifSaving} /> Use</label></td><td>{row.feature}</td><td>{typeof row.vif === "number" && Number.isFinite(row.vif) ? row.vif.toFixed(3) : "Not available"}</td><td>{row.status}</td></tr>)}</tbody></table></div> : null}
          </div>
        </details>
      </div>
    </StepShell>
  );
}

function makeDraft(name: string, origin: FeatureOrigin, sources: string[], formula: string, output: string, config: Record<string, any>): FeatureDraft {
  return {
    feature_name: name,
    display_name: name,
    origin,
    source_features: sources,
    transformation_type: origin,
    formula_or_rule: formula,
    output_datatype: output,
    config,
    selected: true,
    exclusion_reason: "",
    user_rationale: "",
  };
}

function BuilderForm({ type, form, update, allNames, numericNames, categoricalNames }: { type: BuilderType; form: Record<string, string>; update: (name: string, value: string) => void; allNames: string[]; numericNames: string[]; categoricalNames: string[] }) {
  const field = (name: string) => form[name] ?? "";
  const sources = type === "categorical_rule" || type === "date-derived" ? allNames : numericNames;
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      <TextField label="New feature name" value={field("name")} onChange={(value) => update("name", value)} placeholder="e.g. amount_x_velocity" />
      {type === "interaction" || type === "arithmetic" ? <><SelectField label="Left source" value={field("left")} onChange={(value) => update("left", value)} options={numericNames} placeholder="Select predictor" /><SelectField label="Right source" value={field("right")} onChange={(value) => update("right", value)} options={numericNames} placeholder="Select predictor" /></> : <SelectField label="Source predictor" value={field("source")} onChange={(value) => update("source", value)} options={sources} placeholder="Select predictor" />}
      {type === "numeric_bin" ? <><TextField label="Cut points" value={field("cutPoints")} onChange={(value) => update("cutPoints", value)} placeholder="100, 500, 1000" /><TextField label="Labels" value={field("labels")} onChange={(value) => update("labels", value)} placeholder="Low, Medium, High, Very High" /><TextField label="Missing label" value={field("missingLabel")} onChange={(value) => update("missingLabel", value)} placeholder="Missing" /></> : null}
      {type === "categorical_rule" ? <><SelectField label="Operator" value={field("operator") || "equals"} onChange={(value) => update("operator", value)} options={["equals", "contains", "greater_than", "less_than", "is_missing"]} /><TextField label="Rule value" value={field("value")} onChange={(value) => update("value", value)} /><TextField label="Matched label" value={field("thenLabel")} onChange={(value) => update("thenLabel", value)} placeholder="Matched" /><TextField label="Else label" value={field("elseLabel")} onChange={(value) => update("elseLabel", value)} placeholder="Other" /></> : null}
      {type === "polynomial" ? <SelectField label="Degree" value={field("degree") || "2"} onChange={(value) => update("degree", value)} options={["2", "3"]} /> : null}
      {type === "arithmetic" ? <SelectField label="Operation" value={field("operation") || "add"} onChange={(value) => update("operation", value)} options={["add", "subtract", "multiply", "divide"]} /> : null}
      {type === "date-derived" ? <SelectField label="Date component" value={field("component") || "year"} onChange={(value) => update("component", value)} options={["year", "month", "quarter", "day_of_week"]} /> : null}
      {type === "categorical_rule" && !categoricalNames.length ? <div className="text-xs text-amber-800">No categorical source was inferred. Numeric fields remain available for threshold rules.</div> : null}
    </div>
  );
}

function FeaturePreviewTable({ preview }: { preview: FeaturePreview }) {
  return (
    <div className="mt-4">
      <div className="mb-2 flex items-center justify-between"><div className="text-sm font-semibold text-slate-950">Bounded feature preview</div><AtlasDataScopeBadge scope="rendered_sample" rows={preview.preview_row_count} /></div>
      <div className="max-h-80 overflow-auto rounded-lg border border-slate-200"><table className="atlas-table min-w-[760px]"><thead><tr>{preview.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{preview.rows.map((row, index) => <tr key={index}>{preview.columns.map((column) => <td key={column}>{String(row[column] ?? "")}</td>)}</tr>)}</tbody></table></div>
      <p className="mt-2 text-xs text-slate-600">The preview renders {preview.preview_row_count.toLocaleString()} rows. Full-data execution occurs only through Materialize full dataset.</p>
    </div>
  );
}

function StatusMetric({ label, value, warning = false }: { label: string; value: string | number; warning?: boolean }) {
  return <div className={`rounded-lg border px-3 py-2.5 ${warning ? "border-amber-300 bg-amber-50" : "border-slate-200 bg-white"}`}><div className="text-[10px] font-semibold uppercase text-slate-500">{label}</div><div className="mt-1 text-sm font-semibold capitalize text-slate-950">{value}</div></div>;
}

function TextField({ label, value, onChange, placeholder = "" }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string }) {
  return <label><span className="atlas-label">{label}</span><input className="atlas-input mt-1" value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /></label>;
}

function SelectField({ label, value, onChange, options, helper, placeholder }: { label: string; value: string; onChange: (value: string) => void; options: string[]; helper?: string; placeholder?: string }) {
  return <label><span className="atlas-label">{label}</span><select className="atlas-input mt-1" value={value} onChange={(event) => onChange(event.target.value)}>{placeholder ? <option value="">{placeholder}</option> : null}{options.map((option) => <option key={option} value={option}>{option}</option>)}</select>{helper ? <span className="mt-1 block text-xs text-slate-500">{helper}</span> : null}</label>;
}

function originLabel(origin: FeatureOrigin) {
  return origin.split(/[-_]/).map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`).join(" ");
}
