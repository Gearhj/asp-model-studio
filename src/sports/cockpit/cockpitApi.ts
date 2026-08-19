// Cockpit API client + shared experiment-configuration store.
// All calls hit the real /api/cockpit backend; there is no mock path.
import { useCallback, useEffect, useState } from "react";
import { create } from "zustand";
import { getJSON, postJSON } from "../../lib/api";

// ---------------------------------------------------------------------------- types
export type ClassShare = { class: string; count: number; share: number };
export type Objective = {
  objective: string;
  predictionUnit: string;
  downstreamUse: string;
  classOrder: string[];
  targetColumn: string;
  targetDistribution: ClassShare[];
  totalRows: number;
  seasons: number[];
  champion: {
    modelId: string;
    family: string;
    featureCount: number;
    status: string;
    reference: { candidateId: string; val2024: Metric; frozen2025: Metric };
  };
  datasetAuthority: { featureView: string; manifestSha: string; registration: string };
  maturity: string;
};
export type Metric = { logLoss: number; brierScore: number; topLabelEce: number };
export type SeasonRow = { season: number; rows: number; games: number; batters: number | null; role: string };
export type PreviewSchemaRow = { name: string; type: string; role: string; missingPct: number; example: any };
export type DataPreview = {
  matrix: string; grain: string; totalRows: number; filteredRows: number; columns: number; seasons: number[];
  target: string; targetClassOrder: string[]; targetDistribution: ClassShare[];
  splitCounts: { season: number; role: string; rows: number }[];
  numericFeatureColumns: number; categoricalFeatureColumns: number; featureMissingPct: number;
  sample: string; limit: number; season: number | null; previewColumns: string[];
  rows: Record<string, any>[]; schema: PreviewSchemaRow[]; note: string;
};
export type SourceSeasonRow = { season: number; rows: number; role: string };
export type SourceEvidence = {
  registeredSeasons: number[]; priorOnlyHistory: number[]; modelingDevelopment: number[];
  validation: number; frozenFinal: number;
  registeredTotalRows: number; priorHistoryTotalRows: number; modelingTotalRows: number;
  perSeason: SourceSeasonRow[]; note: string;
};
export type Population = {
  perSeason: SeasonRow[];
  totalRows: number;
  waterfall: { stage: string; rows: number; kind: string }[];
  candidatePredictors: number;
  temporalPolicy: { development: number[]; validation: number; frozenFinal: number };
  sourceEvidence?: SourceEvidence;
  knownLimitations: string[];
};
export type FeatureIV = { perClass: Record<string, number>; maxIv: number; meanIv: number; maxIvClass: string | null };
export type FeatureProfileRow = {
  name: string; role: string; kind: string; nonNull: number; missing: number; missingPct: number;
  unique: number; min: number | null; max: number | null; mean: number | null; median: number | null;
  std: number | null; skew: number | null; percentiles: Record<string, number>; outlierCount: number;
  outlierPct: number; iqrBounds: { lower: number; upper: number } | null; seasonMeans: Record<string, number | null>;
  drift: number | null; iv: FeatureIV; mi: number; outlierTreatable: boolean;
};
export type Profile = { features: FeatureProfileRow[]; totalRows: number; miSampleRows: number; ivMethod: string; miEstimator: string; ivScreeningThreshold?: number; ivWeakThreshold?: number };
export type Correlation = {
  scope: string; features: string[]; matrix: (number | null)[][]; threshold: number;
  strongPairs: { a: string; b: string; r: number }[]; strongPairCount: number;
  strongest: Record<string, { feature: string | null; r: number }>;
};
export type FeatureDetail = {
  name: string; kind: string; role: string;
  histogram: { lo: number; hi: number; count: number }[];
  yoyHistogram: Record<string, number[]>;
  box: { min: number; q1: number; median: number; q3: number; max: number; whiskerLo: number; whiskerHi: number } | null;
  targetConditioned: { class: string; mean: number | null; count: number }[];
  iv: FeatureIV; ivBinsMaxClass: string | null; ivBins: { bin: number; count: number; eventRate: number }[];
  missing: number; missingPct: number;
};
export type OutlierEntry = {
  feature: string; role: string; method: string; bounds: { lower: number; upper: number } | null;
  beforeMin: number | null; beforeMax: number | null; afterMin: number | null; afterMax: number | null;
  flagged: number; flaggedPct: number;
  beforeHistogram: { lo: number; hi: number; count: number }[];
  afterHistogram: { lo: number; hi: number; count: number }[];
};
export type OutlierSummary = {
  scope: string; totalObservations: number; featuresAnalyzed: number; featuresWithOutliers: number;
  totalFlagged: number; flaggedPct: number; features: OutlierEntry[];
};
export type HistBin = { lo: number; hi: number; count: number };
export type MissingEntry = {
  feature: string; role: string; kind: string; missing: number; missingPct: number; nonMissing: number;
  method: string; resolvedMethod: string; fillValue: number | null; indicator: boolean;
  bySeason: Record<string, number>;
  beforeHistogram: HistBin[] | null; afterHistogram: HistBin[] | null;
};
export type MissingSummary = {
  scope: string; totalObservations: number; featuresAnalyzed: number;
  continuousFeatures: number; categoricalFeatures: number;
  featuresWithMissing: number; totalMissing: number; missingCellPct: number;
  rowsAffected: number; rowsAffectedPct: number; addIndicator: boolean; features: MissingEntry[];
};
export type ModelFamily = { id: string; label: string; available: boolean; simulatorEligible: boolean; status: string };
export type Champion = {
  family: string; featureCount: number; C: number; val2024: Metric; frozen2025: Metric;
  registeredReference: { candidateId: string; val2024: Metric; frozen2025: Metric };
};
export type EvalMetrics = Record<string, any>;
export type ExperimentResult = {
  experimentId: string; config: ExperimentConfig; family: string; familyLabel: string; featureCount: number; expandedFeatureCount: number;
  fitSeconds: number; simulatorEligible: boolean;
  metrics: { val2024: EvalMetrics; frozen2025: EvalMetrics };
  headline: { val2024: Metric; frozen2025: Metric };
  champion: Champion;
  comparison: { val2024: Metric; frozen2025: Metric; beatsChampion2024: boolean; beatsChampionFrozen: boolean };
  importance: { feature: string; importance: number }[];
  createdAt: string;
  leakageGuards: Record<string, any>;
};
export type ExperimentIndexRow = {
  experimentId: string; family: string; featureCount: number; val2024LogLoss: number;
  frozen2025LogLoss: number; beatsChampion2024: boolean; createdAt: string;
};
export type AutopilotCandidate = {
  label: string; family: string; hyperparameters: Record<string, any>;
  val2024?: Metric; frozen2025?: Metric; runtimeSeconds?: number; status: string; error?: string;
};
export type AutopilotResult = {
  budget: string; featureCount: number; candidateCount: number; candidates: AutopilotCandidate[];
  best: AutopilotCandidate | null; runnerUp: AutopilotCandidate | null; champion: Champion;
  beatsChampion2024: boolean; totalRuntimeSeconds: number; limitations: string[];
};
export type SimEval = {
  label: string; games: number; paLogLoss: number; paBrier: number; totalRunBias: number; totalRunMae: number;
  totalRunCrps: number; runDiffMae: number; homeWinBrier: number; homeWinLogLoss: number; intervalCoverage90: number;
};
export type SimResult = {
  mode: string; season: number; games: number; simsPerGame: number; transitionAuthority: string; kernel: string;
  champion: SimEval; challenger: SimEval; deltas: Record<string, number>; verdict: string; notes: string[];
};
export type TemporalSplit = {
  policy: string; supported: { id: string; label: string; recommended: boolean; active: boolean; warning?: string }[];
  folds: { role: string; seasons: number[]; rows: number }[];
  leakageGuards: { guard: string; status: string }[];
};
export type FeatureCatalog = {
  available: { family: string; features: string[]; status: string }[];
  roadmap: { family: string; status: string }[];
};

// ---------------------------------------------------------------------------- config store
export type OutlierPolicy = { globalMethod: string; params?: Record<string, number>; overrides?: Record<string, any> };
export type MissingPolicy = { globalMethod: string; addIndicator?: boolean; constant?: number; overrides?: Record<string, any> };
export type EngineeredSpec = { name: string; kind: string; inputs?: string[]; params?: Record<string, any> };
export type ExperimentConfig = {
  features: string[];
  family: string;
  hyperparameters: Record<string, any>;
  outlierPolicy: OutlierPolicy;
  missingPolicy: MissingPolicy;
  engineeredFeatures?: EngineeredSpec[];
};
export type EngineeredProfile = {
  name: string; kind: string; simulatorAvailability: string; missing: number; missingPct: number;
  mean: number | null; median?: number | null; std: number | null; min: number | null; max: number | null;
  iv: FeatureIV; mi: number; seasonMeans: Record<string, number | null>; drift: number | null;
  histogram?: HistBin[]; sampleValues: number[];
};
export type AblationResult = {
  addedFeatures: string[];
  control: { features: number; val2024: Metric; frozen2025: Metric };
  challenger: { features: number; val2024: Metric; frozen2025: Metric };
  delta2024: Metric; delta2025: Metric; verdict: string;
};
export type Eligibility = { eligible: boolean; status: string; perFeature: Record<string, string>; blockedFeatures: string[]; reasons: string[] };
export type FullSimEval = {
  label: string; games: number; paLogLoss: number; paBrier: number; totalRunBias: number; totalRunMae: number;
  totalRunCrps: number; runDiffMae: number; homeWinBrier: number; homeWinLogLoss: number;
  coverage50: number; coverage80: number; coverage90: number; coverage95: number;
};
export type FullSimResult = {
  mode: string; provider: string; season: number; games: number; simsPerGame: number; kernel: string;
  eligibility: Eligibility; champion: FullSimEval; challenger: FullSimEval; deltas: Record<string, number>; verdict: string; notes: string[];
};

type CockpitStore = {
  config: ExperimentConfig;
  notes: Record<string, string>;
  engineeredProfiles: Record<string, EngineeredProfile>;
  lastResult?: ExperimentResult;
  lastAutopilot?: AutopilotResult;
  lastSim?: SimResult;
  savedSteps: Record<string, boolean>;
  setFeatures: (f: string[]) => void;
  toggleFeature: (f: string) => void;
  setFamily: (f: string) => void;
  setHyper: (h: Record<string, any>) => void;
  setOutlierPolicy: (p: OutlierPolicy) => void;
  setMissingPolicy: (p: MissingPolicy) => void;
  setNote: (k: string, v: string) => void;
  addEngineered: (spec: EngineeredSpec, profile?: EngineeredProfile) => void;
  removeEngineered: (name: string) => void;
  setLastResult: (r: ExperimentResult) => void;
  setLastAutopilot: (r: AutopilotResult) => void;
  setLastSim: (r: SimResult) => void;
  markSaved: (step: string) => void;
  hydrate: (snapshot: Partial<CockpitStore>) => void;
};

export const ALL_FEATURES = [
  "context_inning", "context_top_bottom", "context_outs_before", "context_base_mask_before", "context_batting_score_diff_before",
  "batter_log1p_pa", "batter_avg", "batter_obp", "batter_slg", "batter_so_per_pa", "batter_bb_hbp_per_pa", "batter_hr_per_pa", "batter_prior_missing",
  "pitcher_log1p_bfp", "pitcher_era9", "pitcher_whip", "pitcher_so_per_bfp", "pitcher_bb_per_bfp", "pitcher_hr_per_bfp", "pitcher_hbp_per_bfp", "pitcher_gs_per_g", "pitcher_prior_missing",
];

export const useCockpitStore = create<CockpitStore>((set) => ({
  config: {
    features: [...ALL_FEATURES],
    family: "logistic",
    hyperparameters: { C: 1.0, maxIter: 2000 },
    outlierPolicy: { globalMethod: "none", params: { k: 3.0 }, overrides: {} },
    missingPolicy: { globalMethod: "median", addIndicator: false, overrides: {} },
    engineeredFeatures: [],
  },
  notes: {},
  engineeredProfiles: {},
  savedSteps: {},
  setFeatures: (features) => set((s) => ({ config: { ...s.config, features } })),
  toggleFeature: (f) =>
    set((s) => {
      const has = s.config.features.includes(f);
      const features = has ? s.config.features.filter((x) => x !== f) : [...s.config.features, f];
      return { config: { ...s.config, features } };
    }),
  setFamily: (family) => set((s) => ({ config: { ...s.config, family } })),
  setHyper: (hyperparameters) => set((s) => ({ config: { ...s.config, hyperparameters } })),
  setOutlierPolicy: (outlierPolicy) => set((s) => ({ config: { ...s.config, outlierPolicy } })),
  setMissingPolicy: (missingPolicy) => set((s) => ({ config: { ...s.config, missingPolicy } })),
  setNote: (k, v) => set((s) => ({ notes: { ...s.notes, [k]: v } })),
  addEngineered: (spec, profile) =>
    set((s) => {
      const existing = (s.config.engineeredFeatures || []).filter((e) => e.name !== spec.name);
      const eng = [...existing, spec];
      const features = s.config.features.includes(spec.name) ? s.config.features : [...s.config.features, spec.name];
      const engineeredProfiles = profile ? { ...s.engineeredProfiles, [spec.name]: profile } : s.engineeredProfiles;
      return { config: { ...s.config, engineeredFeatures: eng, features }, engineeredProfiles };
    }),
  removeEngineered: (name) =>
    set((s) => {
      const { [name]: _dropped, ...engineeredProfiles } = s.engineeredProfiles;
      return {
        config: {
          ...s.config,
          engineeredFeatures: (s.config.engineeredFeatures || []).filter((e) => e.name !== name),
          features: s.config.features.filter((f) => f !== name),
        },
        engineeredProfiles,
      };
    }),
  setLastResult: (lastResult) => set({ lastResult }),
  setLastAutopilot: (lastAutopilot) => set({ lastAutopilot }),
  setLastSim: (lastSim) => set({ lastSim }),
  markSaved: (step) => set((s) => ({ savedSteps: { ...s.savedSteps, [step]: true } })),
  // Replace persisted slices on rehydration (project-scoped autosave restore).
  hydrate: (snapshot) => set((s) => ({ ...s, ...snapshot })),
}));

// ---------------------------------------------------------------------------- fetch hooks
export type Loadable<T> = { status: "idle" | "loading" | "ready" | "error"; data?: T; error?: string };

export function useEndpoint<T>(path: string | null, deps: any[] = []): Loadable<T> {
  const [state, setState] = useState<Loadable<T>>({ status: "idle" });
  useEffect(() => {
    if (!path) return;
    let alive = true;
    setState({ status: "loading" });
    getJSON<T>(path)
      .then((data) => alive && setState({ status: "ready", data }))
      .catch((e) => alive && setState({ status: "error", error: String(e) }));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}

export function usePost<T>() {
  const [state, setState] = useState<Loadable<T>>({ status: "idle" });
  const run = useCallback(async (path: string, body: any) => {
    setState({ status: "loading" });
    try {
      const data = await postJSON<T>(path, body);
      setState({ status: "ready", data });
      return data;
    } catch (e) {
      setState({ status: "error", error: String(e) });
      throw e;
    }
  }, []);
  return { ...state, run, reset: () => setState({ status: "idle" }) };
}

export const cockpitGet = getJSON;
export const cockpitPost = postJSON;
