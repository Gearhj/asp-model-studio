import { BASE } from "./api";

export type ExperimentalFactor = {
  factorId: string;
  name: string;
  kind: "categorical" | "continuous" | "ordinal";
  levels: string[];
  unit: string;
  controllable: boolean;
};

export type NuisanceFactor = {
  nuisanceId: string;
  name: string;
  strategy: string;
  levels: string[];
};

export type StudyContract = {
  schemaVersion: string;
  studyId: string;
  projectId: string;
  title: string;
  dataStrategy: {
    mode: "prospective" | "existing" | "hybrid" | string;
    capturePlan: string;
    provenanceNotes: string;
  };
  objective: {
    businessObjective: string;
    decision: string;
    population: string;
    unitOfRandomization: string;
    primaryResponse: { name: string; type: string; direction: string; unit: string };
    secondaryResponses: string[];
    nullHypothesis: string;
    alternativeHypothesis: string;
    successCriterion: string;
  };
  factors: ExperimentalFactor[];
  nuisanceFactors: NuisanceFactor[];
  blocking: { enabled: boolean; variables: string[]; rationale: string };
  design: {
    family: string;
    analystConfirmed: boolean;
    replicates: number;
    centerPoints: number;
    fraction: string;
    resolution: string;
    rationale: string;
  };
  power: {
    alpha: number;
    targetPower: number;
    minimumDetectableEffect: number;
    standardDeviation: number;
    baselineRate: number;
    responseKind: string;
    effectsTested: number;
  };
  randomization: { seed: number; restricted: boolean; restriction: string };
  datasetBindings: Array<{
    datasetId: string;
    versionId: string;
    datasetRole: string;
    name?: string;
    rowCount?: number;
    columnCount?: number;
    hash?: string | null;
    boundAt?: string;
  }>;
  assumptions: string[];
  limitations: string[];
  analysisPlan: { model: string; includeInteractions: boolean; multipleTesting: string };
};

export type StudyBlocker = { code: string; step: string; message: string };
export type StudyArtifactMap = {
  power?: PowerResult;
  design?: DesignResult;
  randomization?: RandomizationResult;
  simulation?: SimulationJob;
  analysis?: AnalysisResult;
  documentation?: DocumentationResult;
};

export type Study = {
  studyId: string;
  projectId: string;
  currentVersion: number;
  status: string;
  contractHash?: string;
  contract: StudyContract;
  artifacts: StudyArtifactMap;
  blockers: StudyBlocker[];
  updatedAt?: string;
};

export type PowerResult = {
  perCell: number;
  treatmentCells: number;
  totalSample: number;
  achievedPower: number;
  curve: Array<{ perCell: number; total: number; power: number }>;
  assumptions: Record<string, unknown>;
  warning: string;
};

export type DesignRow = Record<string, string | number | Record<string, number>>;
export type DesignResult = {
  designVersion: string;
  family: string;
  runCount: number;
  factorNames: string[];
  rows: DesignRow[];
  aliasStructure: Array<{ effect: string; aliasedWith: string; definingRelation: string }>;
  estimability: Record<string, string>;
};

export type RandomizationResult = {
  randomizationVersion: string;
  designVersion: string;
  seed: number;
  method: string;
  rows: DesignRow[];
};

export type SimulationJob = {
  simulationJobId: string;
  projectId: string;
  studyId: string;
  studyVersion: number;
  designVersion: string;
  status: string;
  progress: number;
  seed: number;
  iterations: number;
  results: {
    empiricalPower?: number;
    wrongDirectionRate?: number;
    falseNegativeRate?: number;
    meanEstimatedEffect?: number;
    standardError?: number;
    estimateSample?: number[];
    warning?: string;
  };
  error?: { message?: string; recoverable?: boolean };
};

export type AnalysisResult = {
  status: string;
  observationCount: number;
  cellCount: number;
  anovaTable: Array<Record<string, string | number | null>>;
  effects: Array<{ term: string; estimate: number; kind: string }>;
  residualDiagnostics: {
    mean: number;
    standardDeviation: number;
    shapiroP?: number | null;
    points: Array<{ fitted: number; residual: number }>;
  };
  recommendation: { bestObservedCell: string; meanResponse: number; basis: string };
  warnings: string[];
};

export type DocumentationResult = {
  packageId: string;
  status: string;
  readinessScore: number;
  sections: Array<{ title: string; status: string }>;
  generatedAt: string;
};

type StudyResponse = {
  ok: true;
  persisted: boolean;
  study: Study;
  versions: Array<{ versionNumber: number; contractHash: string; changeSummary?: string; createdAt?: string }>;
  jobs: SimulationJob[];
};

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    credentials: "same-origin",
    ...init,
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(init.headers || {}),
    },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(String(body?.detail || body?.error || `${response.status} ${response.statusText}`));
  }
  return body as T;
}

export const getExperimentalStudy = (projectId: string) =>
  request<StudyResponse>(`/experimental-design/study?project_id=${encodeURIComponent(projectId)}`);

export const saveExperimentalStudy = (projectId: string, contract: StudyContract, changeSummary: string) =>
  request<{ ok: true; changed: boolean; study: Study; invalidatedArtifacts?: string[] }>(
    `/experimental-design/study/${encodeURIComponent(projectId)}`,
    { method: "PUT", body: JSON.stringify({ contract, changeSummary }) },
  );

export const recommendExperimentalDesign = (projectId: string, contract: StudyContract) =>
  request<{
    recommendation: string | null;
    rationale: string;
    analystDecisionRequired: boolean;
    warning: string;
    catalog: Array<{
      family: string;
      label: string;
      eligible: boolean;
      estimatedRuns?: number | null;
      strength: string;
      tradeoff: string;
    }>;
  }>("/experimental-design/recommend", { method: "POST", body: JSON.stringify({ projectId, contract }) });

export const calculateExperimentalPower = (projectId: string) =>
  request<PowerResult & { study: Study }>("/experimental-design/power", {
    method: "POST",
    body: JSON.stringify({ projectId }),
  });

export const generateExperimentalDesign = (projectId: string) =>
  request<DesignResult & { study: Study }>("/experimental-design/design/generate", {
    method: "POST",
    body: JSON.stringify({ projectId }),
  });

export const randomizeExperimentalDesign = (projectId: string, seed: number) =>
  request<RandomizationResult & { study: Study }>("/experimental-design/randomize", {
    method: "POST",
    body: JSON.stringify({ projectId, seed }),
  });

export const createExperimentalSimulation = (
  projectId: string,
  parameters: { iterations: number; seed: number; samplePerCell?: number },
) =>
  request<{ ok: true; job: SimulationJob }>("/experimental-design/simulations", {
    method: "POST",
    body: JSON.stringify({ projectId, ...parameters }),
  });

export const getExperimentalSimulation = (projectId: string, jobId: string) =>
  request<{ ok: true; job: SimulationJob }>(
    `/experimental-design/simulations/${encodeURIComponent(jobId)}?project_id=${encodeURIComponent(projectId)}`,
  );

export const cancelExperimentalSimulation = (projectId: string, jobId: string) =>
  request<{ ok: true; job: SimulationJob }>(`/experimental-design/simulations/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
    body: JSON.stringify({ projectId }),
  });

export const retryExperimentalSimulation = (projectId: string, jobId: string) =>
  request<{ ok: true; job: SimulationJob }>(`/experimental-design/simulations/${encodeURIComponent(jobId)}/retry`, {
    method: "POST",
    body: JSON.stringify({ projectId }),
  });

export const analyzeExperimentalObservations = (
  projectId: string,
  observations: Array<{ runId: string; response: number }>,
) =>
  request<AnalysisResult & { study: Study }>("/experimental-design/analyze", {
    method: "POST",
    body: JSON.stringify({ projectId, observations }),
  });

export const captureExperimentalDocumentation = (projectId: string) =>
  request<{ ok: true; documentation: DocumentationResult }>("/experimental-design/documentation/capture", {
    method: "POST",
    body: JSON.stringify({ projectId }),
  });
