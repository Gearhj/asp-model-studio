import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Code2 } from "lucide-react";
import { CodeWorkspacePanel } from "./code/CodeWorkspacePanel";
import {
  fetchPythonCapability,
  fetchSasDiagnostics,
  runUserPython,
  type PythonCapability,
  runUserSas,
  runUserSasCompatible,
  type CodeRunResult,
  type SasDiagnostics,
} from "../lib/codeExecution";
import { logDecision } from "../lib/decisionJournal";
import { loadDataAccessMetadata } from "../lib/enterpriseDataAccess";
import { loadLocalDataset } from "../lib/localDataset";
import {
  DatasetIdentityError,
  requireLocalDatasetCanonicalIdentity,
} from "../lib/datasetIdentity";
import {
  acknowledgeCodeDraftContext,
  buildCurrentCodeContext,
  codeContextSummary,
  evaluateCodeDraftContext,
  loadCodeDraft,
  persistCodeDraft,
  resetCodeDraftForCurrentContext,
  retainHistoricalCodeDraft,
  type CodeContextEvaluation,
  type CodeContextLanguage,
  type CodeDraftEnvelope,
} from "../lib/codeContextSafety";
import {
  getNotebookSectionsForRoute,
  notebookRouteSupported,
  USER_STEP_PYTHON_CODE_KEY,
  USER_STEP_SAS_CODE_KEY,
  type NotebookSection,
} from "../lib/notebookExport";
import { createCodeCell, createNotebookCell, saveNotebook } from "../lib/notebookStudio";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { usePredictiveIdentity } from "./PredictiveIdentityProvider";

type SasRunMode = "saspy" | "compatible" | "template" | "external";

function readCode(key: string) {
  try {
    const parsed = JSON.parse(localStorage.getItem(key) || "{}");
    return parsed && typeof parsed === "object" ? (parsed as Record<string, string>) : {};
  } catch {
    return {};
  }
}

function writeCode(key: string, value: Record<string, string>) {
  localStorage.setItem(key, JSON.stringify(value));
  window.dispatchEvent(new CustomEvent("step-code-updated"));
}

function combinedGeneratedCode(sections: NotebookSection[]) {
  return sections.map((section) => `# ${section.title}\n${section.code}`).join("\n\n");
}

function generatedPythonForRoute(
  route: string,
  sections: NotebookSection[],
  projectId: string,
) {
  if (route !== "/step01") return combinedGeneratedCode(sections);

  const metadata = loadDataAccessMetadata();
  const dataset = loadLocalDataset();
  const target = dataset?.target ?? "";
  const selectedFeatures = (dataset?.selected_columns ?? dataset?.headers.filter((column) => column !== target) ?? [])
    .filter((column) => column !== target);
  let accessCode = metadata?.generatedPython || combinedGeneratedCode(sections);

  // CODE-DATAACQ-002: a registered Dataset Library version is bound by the
  // governed runtime, which provides df/TARGET/SELECTED_FEATURES directly. The
  // generated code therefore carries no dataset path at all -- the previous
  // placeholder export path could never resolve and would fail once execution
  // was enabled.
  let canonicalIdentity:
    | ReturnType<typeof requireLocalDatasetCanonicalIdentity>
    | null = null;
  try {
    canonicalIdentity = requireLocalDatasetCanonicalIdentity(
      projectId,
      dataset,
      "Generated code dataset identity",
    );
  } catch {
    canonicalIdentity = null;
  }
  if (dataset?.dataset_library && canonicalIdentity) {
    const library = dataset.dataset_library;
    return `# ATLAS provides df from the authorized project dataset and version.
# Runtime objects: df, TARGET, SELECTED_FEATURES, ATLAS_DATASET_PATH
# Dataset: ${library.datasetName} (${canonicalIdentity.dataset_id})
# Version: ${canonicalIdentity.dataset_version_id}

print("Dataset shape:", df.shape)
print("Target:", TARGET or "Not selected")
print("Selected predictors:", len(SELECTED_FEATURES))`;
  }

  return `${accessCode}

# ATLAS provides df, TARGET, and SELECTED_FEATURES at runtime.
if TARGET:
    if TARGET not in df.columns:
        raise KeyError(f"Target column {TARGET!r} is not present in the loaded dataset.")
    missing_features = [column for column in SELECTED_FEATURES if column not in df.columns]
    if missing_features:
        raise KeyError(f"Selected features are missing from the loaded dataset: {missing_features}")
    modeling_df = df[SELECTED_FEATURES + [TARGET]].copy()
else:
    modeling_df = df.copy()

print("Rows available to this runtime:", len(df))
print("Modeling columns:", len(modeling_df.columns))
print("Target:", TARGET or "Not selected")`;
}

function combinedSavedCode(sections: NotebookSection[], saved: Record<string, string>) {
  return sections.map((section) => saved[section.sectionKey] ?? "").filter(Boolean).join("\n\n");
}

/**
 * The one authoritative SAS table identity for the active dataset.
 *
 * CODE-DATAACQ-003: this must be derived from the active registered dataset, and
 * must match what the backend registers in the SAS-compatible work library. The
 * backend lowercases via its own `_safe_name`, and table lookup is
 * case-insensitive, so `work.CLASS_TRAIN` and `work.class_train` both resolve to
 * the same table. Never a stale regression-era default.
 */
function sasDatasetName() {
  const dataset = loadLocalDataset();
  const sourceName = dataset?.dataset_library?.datasetName || loadDataAccessMetadata()?.fileName || "atlas_modeling_data";
  return sourceName.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9_]+/g, "_").replace(/^([^A-Za-z_])/, "atlas_$1").slice(0, 28) || "atlas_modeling_data";
}

/**
 * Part H: under SAS-compatible execution only statements the compatibility
 * engine actually supports are generated, so the starter program cannot be
 * guaranteed to fail. Data-access statements (PROC IMPORT, LIBNAME, SET) are
 * outside the subset and belong to the export-oriented templates.
 */
function generatedSasCompatibleProgram(route: string) {
  const dataset = loadLocalDataset();
  const table = sasDatasetName();
  const target = dataset?.target || "";
  const lines = [
    `proc contents data=work.${table} varnum;`,
    "run;",
    "",
  ];
  if (target) {
    lines.push(`proc freq data=work.${table};`, `    tables ${target} / missing;`, "run;", "");
  }
  const numericCandidates = (dataset?.selected_columns ?? [])
    .filter((column) => column !== target)
    .slice(0, 12);
  lines.push(
    `proc means data=work.${table} n nmiss mean std min median max;`,
    numericCandidates.length ? `    var ${numericCandidates.join(" ")};` : "",
    "run;",
  );
  return lines.filter((line) => line !== "").join("\n") + (route === "/step01" ? "\n" : "\n");
}

function generatedSasForRoute(route: string) {
  const metadata = loadDataAccessMetadata();
  const dataset = loadLocalDataset();
  const table = sasDatasetName();
  const fileName = metadata?.fileName || dataset?.dataset_library?.datasetName || "path/to/modeling_data.csv";
  let access = "";
  if (metadata?.sourceType === "sql") {
    access = `/* Supply credentials through the configured SAS environment. */\nlibname source ODBC dsn=\"GOVERNED_DSN\";\nproc sql;\n  create table work.${table} as\n  ${metadata.sqlQuery || "select * from source.governed_table"}\n  ;\nquit;`;
  } else if (metadata?.sourceType === "existing") {
    access = `/* Replace the library reference with the registered Dataset Library location. */\ndata work.${table};\n  set atlas.${table};\nrun;`;
  } else if (metadata?.sourceType === "cloud") {
    access = `/* Configure cloud credentials outside this program. */\nfilename source temp;\n/* Download the governed object ${String(metadata.cloudPath || "cloud://path/to/data").replace(/\*\//g, "")} into the SOURCE fileref using the approved SAS access method. */\nproc import datafile=source out=work.${table} dbms=csv replace; guessingrows=max; run;`;
  } else if (metadata?.sourceType === "python") {
    access = `/* Python loader sources require a governed interchange artifact before SAS execution. */\ndata work.${table};\n  set atlas.governed_interchange;\nrun;`;
  } else if (/\.sas7bdat$/i.test(fileName)) {
    access = `libname source \"path/to/sas/library\";\ndata work.${table};\n  set source.${table};\nrun;`;
  } else {
    access = `proc import datafile=\"${fileName.replace(/"/g, "") }\"\n  out=work.${table}\n  dbms=csv replace;\n  guessingrows=max;\nrun;`;
  }
  const verification = `proc contents data=work.${table}; run;\nproc means data=work.${table} n mean std min median max; run;`;
  if (route === "/step01") return `${access}\n\n${verification}`;
  if (route === "/step02") return `proc contents data=work.${table}; run;\nproc means data=work.${table} n mean std min median max; run;\nproc freq data=work.${table}; tables ${dataset?.target || "target"}; run;`;
  if (route === "/step06") return `/* Reproduce final split-readiness checks for the governed feature list. */\n${verification}`;
  if (route === "/step07") return `/* Exportable training handoff. Model fitting remains governed by the ATLAS training service. */\n${verification}`;
  return `/* ${route} reproducibility program */\n${verification}`;
}

function sasStatus(diagnostics: SasDiagnostics | null, mode: SasRunMode) {
  if (mode === "compatible") return "ATLAS SAS-Compatible Local Execution";
  if (mode === "external") return "External SAS Export";
  if (mode === "template") return "Template Only";
  if (diagnostics?.sasCanStartSession && diagnostics?.sasExecutionAvailable) return "SASPy Connected";
  if (diagnostics?.saspyInstalled && diagnostics?.sasConfigFound) return "SASPy Installed, Connection Not Tested";
  if (diagnostics?.saspyInstalled) return "SASPy Configuration Missing";
  return "Template Only";
}

export default function StepPythonPanel() {
  const location = useLocation();
  const { readiness, retry: retryIdentity } = usePredictiveIdentity();
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const currentStepId = useWorkflowStore((state) => state.currentStepId);
  const [expanded, setExpanded] = useState(false);
  const [pythonCodeByStep, setPythonCodeByStep] = useState(() => readCode(USER_STEP_PYTHON_CODE_KEY));
  const [sasCodeByStep, setSasCodeByStep] = useState(() => readCode(USER_STEP_SAS_CODE_KEY));
  const [pythonDraft, setPythonDraft] = useState("");
  const [sasDraft, setSasDraft] = useState("");
  const [pythonDraftEnvelope, setPythonDraftEnvelope] = useState<CodeDraftEnvelope | null>(null);
  const [sasDraftEnvelope, setSasDraftEnvelope] = useState<CodeDraftEnvelope | null>(null);
  const [contextMessages, setContextMessages] = useState<Partial<Record<CodeContextLanguage, string>>>({});
  const [copyingLanguage, setCopyingLanguage] = useState<CodeContextLanguage | null>(null);
  const [pythonResult, setPythonResult] = useState<CodeRunResult | null>(null);
  const [sasResult, setSasResult] = useState<CodeRunResult | null>(null);
  const [pythonRunning, setPythonRunning] = useState(false);
  const [sasRunning, setSasRunning] = useState(false);
  const [sasDiagnostics, setSasDiagnostics] = useState<SasDiagnostics | null>(null);
  const [sasMode, setSasMode] = useState<SasRunMode>("template");
  const [datasetContextRevision, setDatasetContextRevision] = useState(0);
  // CODE-DATAACQ-001: capability comes from the backend, never from a hard-coded
  // badge. Until it resolves the panel reports "Checking runtime", not "Executable".
  const [pythonCapability, setPythonCapability] = useState<PythonCapability | null>(null);

  const supportsRoute = notebookRouteSupported(location.pathname);
  const sectionResolution = useMemo(() => {
    if (!supportsRoute || !expanded || readiness.status !== "ready") {
      return { sections: [] as NotebookSection[], error: "" };
    }
    try {
      return {
        sections: getNotebookSectionsForRoute(location.pathname),
        error: "",
      };
    } catch (error) {
      if (error instanceof DatasetIdentityError) {
        return {
          sections: [] as NotebookSection[],
          error: "The governed notebook cannot be constructed until the exact dataset identity is restored.",
        };
      }
      throw error;
    }
  }, [
    datasetContextRevision,
    expanded,
    location.pathname,
    readiness.identity?.dataset_id,
    readiness.identity?.dataset_version_id,
    readiness.status,
    supportsRoute,
  ]);
  const sections = sectionResolution.sections;

  const sectionKey = sections[0]?.sectionKey ?? "";
  const generatedPython = generatedPythonForRoute(
    location.pathname,
    sections,
    projectId,
  );
  const generatedSas =
    sasMode === "compatible" ? generatedSasCompatibleProgram(location.pathname) : generatedSasForRoute(location.pathname);
  const pageTitle = sections.map((section) => section.title).join(" / ");
  const activeDataset = useMemo(
    () => loadLocalDataset(),
    [datasetContextRevision, projectId],
  );
  const activeDatasetIdentity = useMemo(() => {
    try {
      return requireLocalDatasetCanonicalIdentity(
        projectId,
        activeDataset,
        "Code execution dataset identity",
      );
    } catch {
      return null;
    }
  }, [activeDataset, projectId]);
  const pythonCodeContext = buildCurrentCodeContext({
    workflowPage: location.pathname,
    language: "python",
    projectId,
    dataset: activeDataset,
  });
  const sasCodeContext = buildCurrentCodeContext({
    workflowPage: location.pathname,
    language: "sas",
    projectId,
    dataset: activeDataset,
  });
  const draftLoadOptions = (language: CodeContextLanguage, legacyCode?: string) => ({
    scope: {
      projectId,
      workflowPage: location.pathname,
      language,
    },
    legacyStorageKey: language === "python" ? USER_STEP_PYTHON_CODE_KEY : USER_STEP_SAS_CODE_KEY,
    legacySectionKey: sectionKey,
    legacyCode,
  });

  useEffect(() => {
    const refreshContext = () =>
      setDatasetContextRevision((revision) => revision + 1);
    window.addEventListener("atlas-dataset-updated", refreshContext);
    window.addEventListener("atlas-eda-code-context-updated", refreshContext);
    return () => {
      window.removeEventListener("atlas-dataset-updated", refreshContext);
      window.removeEventListener("atlas-eda-code-context-updated", refreshContext);
    };
  }, []);

  useEffect(() => {
    if (!sectionKey) return;
    const pythonSaved = readCode(USER_STEP_PYTHON_CODE_KEY);
    const sasSaved = readCode(USER_STEP_SAS_CODE_KEY);
    const pythonLoaded = loadCodeDraft(
      draftLoadOptions("python", combinedSavedCode(sections, pythonSaved)),
    );
    const sasLoaded = loadCodeDraft(
      draftLoadOptions("sas", combinedSavedCode(sections, sasSaved)),
    );
    setPythonCodeByStep(pythonSaved);
    setSasCodeByStep(sasSaved);
    setPythonDraftEnvelope(pythonLoaded.draft);
    setSasDraftEnvelope(sasLoaded.draft);
    setPythonDraft(pythonLoaded.draft?.code ?? "");
    setSasDraft(sasLoaded.draft?.code || generatedSasForRoute(location.pathname));
    setContextMessages({});
    // Scope changes are the only time the working draft should be replaced.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname, projectId, sectionKey, sections]);

  useEffect(() => {
    if (!expanded || readiness.status !== "ready") return;
    let alive = true;
    fetchPythonCapability()
      .then((capability) => alive && setPythonCapability(capability))
      .catch(() =>
        alive &&
        setPythonCapability({
          state: "not_configured",
          available: false,
          reason: "Python execution capability could not be determined for this ATLAS environment.",
        })
      );
    return () => {
      alive = false;
    };
  }, [expanded, readiness.status]);

  useEffect(() => {
    if (!expanded || readiness.status !== "ready") return;
    fetchSasDiagnostics()
      .then((diagnostics) => {
        setSasDiagnostics(diagnostics);
        if (diagnostics.sasCanStartSession && diagnostics.sasExecutionAvailable) setSasMode("saspy");
        else if (diagnostics.sasExecutionMode === "external_export") setSasMode("external");
        else setSasMode("template");
      })
      .catch(() => {
        setSasDiagnostics(null);
        setSasMode("template");
      });
  }, [expanded, readiness.status]);

  if (!supportsRoute) return null;
  const pythonContextEvaluation = evaluateCodeDraftContext(
    pythonDraftEnvelope,
    pythonCodeContext,
    pythonDraft,
  );
  const sasContextEvaluation = evaluateCodeDraftContext(sasDraftEnvelope, sasCodeContext, sasDraft);
  const setContextMessage = (language: CodeContextLanguage, message: string) =>
    setContextMessages((current) => ({ ...current, [language]: message }));

  const persist = (language: CodeContextLanguage) => {
    const key = language === "python" ? USER_STEP_PYTHON_CODE_KEY : USER_STEP_SAS_CODE_KEY;
    const current = language === "python" ? pythonCodeByStep : sasCodeByStep;
    const draft = language === "python" ? pythonDraft : sasDraft;
    const currentContext = language === "python" ? pythonCodeContext : sasCodeContext;
    const result = persistCodeDraft({
      ...draftLoadOptions(language, combinedSavedCode(sections, current)),
      currentContext,
      code: draft,
    });
    if (!result.ok) {
      setContextMessage(
        language,
        "Acknowledge the exact historical draft/current-context pair before saving or running this code.",
      );
      return false;
    }

    const next = { ...current, [sectionKey]: draft };
    // Keep the old raw map as a compatibility mirror only. Context-aware reads
    // always prefer the scoped envelope, and a different project sees a legacy,
    // unverified draft rather than having this code silently relabelled.
    writeCode(key, next);
    if (language === "python") {
      setPythonCodeByStep(next);
      setPythonDraftEnvelope(result.draft);
    } else {
      setSasCodeByStep(next);
      setSasDraftEnvelope(result.draft);
    }
    setContextMessage(language, `${language === "python" ? "Python" : "SAS"} draft saved with its code context.`);
    logDecision({
      workflowStep: pageTitle,
      actionType: language === "python" ? "custom_python_code_edited" : "custom_sas_code_edited",
      subject: `Step-level ${language === "python" ? "Python" : "SAS"} code`,
      previousValue: `${String(current[sectionKey] ?? "").length} characters`,
      newValue: `${draft.length} characters`,
      followStatus: "not_applicable",
    });
    return true;
  };

  const acknowledgeMismatch = (language: CodeContextLanguage) => {
    const current = language === "python" ? pythonCodeByStep : sasCodeByStep;
    const code = language === "python" ? pythonDraft : sasDraft;
    const currentContext = language === "python" ? pythonCodeContext : sasCodeContext;
    const acknowledged = acknowledgeCodeDraftContext({
      ...draftLoadOptions(language, combinedSavedCode(sections, current)),
      currentContext,
      code,
    });
    if (!acknowledged) return;
    if (language === "python") setPythonDraftEnvelope(acknowledged);
    else setSasDraftEnvelope(acknowledged);
    setContextMessage(
      language,
      "Mismatch acknowledged for this exact code and current context. Any edit will require acknowledgement again.",
    );
  };

  const keepHistorical = (language: CodeContextLanguage) => {
    const current = language === "python" ? pythonCodeByStep : sasCodeByStep;
    const code = language === "python" ? pythonDraft : sasDraft;
    const retained = retainHistoricalCodeDraft({
      ...draftLoadOptions(language, combinedSavedCode(sections, current)),
      code,
    });
    if (!retained) return;
    if (language === "python") setPythonDraftEnvelope(retained);
    else setSasDraftEnvelope(retained);
    setContextMessage(
      language,
      "Historical draft retained with its original context. It remains blocked from current execution and export.",
    );
  };

  const resetForCurrentContext = (language: CodeContextLanguage) => {
    const current = language === "python" ? pythonCodeByStep : sasCodeByStep;
    const historicalCode = language === "python" ? pythonDraft : sasDraft;
    const generatedCode = language === "python" ? generatedPython : generatedSas;
    const currentContext = language === "python" ? pythonCodeContext : sasCodeContext;
    const reset = resetCodeDraftForCurrentContext({
      ...draftLoadOptions(language, combinedSavedCode(sections, current)),
      currentContext,
      generatedCode,
      historicalCode,
    });
    if (language === "python") {
      setPythonDraftEnvelope(reset.draft);
      setPythonDraft(reset.draft.code);
      setPythonResult(null);
    } else {
      setSasDraftEnvelope(reset.draft);
      setSasDraft(reset.draft.code);
      setSasResult(null);
    }
    setContextMessage(
      language,
      reset.archivedDraft
        ? "Historical draft archived. A separate current-context draft now contains the generated code."
        : "A current-context draft now contains the generated code.",
    );
  };

  const saveHistoricalNotebookCopy = async (language: CodeContextLanguage) => {
    const envelope = language === "python" ? pythonDraftEnvelope : sasDraftEnvelope;
    const source = language === "python" ? pythonDraft : sasDraft;
    const currentContext = language === "python" ? pythonCodeContext : sasCodeContext;
    const evaluation = language === "python" ? pythonContextEvaluation : sasContextEvaluation;
    if (!envelope || !source.trim()) return;
    setCopyingLanguage(language);
    setContextMessage(language, "Saving a distinct, explicitly historical notebook copy...");
    try {
      const languageLabel = language === "python" ? "Python" : "SAS";
      const saved = await saveNotebook({
        name: `${pageTitle} — ${languageLabel} Historical Code Copy`,
        description:
          "A distinct copy of historical edited code. It is not current workflow evidence and does not replace the active draft.",
        projectId,
        projectName,
        primaryDatasetId: envelope.context?.datasetId || undefined,
        primaryVersionId: envelope.context?.datasetVersion || undefined,
        tags: ["historical-code-copy", "code-context", language],
        defaultCodeLanguage: language === "python" ? "python" : "sas_compatible",
        cells: [
          createNotebookCell(
            "markdown",
            `## Historical ${languageLabel} Code Copy

**${evaluation.warning || "Historical code context"}**

This notebook is a separate historical copy. It is not labelled as current workflow evidence.

### Draft context
${codeContextSummary(envelope.context).map((line) => `- ${line}`).join("\n")}

### Current context at copy time
${codeContextSummary(currentContext).map((line) => `- ${line}`).join("\n")}`,
          ),
          createCodeCell(language === "python" ? "python" : "sas_compatible", source),
        ],
      });
      setContextMessage(language, `Saved separate notebook copy “${saved.name}”.`);
    } catch (error) {
      setContextMessage(
        language,
        error instanceof Error ? error.message : "ATLAS could not save the separate notebook copy.",
      );
    } finally {
      setCopyingLanguage(null);
    }
  };

  const contextSafety = (
    language: CodeContextLanguage,
    evaluation: CodeContextEvaluation,
  ) =>
    evaluation.warning
      ? {
          warning: evaluation.warning,
          details: evaluation.details,
          acknowledged: evaluation.acknowledged,
          statusMessage: contextMessages[language],
          savingCopy: copyingLanguage === language,
          onKeepHistorical: () => keepHistorical(language),
          onResetForCurrentContext: () => resetForCurrentContext(language),
          onAcknowledge: () => acknowledgeMismatch(language),
          onSaveAsNotebookCopy: () => void saveHistoricalNotebookCopy(language),
        }
      : undefined;

  // The governed identity travels with every execution request so the backend can
  // resolve the exact authorized artifact rather than trusting a client path.
  const context = {
    previewRows: activeDataset?.rows.slice(0, 500) ?? [],
    datasetName: sasDatasetName(),
    datasetId: activeDatasetIdentity?.dataset_id ?? "",
    versionId: activeDatasetIdentity?.dataset_version_id ?? "",
    target: activeDataset?.target ?? "",
    selectedFeatures: activeDataset?.selected_columns ?? [],
  };

  const pythonBadge = !pythonCapability
    ? "Checking runtime"
    : pythonCapability.state === "executable"
      ? "Executable"
      : pythonCapability.state === "misconfigured"
        ? "Runtime misconfigured"
        : pythonCapability.state === "disabled"
          ? "Runtime disabled"
          : "Runtime not configured";
  const pythonRunnable = pythonCapability?.available === true;

  return (
    <section className="atlas-card overflow-hidden p-0">
      <button type="button" className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left" onClick={() => setExpanded((value) => !value)}>
        <span className="flex items-center gap-2">
          <Code2 size={17} className="text-slate-700" />
          <span>
            <span className="block text-sm font-semibold text-slate-950">{location.pathname === "/step01" ? "Data Access & Reproducibility Code" : "Code & Reproducibility"}</span>
            <span className="block text-xs text-slate-500">Review generated code, add governed custom code, and preserve context-checked drafts for execution and notebook export.</span>
          </span>
        </span>
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">{expanded ? "Hide" : "Show"}</span>
      </button>
      {expanded && (readiness.status !== "ready" || sectionResolution.error || sections.length === 0) ? (
        <div className="border-t border-amber-200 bg-amber-50 p-4 text-sm text-amber-950" data-testid="step-python-panel-identity-disabled">
          <div className="font-semibold">Governed code export is not available yet.</div>
          <p className="mt-1 leading-6">
            {sectionResolution.error || readiness.message || "Verify the active registered Dataset Library version before opening generated code."}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Link to="/step01" className="atlas-primary-button">Open Data Acquisition</Link>
            <button type="button" className="atlas-secondary-button" onClick={retryIdentity}>Retry identity verification</button>
          </div>
        </div>
      ) : expanded ? (
        <div className="border-t border-slate-200 p-4">
          <div className="mb-4 grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3 md:grid-cols-[minmax(0,1fr)_260px] md:items-end">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">SAS runtime status</div>
              <div className="mt-1 text-sm font-semibold text-slate-900">{sasStatus(sasDiagnostics, sasMode)}</div>
              <div className="mt-1 text-xs text-slate-600">Local compatibility supports a governed subset of SAS syntax and reports unsupported statements. It is not a SASPy session.</div>
            </div>
            <label className="grid gap-1 text-xs font-semibold text-slate-700">
              SAS execution mode
              <select className="atlas-input" value={sasMode} onChange={(event) => setSasMode(event.target.value as SasRunMode)}>
                <option value="saspy" disabled={!sasDiagnostics?.sasExecutionAvailable}>SASPy session</option>
                <option value="compatible">ATLAS SAS-compatible local execution</option>
                <option value="template">Template only</option>
                <option value="external">External SAS export</option>
              </select>
            </label>
          </div>
          <CodeWorkspacePanel
            languages={[
              {
                language: "python",
                label: "Python",
                supportBadge: pythonBadge,
                generatedCode: generatedPython,
                userCode: pythonDraft,
                setUserCode: setPythonDraft,
                note: pythonRunnable
                  ? `Runtime objects available: df (authorized dataset version${activeDatasetIdentity?.dataset_version_id ? ` ${activeDatasetIdentity.dataset_version_id}` : ""}), TARGET (selected target column), SELECTED_FEATURES (approved predictor list).${contextMessages.python ? ` ${contextMessages.python}` : ""}`
                  : `${pythonCapability?.reason ?? "Checking whether the governed code sandbox is available for this ATLAS environment."}${contextMessages.python ? ` ${contextMessages.python}` : ""}`,
                runLabel: "Run Python",
                canRun: pythonRunnable && Boolean(pythonDraft.trim()) && pythonContextEvaluation.canUseAsCurrent,
                running: pythonRunning,
                result: pythonResult,
                onRun: async () => {
                  if (!persist("python")) return;
                  setPythonRunning(true);
                  setPythonResult(null);
                  try {
                    setPythonResult(await runUserPython({ code: pythonDraft, projectId, workflowStep: currentStepId, context }));
                  } catch (error) {
                    setPythonResult({ ok: false, status: "unavailable", stdout: "", stderr: error instanceof Error ? error.message : "Python execution is unavailable.", runtimeMs: 0 });
                  } finally {
                    setPythonRunning(false);
                  }
                },
                onCopy: () => void navigator.clipboard?.writeText(pythonDraft || generatedPython),
                onSave: () => persist("python"),
                canSave: pythonContextEvaluation.canUseAsCurrent,
                saveLabel: "Save Python Draft",
                contextSafety: contextSafety("python", pythonContextEvaluation),
              },
              {
                language: "sas",
                label: "SAS",
                supportBadge: sasStatus(sasDiagnostics, sasMode),
                generatedCode: generatedSas,
                userCode: sasDraft,
                setUserCode: setSasDraft,
                note: `${sasMode === "compatible" ? "Runs only the supported local compatibility subset and lists unsupported statements." : sasMode === "saspy" ? "Runs explicit SAS code through the configured and tested SASPy session." : "Editable and exportable. Execution is disabled in this mode."}${contextMessages.sas ? ` ${contextMessages.sas}` : ""}`,
                runLabel: sasMode === "compatible" ? "Run SAS-Compatible" : "Run SAS",
                canRun: Boolean(sasDraft.trim()) && (sasMode === "compatible" || (sasMode === "saspy" && Boolean(sasDiagnostics?.sasExecutionAvailable))) && sasContextEvaluation.canUseAsCurrent,
                running: sasRunning,
                result: sasResult,
                onRun: async () => {
                  if (!persist("sas")) return;
                  setSasRunning(true);
                  setSasResult(null);
                  try {
                    setSasResult(sasMode === "compatible" ? await runUserSasCompatible({ code: sasDraft, context }) : await runUserSas({ code: sasDraft, context }));
                  } catch (error) {
                    setSasResult({ ok: false, status: "unavailable", stdout: "", stderr: error instanceof Error ? error.message : "SAS execution is unavailable.", runtimeMs: 0 });
                  } finally {
                    setSasRunning(false);
                  }
                },
                onCopy: () => void navigator.clipboard?.writeText(sasDraft || generatedSas),
                onSave: () => persist("sas"),
                canSave: sasContextEvaluation.canUseAsCurrent,
                saveLabel: "Save SAS Draft",
                contextSafety: contextSafety("sas", sasContextEvaluation),
              },
            ]}
          />
        </div>
      ) : null}
    </section>
  );
}
