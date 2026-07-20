import { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { Code2 } from "lucide-react";
import { CodeWorkspacePanel } from "./code/CodeWorkspacePanel";
import {
  fetchSasDiagnostics,
  runUserPython,
  runUserSas,
  runUserSasCompatible,
  type CodeRunResult,
  type SasDiagnostics,
} from "../lib/codeExecution";
import { logDecision } from "../lib/decisionJournal";
import { loadDataAccessMetadata } from "../lib/enterpriseDataAccess";
import { loadLocalDataset } from "../lib/localDataset";
import {
  getNotebookSections,
  USER_STEP_PYTHON_CODE_KEY,
  USER_STEP_SAS_CODE_KEY,
  type NotebookSection,
} from "../lib/notebookExport";
import { useWorkflowStore } from "../state/useWorkflowStore";

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

function sectionsForRoute(route: string) {
  return getNotebookSections().filter((section) => section.routes.includes(route));
}

function combinedGeneratedCode(sections: NotebookSection[]) {
  return sections.map((section) => `# ${section.title}\n${section.code}`).join("\n\n");
}

function generatedPythonForRoute(route: string, sections: NotebookSection[]) {
  if (route !== "/step01") return combinedGeneratedCode(sections);

  const metadata = loadDataAccessMetadata();
  const dataset = loadLocalDataset();
  const target = dataset?.target ?? "";
  const selectedFeatures = (dataset?.selected_columns ?? dataset?.headers.filter((column) => column !== target) ?? [])
    .filter((column) => column !== target);
  let accessCode = metadata?.generatedPython || combinedGeneratedCode(sections);

  if (dataset?.dataset_library) {
    const library = dataset.dataset_library;
    accessCode = `import pandas as pd
from pathlib import Path

# Governed ATLAS Dataset Library asset.
DATASET_ID = ${JSON.stringify(library.datasetId)}
DATASET_VERSION = ${JSON.stringify(library.versionId)}
DATASET_NAME = ${JSON.stringify(library.datasetName)}

# Export or mount the confirmed Dataset Library version in the governed runtime.
path = Path("path/to/dataset-library-export.csv")
df = pd.read_csv(path)`;
  }

  return `${accessCode}

TARGET = ${JSON.stringify(target)}
SELECTED_FEATURES = ${JSON.stringify(selectedFeatures)}

if TARGET:
    if TARGET not in df.columns:
        raise KeyError(f"Target column {TARGET!r} is not present in the loaded dataset.")
    missing_features = [column for column in SELECTED_FEATURES if column not in df.columns]
    if missing_features:
        raise KeyError(f"Selected features are missing from the loaded dataset: {missing_features}")
    modeling_df = df[SELECTED_FEATURES + [TARGET]].copy()
else:
    modeling_df = df.copy()

print("Registered rows:", len(df))
print("Modeling columns:", len(modeling_df.columns))
print("Target:", TARGET or "Not selected")`;
}

function combinedSavedCode(sections: NotebookSection[], saved: Record<string, string>) {
  return sections.map((section) => saved[section.sectionKey] ?? "").filter(Boolean).join("\n\n");
}

function sasDatasetName() {
  const dataset = loadLocalDataset();
  const sourceName = dataset?.dataset_library?.datasetName || loadDataAccessMetadata()?.fileName || "atlas_modeling_data";
  return sourceName.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9_]+/g, "_").replace(/^([^A-Za-z_])/, "atlas_$1").slice(0, 28) || "atlas_modeling_data";
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
  const sections = useMemo(() => sectionsForRoute(location.pathname), [location.pathname]);
  const projectId = useWorkflowStore((state) => state.projectId);
  const currentStepId = useWorkflowStore((state) => state.currentStepId);
  const [expanded, setExpanded] = useState(false);
  const [pythonCodeByStep, setPythonCodeByStep] = useState(() => readCode(USER_STEP_PYTHON_CODE_KEY));
  const [sasCodeByStep, setSasCodeByStep] = useState(() => readCode(USER_STEP_SAS_CODE_KEY));
  const [pythonDraft, setPythonDraft] = useState("");
  const [sasDraft, setSasDraft] = useState("");
  const [pythonResult, setPythonResult] = useState<CodeRunResult | null>(null);
  const [sasResult, setSasResult] = useState<CodeRunResult | null>(null);
  const [pythonRunning, setPythonRunning] = useState(false);
  const [sasRunning, setSasRunning] = useState(false);
  const [sasDiagnostics, setSasDiagnostics] = useState<SasDiagnostics | null>(null);
  const [sasMode, setSasMode] = useState<SasRunMode>("template");

  useEffect(() => {
    const pythonSaved = readCode(USER_STEP_PYTHON_CODE_KEY);
    const sasSaved = readCode(USER_STEP_SAS_CODE_KEY);
    setPythonCodeByStep(pythonSaved);
    setSasCodeByStep(sasSaved);
    setPythonDraft(combinedSavedCode(sections, pythonSaved));
    setSasDraft(combinedSavedCode(sections, sasSaved) || generatedSasForRoute(location.pathname));
  }, [location.pathname, sections]);

  useEffect(() => {
    if (!expanded) return;
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
  }, [expanded]);

  if (!sections.length) return null;
  const sectionKey = sections[0].sectionKey;
  const generatedPython = generatedPythonForRoute(location.pathname, sections);
  const generatedSas = generatedSasForRoute(location.pathname);
  const pageTitle = sections.map((section) => section.title).join(" / ");
  const persist = (language: "python" | "sas") => {
    const key = language === "python" ? USER_STEP_PYTHON_CODE_KEY : USER_STEP_SAS_CODE_KEY;
    const current = language === "python" ? pythonCodeByStep : sasCodeByStep;
    const draft = language === "python" ? pythonDraft : sasDraft;
    const next = { ...current, [sectionKey]: draft };
    writeCode(key, next);
    if (language === "python") setPythonCodeByStep(next);
    else setSasCodeByStep(next);
    logDecision({
      workflowStep: pageTitle,
      actionType: language === "python" ? "custom_python_code_edited" : "custom_sas_code_edited",
      subject: `Step-level ${language === "python" ? "Python" : "SAS"} code`,
      previousValue: `${String(current[sectionKey] ?? "").length} characters`,
      newValue: `${draft.length} characters`,
      followStatus: "not_applicable",
    });
  };

  const context = {
    previewRows: loadLocalDataset()?.rows.slice(0, 500) ?? [],
    datasetName: sasDatasetName(),
    target: loadLocalDataset()?.target,
  };

  return (
    <section className="atlas-card overflow-hidden p-0">
      <button type="button" className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left" onClick={() => setExpanded((value) => !value)}>
        <span className="flex items-center gap-2">
          <Code2 size={17} className="text-slate-700" />
          <span>
            <span className="block text-sm font-semibold text-slate-950">{location.pathname === "/step01" ? "Data Access & Reproducibility Code" : "Code & Reproducibility"}</span>
            <span className="block text-xs text-slate-500">Review generated code, add governed custom code, execute supported languages, and preserve the code in notebook and evidence exports.</span>
          </span>
        </span>
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">{expanded ? "Hide" : "Show"}</span>
      </button>
      {expanded && (
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
                supportBadge: "Executable",
                generatedCode: generatedPython,
                userCode: pythonDraft,
                setUserCode: setPythonDraft,
                note: "Generated and user-edited Python execute through the governed local Python runtime.",
                runLabel: "Run Python",
                canRun: Boolean(pythonDraft.trim()),
                running: pythonRunning,
                result: pythonResult,
                onRun: async () => {
                  persist("python");
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
              },
              {
                language: "sas",
                label: "SAS",
                supportBadge: sasStatus(sasDiagnostics, sasMode),
                generatedCode: generatedSas,
                userCode: sasDraft,
                setUserCode: setSasDraft,
                note: sasMode === "compatible" ? "Runs only the supported local compatibility subset and lists unsupported statements." : sasMode === "saspy" ? "Runs explicit SAS code through the configured and tested SASPy session." : "Editable and exportable. Execution is disabled in this mode.",
                runLabel: sasMode === "compatible" ? "Run SAS-Compatible" : "Run SAS",
                canRun: Boolean(sasDraft.trim()) && (sasMode === "compatible" || (sasMode === "saspy" && Boolean(sasDiagnostics?.sasExecutionAvailable))),
                running: sasRunning,
                result: sasResult,
                onRun: async () => {
                  persist("sas");
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
              },
            ]}
          />
        </div>
      )}
    </section>
  );
}
