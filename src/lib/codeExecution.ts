import { DATASET_API_BASE } from "./datasetLibrary";
import { runAnalyticsPreviewSql, type AnalyticsSqlRunResult } from "./analyticsWorkbench";

export type CodeLanguage = "python" | "sql" | "r" | "sas";

export type PythonExecutionResult = {
  ok: boolean;
  stdout: string;
  stderr: string;
  runtimeMs: number;
  status?: string;
  returnCode?: number;
  diagnostics?: PythonDiagnostics;
};

export type PythonDiagnostics = {
  pythonExecutable: string;
  pythonVersion: string;
  platform: string;
  cwd: string;
  runtimeRoot: string;
  runtimeRootExists: boolean;
  canStartPython: boolean;
  canImportSite: boolean;
  canImportPandas: boolean;
  canWriteTempFile: boolean;
  canCaptureStdout: boolean;
  canCaptureStderr: boolean;
  rscriptDetected: boolean;
  rscriptPath: string;
  rVersion: string;
  rExecutionAvailable: boolean;
  saspyInstalled: boolean;
  saspyVersion?: string;
  saspyModulePath?: string;
  sasConfigurationFound: boolean;
  sasConfigFound?: boolean;
  sasExecutionMode?: SasExecutionMode;
  sasActiveCfgName?: string;
  sasActiveCfgFile?: string;
  sasCanStartSession?: boolean;
  sasLastError?: string;
  sasDetectedConfigFiles?: string[];
  sasDetectedConfigNames?: string[];
  sasSetupGuidance?: string[];
  sasExecutionAvailable: boolean;
  sasCompatibleAvailable?: boolean;
  sasCompatibleSupportedProcs?: string[];
  environmentWarnings: string[];
};

export type SasExecutionMode = "template_only" | "saspy_config" | "external_export";

export type SasRuntimeSettings = {
  cfgname: string;
  cfgfile: string;
  executionMode: SasExecutionMode;
  updatedAt?: string;
  updatedBy?: string;
  lastConnectionOk?: boolean;
  lastConnectionTestedAt?: string;
  lastConnectionError?: string;
};

export type SasDiagnostics = {
  ok?: boolean;
  saspyInstalled: boolean;
  saspyVersion?: string;
  saspyModulePath?: string;
  detectedConfigFiles: string[];
  detectedConfigNames: string[];
  activeCfgName?: string;
  activeCfgFile?: string;
  sasConfigFound: boolean;
  sasConfigurationFound: boolean;
  sasCanStartSession: boolean;
  sasExecutionAvailable: boolean;
  sasCompatibleAvailable?: boolean;
  sasCompatibleSupportedProcs?: string[];
  connectionMethod?: string;
  sasExecutionMode: SasExecutionMode;
  lastConnectionTest?: string;
  lastError?: string;
  setupGuidance: string[];
  settings?: SasRuntimeSettings;
};

export type CodeRunResult = PythonExecutionResult | AnalyticsSqlRunResult | {
  ok: boolean;
  status: "template" | "unavailable" | "error" | "success" | "partial";
  stdout: string;
  stderr: string;
  runtimeMs: number;
  returnCode?: number;
  log?: string;
  listing?: string;
  diagnostics?: Record<string, unknown>;
  tables?: Array<{ title: string; columns: string[]; rows: Array<Record<string, unknown>> }>;
  charts?: Array<{ title: string; chartType: string; data: Array<Record<string, unknown>> }>;
  translatedPython?: string;
  unsupportedStatements?: string[];
};

/** Authoritative Python execution capability, as reported by the backend.
 *  CODE-DATAACQ-001: the UI must never assert "Executable" on its own. */
export type PythonCapabilityState = "executable" | "not_configured" | "misconfigured" | "disabled";

export type PythonCapability = {
  state: PythonCapabilityState;
  available: boolean;
  reason: string;
  /** Admin/diagnostics only; absent for ordinary users. */
  detail?: string;
  configurationKey?: string;
  approvedInterpreters?: string[];
};

export async function fetchPythonCapability(): Promise<PythonCapability> {
  const response = await fetch(`${DATASET_API_BASE}/python/capability`, { credentials: "include" });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload) {
    return {
      state: "not_configured",
      available: false,
      reason: "Python execution capability could not be determined for this ATLAS environment.",
    };
  }
  return payload as PythonCapability;
}

export async function fetchPythonDiagnostics(): Promise<PythonDiagnostics> {
  const response = await fetch(`${DATASET_API_BASE}/python/diagnostics`, { credentials: "include" });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload) throw new Error(payload?.detail ?? payload?.error ?? "Python diagnostics are unavailable.");
  return payload as PythonDiagnostics;
}

export async function runUserPython(input: {
  code: string;
  projectId?: string;
  workflowStep?: string;
  context?: Record<string, unknown>;
}): Promise<PythonExecutionResult> {
  const response = await fetch(`${DATASET_API_BASE}/python/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({
      page: "Analytics Workbench",
      userCode: input.code,
      projectId: input.projectId ?? "",
      workflowStep: input.workflowStep ?? "analytics",
      context: input.context ?? {},
    }),
  });
  const payload = await response.json().catch(() => null);
  if (!payload) {
    return { ok: false, status: "unavailable", stdout: "", stderr: `Python execution failed with HTTP ${response.status}.`, runtimeMs: 0 };
  }
  if (!response.ok) {
    return { ok: false, status: "error", stdout: payload.stdout ?? "", stderr: payload.detail ?? payload.error ?? "Python execution failed.", runtimeMs: payload.runtimeMs ?? 0 };
  }
  return payload as PythonExecutionResult;
}

export async function runUserR(input: { code: string; context?: Record<string, unknown> }): Promise<CodeRunResult> {
  return runGenericCode("/code/r/run", input);
}

export async function runUserSas(input: { code: string; context?: Record<string, unknown> }): Promise<CodeRunResult> {
  return runGenericCode("/code/sas/run", input);
}

export async function runUserSasCompatible(input: { code: string; context?: Record<string, unknown> }): Promise<CodeRunResult> {
  return runGenericCode("/code/sas-compatible/run", input);
}

export async function cleanupQuestion(input: { text: string; context?: Record<string, unknown> }): Promise<{ ok?: boolean; cleanedText: string; source: "llm" | "deterministic"; message: string }> {
  const response = await fetch(`${DATASET_API_BASE}/llm/cleanup-question`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({
      text: input.text,
      context: input.context ?? {},
    }),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload) throw new Error(payload?.detail ?? payload?.message ?? "ATLAS question cleanup is unavailable.");
  return payload;
}

export async function fetchSasDiagnostics(): Promise<SasDiagnostics> {
  const response = await fetch(`${DATASET_API_BASE}/code/sas/diagnostics`, { credentials: "include" });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload) throw new Error(payload?.detail ?? payload?.error ?? "SAS diagnostics are unavailable.");
  return payload as SasDiagnostics;
}

export async function saveSasRuntimeSettings(input: { cfgname: string; cfgfile: string; executionMode: SasExecutionMode }): Promise<{ ok: boolean; settings?: SasRuntimeSettings; diagnostics?: SasDiagnostics; detail?: string }> {
  const response = await fetch(`${DATASET_API_BASE}/code/sas/settings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(input),
  });
  const payload = await response.json().catch(() => null);
  if (!payload) return { ok: false, detail: `SAS settings save failed with HTTP ${response.status}.` };
  return payload;
}

export async function testSasConnection(): Promise<CodeRunResult> {
  const response = await fetch(`${DATASET_API_BASE}/code/sas/test-connection`, {
    method: "POST",
    credentials: "include",
  });
  const payload = await response.json().catch(() => null);
  if (!payload) {
    return { ok: false, status: "error", stdout: "", stderr: `SAS connection test failed with HTTP ${response.status}.`, runtimeMs: 0 };
  }
  return payload as CodeRunResult;
}

async function runGenericCode(path: string, input: { code: string; context?: Record<string, unknown> }): Promise<CodeRunResult> {
  const response = await fetch(`${DATASET_API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({
      code: input.code,
      context: input.context ?? {},
    }),
  });
  const payload = await response.json().catch(() => null);
  if (!payload) {
    return { ok: false, status: "error", stdout: "", stderr: `Code execution failed with HTTP ${response.status}.`, runtimeMs: 0 };
  }
  return payload as CodeRunResult;
}

export { runAnalyticsPreviewSql };
