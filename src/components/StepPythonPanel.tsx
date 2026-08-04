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
  buildConfirmedDataAcquisitionCodeContext,
  buildDataAcquisitionMetadataContext,
  buildDataAcquisitionPythonContext,
  buildDataAcquisitionSasContext,
  fetchDataAcquisitionReproducibilityContext,
  isCurrentDataAcquisitionReproducibilityContext,
  REPRODUCIBILITY_CONTEXT_CONFIRMED_EVENT,
  REPRODUCIBILITY_CONTEXT_PENDING_EVENT,
  reproducibilityContextPendingMessage,
  type CurrentDataAcquisitionReproducibilityContext,
  type DataAcquisitionReproducibilityContext,
} from "../lib/dataAcquisitionReproducibility";
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
import {
  normalizeWorkflowRoute,
  projectWorkflowNavigationPath,
  scopedProjectIdForPathname,
} from "../lib/projectScopedRoutes";

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

function downloadGeneratedContext(fileName: string, value: string) {
  if (!value) return;
  const href = URL.createObjectURL(
    new Blob([value], { type: "text/plain;charset=utf-8" }),
  );
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = fileName;
  anchor.click();
  URL.revokeObjectURL(href);
}

function combinedGeneratedCode(sections: NotebookSection[]) {
  return sections.map((section) => `# ${section.title}\n${section.code}`).join("\n\n");
}

function generatedPythonForRoute(
  route: string,
  sections: NotebookSection[],
  projectId: string,
) {
  // Data Acquisition is generated only from the exact backend response below.
  // Returning an empty string here prevents a browser-derived fallback.
  if (route === "/step01") return "";
  void projectId;
  return combinedGeneratedCode(sections);
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
 * Returns a SAS-safe variable reference. Ordinary V7 identifiers remain
 * readable; every other governed column name becomes a quoted name literal so
 * punctuation, quotes, macro triggers, and statement delimiters stay data.
 */
function sasColumnReference(value: string) {
  const normalized = String(value ?? "");
  if (/^[A-Za-z_][A-Za-z0-9_]{0,31}$/.test(normalized)) return normalized;
  return `'${normalized.replace(/'/g, "''")}'n`;
}

/**
 * Part H: under SAS-compatible execution only statements the compatibility
 * engine actually supports are generated, so the starter program cannot be
 * guaranteed to fail. Physical data-access statements are outside the subset
 * and must be configured through an approved external access mechanism.
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
  const numericCandidates = (dataset?.selected_columns ?? [])
    .filter((column) => column !== target)
    .slice(0, 12);
  lines.push(
    `proc means data=work.${table} n nmiss mean std min median max;`,
    numericCandidates.length
      ? `    var ${numericCandidates.map(sasColumnReference).join(" ")};`
      : "",
    "run;",
    "",
    ...(numericCandidates.length
      ? [
          `proc freq data=work.${table};`,
          `    tables ${numericCandidates.slice(0, 3).map(sasColumnReference).join(" ")} / missing;`,
          "run;",
          "",
        ]
      : []),
    "/* Target-directed summaries are withheld until the backend verifies the exact development population and excludes the sealed holdout. */",
  );
  void route;
  return lines.filter((line) => line !== "").join("\n") + "\n";
}

function generatedSasForRoute(route: string) {
  const dataset = loadLocalDataset();
  const table = sasDatasetName();
  // Data Acquisition is generated only from the exact backend response below.
  // Other pages may inspect the actual work table supplied by their execution
  // context, but this function never fabricates a physical data connection.
  if (route === "/step01") return "";
  const verification = `proc contents data=work.${table}; run;\nproc means data=work.${table} n mean std min median max; run;`;
  if (route === "/step02") {
    const predictors = (dataset?.selected_columns ?? [])
      .filter((column) => column !== dataset?.target)
      .slice(0, 32)
      .map(sasColumnReference);
    const predictorMeans = predictors.length
      ? `proc means data=work.${table} n nmiss mean std min median max; var ${predictors.join(" ")}; run;`
      : `proc contents data=work.${table}; run;`;
    return `/* Structural EDA only. Target-directed analysis requires exact verified development membership; no full-population target fallback is permitted. */\nproc contents data=work.${table}; run;\n${predictorMeans}`;
  }
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
  const workflowRoute = normalizeWorkflowRoute(location.pathname);
  const { readiness, retry: retryIdentity } = usePredictiveIdentity();
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const projectType = useWorkflowStore((state) => state.projectType);
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
  const [reproducibilityContext, setReproducibilityContext] =
    useState<DataAcquisitionReproducibilityContext | null>(null);
  const [reproducibilityContextPhase, setReproducibilityContextPhase] =
    useState<"idle" | "loading" | "pending" | "current" | "error">("idle");
  const [reproducibilityContextError, setReproducibilityContextError] =
    useState("");
  const [reproducibilityContextExplicitlyPending, setReproducibilityContextExplicitlyPending] =
    useState(false);
  // CODE-DATAACQ-001: capability comes from the backend, never from a hard-coded
  // badge. Until it resolves the panel reports "Checking runtime", not "Executable".
  const [pythonCapability, setPythonCapability] = useState<PythonCapability | null>(null);

  const supportsRoute = notebookRouteSupported(workflowRoute);
  const predictiveProject =
    String(projectType || "").trim().toLowerCase().replaceAll("_", "-") ===
    "predictive-modeling";
  const sectionResolution = useMemo(() => {
    if (!supportsRoute || !expanded || readiness.status !== "ready") {
      return { sections: [] as NotebookSection[], error: "" };
    }
    try {
      return {
        sections: getNotebookSectionsForRoute(workflowRoute),
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
    workflowRoute,
    readiness.identity?.dataset_id,
    readiness.identity?.dataset_version_id,
    readiness.status,
    supportsRoute,
  ]);
  const sections = sectionResolution.sections;

  const sectionKey = sections[0]?.sectionKey ?? "";
  const currentReproducibilityContext:
    | CurrentDataAcquisitionReproducibilityContext
    | null =
    reproducibilityContext &&
    isCurrentDataAcquisitionReproducibilityContext(reproducibilityContext)
      ? reproducibilityContext
      : null;
  const generatedPython = workflowRoute === "/step01"
    ? currentReproducibilityContext
      ? buildDataAcquisitionPythonContext(currentReproducibilityContext)
      : ""
    : generatedPythonForRoute(workflowRoute, sections, projectId);
  const generatedSas = workflowRoute === "/step01"
    ? currentReproducibilityContext
      ? buildDataAcquisitionSasContext(currentReproducibilityContext)
      : ""
    : sasMode === "compatible"
      ? generatedSasCompatibleProgram(workflowRoute)
      : generatedSasForRoute(workflowRoute);
  const generatedMetadata = currentReproducibilityContext
    ? buildDataAcquisitionMetadataContext(currentReproducibilityContext)
    : "";
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
  const pythonCodeContext = currentReproducibilityContext
    ? buildConfirmedDataAcquisitionCodeContext(
        currentReproducibilityContext,
        "python",
        workflowRoute,
      )
    : buildCurrentCodeContext({
        workflowPage: workflowRoute,
        language: "python",
        projectId,
        dataset: activeDataset,
      });
  const sasCodeContext = currentReproducibilityContext
    ? buildConfirmedDataAcquisitionCodeContext(
        currentReproducibilityContext,
        "sas",
        workflowRoute,
      )
    : buildCurrentCodeContext({
        workflowPage: workflowRoute,
        language: "sas",
        projectId,
        dataset: activeDataset,
      });
  const draftLoadOptions = (language: CodeContextLanguage, legacyCode?: string) => ({
    scope: {
      projectId,
      workflowPage: workflowRoute,
      language,
    },
    legacyStorageKey: language === "python" ? USER_STEP_PYTHON_CODE_KEY : USER_STEP_SAS_CODE_KEY,
    legacySectionKey: sectionKey,
    legacyCode,
  });

  useEffect(() => {
    const refreshContext = () =>
      setDatasetContextRevision((revision) => revision + 1);
    const markPending = () => {
      setReproducibilityContextExplicitlyPending(true);
      setReproducibilityContext(null);
      setReproducibilityContextPhase("pending");
      setReproducibilityContextError("");
    };
    const refreshConfirmed = () => {
      setReproducibilityContextExplicitlyPending(false);
      refreshContext();
    };
    window.addEventListener("atlas-dataset-updated", refreshContext);
    window.addEventListener("atlas-eda-code-context-updated", refreshContext);
    window.addEventListener(REPRODUCIBILITY_CONTEXT_PENDING_EVENT, markPending);
    window.addEventListener(REPRODUCIBILITY_CONTEXT_CONFIRMED_EVENT, refreshConfirmed);
    return () => {
      window.removeEventListener("atlas-dataset-updated", refreshContext);
      window.removeEventListener("atlas-eda-code-context-updated", refreshContext);
      window.removeEventListener(REPRODUCIBILITY_CONTEXT_PENDING_EVENT, markPending);
      window.removeEventListener(REPRODUCIBILITY_CONTEXT_CONFIRMED_EVENT, refreshConfirmed);
    };
  }, []);

  useEffect(() => {
    if (!predictiveProject) {
      setReproducibilityContext(null);
      setReproducibilityContextPhase("idle");
      setReproducibilityContextError("");
      setReproducibilityContextExplicitlyPending(false);
      return;
    }
    if (
      !expanded ||
      readiness.status !== "ready" ||
      !projectId ||
      reproducibilityContextExplicitlyPending
    ) {
      return;
    }
    const controller = new AbortController();
    setReproducibilityContext(null);
    setReproducibilityContextPhase("loading");
    setReproducibilityContextError("");
    fetchDataAcquisitionReproducibilityContext(projectId, controller.signal)
      .then((context) => {
        if (controller.signal.aborted) return;
        setReproducibilityContext(context);
        setReproducibilityContextPhase(
          context.state === "current" ? "current" : "pending",
        );
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setReproducibilityContext(null);
        setReproducibilityContextPhase("error");
        setReproducibilityContextError(
          error instanceof Error
            ? error.message
            : "The exact reproducibility context could not be verified.",
        );
      });
    return () => controller.abort();
  }, [
    datasetContextRevision,
    expanded,
    projectId,
    predictiveProject,
    readiness.status,
    reproducibilityContextExplicitlyPending,
    workflowRoute,
  ]);

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
    setSasDraft(
      sasLoaded.draft?.code ||
        (workflowRoute === "/step01" ? "" : generatedSasForRoute(workflowRoute)),
    );
    setContextMessages({});
    // Scope changes are the only time the working draft should be replaced.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, sectionKey, sections, workflowRoute]);

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
  const exactDataAcquisitionContextReady = predictiveProject
    ? Boolean(currentReproducibilityContext)
    : Boolean(String(projectType || "").trim());
  const exactContextStatusMessage = (() => {
    if (currentReproducibilityContext) {
      return `Exact backend context ${currentReproducibilityContext.context_id} is current.`;
    }
    if (reproducibilityContextError) return reproducibilityContextError;
    if (reproducibilityContext?.state && reproducibilityContext.state !== "current") {
      return reproducibilityContextPendingMessage(reproducibilityContext.state);
    }
    if (reproducibilityContextPhase === "loading") {
      return "Verifying the exact dataset, target authorization, and Analysis Partition...";
    }
    return "Generated code is withheld until the backend confirms the exact current context.";
  })();

  const persist = (language: CodeContextLanguage) => {
    if (!exactDataAcquisitionContextReady) {
      setContextMessage(language, exactContextStatusMessage);
      return false;
    }
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
    if (!exactDataAcquisitionContextReady) {
      setContextMessage(language, exactContextStatusMessage);
      return;
    }
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
    if (!exactDataAcquisitionContextReady) {
      setContextMessage(language, exactContextStatusMessage);
      return;
    }
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
        target: currentReproducibilityContext?.target_contract.target,
        eventValue: currentReproducibilityContext?.target_contract.event_value,
        nonEventValue: currentReproducibilityContext?.target_contract.non_event_value,
        targetContractId:
          currentReproducibilityContext?.target_contract.target_contract_id,
        analysisPartitionId:
          currentReproducibilityContext?.analysis_partition.analysis_partition_id,
        analysisPartitionRevision:
          currentReproducibilityContext?.analysis_partition.revision,
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
  const context = currentReproducibilityContext
    ? {
        previewRows: [],
        datasetName: currentReproducibilityContext.identity.dataset_name,
        datasetId: currentReproducibilityContext.identity.dataset_id,
        versionId: currentReproducibilityContext.identity.dataset_version_id,
        target: currentReproducibilityContext.target_contract.target,
        selectedFeatures:
          currentReproducibilityContext.predictor_authorization
            .authorized_predictors,
        targetContractId:
          currentReproducibilityContext.target_contract.target_contract_id,
        analysisPartitionId:
          currentReproducibilityContext.analysis_partition.analysis_partition_id,
        analysisPartitionRevision:
          currentReproducibilityContext.analysis_partition.revision,
        eventValue: currentReproducibilityContext.target_contract.event_value,
        nonEventValue: currentReproducibilityContext.target_contract.non_event_value,
      }
    : predictiveProject
      ? {
          previewRows: [],
          datasetName: "",
          datasetId: "",
          versionId: "",
          target: "",
          selectedFeatures: [],
        }
      : {
          previewRows: activeDataset?.rows.slice(0, 500) ?? [],
          datasetName: sasDatasetName(),
          datasetId: activeDatasetIdentity?.dataset_id ?? "",
          versionId: activeDatasetIdentity?.dataset_version_id ?? "",
          target: activeDataset?.target ?? "",
          selectedFeatures: activeDataset?.selected_columns ?? [],
        };

  const notebookStudioPath = currentReproducibilityContext
    ? `/notebook-studio?${new URLSearchParams({
        projectId: currentReproducibilityContext.project_id,
        datasetId: currentReproducibilityContext.identity.dataset_id,
        versionId: currentReproducibilityContext.identity.dataset_version_id,
        target: currentReproducibilityContext.target_contract.target,
        eventValue:
          JSON.stringify(currentReproducibilityContext.target_contract.event_value) ?? "",
        nonEventValue:
          JSON.stringify(currentReproducibilityContext.target_contract.non_event_value) ?? "",
        targetContractId:
          currentReproducibilityContext.target_contract.target_contract_id,
        analysisPartitionId:
          currentReproducibilityContext.analysis_partition.analysis_partition_id,
        analysisPartitionRevision: String(
          currentReproducibilityContext.analysis_partition.revision,
        ),
      }).toString()}`
    : "/notebook-studio";

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
            <span className="block text-sm font-semibold text-slate-950">{workflowRoute === "/step01" ? "Data Access & Reproducibility Code" : "Code & Reproducibility"}</span>
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
            <Link
              to={projectWorkflowNavigationPath({
                targetPath: "/step01",
                routeProjectId: scopedProjectIdForPathname(location.pathname),
                projectId,
                projectName,
                projectType: useWorkflowStore.getState().projectType,
              })}
              className="atlas-primary-button"
            >
              Open Data Acquisition
            </Link>
            <button type="button" className="atlas-secondary-button" onClick={retryIdentity}>Retry identity verification</button>
          </div>
        </div>
      ) : expanded ? (
        <div className="border-t border-slate-200 p-4">
          {workflowRoute === "/step01" ? (
            <div
              className={`mb-4 rounded-xl border p-3 text-sm ${currentReproducibilityContext ? "border-emerald-200 bg-emerald-50 text-emerald-950" : reproducibilityContextPhase === "error" ? "border-rose-200 bg-rose-50 text-rose-950" : "border-amber-200 bg-amber-50 text-amber-950"}`}
              data-testid="data-acquisition-reproducibility-status"
              data-context-state={reproducibilityContext?.state ?? reproducibilityContextPhase}
              role="status"
            >
              <div className="font-semibold">
                {currentReproducibilityContext
                  ? "Backend-confirmed reproducibility context"
                  : "Reproducibility context pending"}
              </div>
              <p className="mt-1 leading-6">{exactContextStatusMessage}</p>
              <p className="mt-1 text-xs">
                No local data path is assumed. Final-holdout rows and values are never exposed here.
              </p>
              {currentReproducibilityContext ? (
                <Link
                  className="atlas-secondary-button mt-3 inline-flex"
                  to={notebookStudioPath}
                >
                  Open in Notebook Studio
                </Link>
              ) : null}
            </div>
          ) : (
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
          )}
          <CodeWorkspacePanel
            languages={[
              {
                language: "python",
                label: "Python",
                supportBadge: workflowRoute === "/step01"
                  ? currentReproducibilityContext
                    ? "Exact current"
                    : "Pending"
                  : pythonBadge,
                generatedCode: generatedPython,
                userCode: pythonDraft,
                setUserCode: setPythonDraft,
                note: workflowRoute === "/step01"
                  ? `${exactContextStatusMessage} This is a metadata-only context block; it does not load either population.${contextMessages.python ? ` ${contextMessages.python}` : ""}`
                  : pythonRunnable
                    ? `Runtime objects available: df (authorized dataset version${activeDatasetIdentity?.dataset_version_id ? ` ${activeDatasetIdentity.dataset_version_id}` : ""}), TARGET (selected target column), SELECTED_FEATURES (approved predictor list).${contextMessages.python ? ` ${contextMessages.python}` : ""}`
                    : `${pythonCapability?.reason ?? "Checking whether the governed code sandbox is available for this ATLAS environment."}${contextMessages.python ? ` ${contextMessages.python}` : ""}`,
                runLabel: "Run Python",
                canRun: workflowRoute !== "/step01" && exactDataAcquisitionContextReady && pythonRunnable && Boolean(pythonDraft.trim()) && pythonContextEvaluation.canUseAsCurrent,
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
                onDownload: workflowRoute === "/step01" && currentReproducibilityContext
                  ? () => downloadGeneratedContext("atlas-data-acquisition-context.py", generatedPython)
                  : undefined,
                downloadLabel: "Download .py",
                onSave: () => persist("python"),
                canSave: exactDataAcquisitionContextReady && pythonContextEvaluation.canUseAsCurrent,
                saveLabel: "Save Python Draft",
                contextSafety: contextSafety("python", pythonContextEvaluation),
              },
              {
                language: "sas",
                label: "SAS",
                supportBadge: workflowRoute === "/step01"
                  ? currentReproducibilityContext
                    ? "Exact current"
                    : "Pending"
                  : sasStatus(sasDiagnostics, sasMode),
                generatedCode: generatedSas,
                userCode: sasDraft,
                setUserCode: setSasDraft,
                note: workflowRoute === "/step01"
                  ? `${exactContextStatusMessage} SAS values are safely quoted metadata only; no physical data connection is assumed.${contextMessages.sas ? ` ${contextMessages.sas}` : ""}`
                  : `${sasMode === "compatible" ? "Runs only the supported local compatibility subset and lists unsupported statements." : sasMode === "saspy" ? "Runs explicit SAS code through the configured and tested SASPy session." : "Editable and exportable. Execution is disabled in this mode."}${contextMessages.sas ? ` ${contextMessages.sas}` : ""}`,
                runLabel: sasMode === "compatible" ? "Run SAS-Compatible" : "Run SAS",
                canRun: workflowRoute !== "/step01" && exactDataAcquisitionContextReady && Boolean(sasDraft.trim()) && (sasMode === "compatible" || (sasMode === "saspy" && Boolean(sasDiagnostics?.sasExecutionAvailable))) && sasContextEvaluation.canUseAsCurrent,
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
                onDownload: workflowRoute === "/step01" && currentReproducibilityContext
                  ? () => downloadGeneratedContext("atlas-data-acquisition-context.sas", generatedSas)
                  : undefined,
                downloadLabel: "Download .sas",
                onSave: () => persist("sas"),
                canSave: exactDataAcquisitionContextReady && sasContextEvaluation.canUseAsCurrent,
                saveLabel: "Save SAS Draft",
                contextSafety: contextSafety("sas", sasContextEvaluation),
              },
              ...(workflowRoute === "/step01"
                ? [
                    {
                      language: "metadata" as const,
                      label: "Metadata",
                      supportBadge: currentReproducibilityContext ? "Exact current" : "Pending",
                      generatedCode: generatedMetadata,
                      userCode: "",
                      setUserCode: () => undefined,
                      note: `${exactContextStatusMessage} This view contains identifiers and protected population counts only.`,
                      runLabel: "",
                      canRun: false,
                      onCopy: () =>
                        void navigator.clipboard?.writeText(generatedMetadata),
                      onDownload: currentReproducibilityContext
                        ? () => downloadGeneratedContext("atlas-data-acquisition-context.json", generatedMetadata)
                        : undefined,
                      downloadLabel: "Download .json",
                      readOnlyGenerated: true,
                    },
                  ]
                : []),
            ]}
          />
        </div>
      ) : null}
    </section>
  );
}
