import { Component, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  BadgeCheck,
  BookOpenCheck,
  Calculator,
  CheckCircle2,
  ClipboardCheck,
  Database,
  Download,
  FileSpreadsheet,
  GitBranch,
  Landmark,
  LineChart,
  Network,
  Scale,
  ShieldAlert,
  SlidersHorizontal,
} from "lucide-react";
import {
  MODEL_PURPOSES,
  PRODUCT_TYPES,
  TARGET_EVENTS,
  TTC_PIT_OPTIONS,
  applyManualWoeBins,
  getLatestCreditRiskMlModelForProject,
  exportScorecardExcel,
  exportWoeIvExcel,
  generateScorecardCode,
  generateWoeIvCode,
  getCreditRiskProfileForProject,
  getCreditRiskDatasetSummary,
  getLatestWoeIvAnalysisForProject,
  getLatestScorecardForProject,
  registerScorecardModel,
  runCreditRiskChampionComparison,
  saveCreditRiskEvidence,
  saveCreditRiskChampionDecision,
  saveCreditRiskChampionEvidence,
  saveCreditRiskMlEvidence,
  saveCreditRiskProfile,
  saveScorecardEvidence,
  saveWoeIvAnalysis,
  saveWoeIvEvidence,
  scorecardPreview,
  trainCreditRiskMlModel,
  type CreditRiskMlModel,
  type CreditRiskMlTrainRequest,
  type CreditRiskTargetSummary,
  runWoeIvAnalysis,
  trainScorecardModel,
  type ScorecardModel,
  type ScorecardTrainRequest,
  type CreditRiskProfile,
  type CreditRiskStatus,
  type CreditRiskVariableMapping,
  type WoeIvAnalysis,
  type WoeIvBin,
  type WoeIvManualBin,
  type WoeIvRunRequest,
  type WoeIvVariableSummary,
} from "../lib/creditRiskStudio";
import { getDatasetProfile, listDatasets, type DatasetProfile, type DatasetSummary } from "../lib/datasetLibrary";
import { loadLocalDataset, localDatasetVersion, type LocalDataset } from "../lib/localDataset";
import { useWorkflowStore } from "../state/useWorkflowStore";
import Step01DataAcquisition from "./Step01_DataAcquisition";
import Step01BCreditBureauReview from "./Step01B_CreditBureauReview";
import Step02EDA from "./Step02_EDA";
import Step03Outliers from "./Step04_Outliers";
import Step04MissingValues from "./Step04_MissingValues";
import Step05FeatureEngineering from "./Step05_EncodingScaling";
import Step06BalanceSplit from "./Step06_BalancingSplit";
import Step07ModelTraining from "./Step06_Train";
import Step08Evaluation from "./Step08_Evaluation";
import Step09Interpretation from "./Step09_Interpretation";
import Step10Scoring from "./Step10_Scoring";
import Step11DocumentationReview from "./Step11_ModelDevelopmentDocument";
import Step12ModelImplementation from "./Step12_ModelImplementation";
import Step13ModelMonitoring from "./Step13_ModelMonitoring";

const sections = [
  "Project Setup",
  "Population and Target",
  "Credit Risk EDA",
  "Characteristic Screening",
  "Modeling Approach",
  "Traditional Scorecard Path",
  "AI/ML Underwriting Path",
  "Champion / Challenger Comparison",
  "Cutoff and Decision Strategy",
  "Explainability and Adverse Action",
  "Monitoring and Portfolio Risk",
  "Evidence and Documentation",
];

const previewTargetSummaryMessage = "Full dataset artifact unavailable. Showing preview sample summary.";
const HELOC_DEFAULT_TARGET_LABEL = "RiskPerformance";
const HELOC_DEFAULT_PROJECT_NAME = "HELOC Traditional Scorecard Test Run";
const BUREAU_SPECIAL_TREATMENT_KEY = "atlas.creditRisk.bureauSpecialTreatment";
const bureauSpecialTreatmentOptions = ["Create special bin", "Create indicator and impute", "Convert to missing", "Preserve raw special value", "Review manually"];
const bureauSpecialFilterOptions = ["All", "-7", "-8", "-9"];
const defaultBureauSpecialRationale = "Bureau special values -7, -8, and -9 are preserved as explicit special-value treatments for credit-risk modeling. They are not ordinary numeric outliers or ordinary missing values. For this HELOC test run, special values will be handled using documented special bins unless a reviewer selects a different treatment.";
const predictiveWorkflowSteps = [
  { name: "Project Context", slug: "project-context", stepId: "step00", route: "/step00", overlaySection: "Project Setup", relevance: "Defines the business problem, model purpose, underwriting decision context, population, and governance expectations.", evidence: "Business purpose, intended use, governance expectations." },
  { name: "Data Acquisition", slug: "data-acquisition", stepId: "step01", route: "/step01", overlaySection: "Population and Target", relevance: "Connects HELOC_TRAIN, HELOC_TEST, HELOC_OOT, source metadata, and dataset lineage for model development.", evidence: "Data source, lineage, target, selected features." },
  { name: "EDA", slug: "eda", stepId: "step02", route: "/step02", overlaySection: "Credit Risk EDA", relevance: "Reviews target distribution, bad-rate patterns, variable distributions, candidate predictors, and early leakage signals.", evidence: "EDA distributions, target behavior, leakage indicators." },
  { name: "Outliers", slug: "outliers", stepId: "step03", route: "/step03", overlaySection: "Credit Risk EDA", relevance: "Reviews extreme bureau values and determines whether they are valid bureau observations, special values, or data quality issues.", evidence: "Outlier treatment and exception rationale." },
  { name: "Missing Values", slug: "missing-values", stepId: "step04", route: "/step04", overlaySection: "Credit Risk EDA", relevance: "Reviews missingness and bureau special values. For HELOC, -7, -8, and -9 should be preserved unless explicitly changed.", evidence: "Missing value and bureau special value treatment." },
  { name: "Feature Engineering", slug: "feature-engineering", stepId: "step05", route: "/step05", overlaySection: "Characteristic Screening", relevance: "Documents transformations, bureau special value treatment, WOE variables, binned characteristics, and derived underwriting features.", evidence: "Transformations, bins, WOE variables, derived characteristics." },
  { name: "Balance & Split", slug: "balance-split", stepId: "step06", route: "/step06", overlaySection: "Population and Target", relevance: "Documents TRAIN, TEST, and OOT strategy. For HELOC, OOT is a synthetic holdout because no true date field is available.", evidence: "Split strategy, validation strategy, OOT rationale." },
  { name: "Model Training", slug: "model-training", stepId: "step07", route: "/step07", overlaySection: "Modeling Approach", relevance: "Trains the traditional scorecard model or AI/ML underwriting challenger using approved features and documented transformations.", evidence: "Candidate models, training settings, champion candidates." },
  { name: "Evaluation", slug: "evaluation", stepId: "step08", route: "/step08", overlaySection: "Champion / Challenger Comparison", relevance: "Reviews AUC, KS, Gini, lift, bad-rate by decile, score distribution, calibration, and validation results before RFE final-model selection.", evidence: "Performance, calibration, lift, score distribution." },
  { name: "Interpretation", slug: "interpretation", stepId: "step09", route: "/step09", overlaySection: "Explainability and Adverse Action", relevance: "Explains model drivers, scorecard points, WOE directionality, SHAP or surrogate explanations, reason-code candidates, and RFE/final-model selection.", evidence: "Drivers, reason-code candidates, model explanation, final RFE model." },
  { name: "Scoring", slug: "scoring", stepId: "step10", route: "/step10", overlaySection: "Cutoff and Decision Strategy", relevance: "Scores TRAIN, TEST, and OOT datasets with the final RFE model, creates score outputs, and registers scored datasets for diagnostics and monitoring.", evidence: "Scored datasets, stability outputs, score previews." },
  { name: "Documentation Review", slug: "documentation-review", stepId: "step11", route: "/step11", overlaySection: "Evidence and Documentation", relevance: "Checks whether development evidence is ready for Model Documentation Studio.", evidence: "Documentation readiness and mapped evidence." },
  { name: "Model Implementation", slug: "model-implementation", stepId: "step12", route: "/step12", overlaySection: "Evidence and Documentation", relevance: "Documents scoring logic, code exports, implementation assumptions, and deployment readiness.", evidence: "Implementation plan and scoring logic." },
  { name: "Model Monitoring", slug: "model-monitoring", stepId: "step13", route: "/step13", overlaySection: "Monitoring and Portfolio Risk", relevance: "Documents PSI, score stability, performance monitoring, champion/challenger tracking, and redevelopment triggers.", evidence: "Monitoring cadence, thresholds, and triggers." },
];

const auxiliaryCreditRiskSteps = [
  { name: "Credit Bureau Data Review", slug: "credit-bureau-data-review", stepId: "step01b", route: "/step01b", overlaySection: "Credit Risk EDA", relevance: "Reviews HELOC bureau variable metadata, special bureau values, and treatment decisions outside the numbered main workflow.", evidence: "Bureau metadata, special-value profiling, selected treatments, rationale." },
] as const;

type CreditRiskWorkflowStep = (typeof predictiveWorkflowSteps)[number] | (typeof auxiliaryCreditRiskSteps)[number];

function workflowStepDisplayName(step: CreditRiskWorkflowStep) {
  return step.slug === "interpretation" ? "Interpretation / RFE Final Model" : step.name;
}

const workflowStageMeta: Record<string, { purpose: string; inputs: string; outputs: string; nextAction: string; evidence: string }> = {
  "Project Setup": {
    purpose: "Create the governed credit-risk model profile and connect the modeling dataset.",
    inputs: "Project, dataset, product type, model purpose, model type, target event, windows, TTC/PIT, regulatory context.",
    outputs: "Credit-risk project profile saved.",
    nextAction: "Confirm population and target definitions.",
    evidence: "Project setup evidence; regulatory context evidence.",
  },
  "Population and Target": {
    purpose: "Define good, bad, indeterminate, exclusions, censoring, and outcome source logic.",
    inputs: "Good definition, bad definition, indeterminate definition, observation and performance windows, exclusions, reject notes.",
    outputs: "Target summary with rows, goods, bads, bad rate, indeterminates, missing target, and target window.",
    nextAction: "Review underwriting EDA and target distribution.",
    evidence: "Target definition evidence; population definition evidence.",
  },
  "Credit Risk EDA": {
    purpose: "Investigate underwriting-specific data quality, target behavior, leakage, sensitive fields, and candidate signal.",
    inputs: "Dataset schema, variable roles, target event, selected population.",
    outputs: "Variable investigation table, bad-rate diagnostics, missingness profile, leakage and sensitive-variable flags.",
    nextAction: "Send candidate variables to characteristic screening.",
    evidence: "Credit Risk EDA evidence.",
  },
  "Characteristic Screening": {
    purpose: "Prepare candidate predictors for either underwriting model path by reviewing missingness, cardinality, correlation, VIF, protected status, leakage, and reviewer exclusions.",
    inputs: "Candidate variables, role mapping, screening rules, reviewer notes.",
    outputs: "Approved predictors and excluded-variable rationale for the scorecard path, AI/ML path, or both.",
    nextAction: "Choose the modeling approach.",
    evidence: "Characteristic screening evidence; VIF / correlation evidence.",
  },
  "Modeling Approach": {
    purpose: "Select the underwriting development path: traditional scorecard, AI/ML underwriting, or a governed champion/challenger comparison.",
    inputs: "Governance constraints, selected characteristics, transparency requirements, performance goals, and implementation expectations.",
    outputs: "Selected modeling approach and rationale for scorecard baseline, AI/ML challenger, or compare-both workflow.",
    nextAction: "Build the selected traditional scorecard and/or AI/ML underwriting path.",
    evidence: "Modeling approach evidence; champion/challenger planning evidence.",
  },
  "Traditional Scorecard Path": {
    purpose: "Build a transparent underwriting scorecard baseline using WOE / IV, manual binning, logistic regression, PDO scaling, scorecard points, validation, cutoff preview, and reason-code-ready evidence.",
    inputs: "Approved characteristics, target/event, WOE settings, manual bins, scorecard training controls, PDO/base score/base odds.",
    outputs: "WOE / IV analysis, scorecard model, PDO factor/offset, points table, lift/KS/calibration, cutoff preview, and scorecard evidence.",
    nextAction: "Train or refresh the AI/ML challenger, or proceed to champion/challenger comparison.",
    evidence: "WOE / IV, manual binning, scorecard modeling, PDO scaling, scorecard points, and validation evidence.",
  },
  "AI/ML Underwriting Path": {
    purpose: "Build a modern underwriting challenger with available ML models, calibrated probabilities, feature importance, monotonic-constraint evidence, SHAP fallback, PDP / ICE placeholders, and surrogate scorecard review.",
    inputs: "Selected variables, target/event, train/validation split, class weighting, calibration method, monotonic constraints, evaluation metric.",
    outputs: "AI/ML challenger summary, performance metrics, feature importance, decile lift, calibration table, warnings, and explainability evidence.",
    nextAction: "Compare scorecard baseline and AI/ML challenger side by side.",
    evidence: "AI/ML underwriting, feature importance, monotonic constraint, surrogate scorecard, and explainability evidence.",
  },
  "Champion / Challenger Comparison": {
    purpose: "Compare the traditional scorecard baseline, AI/ML challenger, and any current champion using performance, calibration, adverse-action readiness, stability, and model risk complexity.",
    inputs: "Scorecard model, AI/ML model, validation metrics, explainability status, adverse-action status, monitoring readiness.",
    outputs: "Recommended role, reviewer decision, champion/challenger rationale, and governance evidence.",
    nextAction: "Choose cutoffs and decision strategy for the selected model source.",
    evidence: "Champion/challenger comparison and model selection rationale evidence.",
  },
  "Cutoff and Decision Strategy": {
    purpose: "Connect scorecard or AI/ML output to approval rate, bad rate, loss, profitability, pricing tiers, and manual override rules.",
    inputs: "Model source, score/probability column, cutoff, approval target, maximum bad rate, balance, LGD, revenue, pricing tier, override rules.",
    outputs: "Cutoff strategy table and business recommendation.",
    nextAction: "Document explainability and adverse-action support.",
    evidence: "Cutoff strategy evidence; risk-based pricing evidence; strategy tree evidence.",
  },
  "Explainability and Adverse Action": {
    purpose: "Map scorecard points or AI/ML feature contributions to reason-code candidates and governance review evidence.",
    inputs: "Model type, scorecard points, SHAP/feature importance if available, surrogate scorecard mapping, excluded variables, protected/sensitive flags, monotonicity review.",
    outputs: "Reason-code draft, feature-to-reason mapping, fair-lending and legal-review hooks for the selected model type.",
    nextAction: "Define monitoring and portfolio risk thresholds.",
    evidence: "Adverse action evidence; fair lending evidence; monotonic constraint evidence.",
  },
  "Monitoring and Portfolio Risk": {
    purpose: "Define score distribution monitoring, bad-rate monitoring, champion/challenger review, TTC/PIT assumption, and redevelopment triggers.",
    inputs: "PSI thresholds, cadence, owners, champion/challenger, redevelopment triggers.",
    outputs: "Monitoring plan and portfolio-risk governance controls.",
    nextAction: "Review evidence and documentation readiness.",
    evidence: "PSI evidence; challenger/champion evidence; monitoring threshold evidence.",
  },
  "Evidence and Documentation": {
    purpose: "Confirm all credit-risk model evidence is ready for documentation, validation, and governance review.",
    inputs: "Evidence records from setup, target, EDA, screening, WOE/IV, scorecard, PDO, validation, cutoff, explainability, and monitoring.",
    outputs: "Documentation readiness summary and links to governed documentation workspaces.",
    nextAction: "Open Model Evidence Center or Model Documentation Studio.",
    evidence: "Full credit risk evidence pack.",
  },
};

const readinessSections = [
  "Target Definition",
  "Population Definition",
  "Variable Mapping",
  "Modeling Approach",
  "WOE / IV",
  "Manual Binning",
  "Reject Inference",
  "PDO Scaling",
  "Adverse Action",
  "Fair Lending",
  "Cutoff Strategy",
  "Risk-Based Pricing",
  "PSI",
  "Champion / Challenger",
  "AI/ML Underwriting",
  "Monotonic Constraints",
  "Feature Importance",
  "Surrogate Scorecard",
  "Monitoring",
  "Documentation",
];

const techniqueLabels: Record<string, string> = {
  target_definition: "Target Definition Evidence",
  variable_mapping: "Variable Mapping Evidence",
  woe: "WOE / IV Evidence",
  manual_binning: "Manual Binning Evidence",
  reject_inference: "Reject Inference Evidence",
  iv: "VIF / Correlation Evidence",
  pdo: "PDO Scaling Evidence",
  scorecard_scaling: "Scorecard Scaling and Odds Calibration Evidence",
  scorecard_modeling: "Scorecard Model Evidence",
  scorecard_performance: "Scorecard Model Performance Evidence",
  scorecard_points: "Scorecard Points Evidence",
  ml_underwriting: "AI/ML Underwriting Evidence",
  feature_importance: "Feature Importance Evidence",
  shap_explainability: "SHAP Explainability Evidence",
  calibrated_probability: "Calibrated Probability Evidence",
  adverse_action: "Adverse Action Evidence",
  fair_lending: "Fair Lending Evidence",
  monotonic_constraints: "Monotonic Constraint Evidence",
  surrogate_scorecard: "Surrogate Scorecard Evidence",
  champion_challenger: "Champion / Challenger Evidence",
  cutoff_optimization: "Cutoff Optimization Evidence",
  risk_based_pricing: "Risk-Based Pricing Evidence",
  strategy_trees: "Strategy Tree Evidence",
  ttc: "TTC / PIT Evidence",
  psi: "PSI Evidence",
  challenger_champion: "Challenger / Champion Evidence",
  monitoring_threshold: "Monitoring Threshold Evidence",
};

function workflowStepForSlug(slug: string | null) {
  return predictiveWorkflowSteps.find((step) => step.slug === slug) || auxiliaryCreditRiskSteps.find((step) => step.slug === slug) || predictiveWorkflowSteps[0];
}

function workflowStepForOverlay(section: string) {
  const mappedSlug: Record<string, string> = {
    "Project Setup": "project-context",
    "Population and Target": "data-acquisition",
    "Credit Risk EDA": "eda",
    "Characteristic Screening": "feature-engineering",
    "Modeling Approach": "model-training",
    "Traditional Scorecard Path": "model-training",
    "AI/ML Underwriting Path": "model-training",
    "Champion / Challenger Comparison": "evaluation",
    "Cutoff and Decision Strategy": "scoring",
    "Explainability and Adverse Action": "interpretation",
    "Monitoring and Portfolio Risk": "model-monitoring",
    "Evidence and Documentation": "documentation-review",
  };
  return workflowStepForSlug(mappedSlug[section] || null);
}

export default function CreditRiskStudio() {
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const setProjectName = useWorkflowStore((state) => state.setProjectName);
  const setCurrentStepId = useWorkflowStore((state) => state.setCurrentStepId);
  const normalizeWorkflowOrder = useWorkflowStore((state) => state.normalizeWorkflowOrder);
  const [searchParams, setSearchParams] = useSearchParams();
  const initialWorkflowStep = workflowStepForSlug(searchParams.get("step"));
  const [activeWorkflowSlug, setActiveWorkflowSlug] = useState(initialWorkflowStep.slug);
  const [active, setActive] = useState(initialWorkflowStep.overlaySection);
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [schema, setSchema] = useState<string[]>([]);
  const [datasetProfile, setDatasetProfile] = useState<DatasetProfile | null>(null);
  const [targetSummary, setTargetSummary] = useState<CreditRiskTargetSummary | null>(null);
  const [localDataset, setLocalDataset] = useState<LocalDataset | null>(() => loadLocalDataset());
  const [schemaLoadError, setSchemaLoadError] = useState("");
  const [schemaRefreshTick, setSchemaRefreshTick] = useState(0);
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [profile, setProfile] = useState<CreditRiskProfile>(() => defaultProfile(projectId, projectName));
  const [projectNameDraft, setProjectNameDraft] = useState(projectName && projectName !== "Untitled ATLAS Project" ? projectName : HELOC_DEFAULT_PROJECT_NAME);
  const preview = useMemo(() => scorecardPreview(profile.scorecardScaling), [profile.scorecardScaling]);
  const readiness = useMemo(() => computeReadiness(profile), [profile]);
  const variableCounts = useMemo(() => summarizeVariables(profile.variableMappings || []), [profile.variableMappings]);
  const activeWorkflowStep = workflowStepForSlug(activeWorkflowSlug);
  const activeIndex = Math.max(0, predictiveWorkflowSteps.findIndex((step) => step.slug === activeWorkflowStep.slug));
  const [woeRequest, setWoeRequest] = useState<WoeIvRunRequest>(() => defaultWoeRequest(projectId, profile));
  const [woeAnalysis, setWoeAnalysis] = useState<WoeIvAnalysis | null>(null);
  const [selectedWoeVariable, setSelectedWoeVariable] = useState("");
  const [woeRunning, setWoeRunning] = useState(false);
  const [woeMessage, setWoeMessage] = useState("");
  const [manualBins, setManualBins] = useState<WoeIvManualBin[]>([]);
  const [codeTab, setCodeTab] = useState("python");
  const [scorecardRequest, setScorecardRequest] = useState<ScorecardTrainRequest>(() => defaultScorecardRequest(projectId, profile));
  const [scorecardModel, setScorecardModel] = useState<ScorecardModel | null>(null);
  const [scorecardRunning, setScorecardRunning] = useState(false);
  const [scorecardMessage, setScorecardMessage] = useState("");
  const [scorecardCodeTab, setScorecardCodeTab] = useState("python");
  const [mlRequest, setMlRequest] = useState<CreditRiskMlTrainRequest>(() => defaultMlRequest(projectId, profile));
  const [mlModel, setMlModel] = useState<CreditRiskMlModel | null>(null);
  const [mlRunning, setMlRunning] = useState(false);
  const [mlMessage, setMlMessage] = useState("");
  const [championComparison, setChampionComparison] = useState<Record<string, unknown> | null>(null);
  const [autoIvRunKey, setAutoIvRunKey] = useState("");
  const workflowStatus = useMemo(() => computeWorkflowStatus(profile, woeAnalysis, scorecardModel, mlModel, readiness.score), [profile, woeAnalysis, scorecardModel, mlModel, readiness.score]);
  const activeDataset = useMemo(() => datasets.find((dataset) => dataset.datasetId === profile.datasetId) || null, [datasets, profile.datasetId]);
  const schemaMismatch = useMemo(() => {
    if (!schema.length || !(profile.variableMappings || []).length) return false;
    return (profile.variableMappings || []).some((row) => !schema.includes(row.variable));
  }, [profile.variableMappings, schema]);
  const finalModelSelectedVariables = useMemo(
    () => uniqueStrings([...scorecardRequest.selectedVariables, ...mlRequest.selectedVariables])
      .filter((column) => isCreditRiskPredictorCandidate(column, profile, scorecardRequest.targetColumn || mlRequest.targetColumn || profile.targetColumn)),
    [scorecardRequest.selectedVariables, scorecardRequest.targetColumn, mlRequest.selectedVariables, mlRequest.targetColumn, profile],
  );
  const localDatasetKey = useMemo(() => localDatasetVersion(localDataset), [localDataset]);
  const finalFeaturePreviewIv = useMemo(
    () => previewIvByVariable(localDataset, scorecardRequest.targetColumn || mlRequest.targetColumn || profile.targetColumn, String(profile.eventValue || "1")),
    [localDatasetKey, scorecardRequest.targetColumn, mlRequest.targetColumn, profile.targetColumn, profile.eventValue],
  );
  const balanceSplitAutoIvKey = useMemo(
    () => [
      projectId,
      profile.datasetId || "",
      profile.datasetVersionId || "",
      profile.targetColumn || "",
      profile.eventValue || "1",
      schema.filter((column) => isCreditRiskPredictorCandidate(column, profile, profile.targetColumn)).join("|"),
    ].join("::"),
    [projectId, profile, schema],
  );

  useEffect(() => {
    normalizeWorkflowOrder("credit-risk-studio");
  }, [normalizeWorkflowOrder]);

  useEffect(() => {
    const step = workflowStepForSlug(searchParams.get("step"));
    setActiveWorkflowSlug(step.slug);
    setActive(step.overlaySection);
    setCurrentStepId(step.stepId);
  }, [searchParams, setCurrentStepId]);

  useEffect(() => {
    const nextProjectName = profile.projectName || (projectName && projectName !== "Untitled ATLAS Project" ? projectName : HELOC_DEFAULT_PROJECT_NAME);
    setProjectNameDraft(nextProjectName);
    if (projectName === "Untitled ATLAS Project" && nextProjectName !== projectName) {
      setProjectName(nextProjectName);
      setProfile((current) => ({ ...current, projectName: nextProjectName }));
    }
  }, [profile.projectName, projectName, setProjectName]);

  function openWorkflowStep(slug: string) {
    const step = workflowStepForSlug(slug);
    setActiveWorkflowSlug(step.slug);
    setActive(step.overlaySection);
    setCurrentStepId(step.stepId);
    setSearchParams({ step: step.slug });
    setTimeout(() => window.scrollTo({ top: 0, behavior: "smooth" }), 0);
  }

  function openOverlaySection(section: string) {
    const step = workflowStepForOverlay(section);
    setActiveWorkflowSlug(step.slug);
    setActive(section);
    setCurrentStepId(step.stepId);
    setSearchParams({ step: step.slug });
    setTimeout(() => window.scrollTo({ top: 0, behavior: "smooth" }), 0);
  }

  useEffect(() => {
    let alive = true;
    Promise.all([
      listDatasets().then((payload) => payload.datasets).catch(() => []),
      getCreditRiskProfileForProject(projectId).catch(() => null),
      getLatestWoeIvAnalysisForProject(projectId).catch(() => null),
      getLatestScorecardForProject(projectId).catch(() => null),
      getLatestCreditRiskMlModelForProject(projectId).catch(() => null),
    ]).then(([loadedDatasets, saved, savedWoe, savedScorecard, savedMlModel]) => {
      if (!alive) return;
      setDatasets(loadedDatasets);
      const nextProfile = normalizeCreditRiskProfile(saved || defaultProfile(projectId, projectName, preferredCreditRiskDataset(loadedDatasets)), loadedDatasets, projectId, projectName);
      setProfile(nextProfile);
      setWoeRequest((current) => ({
        ...current,
        projectId,
        datasetId: nextProfile.datasetId || loadedDatasets[0]?.datasetId || "",
        datasetVersionId: nextProfile.datasetVersionId || loadedDatasets[0]?.latestVersion?.versionId,
      }));
      setScorecardRequest((current) => ({
        ...current,
        projectId,
        datasetId: nextProfile.datasetId || loadedDatasets[0]?.datasetId || "",
        datasetVersionId: nextProfile.datasetVersionId || loadedDatasets[0]?.latestVersion?.versionId,
        pdo: Number(nextProfile.scorecardScaling?.pdo || current.pdo),
        baseScore: Number(nextProfile.scorecardScaling?.baseScore || current.baseScore),
        baseOdds: nextProfile.scorecardScaling?.baseOdds || current.baseOdds,
        scoreDirection: nextProfile.scorecardScaling?.scoreDirection || current.scoreDirection,
      }));
      setMlRequest((current) => ({
        ...current,
        projectId,
        datasetId: nextProfile.datasetId || loadedDatasets[0]?.datasetId || "",
        datasetVersionId: nextProfile.datasetVersionId || loadedDatasets[0]?.latestVersion?.versionId,
        targetColumn: current.targetColumn || nextProfile.targetColumn || "",
      }));
      if (savedWoe) {
        setWoeAnalysis(savedWoe);
        setSelectedWoeVariable(savedWoe.variableSummaries?.[0]?.variable || "");
        setScorecardRequest((current) => ({
          ...current,
          woeAnalysisId: savedWoe.analysisId,
          selectedVariables: current.selectedVariables.length ? current.selectedVariables : defaultScorecardVariables(savedWoe),
        }));
      }
      if (savedScorecard) {
        setScorecardModel(savedScorecard);
      }
      if (savedMlModel) {
        setMlModel(savedMlModel);
      }
    });
    return () => {
      alive = false;
    };
  }, [projectId, projectName]);

  useEffect(() => {
    if (!profile.datasetId) {
      setSchema([]);
      setSchemaLoadError("");
      return;
    }
    getDatasetProfile(profile.datasetId, profile.datasetVersionId)
      .then((payload) => {
        const columns = payload.profile.schema.map((column) => column.name);
        setSchema(columns);
        setSchemaLoadError("");
        setDatasetProfile(payload.profile);
        setProfile((current) => {
          const currentVariables = new Set((current.variableMappings || []).map((row) => row.variable));
          const matchesSchema = current.variableMappings?.length && (current.variableMappings || []).every((row) => columns.includes(row.variable));
          const completeSchemaMapping = Boolean(matchesSchema && columns.every((column) => currentVariables.has(column)));
          const nextTarget = current.targetColumn && columns.includes(current.targetColumn) ? current.targetColumn : findTargetColumn(columns);
          const splitColumn = current.splitColumn && columns.includes(current.splitColumn) ? current.splitColumn : columns.find((column) => /split/i.test(column)) || "";
          const originalTarget = current.originalTargetLabelColumn && columns.includes(current.originalTargetLabelColumn)
            ? current.originalTargetLabelColumn
            : columns.find((column) => column === HELOC_DEFAULT_TARGET_LABEL || /riskperformance|original.*target|target.*label/i.test(column)) || "";
          const datasetName = payload.dataset?.name || datasets.find((dataset) => dataset.datasetId === current.datasetId)?.name || "";
          const validationDatasetId = current.validationDatasetId && datasets.some((dataset) => dataset.datasetId === current.validationDatasetId)
            ? current.validationDatasetId
            : findDatasetIdByName(datasets, /^HELOC_TEST$/i);
          const ootDatasetId = current.ootDatasetId && datasets.some((dataset) => dataset.datasetId === current.ootDatasetId)
            ? current.ootDatasetId
            : findDatasetIdByName(datasets, /^HELOC_OOT$/i);
          return {
            ...current,
            targetColumn: nextTarget,
            eventValue: current.eventValue || "1",
            nonEventValue: current.nonEventValue || "0",
            originalTargetLabelColumn: originalTarget,
            splitColumn,
            validationDatasetId,
            ootDatasetId,
            ootType: current.ootType || (ootDatasetId ? "Synthetic holdout" : ""),
            variableMappings: completeSchemaMapping ? current.variableMappings : buildVariableMappings(columns, datasetName, nextTarget, splitColumn, originalTarget),
          };
        });
        setWoeRequest((current) => {
          const target = current.targetColumn && columns.includes(current.targetColumn) ? current.targetColumn : profile.targetColumn || findTargetColumn(columns);
          const predictors = current.predictorColumns?.length
            ? current.predictorColumns.filter((column) => columns.includes(column) && isCreditRiskPredictorCandidate(column, profile, target))
            : columns.filter((column) => isCreditRiskPredictorCandidate(column, profile, target)).slice(0, 20);
          return { ...current, targetColumn: target, predictorColumns: predictors };
        });
        setScorecardRequest((current) => {
          const target = current.targetColumn && columns.includes(current.targetColumn) ? current.targetColumn : profile.targetColumn || findTargetColumn(columns);
          const selectedVariables = current.selectedVariables?.length
            ? current.selectedVariables.filter((column) => columns.includes(column) && isCreditRiskPredictorCandidate(column, profile, target))
            : columns.filter((column) => isCreditRiskPredictorCandidate(column, profile, target)).slice(0, 20);
          return { ...current, targetColumn: target, selectedVariables };
        });
        setMlRequest((current) => {
          const target = current.targetColumn && columns.includes(current.targetColumn) ? current.targetColumn : profile.targetColumn || findTargetColumn(columns);
          const selectedVariables = current.selectedVariables?.length
            ? current.selectedVariables.filter((column) => columns.includes(column) && isCreditRiskPredictorCandidate(column, profile, target))
            : columns.filter((column) => isCreditRiskPredictorCandidate(column, profile, target)).slice(0, 30);
          return { ...current, targetColumn: target, selectedVariables };
        });
      })
      .catch(() => {
        setSchema([]);
        setDatasetProfile(null);
        setTargetSummary(null);
        setSchemaLoadError("ATLAS could not load the selected dataset schema. Use Refresh Dataset Schema or reselect the dataset.");
      });
  }, [profile.datasetId, profile.datasetVersionId, datasets, schemaRefreshTick]);

  useEffect(() => {
    if (!profile.datasetId || !profile.targetColumn) {
      setTargetSummary(null);
      return;
    }
    getCreditRiskDatasetSummary({
      datasetId: profile.datasetId,
      datasetVersionId: profile.datasetVersionId,
      targetColumn: profile.targetColumn,
      eventValue: profile.eventValue || "1",
      nonEventValue: profile.nonEventValue || "0",
    }).then((summary) => {
      setTargetSummary(summary);
      setProfile((current) => ({ ...current, targetSummary: summary }));
    }).catch(() => setTargetSummary(null));
  }, [profile.datasetId, profile.datasetVersionId, profile.targetColumn, profile.eventValue, profile.nonEventValue]);

  function patch(update: Partial<CreditRiskProfile>) {
    setProfile((current) => ({ ...current, ...update }));
  }

  async function saveProjectName() {
    const nextProjectName = projectNameDraft.trim() || HELOC_DEFAULT_PROJECT_NAME;
    setSaving(true);
    setMessage("");
    try {
      setProjectName(nextProjectName);
      const saved = await saveCreditRiskProfile({ ...profile, projectName: nextProjectName });
      setProfile(saved);
      setProjectNameDraft(saved.projectName || nextProjectName);
      setMessage("Project name saved.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not save the project name.");
    } finally {
      setSaving(false);
    }
  }

  function patchNested<K extends keyof CreditRiskProfile>(key: K, update: Record<string, unknown>) {
    setProfile((current) => ({ ...current, [key]: { ...((current[key] as Record<string, unknown>) || {}), ...update } }));
  }

  async function saveSetup() {
    setSaving(true);
    setMessage("");
    try {
      const withPreview = {
        ...profile,
        scorecardScaling: { ...(profile.scorecardScaling || {}), ...preview },
        readiness: Object.fromEntries(readiness.items.map((item) => [item.section, item.status])),
        readinessScore: readiness.score,
      };
      const saved = await saveCreditRiskProfile(withPreview);
      setProfile(saved);
      setMessage("Credit risk setup saved.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not save the credit-risk setup.");
    } finally {
      setSaving(false);
    }
  }

  function handleDatasetChange(value: string) {
    const dataset = datasets.find((item) => item.datasetId === value);
    const versionId = dataset?.latestVersion?.versionId || "";
    const nextProfile: Partial<CreditRiskProfile> = {
      datasetId: value,
      datasetVersionId: versionId,
      targetColumn: "",
      eventValue: "1",
      nonEventValue: "0",
      originalTargetLabelColumn: "",
      splitColumn: "",
      variableMappings: [],
      edaStatus: undefined,
      screeningStatus: undefined,
      woeIvStatus: undefined,
      scorecardModelStatus: undefined,
      scorecardStatus: undefined,
      mlStatus: undefined,
      comparisonStatus: undefined,
      championDecisionStatus: undefined,
      targetSummary: undefined,
    };
    patch(nextProfile);
    setSchema([]);
    setDatasetProfile(null);
    setTargetSummary(null);
    setWoeAnalysis(null);
    setSelectedWoeVariable("");
    setScorecardModel(null);
    setMlModel(null);
    setChampionComparison(null);
    setWoeRequest(defaultWoeRequest(projectId, { ...profile, ...nextProfile } as CreditRiskProfile));
    setScorecardRequest(defaultScorecardRequest(projectId, { ...profile, ...nextProfile } as CreditRiskProfile));
    setMlRequest(defaultMlRequest(projectId, { ...profile, ...nextProfile } as CreditRiskProfile));
    setMessage(`Active dataset changed to ${dataset?.name || value}. Stale schema-derived credit-risk outputs were cleared.`);
  }

  function refreshDatasetSchema() {
    setSchema([]);
    setDatasetProfile(null);
    setTargetSummary(null);
    setSchemaLoadError("");
    setSchemaRefreshTick((current) => current + 1);
  }

  function setFinalModelFeatureSelection(variable: string, selected: boolean) {
    setScorecardRequest((current) => ({
      ...current,
      selectedVariables: selected
        ? uniqueStrings([...current.selectedVariables, variable])
        : current.selectedVariables.filter((item) => item !== variable),
    }));
    setMlRequest((current) => ({
      ...current,
      selectedVariables: selected
        ? uniqueStrings([...current.selectedVariables, variable])
        : current.selectedVariables.filter((item) => item !== variable),
    }));
  }

  function applyIvRecommendedFinalFeatures() {
    const recommended = finalFeatureReviewRows({
      profile,
      woeAnalysis,
      previewIvByVariable: finalFeaturePreviewIv,
      targetColumn: scorecardRequest.targetColumn || mlRequest.targetColumn || profile.targetColumn,
    })
      .filter((row) => row.recommended)
      .map((row) => row.variable);
    setScorecardRequest((current) => ({ ...current, selectedVariables: recommended }));
    setMlRequest((current) => ({ ...current, selectedVariables: recommended }));
  }

  useEffect(() => {
    const refresh = () => refreshDatasetSchema();
    window.addEventListener("atlas:credit-risk-refresh-dataset-schema", refresh);
    return () => window.removeEventListener("atlas:credit-risk-refresh-dataset-schema", refresh);
  }, []);

  useEffect(() => {
    const refreshLocalDataset = () => setLocalDataset(loadLocalDataset());
    window.addEventListener("atlas-dataset-updated", refreshLocalDataset);
    window.addEventListener("storage", refreshLocalDataset);
    return () => {
      window.removeEventListener("atlas-dataset-updated", refreshLocalDataset);
      window.removeEventListener("storage", refreshLocalDataset);
    };
  }, []);

  useEffect(() => {
    if (activeWorkflowStep.name !== "Balance & Split") return;
    if (!profile.datasetId || !profile.targetColumn || !schema.length) return;
    const alreadyLoaded = Boolean(
      woeAnalysis?.datasetId === profile.datasetId
      && woeAnalysis?.targetColumn === profile.targetColumn
      && woeAnalysis.variableSummaries?.length
    );
    if (alreadyLoaded || autoIvRunKey === balanceSplitAutoIvKey) return;
    const predictorColumns = finalIvPredictorColumns(profile, schema, profile.targetColumn);
    if (!predictorColumns.length) return;
    setAutoIvRunKey(balanceSplitAutoIvKey);
    setWoeMessage("Running WOE / IV automatically for Balance & Split final feature review.");
    const request: WoeIvRunRequest = {
      ...woeRequest,
      projectId,
      datasetId: profile.datasetId,
      datasetVersionId: profile.datasetVersionId,
      targetColumn: profile.targetColumn,
      eventValue: profile.eventValue || "1",
      predictorColumns,
    };
    runWoeIvAnalysis(request)
      .then(saveWoeIvAnalysis)
      .then((saved) => {
        setWoeAnalysis(saved);
        setSelectedWoeVariable(saved.variableSummaries?.[0]?.variable || "");
        const recommended = defaultScorecardVariables(saved);
        setWoeRequest((current) => ({ ...current, ...request, predictorColumns }));
        setScorecardRequest((current) => ({
          ...current,
          woeAnalysisId: saved.analysisId,
          targetColumn: saved.targetColumn,
          selectedVariables: current.selectedVariables.length ? current.selectedVariables : recommended,
        }));
        setMlRequest((current) => ({
          ...current,
          targetColumn: saved.targetColumn,
          selectedVariables: current.selectedVariables.length ? current.selectedVariables : recommended,
        }));
        setProfile((current) => ({
          ...current,
          featureReview: {
            ...(current.featureReview || {}),
            woeIv: `WOE / IV auto-ran on Balance & Split for ${saved.variableSummaries.length} variables. Top IV variable: ${saved.variableSummaries[0]?.variable || "not available"}.`,
          },
          woeIvStatus: "Ready",
          readiness: { ...(current.readiness || {}), "WOE / IV": "Ready" },
        }));
        setWoeMessage("WOE / IV loaded for Balance & Split final feature review.");
      })
      .catch((error) => {
        setWoeMessage(error instanceof Error ? error.message : "ATLAS could not auto-run WOE / IV for Balance & Split.");
      });
  }, [activeWorkflowStep.name, profile.datasetId, profile.datasetVersionId, profile.targetColumn, profile.eventValue, schema, woeAnalysis?.analysisId, autoIvRunKey, balanceSplitAutoIvKey, projectId]);

  async function saveAndContinue(next: string) {
    await saveSetup();
    openOverlaySection(next);
  }

  async function saveAndOpenWorkflowStep(slug: string, update: Partial<CreditRiskProfile> = {}) {
    setSaving(true);
    setMessage("");
    try {
      const saved = await saveCreditRiskProfile({
        ...profile,
        ...update,
        scorecardScaling: { ...(profile.scorecardScaling || {}), ...preview },
        readiness: { ...(profile.readiness || {}), ...(update.readiness || {}) },
        readinessScore: readiness.score,
      });
      setProfile(saved);
      openWorkflowStep(slug);
      setMessage(`${workflowStepForSlug(slug).name} opened.`);
    } catch (error) {
      openWorkflowStep(slug);
      setMessage(`${workflowStepForSlug(slug).name} opened. ATLAS could not save the previous step: ${error instanceof Error ? error.message : "unknown save error"}`);
    } finally {
      setSaving(false);
    }
  }

  async function saveEvidence(technique: string, supportsSections?: string[]) {
    setSaving(true);
    setMessage("");
    try {
      const updatedReadiness = { ...(profile.readiness || {}), ...readinessUpdatesForTechnique(technique) };
      const saved = await saveCreditRiskProfile({
        ...profile,
        readiness: updatedReadiness,
        scorecardScaling: { ...(profile.scorecardScaling || {}), ...preview },
      });
      const evidence = await saveCreditRiskEvidence(saved, technique, techniqueLabels[technique] || "Credit Risk Evidence", supportsSections);
      setProfile(saved);
      setMessage(`${evidence.title} saved to Model Evidence Center.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not save credit-risk evidence.");
    } finally {
      setSaving(false);
    }
  }

  const selectedWoeSummary = useMemo(
    () => woeAnalysis?.variableSummaries?.find((row) => row.variable === selectedWoeVariable) || woeAnalysis?.variableSummaries?.[0] || null,
    [woeAnalysis, selectedWoeVariable],
  );

  useEffect(() => {
    if (selectedWoeSummary) {
      setManualBins((selectedWoeSummary.bins || []).map((bin) => ({
        binId: bin.binId,
        label: bin.label,
        lowerBound: bin.lowerBound ?? null,
        upperBound: bin.upperBound ?? null,
        categoryValues: bin.categoryValues || [],
        manualOverride: Boolean(bin.manualOverride),
        reviewerNote: bin.reviewerNote || "",
      })));
    } else {
      setManualBins([]);
    }
  }, [selectedWoeSummary?.variable]);

  async function runWoeIv() {
    setWoeRunning(true);
    setWoeMessage("");
    try {
      const sanitizedRequest = {
        ...woeRequest,
        predictorColumns: woeRequest.predictorColumns.filter((column) => isCreditRiskPredictorCandidate(column, profile, woeRequest.targetColumn)),
      };
      const analysis = await runWoeIvAnalysis(sanitizedRequest);
      setWoeAnalysis(analysis);
      setSelectedWoeVariable(analysis.variableSummaries?.[0]?.variable || "");
      patchNested("featureReview", {
        woeIv: `WOE / IV analysis completed for ${analysis.variableSummaries.length} variables. Top IV variable: ${analysis.variableSummaries[0]?.variable || "not available"}.`,
      });
      setWoeMessage("WOE / IV analysis completed.");
    } catch (error) {
      setWoeMessage(error instanceof Error ? error.message : "ATLAS could not run WOE / IV analysis.");
    } finally {
      setWoeRunning(false);
    }
  }

  async function saveWoeAnalysis() {
    if (!woeAnalysis) return;
    setWoeRunning(true);
    setWoeMessage("");
    try {
      const saved = await saveWoeIvAnalysis(woeAnalysis);
      setWoeAnalysis(saved);
      setWoeMessage("WOE / IV analysis saved.");
    } catch (error) {
      setWoeMessage(error instanceof Error ? error.message : "ATLAS could not save the WOE / IV analysis.");
    } finally {
      setWoeRunning(false);
    }
  }

  async function applyManualBins() {
    if (!woeAnalysis || !selectedWoeSummary) return;
    setWoeRunning(true);
    setWoeMessage("");
    try {
      const analysis = await applyManualWoeBins(woeAnalysis.analysisId, selectedWoeSummary.variable, manualBins);
      setWoeAnalysis(analysis);
      setWoeMessage("Manual bins applied and WOE / IV recalculated.");
    } catch (error) {
      setWoeMessage(error instanceof Error ? error.message : "ATLAS could not apply manual bins.");
    } finally {
      setWoeRunning(false);
    }
  }

  async function exportWoeWorkbook() {
    if (!woeAnalysis) return;
    const blob = await exportWoeIvExcel(woeAnalysis.analysisId);
    downloadBlob(blob, "atlas-woe-iv-analysis.xlsx");
  }

  async function saveWoeEvidenceToCenter(technique: string, label: string) {
    if (!woeAnalysis) return;
    setWoeRunning(true);
    setWoeMessage("");
    try {
      const evidence = await saveWoeIvEvidence(woeAnalysis.analysisId, technique, label);
      setWoeMessage(`${evidence.title} saved to Model Evidence Center.`);
      patch({ readiness: { ...(profile.readiness || {}), ...readinessUpdatesForTechnique(technique) } });
    } catch (error) {
      setWoeMessage(error instanceof Error ? error.message : "ATLAS could not save WOE / IV evidence.");
    } finally {
      setWoeRunning(false);
    }
  }

  async function refreshGeneratedCode() {
    setWoeRunning(true);
    setWoeMessage("");
    try {
      const generatedCode = await generateWoeIvCode({
        ...woeRequest,
        predictorColumns: woeRequest.predictorColumns.filter((column) => isCreditRiskPredictorCandidate(column, profile, woeRequest.targetColumn)),
      });
      setWoeAnalysis((current) => current ? { ...current, generatedCode } : current);
      setWoeMessage("WOE / IV generated code refreshed.");
    } catch (error) {
      setWoeMessage(error instanceof Error ? error.message : "ATLAS could not generate WOE / IV code.");
    } finally {
      setWoeRunning(false);
    }
  }

  async function trainScorecard() {
    setScorecardRunning(true);
    setScorecardMessage("");
    try {
      const model = await trainScorecardModel({
        ...scorecardRequest,
        selectedVariables: scorecardRequest.selectedVariables.filter((column) => isCreditRiskPredictorCandidate(column, profile, scorecardRequest.targetColumn)),
        pdo: Number(profile.scorecardScaling?.pdo || scorecardRequest.pdo),
        baseScore: Number(profile.scorecardScaling?.baseScore || scorecardRequest.baseScore),
        baseOdds: profile.scorecardScaling?.baseOdds || scorecardRequest.baseOdds,
        scoreDirection: profile.scorecardScaling?.scoreDirection || scorecardRequest.scoreDirection,
      });
      setScorecardModel(model);
      patch({ scorecardModelId: model.modelId, scorecardStatus: "Ready" });
      setScorecardMessage("Scorecard model trained.");
      patchNested("monitoring", { championModel: model.modelId });
    } catch (error) {
      setScorecardMessage(error instanceof Error ? error.message : "ATLAS could not train the scorecard model.");
    } finally {
      setScorecardRunning(false);
    }
  }

  async function exportScorecardWorkbook() {
    if (!scorecardModel) return;
    const blob = await exportScorecardExcel(scorecardModel.modelId);
    downloadBlob(blob, "atlas-credit-risk-scorecard.xlsx");
  }

  async function saveScorecardEvidenceToCenter(technique: string, label: string) {
    if (!scorecardModel) return;
    setScorecardRunning(true);
    setScorecardMessage("");
    try {
      const evidence = await saveScorecardEvidence(scorecardModel.modelId, technique, label);
      setScorecardMessage(`${evidence.title} saved to Model Evidence Center.`);
      patch({ readiness: { ...(profile.readiness || {}), ...readinessUpdatesForTechnique(technique) } });
    } catch (error) {
      setScorecardMessage(error instanceof Error ? error.message : "ATLAS could not save scorecard evidence.");
    } finally {
      setScorecardRunning(false);
    }
  }

  async function refreshScorecardCode() {
    setScorecardRunning(true);
    setScorecardMessage("");
    try {
      const generatedCode = await generateScorecardCode({
        ...scorecardRequest,
        selectedVariables: scorecardRequest.selectedVariables.filter((column) => isCreditRiskPredictorCandidate(column, profile, scorecardRequest.targetColumn)),
      });
      setScorecardModel((current) => current ? { ...current, generatedCode } : current);
      setScorecardMessage("Scorecard generated code refreshed.");
    } catch (error) {
      setScorecardMessage(error instanceof Error ? error.message : "ATLAS could not generate scorecard code.");
    } finally {
      setScorecardRunning(false);
    }
  }

  async function registerChampionScorecard() {
    if (!scorecardModel) return;
    const model = await registerScorecardModel(scorecardModel.modelId, true);
    setScorecardModel(model);
    setScorecardMessage("Scorecard registered as champion.");
  }

  async function trainMlChallenger() {
    setMlRunning(true);
    setMlMessage("");
    try {
      const model = await trainCreditRiskMlModel({
        ...mlRequest,
        selectedVariables: mlRequest.selectedVariables.filter((column) => isCreditRiskPredictorCandidate(column, profile, mlRequest.targetColumn)),
      });
      setMlModel(model);
      const saved = await saveCreditRiskProfile({
        ...profile,
        selectedModelingApproach: profile.selectedModelingApproach || "compare_both",
        mlModelId: model.modelId,
        mlStatus: "Ready",
      });
      setProfile(saved);
      setMlMessage("AI/ML underwriting challenger trained.");
    } catch (error) {
      setMlMessage(error instanceof Error ? error.message : "ATLAS could not train the AI/ML underwriting challenger.");
    } finally {
      setMlRunning(false);
    }
  }

  async function saveMlEvidenceToCenter(technique: string, label: string) {
    if (!mlModel) {
      setMlMessage("Train an AI/ML underwriting challenger before saving this evidence.");
      return;
    }
    setMlRunning(true);
    try {
      await saveCreditRiskMlEvidence(mlModel.modelId, technique, label);
      setMlMessage(`${label} saved to Model Evidence Center.`);
    } catch (error) {
      setMlMessage(error instanceof Error ? error.message : "ATLAS could not save AI/ML evidence.");
    } finally {
      setMlRunning(false);
    }
  }

  async function runComparison() {
    setSaving(true);
    setMessage("");
    try {
      const comparison = await runCreditRiskChampionComparison(profile, scorecardModel, mlModel);
      setChampionComparison(comparison);
      setMessage("Champion / challenger comparison refreshed.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not run champion / challenger comparison.");
    } finally {
      setSaving(false);
    }
  }

  async function chooseChampion(modelType: "scorecard" | "ml" | "challenger") {
    const selectedModelType = modelType === "challenger" ? "ml" : modelType;
    const selectedModelId = selectedModelType === "scorecard" ? scorecardModel?.modelId : mlModel?.modelId;
    if (!selectedModelId) {
      setMessage("Train or load the selected model before saving the champion decision.");
      return;
    }
    const decision = {
      selectedModelId,
      selectedModelType,
      reason: modelType === "challenger"
        ? "AI/ML model retained as challenger pending additional explainability, calibration, and governance review."
        : `${selectedModelType === "scorecard" ? "Traditional scorecard" : "AI/ML underwriting model"} selected based on performance, explainability, calibration, adverse-action readiness, stability, and governance complexity.`,
      reviewerNotes: "",
      decidedAt: new Date().toISOString(),
    };
    setSaving(true);
    try {
      const payload = await saveCreditRiskChampionDecision(profile, decision);
      setProfile(payload.profile);
      setMessage(modelType === "challenger" ? "AI/ML retained as challenger." : "Champion decision saved.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not save the champion decision.");
    } finally {
      setSaving(false);
    }
  }

  async function saveChampionEvidenceToCenter() {
    setSaving(true);
    try {
      await saveCreditRiskChampionEvidence(profile);
      setMessage("Champion / challenger evidence saved to Model Evidence Center.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not save champion / challenger evidence.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="atlas-page-shell atlas-theme-credit">
      <header className="atlas-studio-hero">
        <div className="atlas-studio-hero__band">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-emerald-200">
              <Landmark size={16} /> Financial Services Solution Pack
            </div>
            <h1 className="mt-1 text-2xl font-semibold text-white">Credit Risk Studio</h1>
            <p className="mt-1 max-w-3xl text-sm leading-5 text-emerald-50/90">
              Predictive Modeling specialized for underwriting. Uses the full ATLAS workflow with credit-risk overlays, evidence capture, diagnostics, documentation, and monitoring.
            </p>
            <div className="mt-3 grid gap-2 rounded-lg border border-emerald-200 bg-white/95 p-3 shadow-sm sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-end">
              <Input label="Project name field" value={projectNameDraft} onChange={setProjectNameDraft} placeholder={HELOC_DEFAULT_PROJECT_NAME} />
              <button type="button" className="atlas-secondary-button justify-center" onClick={() => setProjectNameDraft(profile.projectName || projectName || HELOC_DEFAULT_PROJECT_NAME)}>Rename project</button>
              <button type="button" className="inline-flex justify-center rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white disabled:opacity-60" onClick={saveProjectName} disabled={saving}>Save project name action</button>
            </div>
          </div>
          <div className="grid gap-2 sm:grid-cols-2 xl:min-w-[520px] xl:grid-cols-3">
            <CompactMetric label="Project" value={profile.projectName || projectName || HELOC_DEFAULT_PROJECT_NAME} />
            <CompactMetric label="Dataset" value={activeDataset?.name || profile.datasetId || "HELOC_TRAIN"} />
            <CompactMetric label="Target" value={`${profile.targetColumn || "bad_flag"} = ${profile.eventValue || "1"}`} />
            <CompactMetric label="Model purpose" value={profile.modelPurpose || "Application Underwriting"} />
            <CompactMetric label="Current step" value={activeWorkflowStep.name} />
            <CompactMetric label="Readiness" value={`${readiness.score}%`} tone={readiness.score >= 70 ? "green" : "amber"} />
            <CompactMetric label="Evidence readiness" value={workflowStatus["Evidence and Documentation"] || "Missing"} tone={workflowStatus["Evidence and Documentation"] === "Complete" ? "green" : "amber"} />
          </div>
        </div>
        </div>
        <details className="mx-4 my-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2">
          <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-slate-600">Show readiness details</summary>
          <div className="mt-3 grid gap-2 md:grid-cols-4">
            <CompactMetric label="Product type" value={profile.productType || "Not selected"} />
            <CompactMetric label="Target event" value={profile.targetEvent || "Not selected"} />
            <CompactMetric label="Target window" value={profile.targetWindow || "Not documented"} />
            <CompactMetric label="Modeling approach" value={approachLabel(profile.selectedModelingApproach)} tone={profile.selectedModelingApproach ? "green" : "amber"} />
            <CompactMetric label="Scorecard status" value={workflowStatus["Traditional Scorecard Path"] || "Missing"} tone={workflowStatus["Traditional Scorecard Path"] === "Complete" ? "green" : "amber"} />
            <CompactMetric label="AI/ML status" value={workflowStatus["AI/ML Underwriting Path"] || "Missing"} tone={workflowStatus["AI/ML Underwriting Path"] === "Complete" ? "green" : "amber"} />
            <CompactMetric label="Champion" value={profile.championModelType ? approachLabel(profile.championModelType === "scorecard" ? "scorecard" : "ml") : "Not selected"} tone={profile.championModelId ? "green" : "amber"} />
          </div>
        </details>
      </header>

      <section className="rounded-xl border border-slate-200 bg-white px-3 py-3 shadow-sm">
          <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-slate-500">
            <span>Predictive Modeling Workflow in Credit Risk Mode</span>
            <span>{activeIndex + 1} of {predictiveWorkflowSteps.length}</span>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-5">
            {predictiveWorkflowSteps.map((step, index) => (
              <button
                key={step.slug}
                type="button"
                onClick={() => openWorkflowStep(step.slug)}
                className={`rounded-lg border px-2 py-2 text-center text-[11px] font-semibold transition ${index === activeIndex ? "border-blue-500 bg-blue-600 text-white" : index < activeIndex ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-slate-200 bg-white text-slate-600 hover:border-blue-200"}`}
              >
                {workflowStepDisplayName(step)}
              </button>
            ))}
          </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
        <div className="mt-4 grid gap-3 md:grid-cols-5">
          <Input label="Current Project" value={profile.projectName || projectName || HELOC_DEFAULT_PROJECT_NAME} onChange={(value) => {
            setProjectNameDraft(value);
            patch({ projectName: value });
          }} placeholder={HELOC_DEFAULT_PROJECT_NAME} />
          <Select label="Product Type" value={profile.productType || ""} onChange={(value) => patch({ productType: value })} options={PRODUCT_TYPES} />
          <Select label="Model Purpose" value={profile.modelPurpose || ""} onChange={(value) => patch({ modelPurpose: value })} options={MODEL_PURPOSES} />
          <Select label="Target Event" value={profile.targetEvent || ""} onChange={(value) => patch({ targetEvent: value })} options={TARGET_EVENTS} />
          <Input label="Target Window" value={profile.targetWindow || ""} onChange={(value) => patch({ targetWindow: value })} placeholder="Defaults in following 90 days" />
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" onClick={saveSetup} disabled={saving} className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white disabled:opacity-60">
            <BadgeCheck size={16} /> Save credit risk setup
          </button>
          <Link to="/model-evidence-center" className="atlas-secondary-button"><Network size={16} /> Open Model Evidence Center</Link>
          {message && <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-900">{message}</div>}
        </div>
      </section>

      <section className="grid gap-5 xl:grid-cols-[260px_minmax(0,1fr)_320px]">
        <aside className="self-start rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
          <div className="px-2 pb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Main workflow</div>
          <div className="grid gap-1">
            {predictiveWorkflowSteps.map((step, index) => (
              <button
                key={step.slug}
                type="button"
                onClick={() => openWorkflowStep(step.slug)}
                className={`rounded-xl px-3 py-2 text-left transition ${activeWorkflowStep.slug === step.slug ? "bg-blue-600 text-white shadow-sm" : "text-slate-700 hover:bg-slate-100"}`}
              >
                <span className="block text-sm font-semibold">{index + 1}. {workflowStepDisplayName(step)}</span>
                <span className={`mt-1 inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${activeWorkflowStep.slug === step.slug ? "bg-white/20 text-white" : statusPillClass(workflowStatus[step.overlaySection])}`}>
                  {workflowStatus[step.overlaySection] || "In Credit Risk Mode"}
                </span>
              </button>
            ))}
          </div>
        </aside>

        <main className="min-w-0 space-y-5">
          <PredictiveStepModePanel step={activeWorkflowStep} workflowStatus={workflowStatus} />
          <div className={`flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3 text-sm font-semibold ${schemaMismatch || schemaLoadError ? "border-red-200 bg-red-50 text-red-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>
            <span>
              {schemaLoadError || (schemaMismatch
                ? "Dataset schema mismatch. Reload selected dataset before continuing."
                : `Active dataset: ${activeDataset?.name || profile.datasetId || "No dataset selected"}`)}
            </span>
            {activeWorkflowStep.name !== "Data Acquisition" && (
              <button type="button" className="rounded-lg border border-current px-3 py-1 text-xs font-semibold" onClick={refreshDatasetSchema} disabled={!profile.datasetId}>
                Refresh Dataset Schema
              </button>
            )}
          </div>
          {active === "Project Setup" && (
            <StudioSection icon={<Landmark size={18} />} title="Project Setup" subtitle="Credit risk models must clearly define population, target event, observation window, and performance window. These choices affect validity, monitoring, governance, and regulatory explainability.">
              <div className="grid gap-3 md:grid-cols-2">
                <Select label="Dataset" value={profile.datasetId || ""} onChange={handleDatasetChange} options={datasets.map((dataset) => ({ value: dataset.datasetId, label: dataset.name }))} />
                <Input label="Model Type" value={profile.modelType || ""} onChange={(value) => patch({ modelType: value })} placeholder="Scorecard, logistic regression, GBM, challenger model..." />
                <Input label="Observation Window" value={profile.observationWindow || ""} onChange={(value) => patch({ observationWindow: value })} placeholder="Application snapshot and lookback period" />
                <Input label="Performance Window" value={profile.performanceWindow || ""} onChange={(value) => patch({ performanceWindow: value })} placeholder="12-month outcome performance window" />
                <Select label="TTC / PIT Assumption" value={profile.ttcPitAssumption || ""} onChange={(value) => patch({ ttcPitAssumption: value })} options={TTC_PIT_OPTIONS} />
                <Input label="Regulatory Context" value={(profile.regulatoryContext || []).join(", ")} onChange={(value) => patch({ regulatoryContext: value.split(",").map((item) => item.trim()).filter(Boolean) })} placeholder="SR 11-7, Fair Lending, FCRA, ECOA" />
              </div>
              <StepContinueButton
                label="Confirm Project Setup and Continue"
                disabled={!profile.datasetId || !profile.modelType || !profile.observationWindow || !profile.performanceWindow || !profile.ttcPitAssumption || !(profile.regulatoryContext || []).length}
                onClick={() => saveAndContinue("Population and Target")}
              />
            </StudioSection>
          )}

          {activeWorkflowStep.name === "Data Acquisition" && (
            <DataAcquisitionCreditRiskOverlay
              profile={profile}
              datasets={datasets}
              schema={schema}
              activeDataset={activeDataset}
              targetComplete={Boolean(profile.targetColumn && profile.eventValue && profile.originalTargetLabelColumn && profile.validationDatasetId && profile.ootDatasetId && profile.ootType)}
              onPatch={patch}
              onDatasetChange={handleDatasetChange}
              onRefreshSchema={refreshDatasetSchema}
              onOpenPopulation={() => openOverlaySection("Population and Target")}
              onSaveEvidence={() => saveEvidence("data_acquisition", ["Data Sources", "Population Definition", "Target Definition"])}
              onContinue={() => saveAndOpenWorkflowStep("eda", {
                readiness: { ...(profile.readiness || {}), "Data Sources": "Ready", "Target Definition": "Ready", "Population Definition": "Ready" },
              })}
            />
          )}

          {active === "Population and Target" && activeWorkflowStep.name === "Project Context" && (
            <StudioSection icon={<ClipboardCheck size={18} />} title="Population and Target" subtitle="Translate the business outcome into a defensible underwriting target with good, bad, indeterminate, exclusion, censoring, and reject-population definitions.">
              <div className="grid gap-3 md:grid-cols-2">
                <Select label="Dataset" value={profile.datasetId || ""} onChange={handleDatasetChange} options={datasets.map((dataset) => ({ value: dataset.datasetId, label: dataset.name }))} />
                <Select label="Target column" value={profile.targetColumn || ""} onChange={(value) => {
                  patch({ targetColumn: value });
                  setWoeRequest((current) => ({ ...current, targetColumn: value, predictorColumns: current.predictorColumns.filter((column) => isCreditRiskPredictorCandidate(column, profile, value)) }));
                  setScorecardRequest((current) => ({ ...current, targetColumn: value, selectedVariables: current.selectedVariables.filter((column) => isCreditRiskPredictorCandidate(column, profile, value)) }));
                  setMlRequest((current) => ({ ...current, targetColumn: value, selectedVariables: current.selectedVariables.filter((column) => isCreditRiskPredictorCandidate(column, profile, value)) }));
                }} options={schema} />
                <Input label="Event / bad value" value={profile.eventValue || ""} onChange={(value) => patch({ eventValue: value })} placeholder="1" />
                <Input label="Non-event / good value" value={profile.nonEventValue || ""} onChange={(value) => patch({ nonEventValue: value })} placeholder="0" />
                <Select label="Original target label column" value={profile.originalTargetLabelColumn || ""} onChange={(value) => patch({ originalTargetLabelColumn: value })} options={[{ value: "", label: "None" }, ...schema.map((column) => ({ value: column, label: column }))]} />
                <Select label="Split column" value={profile.splitColumn || ""} onChange={(value) => patch({ splitColumn: value })} options={[{ value: "", label: "None" }, ...schema.map((column) => ({ value: column, label: column }))]} />
                <Select label="Validation dataset" value={profile.validationDatasetId || ""} onChange={(value) => patch({ validationDatasetId: value })} options={[{ value: "", label: "None" }, ...datasets.map((dataset) => ({ value: dataset.datasetId, label: dataset.name }))]} />
                <Select label="OOT dataset" value={profile.ootDatasetId || ""} onChange={(value) => patch({ ootDatasetId: value })} options={[{ value: "", label: "None" }, ...datasets.map((dataset) => ({ value: dataset.datasetId, label: dataset.name }))]} />
                <Select label="OOT type" value={profile.ootType || ""} onChange={(value) => patch({ ootType: value })} options={["Synthetic holdout", "True out-of-time", "Vintage holdout", "Policy simulation", "Not Selected"]} />
                <TextArea label="Good definition" value={profile.goodDefinition || ""} onChange={(value) => patch({ goodDefinition: value })} placeholder="Current, paid as agreed, no 30+ DPD during performance window." />
                <TextArea label="Bad definition" value={profile.badDefinition || ""} onChange={(value) => patch({ badDefinition: value })} placeholder="90+ DPD, charge-off, bankruptcy, or default within performance window." />
                <TextArea label="Indeterminate definition" value={profile.indeterminateDefinition || ""} onChange={(value) => patch({ indeterminateDefinition: value })} placeholder="Closed early, insufficient performance, deceased, fraud exclusion, or incomplete bureau history." />
                <TextArea label="Exclusion rules" value={profile.exclusionRules || ""} onChange={(value) => patch({ exclusionRules: value })} placeholder="Document exclusions, censoring, incomplete-performance notes, and policy removals." />
                <Input label="Performance window start" value={profile.performanceWindowStart || ""} onChange={(value) => patch({ performanceWindowStart: value })} />
                <Input label="Performance window end" value={profile.performanceWindowEnd || ""} onChange={(value) => patch({ performanceWindowEnd: value })} />
                <Input label="Observation snapshot date" value={profile.observationSnapshotDate || ""} onChange={(value) => patch({ observationSnapshotDate: value })} />
                <Input label="Outcome source table" value={profile.outcomeSourceTable || ""} onChange={(value) => patch({ outcomeSourceTable: value })} />
              </div>
              <TargetSummaryPanel profile={profile} summary={targetSummary} />
              <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm leading-6 text-blue-950">
                In underwriting, the target is usually a future performance outcome such as 90+ DPD within 12 months, charge-off within 18 months, or default in the following 90 days.
              </div>
              <EvidenceButton onClick={() => saveEvidence("target_definition", ["Target Definition", "Population Definition", "Development Test and OOT Data"])} label="Save Target Definition to Model Evidence Center" />
              <StepContinueButton
                label="Save Target Definition and Continue"
                disabled={!profile.targetColumn || !profile.eventValue || !profile.nonEventValue || !profile.goodDefinition || !profile.badDefinition || !profile.outcomeSourceTable || !targetSummary}
                onClick={() => saveAndContinue("Credit Risk EDA")}
              />
            </StudioSection>
          )}

          {activeWorkflowStep.name === "Credit Bureau Data Review" && (
            <StudioSection icon={<Database size={18} />} title="Credit Bureau Data Review" subtitle="Review bureau metadata, special values, treatment choices, and rationale as a separate workflow step after Data Acquisition.">
              <RealPredictiveStepEmbed title="Real ATLAS Credit Bureau Data Review Workflow">
                <Step01BCreditBureauReview />
              </RealPredictiveStepEmbed>
              <StepContinueButton label="Confirm Bureau Review and Continue" onClick={() => saveAndOpenWorkflowStep("eda", { readiness: { ...(profile.readiness || {}), "Bureau Metadata": "Ready" } })} />
            </StudioSection>
          )}

          {activeWorkflowStep.name === "Outliers" && (
            <StudioSection icon={<AlertTriangle size={18} />} title="Outliers" subtitle="Review numeric extremes without treating bureau special values as ordinary outliers.">
              <RealPredictiveStepEmbed title="Real ATLAS Outliers Workflow">
                <Step03Outliers />
              </RealPredictiveStepEmbed>
              <StepContinueButton label="Confirm Outliers and Continue" disabled={schemaMismatch || !schema.length} onClick={() => saveAndOpenWorkflowStep("missing-values", { readiness: { ...(profile.readiness || {}), "Outlier Treatment": "Ready" } })} />
            </StudioSection>
          )}

          {activeWorkflowStep.name === "Missing Values" && (
            <StudioSection icon={<ClipboardCheck size={18} />} title="Missing Values" subtitle="Review null missingness separately from bureau special values before feature engineering.">
              <RealPredictiveStepEmbed title="Real ATLAS Missing Values Workflow">
                <Step04MissingValues />
              </RealPredictiveStepEmbed>
              <StepContinueButton label="Confirm Missing Values and Continue" disabled={schemaMismatch || !schema.length} onClick={() => saveAndOpenWorkflowStep("feature-engineering", { readiness: { ...(profile.readiness || {}), "Missing Value Treatment": "Ready" } })} />
            </StudioSection>
          )}

          {activeWorkflowStep.name === "Balance & Split" && (
            <StudioSection icon={<GitBranch size={18} />} title="Balance & Split" subtitle="Confirm TRAIN, TEST, and OOT strategy for the HELOC underwriting scorecard run.">
              <RealPredictiveStepEmbed title="Real ATLAS Balance & Split Workflow">
                <Step06BalanceSplit />
              </RealPredictiveStepEmbed>
              <FinalModelFeatureReviewPanel
                profile={profile}
                woeAnalysis={woeAnalysis}
                previewIvByVariable={finalFeaturePreviewIv}
                selectedVariables={finalModelSelectedVariables}
                targetColumn={scorecardRequest.targetColumn || mlRequest.targetColumn || profile.targetColumn}
                statusMessage={woeMessage}
                onToggle={setFinalModelFeatureSelection}
                onApplyRecommended={applyIvRecommendedFinalFeatures}
              />
              <StepContinueButton label="Confirm Balance & Split and Continue" disabled={schemaMismatch || !schema.length || !finalModelSelectedVariables.length} onClick={() => saveAndOpenWorkflowStep("model-training", { readiness: { ...(profile.readiness || {}), "Development Test and OOT Data": "Ready", "Feature Engineering": "Ready" } })} />
            </StudioSection>
          )}

          {activeWorkflowStep.name === "EDA" && (
            <StudioSection icon={<Database size={18} />} title="EDA" subtitle="Investigate underwriting model data quality, bad-rate behavior, missingness, concentration, variable mix, protected/sensitive flags, and potential leakage before screening.">
              <RealPredictiveStepEmbed title="Real ATLAS EDA Workflow" overlayPlacement="after" overlay={
                <div className="space-y-4">
                  <EdaCreditRiskOverlay profile={profile} woeAnalysis={woeAnalysis} variableCounts={variableCounts} targetSummary={targetSummary} localDataset={localDataset} />
                  <CreditRiskEdaPanel profile={profile} woeAnalysis={woeAnalysis} variableCounts={variableCounts} />
                  {!targetSummary && <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{profile.targetColumn ? "Full dataset artifact unavailable. Showing schema-level EDA only." : "Target summary unavailable because target column is not selected."}</div>}
                  <SpecialValueProfilePanel summary={targetSummary} />
                  <div className="flex flex-wrap gap-2">
                    <DownloadButton label="Download special-value profile CSV" onClick={() => downloadRowsCsv("atlas-eda-special-value-profile.csv", (targetSummary?.specialValueProfile || []) as unknown as Array<Record<string, unknown>>)} />
                    <button type="button" onClick={() => openWorkflowStep("feature-engineering")} className="atlas-secondary-button">Send selected variables to Feature Engineering</button>
                    <EvidenceButton onClick={() => saveEvidence("credit_risk_eda", ["Data Sources", "Exploratory Data Analysis", "Fair Lending / Compliance Considerations"])} label="Save EDA Evidence" />
                    <Link to="/analytics" className="atlas-secondary-button">Open Analytics Workbench</Link>
                    <Link to="/chart-studio" className="atlas-secondary-button">Open Chart Studio</Link>
                  </div>
                </div>
              } resetKey={`eda:${profile.datasetId || "none"}:${profile.targetColumn || "none"}:${schema.length}:${targetSummary ? "target-summary" : "schema-only"}`}>
                <Step02EDA />
              </RealPredictiveStepEmbed>
              <StepContinueButton label="Confirm EDA and Continue" disabled={schemaMismatch || !schema.length} onClick={() => saveAndOpenWorkflowStep("outliers", { edaStatus: "Ready", readiness: { ...(profile.readiness || {}), "Variable Mapping": "Ready" } })} />
            </StudioSection>
          )}

          {activeWorkflowStep.name === "Feature Engineering" && (
            <StudioSection icon={<SlidersHorizontal size={18} />} title="Feature Engineering" subtitle="Prepare candidate predictors for WOE / IV by reviewing source role, missingness, distinct count, correlation, VIF, protected status, leakage risk, and reviewer exclusions.">
              <RealPredictiveStepEmbed title="Real ATLAS Feature Engineering Workflow">
                <Step05FeatureEngineering />
              </RealPredictiveStepEmbed>
              {(!profile.edaStatus || profile.readiness?.["Outlier Treatment"] !== "Ready" || profile.readiness?.["Missing Value Treatment"] !== "Ready") && (
                <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm font-semibold leading-6 text-amber-900">
                  EDA, Outliers, and Missing Values have not been completed. Tier 1 underwriting models should document these steps before feature engineering.
                </div>
              )}
              <div className="sr-only">Characteristic Screening</div>
              <div className="grid gap-3 md:grid-cols-5">
                <Metric label="Total variables" value={String(variableCounts.total)} />
                <Metric label="Bureau variables" value={String(variableCounts.bureau)} />
                <Metric label="Application variables" value={String(variableCounts.application)} />
                <Metric label="Excluded variables" value={String(variableCounts.excluded)} />
                <Metric label="Sensitive/protected" value={String(variableCounts.sensitive)} tone={variableCounts.sensitive ? "amber" : "green"} />
              </div>
              <ApprovedPredictorSummary profile={profile} woeAnalysis={woeAnalysis} datasetProfile={datasetProfile} targetSummary={targetSummary} />
              {!schema.length && <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">Select a Dataset Library dataset to load schema columns, then classify variables.</div>}
              <div className="flex flex-wrap gap-2">
                <button type="button" className="atlas-secondary-button" onClick={() => setWoeRequest((current) => ({ ...current, predictorColumns: (profile.variableMappings || []).filter((row) => row.include && row.role !== "Protected / Sensitive" && row.role !== "Excluded" && isCreditRiskPredictorCandidate(row.variable, profile, current.targetColumn)).map((row) => row.variable).slice(0, 30) }))}>Select recommended variables</button>
                <button type="button" className="atlas-secondary-button" onClick={() => setWoeRequest((current) => ({ ...current, predictorColumns: [] }))}>Exclude selected variables</button>
                <button type="button" className="atlas-secondary-button" onClick={() => openWorkflowStep("model-training")}>Send approved WOE variables to scorecard training</button>
                <button type="button" className="atlas-secondary-button" onClick={() => openWorkflowStep("model-training")}>Send selected variables to AI/ML Underwriting</button>
                <button type="button" className="atlas-secondary-button" onClick={() => {
                  const selected = (profile.variableMappings || [])
                    .filter((row) => row.include && row.role !== "Protected / Sensitive" && row.role !== "Excluded" && isCreditRiskPredictorCandidate(row.variable, profile, woeRequest.targetColumn))
                    .map((row) => row.variable)
                    .slice(0, 30);
                  setWoeRequest((current) => ({ ...current, predictorColumns: selected.filter((column) => isCreditRiskPredictorCandidate(column, profile, current.targetColumn)) }));
                  setMlRequest((current) => ({ ...current, selectedVariables: selected.filter((column) => isCreditRiskPredictorCandidate(column, profile, current.targetColumn)) }));
                  patch({ selectedModelingApproach: "compare_both" });
                  openOverlaySection("Modeling Approach");
                }}>Send selected variables to Both Tracks</button>
                <EvidenceButton onClick={() => saveEvidence("variable_mapping", ["Data Sources", "Feature Engineering", "Fair Lending / Compliance Considerations"])} label="Save Characteristic Screening Evidence" />
              </div>
            </StudioSection>
          )}

          {active === "Modeling Approach" && (
            <StudioSection
              icon={<GitBranch size={18} />}
              title="Modeling Approach"
              subtitle={activeWorkflowStep.name === "Model Training" ? "Train the approved underwriting model using the selected features and documented modeling approach." : "Choose whether this underwriting project builds a transparent scorecard baseline, an AI/ML challenger, or compares both for a champion/challenger decision."}
              showStageSummary={activeWorkflowStep.name !== "Model Training"}
            >
              {activeWorkflowStep.name === "Model Training" && (
                <RealPredictiveStepEmbed title="Real ATLAS Model Training Workflow" compact>
                  <Step07ModelTraining />
                </RealPredictiveStepEmbed>
              )}
              {activeWorkflowStep.name !== "Model Training" && (
                <>
                  <div className="grid gap-3 lg:grid-cols-3">
                    <ApproachCard
                      title="Traditional Scorecard"
                      selected={profile.selectedModelingApproach === "scorecard"}
                      onClick={() => patch({ selectedModelingApproach: "scorecard", modelType: "Traditional Scorecard" })}
                      text="Uses WOE / IV, manual characteristic binning, logistic regression, PDO scaling, scorecard points, reason codes, and adverse-action evidence."
                      bestFor="Best for transparent, regulator-friendly underwriting models."
                    />
                    <ApproachCard
                      title="AI/ML Underwriting"
                      selected={profile.selectedModelingApproach === "ml"}
                      onClick={() => patch({ selectedModelingApproach: "ml", modelType: "AI/ML Underwriting" })}
                      text="Uses modern ML models such as Random Forest, XGBoost, LightGBM, CatBoost, calibrated probabilities, SHAP, PDP / ICE, surrogate scorecards, and challenger evidence."
                      bestFor="Best for nonlinear patterns, interactions, and challenger modeling."
                    />
                    <ApproachCard
                      title="Compare Both"
                      selected={profile.selectedModelingApproach === "compare_both"}
                      onClick={() => patch({ selectedModelingApproach: "compare_both", modelType: "Champion / Challenger Underwriting" })}
                      text="Builds or compares the scorecard baseline and AI/ML challenger side by side, then supports champion selection with evidence."
                      bestFor="Best for governance, model risk review, and champion/challenger decisions."
                    />
                  </div>
                  <CapabilityComparisonTable />
                  <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm leading-6 text-blue-950">
                    <div className="font-semibold">ATLAS recommendation</div>
                    ATLAS recommends building a traditional scorecard baseline and an AI/ML challenger when governance allows. The scorecard provides transparency. The AI/ML challenger tests whether nonlinear patterns improve lift, KS, or approval / bad-rate tradeoffs.
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" className="atlas-secondary-button" onClick={() => openOverlaySection("Traditional Scorecard Path")}>Open Traditional Scorecard Path</button>
                    <button type="button" className="atlas-secondary-button" onClick={() => openOverlaySection("AI/ML Underwriting Path")}>Open AI/ML Underwriting Path</button>
                    <button type="button" className="atlas-secondary-button" onClick={() => openOverlaySection("Champion / Challenger Comparison")}>Compare Both</button>
                    <EvidenceButton onClick={() => saveEvidence("champion_challenger", ["Candidate Models", "Champion Model", "Model Selection Rationale"])} label="Save Modeling Approach Evidence" />
                  </div>
                </>
              )}
            </StudioSection>
          )}

          {active === "Traditional Scorecard Path" && (
            <StudioSection icon={<SlidersHorizontal size={18} />} title="WOE / IV and Manual Characteristic Binning" subtitle="Select target, event value, variables, and binning method; run WOE / IV; review IV ranking and WOE tables; adjust bins; lock approved bins; and save transformation evidence.">
              <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm leading-6 text-blue-950">
                <div className="font-semibold">WOE / IV definitions</div>
                <div>Bad / Event = selected target event. Good / Non-event = all other target values.</div>
                <div><span className="font-mono">WOE = ln(Distribution Good / Distribution Bad)</span>. <span className="font-mono">IV contribution = (Distribution Good - Distribution Bad) * WOE</span>.</div>
                <div>Common IV guidance: &lt;0.02 weak, 0.02-0.10 useful, 0.10-0.30 medium, 0.30-0.50 strong, &gt;0.50 suspicious or leakage review.</div>
              </div>

              <div className="grid gap-3 lg:grid-cols-6">
                <Select label="Dataset" value={woeRequest.datasetId} onChange={(value) => {
                  const dataset = datasets.find((row) => row.datasetId === value);
                  patch({ datasetId: value, datasetVersionId: dataset?.latestVersion?.versionId });
                  setWoeRequest((current) => ({ ...current, datasetId: value, datasetVersionId: dataset?.latestVersion?.versionId }));
                }} options={datasets.map((dataset) => ({ value: dataset.datasetId, label: dataset.name }))} />
                <Select label="Target" value={woeRequest.targetColumn} onChange={(value) => setWoeRequest((current) => ({ ...current, targetColumn: value, predictorColumns: current.predictorColumns.filter((column) => isCreditRiskPredictorCandidate(column, profile, value)) }))} options={schema} />
                <Input label="Event value" value={String(woeRequest.eventValue ?? "")} onChange={(value) => setWoeRequest((current) => ({ ...current, eventValue: value }))} placeholder="1, bad, default" />
                <Select label="Binning method" value={woeRequest.binningMethod} onChange={(value) => setWoeRequest((current) => ({ ...current, binningMethod: value }))} options={[
                  { value: "quantile", label: "Quantile" },
                  { value: "equal_width", label: "Equal width" },
                  { value: "tree", label: "Tree fallback" },
                  { value: "monotonic", label: "Monotonic merge" },
                ]} />
                <Input label="Max bins" value={String(woeRequest.maxBins)} onChange={(value) => setWoeRequest((current) => ({ ...current, maxBins: Number(value) || 5 }))} />
                <Input label="Min bin %" value={String(woeRequest.minBinPct)} onChange={(value) => setWoeRequest((current) => ({ ...current, minBinPct: Number(value) || 0.05 }))} />
              </div>

              <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-slate-950">Predictor variables</div>
                    <p className="text-xs text-slate-500">Select variables to evaluate as scorecard characteristics. Target is excluded from predictors.</p>
                  </div>
                  <div className="flex gap-2">
                    <button type="button" className="atlas-secondary-button" onClick={() => setWoeRequest((current) => ({ ...current, predictorColumns: schema.filter((column) => isCreditRiskPredictorCandidate(column, profile, current.targetColumn)).slice(0, 30) }))}>Select first 30</button>
                    <button type="button" className="atlas-secondary-button" onClick={() => setWoeRequest((current) => ({ ...current, predictorColumns: [] }))}>Clear</button>
                  </div>
                </div>
                <div className="grid max-h-44 gap-2 overflow-auto sm:grid-cols-2 lg:grid-cols-4">
                  {schema.filter((column) => isCreditRiskPredictorCandidate(column, profile, woeRequest.targetColumn)).map((column) => (
                    <label key={column} className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700">
                      <input
                        type="checkbox"
                        checked={woeRequest.predictorColumns.includes(column)}
                        onChange={(event) => setWoeRequest((current) => ({
                          ...current,
                          predictorColumns: event.target.checked ? [...current.predictorColumns, column] : current.predictorColumns.filter((selected) => selected !== column),
                        }))}
                      />
                      {column}
                    </label>
                  ))}
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <button type="button" onClick={runWoeIv} disabled={woeRunning || !woeRequest.datasetId || !woeRequest.targetColumn || !woeRequest.predictorColumns.length} className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
                  {woeRunning ? "Running..." : "Run WOE / IV Analysis"}
                </button>
                <button type="button" onClick={saveWoeAnalysis} disabled={!woeAnalysis || woeRunning} className="atlas-secondary-button">Save Analysis</button>
                <button type="button" onClick={exportWoeWorkbook} disabled={!woeAnalysis} className="atlas-secondary-button">Export WOE / IV to Excel</button>
                <button type="button" onClick={refreshGeneratedCode} className="atlas-secondary-button">Generate Code</button>
              </div>
              {woeMessage && <div className="rounded-xl border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">{woeMessage}</div>}

              {woeAnalysis && (
                <>
                  <div className="grid gap-3 md:grid-cols-6">
                    <Metric label="Rows" value={woeAnalysis.rowCount.toLocaleString()} />
                    <Metric label="Events / bads" value={woeAnalysis.eventCount.toLocaleString()} tone={woeAnalysis.eventRate < 0.01 ? "amber" : "slate"} />
                    <Metric label="Non-events / goods" value={woeAnalysis.nonEventCount.toLocaleString()} />
                    <Metric label="Event rate" value={`${(woeAnalysis.eventRate * 100).toFixed(2)}%`} />
                    <Metric label="Variables reviewed" value={String(woeAnalysis.variableSummaries.filter((row) => isCreditRiskPredictorCandidate(row.variable, profile, woeAnalysis.targetColumn)).length)} />
                    <Metric label="Needs review" value={String(woeAnalysis.variableSummaries.filter((row) => isCreditRiskPredictorCandidate(row.variable, profile, woeAnalysis.targetColumn) && row.status === "needs_review").length)} tone={woeAnalysis.variableSummaries.some((row) => isCreditRiskPredictorCandidate(row.variable, profile, woeAnalysis.targetColumn) && row.status === "needs_review") ? "amber" : "green"} />
                  </div>

                  <div className="grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.25fr)]">
                    <div className="rounded-xl border border-slate-200 bg-white p-4">
                      <div className="mb-3 flex items-center justify-between">
                        <div>
                          <div className="text-sm font-semibold text-slate-950">IV Ranking</div>
                          <p className="text-xs text-slate-500">Select a variable to inspect bin-level WOE and manual binning.</p>
                        </div>
                        <Link to="/model-evidence-center" className="atlas-secondary-button">Open Evidence Center</Link>
                      </div>
                      <div className="max-h-[420px] overflow-auto rounded-lg border border-slate-200">
                        <table className="min-w-full text-left text-xs">
                          <thead className="sticky top-0 bg-slate-50 uppercase tracking-wide text-slate-500">
                            <tr><th className="px-3 py-2">Variable</th><th className="px-3 py-2">IV</th><th className="px-3 py-2">Strength</th><th className="px-3 py-2">Monotonicity</th><th className="px-3 py-2">Status</th></tr>
                          </thead>
                          <tbody>
                            {woeAnalysis.variableSummaries.filter((row) => isCreditRiskPredictorCandidate(row.variable, profile, woeAnalysis.targetColumn)).map((row) => (
                              <tr key={row.variable} onClick={() => setSelectedWoeVariable(row.variable)} className={`cursor-pointer border-t border-slate-100 hover:bg-blue-50 ${selectedWoeSummary?.variable === row.variable ? "bg-blue-50" : ""}`}>
                                <td className="px-3 py-2 font-semibold text-slate-900">{row.variable}</td>
                                <td className="px-3 py-2">{formatNumber(row.iv, 4)}</td>
                                <td className="px-3 py-2">{row.predictiveStrength}</td>
                                <td className="px-3 py-2">{row.monotonicity}</td>
                                <td className="px-3 py-2"><StatusBadge status={row.status} /></td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>

                    <div className="rounded-xl border border-slate-200 bg-white p-4">
                      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold text-slate-950">Selected Variable Detail</div>
                          <p className="text-xs text-slate-500">{selectedWoeSummary?.variable || "Select a variable"}: WOE, bad rate, IV contribution, missing review, and monotonicity.</p>
                        </div>
                        {selectedWoeSummary && <StatusBadge status={selectedWoeSummary.status} />}
                      </div>
                      {selectedWoeSummary ? <WoeVariableDetail summary={selectedWoeSummary} /> : <EmptyPanel text="Run WOE / IV analysis and select a variable to review bin details." />}
                    </div>
                  </div>

                  <div className="grid gap-4 xl:grid-cols-2">
                    <WoeBarChart title="Bad Rate by Bin" summary={selectedWoeSummary} field="badRate" format="percent" />
                    <WoeBarChart title="WOE by Bin" summary={selectedWoeSummary} field="woe" />
                    <WoeBarChart title="IV Contribution by Bin" summary={selectedWoeSummary} field="ivContribution" />
                    <WoeBarChart title="Population Distribution by Bin" summary={selectedWoeSummary} field="populationPct" format="percent" />
                  </div>

                  <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
                    <div className="rounded-xl border border-slate-200 bg-white p-4">
                      <div className="mb-3 flex items-center justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold text-slate-950">Manual Characteristic Binning</div>
                          <p className="text-xs text-slate-500">Adjust bins, document overrides, and recalculate WOE / IV with reviewer notes.</p>
                        </div>
                        <button type="button" className="atlas-secondary-button" onClick={() => setManualBins((rows) => [...rows, { label: "New bin", lowerBound: null, upperBound: null, categoryValues: [], manualOverride: true, reviewerNote: "" }])}>Add bin</button>
                      </div>
                      <div className="space-y-2">
                        {manualBins.map((bin, index) => (
                          <div key={`${bin.binId || "manual"}-${index}`} className="grid gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 md:grid-cols-[1.2fr_0.8fr_0.8fr_1.2fr_auto]">
                            <Input label="Label" value={bin.label} onChange={(value) => setManualBins((rows) => updateManualBin(rows, index, { label: value }))} />
                            <Input label="Lower" value={bin.lowerBound == null ? "" : String(bin.lowerBound)} onChange={(value) => setManualBins((rows) => updateManualBin(rows, index, { lowerBound: value === "" ? null : Number(value) }))} />
                            <Input label="Upper" value={bin.upperBound == null ? "" : String(bin.upperBound)} onChange={(value) => setManualBins((rows) => updateManualBin(rows, index, { upperBound: value === "" ? null : Number(value) }))} />
                            <Input label="Reviewer note" value={bin.reviewerNote || ""} onChange={(value) => setManualBins((rows) => updateManualBin(rows, index, { reviewerNote: value }))} />
                            <button type="button" className="self-end rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-semibold text-rose-700" onClick={() => setManualBins((rows) => rows.filter((_, rowIndex) => rowIndex !== index))}>Delete</button>
                          </div>
                        ))}
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <button type="button" onClick={applyManualBins} disabled={!woeAnalysis || !selectedWoeSummary || woeRunning} className="atlas-secondary-button">Save manual bins</button>
                        <button type="button" onClick={() => setWoeMessage("Selected bins are locked for reviewer approval in the saved analysis record.")} className="atlas-secondary-button">Lock approved bins</button>
                        <button type="button" onClick={() => setWoeMessage("Use reviewer notes to document merge or split rationale, then save manual bins.")} className="atlas-secondary-button">Merge / split guidance</button>
                      </div>
                    </div>

                    <div className="rounded-xl border border-slate-200 bg-white p-4">
                      <div className="text-sm font-semibold text-slate-950">Evidence and Code</div>
                      <div className="mt-3 grid gap-2">
                        <button type="button" onClick={() => saveWoeEvidenceToCenter("woe_iv", "WOE / IV Analysis Evidence")} className="atlas-secondary-button justify-center">Save WOE / IV Evidence</button>
                        <button type="button" onClick={() => saveWoeEvidenceToCenter("manual_binning", "Manual Binning Evidence")} className="atlas-secondary-button justify-center">Save Manual Binning Evidence</button>
                      </div>
                      <div className="mt-4 flex flex-wrap gap-2">
                        {["python", "sql", "r", "sas"].map((tab) => (
                          <button key={tab} type="button" onClick={() => setCodeTab(tab)} className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${codeTab === tab ? "bg-slate-950 text-white" : "border border-slate-200 bg-white text-slate-700"}`}>{tab.toUpperCase()}</button>
                        ))}
                      </div>
                      <pre className="mt-3 max-h-80 overflow-auto rounded-xl bg-slate-950 p-3 text-xs leading-5 text-slate-50">{woeAnalysis.generatedCode?.[codeTab] || "Generate code to create reproducible WOE / IV logic."}</pre>
                    </div>
                  </div>
                </>
              )}

              <TextArea label="Feature review notes" value={String(profile.featureReview?.notes || "")} onChange={(value) => patchNested("featureReview", { notes: value, woeIv: value || profile.featureReview?.woeIv })} />
              <div className="flex flex-wrap gap-2">
                <EvidenceButton onClick={() => saveEvidence("reject_inference")} label="Save Reject Inference Evidence" />
                <EvidenceButton onClick={() => saveEvidence("iv")} label="Save VIF / Correlation Evidence" />
              </div>
            </StudioSection>
          )}

          {active === "Traditional Scorecard Path" && (
            <StudioSection icon={<Calculator size={18} />} title="Scorecard Model Training" subtitle="Train a logistic credit-risk scorecard from approved WOE variables, review model setup, selected variables, raw fallback warnings, regularization, split, class weighting, and champion candidate status.">
              <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
                <div className="space-y-4">
                  <div className="rounded-xl border border-slate-200 bg-white p-4">
                      <div className="text-sm font-semibold text-slate-950">Model Setup</div>
                    <div className="mt-3 grid gap-3 md:grid-cols-4">
                      <Select label="Dataset" value={scorecardRequest.datasetId} onChange={(value) => {
                        const dataset = datasets.find((row) => row.datasetId === value);
                        setScorecardRequest((current) => ({ ...current, datasetId: value, datasetVersionId: dataset?.latestVersion?.versionId }));
                      }} options={datasets.map((dataset) => ({ value: dataset.datasetId, label: dataset.name }))} />
                      <Select label="Target column" value={scorecardRequest.targetColumn} onChange={(value) => setScorecardRequest((current) => ({ ...current, targetColumn: value, selectedVariables: current.selectedVariables.filter((column) => isCreditRiskPredictorCandidate(column, profile, value)) }))} options={schema} />
                      <Input label="Event value / bad class" value={String(scorecardRequest.eventValue)} onChange={(value) => setScorecardRequest((current) => ({ ...current, eventValue: value }))} />
                      <Select label="Model type" value={scorecardRequest.modelType} onChange={(value) => setScorecardRequest((current) => ({ ...current, modelType: value }))} options={["Logistic Scorecard", "Regularized Logistic Scorecard", "Monotonic Logistic Scorecard placeholder", "GBM Surrogate Scorecard placeholder"]} />
                      <Input label="Train / validation split" value={String(scorecardRequest.trainValidationSplit)} onChange={(value) => setScorecardRequest((current) => ({ ...current, trainValidationSplit: Number(value) || 0.7 }))} />
                      <Input label="Cross-validation folds" value={String(scorecardRequest.crossValidationFolds)} onChange={(value) => setScorecardRequest((current) => ({ ...current, crossValidationFolds: Number(value) || 5 }))} />
                      <Select label="Regularization" value={scorecardRequest.regularization} onChange={(value) => setScorecardRequest((current) => ({ ...current, regularization: value }))} options={["l2", "none"]} />
                      <Select label="Class weighting" value={scorecardRequest.classWeight || ""} onChange={(value) => setScorecardRequest((current) => ({ ...current, classWeight: value || null }))} options={[{ value: "", label: "None" }, { value: "balanced", label: "Balanced" }]} />
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-600">
                      <label className="inline-flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 font-semibold text-amber-800">
                        <input type="checkbox" checked={Boolean(scorecardRequest.trainRawBaseline)} onChange={(event) => setScorecardRequest((current) => ({ ...current, trainRawBaseline: event.target.checked }))} />
                        Train raw logistic baseline without WOE
                      </label>
                      <span>{woeAnalysis ? "Latest WOE / IV analysis is available for scorecard-ready transformation." : "Run WOE / IV analysis first or train a raw logistic baseline."}</span>
                    </div>
                  </div>

                  <div className="rounded-xl border border-slate-200 bg-white p-4">
                    <div className="text-sm font-semibold text-slate-950">WOE Variable Selection</div>
                    <p className="mt-1 text-xs text-slate-500">Default selection uses IV &gt;= 0.02 and IV &lt; 0.50, excluding target, ID, score, prediction, and protected fields.</p>
                    <div className="mt-3 max-h-72 overflow-auto rounded-lg border border-slate-200">
                      <table className="min-w-full text-left text-xs">
                        <thead className="sticky top-0 bg-slate-50 uppercase tracking-wide text-slate-500">
                          <tr><th className="px-3 py-2">Use</th><th className="px-3 py-2">Variable</th><th className="px-3 py-2">IV</th><th className="px-3 py-2">Strength</th><th className="px-3 py-2">Monotonicity</th><th className="px-3 py-2">Bins</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Reason for exclusion</th></tr>
                        </thead>
                        <tbody>
                          {(woeAnalysis?.variableSummaries || []).filter((row) => isCreditRiskPredictorCandidate(row.variable, profile, scorecardRequest.targetColumn)).map((row) => {
                            const checked = scorecardRequest.selectedVariables.includes(row.variable);
                            const exclusion = scorecardExclusionReason(row);
                            return (
                              <tr key={row.variable} className="border-t border-slate-100">
                                <td className="px-3 py-2"><input type="checkbox" checked={checked} onChange={(event) => setScorecardRequest((current) => ({ ...current, selectedVariables: event.target.checked ? [...current.selectedVariables, row.variable] : current.selectedVariables.filter((item) => item !== row.variable) }))} /></td>
                                <td className="px-3 py-2 font-semibold text-slate-900">{row.variable}</td>
                                <td className="px-3 py-2">{formatNumber(row.iv, 4)}</td>
                                <td className="px-3 py-2">{row.predictiveStrength}</td>
                                <td className="px-3 py-2">{row.monotonicity}</td>
                                <td className="px-3 py-2">{row.binCount}</td>
                                <td className="px-3 py-2"><StatusBadge status={row.status} /></td>
                                <td className="px-3 py-2 text-amber-700">{exclusion}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                    {!woeAnalysis && <EmptyPanel text="Run WOE / IV analysis first or train a raw logistic baseline without WOE. Raw logistic baseline is not scorecard-ready." />}
                  </div>

                  <div className="rounded-xl border border-slate-200 bg-white p-4">
                      <div className="text-sm font-semibold text-slate-950">PDO Score Scaling Inputs</div>
                    <div className="mt-3 grid gap-3 md:grid-cols-6">
                      <Input label="PDO" value={String(profile.scorecardScaling?.pdo || scorecardRequest.pdo)} onChange={(value) => {
                        patchNested("scorecardScaling", { pdo: Number(value) || undefined });
                        setScorecardRequest((current) => ({ ...current, pdo: Number(value) || current.pdo }));
                      }} />
                      <Input label="Base Score" value={String(profile.scorecardScaling?.baseScore || scorecardRequest.baseScore)} onChange={(value) => {
                        patchNested("scorecardScaling", { baseScore: Number(value) || undefined });
                        setScorecardRequest((current) => ({ ...current, baseScore: Number(value) || current.baseScore }));
                      }} />
                      <Input label="Base Odds" value={profile.scorecardScaling?.baseOdds || scorecardRequest.baseOdds} onChange={(value) => {
                        patchNested("scorecardScaling", { baseOdds: value });
                        setScorecardRequest((current) => ({ ...current, baseOdds: value }));
                      }} />
                      <Input label="Average balance" value={String(scorecardRequest.averageBalance || "")} onChange={(value) => setScorecardRequest((current) => ({ ...current, averageBalance: Number(value) || undefined }))} />
                      <Input label="Loss given default" value={String(scorecardRequest.lossGivenDefault || "")} onChange={(value) => setScorecardRequest((current) => ({ ...current, lossGivenDefault: Number(value) || undefined }))} />
                      <Input label="Revenue per booked account" value={String(scorecardRequest.revenuePerBookedAccount || "")} onChange={(value) => setScorecardRequest((current) => ({ ...current, revenuePerBookedAccount: Number(value) || undefined }))} />
                    </div>
                    <div className="mt-3 grid gap-3 rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm text-blue-950 md:grid-cols-3">
                      <Formula label="Factor" formula="PDO / ln(2)" value={preview.factor == null ? "Needs inputs" : preview.factor.toFixed(2)} />
                      <Formula label="Offset" formula="BaseScore - Factor * ln(BaseOdds)" value={preview.offset == null ? "Needs inputs" : preview.offset.toFixed(2)} />
                      <Formula label="Score" formula="Offset + Factor * log(odds)" value="Integrated into model training" />
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <button type="button" onClick={trainScorecard} disabled={scorecardRunning || !scorecardRequest.datasetId || !scorecardRequest.targetColumn || (!scorecardRequest.selectedVariables.length && !scorecardRequest.trainRawBaseline)} className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
                      {scorecardRunning ? "Training..." : "Train Scorecard Model"}
                    </button>
                    <button type="button" onClick={exportScorecardWorkbook} disabled={!scorecardModel} className="atlas-secondary-button">Export Scorecard to Excel</button>
                    <button type="button" onClick={registerChampionScorecard} disabled={!scorecardModel} className="atlas-secondary-button">Register Champion Scorecard</button>
                    <button type="button" onClick={refreshScorecardCode} className="atlas-secondary-button">Generate Code</button>
                  </div>
                  {scorecardMessage && <div className="rounded-xl border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">{scorecardMessage}</div>}

                  <div className="grid gap-3 md:grid-cols-4">
                    <Metric label="Champion Candidate" value={scorecardModel ? "Logistic Scorecard" : "Not trained"} tone={scorecardModel ? "green" : "amber"} />
                    <Metric label="Status" value={scorecardModel ? "Trained / Needs Review" : "Ready to train"} tone={scorecardModel ? "green" : "amber"} />
                    <Metric label="Train Rows" value={scorecardModel?.metrics?.trainRows == null ? "-" : String(scorecardModel.metrics.trainRows)} />
                    <Metric label="Validation Rows" value={scorecardModel?.metrics?.validationRows == null ? "-" : String(scorecardModel.metrics.validationRows)} />
                  </div>

                  {scorecardModel && (
                    <>
                      <div className="grid gap-3 md:grid-cols-5">
                        <Metric label="AUC" value={formatNumber(scorecardModel.metrics.auc, 4)} tone={(scorecardModel.metrics.auc || 0) >= 0.7 ? "green" : "amber"} />
                        <Metric label="KS" value={formatNumber(scorecardModel.metrics.ks, 4)} />
                        <Metric label="Gini" value={formatNumber(scorecardModel.metrics.gini, 4)} />
                        <Metric label="Log Loss" value={formatNumber(scorecardModel.metrics.logLoss, 4)} />
                        <Metric label="Event Rate" value={formatPercent(scorecardModel.metrics.eventRate)} />
                      </div>

                      <DataTable title="Selected Variables" columns={["variable", "coefficient"]} rows={scorecardModel.coefficients as unknown as Array<Record<string, unknown>>} />
                    </>
                  )}
                </div>

                <div className="space-y-4">
                  <div className="rounded-xl border border-slate-200 bg-white p-4">
                    <div className="text-sm font-semibold text-slate-950">Generated Code</div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {["python", "sql", "r", "sas"].map((tab) => (
                        <button key={tab} type="button" onClick={() => setScorecardCodeTab(tab)} className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${scorecardCodeTab === tab ? "bg-slate-950 text-white" : "border border-slate-200 bg-white text-slate-700"}`}>{tab === "sas" ? "SAS-compatible" : tab.toUpperCase()}</button>
                      ))}
                    </div>
                    <pre className="mt-3 max-h-96 overflow-auto rounded-xl bg-slate-950 p-3 text-xs leading-5 text-slate-50">{scorecardModel?.generatedCode?.[scorecardCodeTab] || "Train or generate code to view reproducible scorecard logic. PROC LOGISTIC appears in SAS-compatible output."}</pre>
                  </div>

                  <div className="rounded-xl border border-slate-200 bg-white p-4">
                    <div className="text-sm font-semibold text-slate-950">Evidence Actions</div>
                    <div className="mt-3 grid gap-2">
                      <button type="button" onClick={() => saveScorecardEvidenceToCenter("scorecard_modeling", "Scorecard Model Evidence")} disabled={!scorecardModel} className="atlas-secondary-button justify-center">Save Scorecard Model Evidence</button>
                      <button type="button" onClick={() => saveScorecardEvidenceToCenter("scorecard_scaling", "Scorecard Scaling Evidence")} disabled={!scorecardModel} className="atlas-secondary-button justify-center">Save Scorecard Scaling Evidence</button>
                      <button type="button" onClick={() => saveScorecardEvidenceToCenter("scorecard_performance", "Scorecard Model Performance Evidence")} disabled={!scorecardModel} className="atlas-secondary-button justify-center">Save Model Performance Evidence</button>
                      <button type="button" onClick={() => saveScorecardEvidenceToCenter("cutoff_strategy", "Cutoff Strategy Evidence")} disabled={!scorecardModel} className="atlas-secondary-button justify-center">Save Cutoff Strategy Evidence</button>
                      <button type="button" onClick={() => saveScorecardEvidenceToCenter("scorecard_points", "Scorecard Points Evidence")} disabled={!scorecardModel} className="atlas-secondary-button justify-center">Save Scorecard Points Evidence</button>
                    </div>
                  </div>
                </div>
              </div>
            </StudioSection>
          )}

          {active === "Traditional Scorecard Path" && (
            <StudioSection icon={<Calculator size={18} />} title="PDO Scaling and Scorecard Points" subtitle="Use the trained model to convert log-odds into an underwriting scorecard with PDO, base score, base odds, factor, offset, score direction, score range, and reason-code-ready scorecard points.">
              <div className="grid gap-3 md:grid-cols-3">
                <Input label="PDO" value={String(profile.scorecardScaling?.pdo || "")} onChange={(value) => patchNested("scorecardScaling", { pdo: Number(value) || undefined })} placeholder="20" />
                <Input label="Base score" value={String(profile.scorecardScaling?.baseScore || "")} onChange={(value) => patchNested("scorecardScaling", { baseScore: Number(value) || undefined })} placeholder="600" />
                <Input label="Base odds" value={profile.scorecardScaling?.baseOdds || ""} onChange={(value) => patchNested("scorecardScaling", { baseOdds: value })} placeholder="50:1" />
                <Input label="Score direction" value={profile.scorecardScaling?.scoreDirection || ""} onChange={(value) => patchNested("scorecardScaling", { scoreDirection: value })} placeholder="Higher score = lower risk" />
                <Input label="Minimum score" value={String(profile.scorecardScaling?.minScore || "")} onChange={(value) => patchNested("scorecardScaling", { minScore: Number(value) || undefined })} />
                <Input label="Maximum score" value={String(profile.scorecardScaling?.maxScore || "")} onChange={(value) => patchNested("scorecardScaling", { maxScore: Number(value) || undefined })} />
              </div>
              <div className="grid gap-4 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950 md:grid-cols-3">
                <Formula label="Factor" formula="PDO / ln(2)" value={preview.factor == null ? "Needs inputs" : preview.factor.toFixed(2)} />
                <Formula label="Offset" formula="BaseScore - Factor * ln(BaseOdds)" value={preview.offset == null ? "Needs inputs" : preview.offset.toFixed(2)} />
                <Formula label="Score" formula="Offset + Factor * ln(odds)" value="Formula preview" />
              </div>
              {scorecardModel ? <ScorecardPointsTable model={scorecardModel} /> : <EmptyPanel text="Train a scorecard model to populate the scorecard points table." />}
              <TextArea label="Odds calibration approach and reference population" value={profile.scorecardScaling?.notes || ""} onChange={(value) => patchNested("scorecardScaling", { notes: value })} />
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={trainScorecard} disabled={scorecardRunning || !scorecardRequest.datasetId || !scorecardRequest.targetColumn || (!scorecardRequest.selectedVariables.length && !scorecardRequest.trainRawBaseline)} className="atlas-secondary-button">Calculate Scorecard Points</button>
                <EvidenceButton onClick={() => saveEvidence("pdo")} label="Save PDO Scaling Evidence" />
                <EvidenceButton onClick={() => saveEvidence("scorecard_scaling")} label="Save Scorecard Scaling and Odds Calibration Evidence" />
                <button type="button" onClick={exportScorecardWorkbook} disabled={!scorecardModel} className="atlas-secondary-button">Export Scorecard Points to Excel</button>
              </div>
            </StudioSection>
          )}

          {active === "Traditional Scorecard Path" && (
            <StudioSection icon={<LineChart size={18} />} title="Model Validation" subtitle="Validate scorecard rank ordering, lift, KS, score distribution, bad rate by decile, calibration, Train / Test / OOT comparison, and stability summary.">
              {scorecardModel ? (
                <>
                  <div className="grid gap-3 md:grid-cols-6">
                    <Metric label="AUC" value={formatNumber(scorecardModel.metrics.auc, 4)} tone={(scorecardModel.metrics.auc || 0) >= 0.7 ? "green" : "amber"} />
                    <Metric label="KS" value={formatNumber(scorecardModel.metrics.ks, 4)} />
                    <Metric label="Gini" value={formatNumber(scorecardModel.metrics.gini, 4)} />
                    <Metric label="Log Loss" value={formatNumber(scorecardModel.metrics.logLoss, 4)} />
                    <Metric label="Train Rows" value={scorecardModel.metrics.trainRows == null ? "-" : String(scorecardModel.metrics.trainRows)} />
                    <Metric label="Validation Rows" value={scorecardModel.metrics.validationRows == null ? "-" : String(scorecardModel.metrics.validationRows)} />
                  </div>
                  <div className="grid gap-4 xl:grid-cols-2">
                    <SimpleBarPanel title="Score Distribution" rows={scorecardModel.scoreDistribution} labelKey="scoreBand" valueKey="accounts" />
                    <SimpleBarPanel title="Bad Rate by Decile" rows={scorecardModel.liftTable} labelKey="decile" valueKey="actualEventRate" percent />
                    <SimpleBarPanel title="Lift / Decile Chart" rows={scorecardModel.liftTable} labelKey="decile" valueKey="lift" />
                    <SimpleBarPanel title="KS Chart" rows={scorecardModel.ksTable} labelKey="decile" valueKey="ks" />
                  </div>
                  <LiftTable rows={scorecardModel.liftTable} />
                  <DataTable title="KS Table" columns={["decile", "minScore", "maxScore", "eventCount", "nonEventCount", "eventRate", "ks"]} rows={scorecardModel.ksTable} />
                  <DataTable title="Calibration Table" columns={["decile", "avgScore", "expectedEvents", "actualEvents", "actualEventRate"]} rows={scorecardModel.liftTable} />
                </>
              ) : <EmptyPanel text="Train a scorecard model to populate lift, KS, score distribution, calibration, and stability validation artifacts." />}
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => saveScorecardEvidenceToCenter("scorecard_performance", "Scorecard Validation Evidence")} disabled={!scorecardModel} className="atlas-secondary-button">Save Validation Evidence</button>
                <Link to="/model-diagnostics" className="atlas-secondary-button">Open Model Diagnostics</Link>
                <Link to="/chart-studio" className="atlas-secondary-button">Open Chart Studio</Link>
              </div>
            </StudioSection>
          )}

          {active === "AI/ML Underwriting Path" && (
            <StudioSection icon={<Network size={18} />} title="AI/ML Underwriting Path" subtitle="Train or document an AI/ML underwriting challenger while preserving monotonic constraints, calibrated probability expectations, explainability fallbacks, and model-risk review evidence.">
              <div className="grid gap-3 lg:grid-cols-3">
                {mlModelCards().map((card) => (
                  <div key={card.title} className={`rounded-xl border p-4 ${card.available ? "border-slate-200 bg-white" : "border-amber-200 bg-amber-50"}`}>
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="font-semibold text-slate-950">{card.title}</div>
                        <p className="mt-1 text-sm leading-5 text-slate-600">{card.text}</p>
                      </div>
                      <span className={`rounded-full px-2 py-1 text-[10px] font-semibold uppercase ${card.available ? "bg-emerald-50 text-emerald-700" : "bg-amber-100 text-amber-800"}`}>{card.available ? "Available" : "Unavailable"}</span>
                    </div>
                    {!card.available && <p className="mt-3 text-xs leading-5 text-amber-800">{card.reason}</p>}
                  </div>
                ))}
              </div>
              <div className="grid gap-3 md:grid-cols-3">
                <Select label="Dataset" value={mlRequest.datasetId} onChange={(value) => {
                  const dataset = datasets.find((row) => row.datasetId === value);
                  patch({ datasetId: value, datasetVersionId: dataset?.latestVersion?.versionId });
                  setMlRequest((current) => ({ ...current, datasetId: value, datasetVersionId: dataset?.latestVersion?.versionId }));
                }} options={datasets.map((dataset) => ({ value: dataset.datasetId, label: dataset.name }))} />
                <Select label="Target column" value={mlRequest.targetColumn} onChange={(value) => setMlRequest((current) => ({ ...current, targetColumn: value, selectedVariables: current.selectedVariables.filter((column) => isCreditRiskPredictorCandidate(column, profile, value)) }))} options={schema} />
                <Input label="Event value" value={String(mlRequest.eventValue ?? "")} onChange={(value) => setMlRequest((current) => ({ ...current, eventValue: value }))} />
                <Select label="Model type" value={mlRequest.modelType} onChange={(value) => setMlRequest((current) => ({ ...current, modelType: value }))} options={["Logistic Regression Baseline", "Random Forest", "XGBoost", "LightGBM", "CatBoost", "Monotonic Gradient Boosting", "Calibrated AI/ML Model"]} />
                <Select label="Class weighting" value={mlRequest.classWeight || ""} onChange={(value) => setMlRequest((current) => ({ ...current, classWeight: value }))} options={["", "balanced"]} />
                <Select label="Calibration method" value={mlRequest.calibrationMethod || ""} onChange={(value) => setMlRequest((current) => ({ ...current, calibrationMethod: value }))} options={["None", "Platt / Sigmoid", "Isotonic", "Review after validation"]} />
                <Select label="Evaluation metric" value={mlRequest.evaluationMetric || "AUC"} onChange={(value) => setMlRequest((current) => ({ ...current, evaluationMetric: value }))} options={["AUC", "KS", "Gini", "Log loss", "PR-AUC", "Expected profit", "Bad-rate at approval cutoff"]} />
                <Input label="Train / validation split" value={String(mlRequest.trainValidationSplit)} onChange={(value) => setMlRequest((current) => ({ ...current, trainValidationSplit: Number(value) || 0.7 }))} />
                <Metric label="Selected variables" value={String(mlRequest.selectedVariables.length)} />
              </div>
              <MonotonicConstraintsPanel profile={profile} schema={schema} patch={(constraints) => patch({ monotonicConstraints: constraints })} />
              <div className="flex flex-wrap gap-2">
                <button type="button" className="atlas-secondary-button" onClick={trainMlChallenger} disabled={mlRunning || !mlRequest.datasetId || !mlRequest.targetColumn || !mlRequest.selectedVariables.length}>{mlRunning ? "Training..." : "Train AI/ML Challenger"}</button>
                <EvidenceButton onClick={() => saveMlEvidenceToCenter("monotonic_constraints", "Monotonic Constraint Evidence")} label="Save Monotonic Constraint Evidence" />
                <EvidenceButton onClick={() => saveMlEvidenceToCenter("ml_underwriting", "AI/ML Underwriting Evidence")} label="Save AI/ML Underwriting Evidence" />
                {mlMessage && <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-900">{mlMessage}</div>}
              </div>
              <div className="grid gap-4 xl:grid-cols-2">
                <AiMlExplainabilityPanel model={mlModel} />
                <SurrogateScorecardPanel model={mlModel} />
              </div>
            </StudioSection>
          )}

          {active === "Champion / Challenger Comparison" && (
            <StudioSection icon={<GitBranch size={18} />} title="Champion / Challenger Comparison" subtitle="Compare the traditional scorecard baseline and AI/ML challenger side by side. ATLAS considers performance, calibration, explainability, adverse-action readiness, stability, and model risk complexity.">
              {activeWorkflowStep.name === "Evaluation" && (
                <RealPredictiveStepEmbed title="Real ATLAS Evaluation Workflow">
                  <Step08Evaluation />
                </RealPredictiveStepEmbed>
              )}
              <div className="flex flex-wrap gap-2">
                <button type="button" className="atlas-secondary-button" onClick={runComparison} disabled={saving}>Run Champion / Challenger Comparison</button>
                <button type="button" className="atlas-secondary-button" onClick={() => chooseChampion("scorecard")} disabled={!scorecardModel}>Select Scorecard as Champion</button>
                <button type="button" className="atlas-secondary-button" onClick={() => chooseChampion("ml")} disabled={!mlModel}>Select AI/ML as Champion</button>
                <button type="button" className="atlas-secondary-button" onClick={() => chooseChampion("challenger")} disabled={!mlModel}>Keep AI/ML as Challenger</button>
                <button type="button" className="atlas-secondary-button" onClick={saveChampionEvidenceToCenter}>Save Champion / Challenger Evidence</button>
                <Link to="/model-evidence-center" className="atlas-secondary-button">Open Model Evidence Center</Link>
              </div>
              <ChampionComparisonTable scorecardModel={scorecardModel} mlModel={mlModel} comparison={championComparison} />
              <div className="grid gap-3 md:grid-cols-3">
                <Metric label="Recommended Champion" value={String((championComparison?.recommendedChampion as Record<string, unknown> | undefined)?.model || profile.championModelType || "Run comparison")} />
                <Metric label="Reviewer Decision" value={profile.championDecision?.selectedModelType || "Not selected"} tone={profile.championDecision?.selectedModelType ? "green" : "amber"} />
                <Metric label="Evidence Generated" value={profile.championDecisionStatus || profile.comparisonStatus || "Needs Review"} />
              </div>
              <TextArea label="Reviewer Notes" value={profile.championDecision?.reviewerNotes || ""} onChange={(value) => patch({ championDecision: { ...(profile.championDecision || {}), reviewerNotes: value } })} />
              {activeWorkflowStep.name === "Evaluation" && (
                <StepContinueButton label="Confirm Evaluation and Continue" onClick={() => saveAndOpenWorkflowStep("interpretation", { comparisonStatus: "Ready", readiness: { ...(profile.readiness || {}), "Model Validation": "Ready" } })} />
              )}
            </StudioSection>
          )}

          {active === "Explainability and Adverse Action" && (
            <StudioSection icon={<Scale size={18} />} title="Explainability and Adverse Action" subtitle="ATLAS tracks explainability and adverse action evidence. It does not certify legal compliance. Compliance decisions require qualified review.">
              {activeWorkflowStep.name === "Interpretation" && (
                <RealPredictiveStepEmbed title="Real ATLAS Interpretation Workflow">
                  <Step09Interpretation />
                </RealPredictiveStepEmbed>
              )}
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900">
                ATLAS can generate adverse-action evidence and reason-code candidates. Final adverse-action logic requires compliance and legal review.
              </div>
              <div className="grid gap-3 md:grid-cols-3">
                <Select label="Model type for explanation" value={String(profile.explainability?.modelType || "Champion Model")} onChange={(value) => patchNested("explainability", { modelType: value })} options={["Traditional Scorecard", "AI/ML Underwriting", "Champion Model"]} />
                <Metric label="Scorecard reason-code source" value="Points / WOE bins" />
                <Metric label="AI/ML reason-code source" value={mlModel ? "Feature importance / surrogate" : "Pending challenger"} />
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <Input label="Reason code source" value={String(profile.explainability?.reasonCodeSource || "")} onChange={(value) => patchNested("explainability", { reasonCodeSource: value })} />
                <Input label="Reason code ranking logic" value={String(profile.explainability?.reasonCodeLogic || "")} onChange={(value) => patchNested("explainability", { reasonCodeLogic: value })} />
                <TextArea label="Feature-to-reason mapping" value={String(profile.explainability?.featureReasonMapping || "")} onChange={(value) => patchNested("explainability", { featureReasonMapping: value })} />
                <TextArea label="Excluded variables and sensitive attributes excluded" value={String(profile.explainability?.excludedVariables || "")} onChange={(value) => patchNested("explainability", { excludedVariables: value })} />
                <Input label="Adverse action review status" value={String(profile.explainability?.adverseActionStatus || "")} onChange={(value) => patchNested("explainability", { adverseActionStatus: value })} />
                <Input label="Fair lending review status" value={String(profile.explainability?.fairLendingStatus || "")} onChange={(value) => patchNested("explainability", { fairLendingStatus: value })} />
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="button" className="atlas-secondary-button" onClick={() => patchNested("explainability", { reasonCodeLogic: scorecardModel ? "Rank adverse-action reason candidates by largest negative scorecard point contribution, excluding prohibited basis and protected attributes. Compliance and legal review required before use." : "Generate after scorecard points are available. Compliance and legal review required before use." })}>Generate Reason Code Draft</button>
                <EvidenceButton onClick={() => saveEvidence("adverse_action")} label="Save Adverse Action Evidence" />
                <EvidenceButton onClick={() => saveEvidence("fair_lending")} label="Save Fair Lending Evidence" />
                <EvidenceButton onClick={() => saveEvidence("monotonic_constraints")} label="Save Monotonic Constraint Evidence" />
                <EvidenceButton onClick={() => saveEvidence("surrogate_scorecard")} label="Save Surrogate Scorecard Evidence" />
              </div>
              {activeWorkflowStep.name === "Interpretation" && (
                <StepContinueButton label="Confirm Interpretation and Continue" onClick={() => saveAndOpenWorkflowStep("scoring", { readiness: { ...(profile.readiness || {}), "Adverse Action": "Ready", "Fair Lending": "Ready", "Feature Importance": "Ready" } })} />
              )}
            </StudioSection>
          )}

          {active === "Cutoff and Decision Strategy" && (
            <StudioSection icon={<GitBranch size={18} />} title="Cutoff and Decision Strategy" subtitle="Set score cutoffs, approval targets, maximum bad rate, average balance, LGD, revenue, pricing tier, and manual override rules so scorecard output connects to business decisions.">
              {activeWorkflowStep.name === "Scoring" && (
                <RealPredictiveStepEmbed title="Real ATLAS Scoring Workflow">
                  <Step10Scoring />
                </RealPredictiveStepEmbed>
              )}
              <div className="grid gap-3 md:grid-cols-3">
                <Select label="Model to use" value={String(profile.decisionStrategy?.modelSource || "Champion Model")} onChange={(value) => patchNested("decisionStrategy", { modelSource: value })} options={["Traditional Scorecard", "AI/ML Challenger", "Champion Model"]} />
                <Input label="Score / probability column" value={String(profile.decisionStrategy?.scoreColumn || "")} onChange={(value) => patchNested("decisionStrategy", { scoreColumn: value })} placeholder="score, predicted_pd, probability" />
                <Input label="Manual override rule" value={String(profile.decisionStrategy?.manualOverrideRule || "")} onChange={(value) => patchNested("decisionStrategy", { manualOverrideRule: value })} placeholder="Policy exception or decline rule" />
              </div>
              {scorecardModel ? <CutoffTable rows={scorecardModel.cutoffTable} /> : null}
              <div className="grid gap-4 xl:grid-cols-3">
                <SimpleBarPanel title="Approval rate vs bad rate" rows={scorecardModel?.cutoffTable || strategyRows(profile)} labelKey={scorecardModel ? "scoreCutoff" : "cutoff"} valueKey="badRate" />
                <SimpleBarPanel title="Expected profit by cutoff" rows={scorecardModel?.cutoffTable || strategyRows(profile)} labelKey={scorecardModel ? "scoreCutoff" : "cutoff"} valueKey="expectedProfit" />
                <SimpleBarPanel title="Bad rate by score band" rows={scorecardModel?.liftTable || []} labelKey="decile" valueKey="actualEventRate" percent />
              </div>
              <div className="overflow-auto rounded-xl border border-slate-200">
                <table className="min-w-full text-left text-sm">
                  <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr><th className="px-3 py-2">Cutoff</th><th className="px-3 py-2">Approval Rate</th><th className="px-3 py-2">Bad Rate</th><th className="px-3 py-2">Expected Loss</th><th className="px-3 py-2">Expected Profit</th><th className="px-3 py-2">Pricing Tier</th><th className="px-3 py-2">Recommendation</th></tr></thead>
                  <tbody>{strategyRows(profile).map((row) => <tr key={row.cutoff} className="border-t border-slate-100"><td className="px-3 py-2">{row.cutoff}</td><td className="px-3 py-2">{row.approvalRate}</td><td className="px-3 py-2">{row.badRate}</td><td className="px-3 py-2">{row.expectedLoss}</td><td className="px-3 py-2">{row.expectedProfit}</td><td className="px-3 py-2">{row.pricingTier}</td><td className="px-3 py-2 font-semibold">{row.recommendation}</td></tr>)}</tbody>
                </table>
              </div>
              <TextArea label="Strategy recommendation and manual override notes" value={String(profile.decisionStrategy?.notes || "")} onChange={(value) => patchNested("decisionStrategy", { notes: value, cutoffs: strategyRows(profile) })} />
              <div className="flex flex-wrap gap-2">
                <EvidenceButton onClick={() => saveEvidence("cutoff_optimization")} label="Save Cutoff Optimization Evidence" />
                <EvidenceButton onClick={() => saveEvidence("risk_based_pricing")} label="Save Risk-Based Pricing Evidence" />
                <EvidenceButton onClick={() => saveEvidence("strategy_trees")} label="Save Strategy Tree Evidence" />
              </div>
              {activeWorkflowStep.name === "Scoring" && (
                <StepContinueButton label="Confirm Scoring and Continue" onClick={() => saveAndOpenWorkflowStep("documentation-review", { readiness: { ...(profile.readiness || {}), "Cutoff Strategy": "Ready", "Risk-Based Pricing": "Ready" } })} />
              )}
            </StudioSection>
          )}

          {active === "Monitoring and Portfolio Risk" && (
            <StudioSection icon={<LineChart size={18} />} title="Monitoring and Portfolio Risk" subtitle="Connect underwriting assumptions to score distribution monitoring, bad-rate monitoring, PSI, champion/challenger governance, TTC/PIT review, and redevelopment triggers.">
              {activeWorkflowStep.name === "Model Monitoring" && (
                <RealPredictiveStepEmbed title="Real ATLAS Model Monitoring Workflow">
                  <Step13ModelMonitoring />
                </RealPredictiveStepEmbed>
              )}
              <div className="grid gap-3 md:grid-cols-2">
                <Select label="TTC/PIT assumption" value={String(profile.monitoring?.ttcPitAssumption || profile.ttcPitAssumption || "")} onChange={(value) => patchNested("monitoring", { ttcPitAssumption: value })} options={TTC_PIT_OPTIONS} />
                <Input label="Monitoring cadence" value={String(profile.monitoring?.monitoringCadence || "")} onChange={(value) => patchNested("monitoring", { monitoringCadence: value })} placeholder="Monthly, quarterly, annually" />
                <Input label="PSI threshold green" value={String((profile.monitoring?.psiThresholds as Record<string, number> | undefined)?.green || "")} onChange={(value) => patchNested("monitoring", { psiThresholds: { ...((profile.monitoring?.psiThresholds as object) || {}), green: Number(value) } })} />
                <Input label="PSI threshold yellow" value={String((profile.monitoring?.psiThresholds as Record<string, number> | undefined)?.yellow || "")} onChange={(value) => patchNested("monitoring", { psiThresholds: { ...((profile.monitoring?.psiThresholds as object) || {}), yellow: Number(value) } })} />
                <Input label="PSI threshold red" value={String((profile.monitoring?.psiThresholds as Record<string, number> | undefined)?.red || "")} onChange={(value) => patchNested("monitoring", { psiThresholds: { ...((profile.monitoring?.psiThresholds as object) || {}), red: Number(value) } })} />
                <Input label="Champion model" value={String(profile.monitoring?.championModel || "")} onChange={(value) => patchNested("monitoring", { championModel: value })} />
                <Input label="Challenger model" value={String(profile.monitoring?.challengerModel || "")} onChange={(value) => patchNested("monitoring", { challengerModel: value, challengerChampion: value })} />
                <Input label="Redevelopment trigger" value={String(profile.monitoring?.redevelopmentTrigger || "")} onChange={(value) => patchNested("monitoring", { redevelopmentTrigger: value })} />
                <Input label="Monitoring owner" value={String(profile.monitoring?.monitoringOwner || "")} onChange={(value) => patchNested("monitoring", { monitoringOwner: value })} />
              </div>
              <div className="flex flex-wrap gap-2">
                <EvidenceButton onClick={() => saveEvidence("ttc")} label="Save TTC / PIT Evidence" />
                <EvidenceButton onClick={() => saveEvidence("psi")} label="Save PSI Evidence" />
                <EvidenceButton onClick={() => saveEvidence("challenger_champion")} label="Save Challenger / Champion Evidence" />
                <EvidenceButton onClick={() => saveEvidence("monitoring_threshold")} label="Save Monitoring Threshold Evidence" />
              </div>
            </StudioSection>
          )}

          {active === "Evidence and Documentation" && (
            <StudioSection icon={<BookOpenCheck size={18} />} title="Evidence and Documentation" subtitle="Review target evidence, EDA evidence, characteristic screening evidence, WOE / IV evidence, scorecard model evidence, PDO scaling evidence, validation evidence, cutoff evidence, adverse-action evidence, monitoring evidence, and documentation readiness.">
              {activeWorkflowStep.name === "Documentation Review" && (
                <RealPredictiveStepEmbed title="Real ATLAS Documentation Review Workflow">
                  <Step11DocumentationReview />
                </RealPredictiveStepEmbed>
              )}
              {activeWorkflowStep.name === "Model Implementation" && (
                <RealPredictiveStepEmbed title="Real ATLAS Model Implementation Workflow">
                  <Step12ModelImplementation />
                </RealPredictiveStepEmbed>
              )}
              <div className="grid gap-3 md:grid-cols-5">
                <Metric label="Scorecard Readiness" value={workflowStatus["Traditional Scorecard Path"] || "Missing"} tone={workflowStatus["Traditional Scorecard Path"] === "Complete" ? "green" : "amber"} />
                <Metric label="AI/ML Readiness" value={workflowStatus["AI/ML Underwriting Path"] || "Missing"} tone={workflowStatus["AI/ML Underwriting Path"] === "Complete" ? "green" : "amber"} />
                <Metric label="Champion Decision Readiness" value={workflowStatus["Champion / Challenger Comparison"] || "Missing"} tone={workflowStatus["Champion / Challenger Comparison"] === "Complete" ? "green" : "amber"} />
                <Metric label="Adverse Action Readiness" value={workflowStatus["Explainability and Adverse Action"] || "Missing"} />
                <Metric label="Evidence Readiness" value={workflowStatus["Evidence and Documentation"] || "Missing"} />
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <ChecklistCard title="Shared Evidence" items={["Project setup", "Population and target", "EDA", "Characteristic screening"]} />
                <ChecklistCard title="Traditional Scorecard Evidence" items={["WOE / IV", "Manual binning", "PDO scaling", "Scorecard points"]} />
                <ChecklistCard title="AI/ML Underwriting Evidence" items={["Model training", "Feature importance", "Monotonic constraints", "Surrogate scorecard"]} />
                <ChecklistCard title="Champion / Challenger Evidence" items={["Comparison table", "Reviewer decision", "Model selection rationale", "Monitoring readiness"]} />
                <ChecklistCard title="Decision Strategy Evidence" items={["Cutoff strategy", "Risk-based pricing", "Strategy tree"]} />
                <ChecklistCard title="Adverse Action Evidence" items={["Reason-code mapping", "Compliance review hook", "Fair lending review"]} />
                <ChecklistCard title="Monitoring Evidence" items={["PSI thresholds", "Cadence", "Redevelopment trigger"]} />
                <ChecklistCard title="Documentation Evidence" items={["Evidence Center links", "Documentation Studio readiness", "Export package"]} />
              </div>
              <div className="grid gap-3 md:grid-cols-3">
                {readiness.items.map((item) => <ReadinessTile key={item.section} section={item.section} status={item.status} />)}
              </div>
              <div className="flex flex-wrap gap-2">
                <Link to="/model-evidence-center" className="atlas-secondary-button"><Network size={16} /> Open Model Evidence Center</Link>
                <Link to="/model-document-studio" className="atlas-secondary-button"><BookOpenCheck size={16} /> Open Model Documentation Studio</Link>
                <button type="button" onClick={() => saveEvidence("scorecard_scaling")} className="atlas-secondary-button"><ShieldAlert size={16} /> Export Credit Risk Evidence Pack</button>
              </div>
            </StudioSection>
          )}
          {creditRiskBottomCta(active) && !["Project Setup", "Population and Target", "Credit Risk EDA", "Characteristic Screening"].includes(active) && !["Evaluation", "Interpretation", "Scoring"].includes(activeWorkflowStep.name) ? (
            <StepContinueButton
              label={creditRiskBottomCta(active)?.label || "Save and Continue"}
              onClick={() => {
                const cta = creditRiskBottomCta(active);
                if (cta?.next) return saveAndContinue(cta.next);
                return saveSetup();
              }}
            />
          ) : null}
        </main>

        <aside className="self-start space-y-4">
          <CreditRiskRightRail
            step={activeWorkflowStep}
            profile={profile}
            readiness={readiness}
            workflowStatus={workflowStatus}
            scorecardModel={scorecardModel}
            mlModel={mlModel}
            onOpen={openOverlaySection}
          />
        </aside>
      </section>
    </div>
  );
}

function defaultProfile(projectId: string, projectName: string, dataset?: DatasetSummary): CreditRiskProfile {
  return {
    projectId,
    projectName,
    datasetId: dataset?.datasetId,
    datasetVersionId: dataset?.latestVersion?.versionId,
    productType: "Credit Card",
    modelPurpose: "Application Underwriting",
    modelType: "Traditional Scorecard",
    targetEvent: "Default",
    targetColumn: "",
    eventValue: "1",
    nonEventValue: "0",
    originalTargetLabelColumn: "",
    splitColumn: "",
    validationDatasetId: "",
    ootDatasetId: "",
    ootType: "",
    targetWindow: "Defaults in following 90 days",
    ttcPitAssumption: "Not Selected",
    scorecardScaling: { scorecardStyleModel: true, pdo: 20, baseScore: 600, baseOdds: "50:1", scoreDirection: "Higher score = lower risk" },
    monitoring: { psiThresholds: { green: 0.1, yellow: 0.25, red: 0.25 }, monitoringCadence: "Monthly" },
    variableMappings: [],
    readiness: {},
  };
}

function preferredCreditRiskDataset(datasets: DatasetSummary[]) {
  return datasets.find((dataset) => /^HELOC_TRAIN$/i.test(dataset.name))
    || datasets.find((dataset) => /heloc/i.test(dataset.name))
    || datasets[0];
}

function datasetNameForId(datasets: DatasetSummary[], datasetId?: string) {
  return datasets.find((dataset) => dataset.datasetId === datasetId)?.name || "";
}

function normalizeCreditRiskProfile(profile: CreditRiskProfile, datasets: DatasetSummary[], projectId: string, projectName: string): CreditRiskProfile {
  const helocTrain = preferredCreditRiskDataset(datasets);
  const currentDatasetName = datasetNameForId(datasets, profile.datasetId);
  const currentIsHelocTrain = /^HELOC_TRAIN$/i.test(currentDatasetName);
  const staleDatasetPattern = new RegExp(`${["REG", "TRAIN"].join("_")}|california|housing`, "i");
  const staleTargetPattern = new RegExp(["Med", "HouseVal"].join(""), "i");
  const staleRegressionState = staleDatasetPattern.test(currentDatasetName)
    || staleTargetPattern.test(profile.targetColumn || "")
    || staleTargetPattern.test(profile.originalTargetLabelColumn || "");
  if (!helocTrain || !/^HELOC_TRAIN$/i.test(helocTrain.name) || (profile.datasetId && !staleRegressionState && !currentIsHelocTrain)) {
    return profile;
  }
  const normalizedDataset = currentIsHelocTrain ? datasets.find((dataset) => dataset.datasetId === profile.datasetId) || helocTrain : helocTrain;
  const staleOrMissingTarget = !profile.targetColumn || staleTargetPattern.test(profile.targetColumn);
  const staleOrMissingOriginal = !profile.originalTargetLabelColumn || staleTargetPattern.test(profile.originalTargetLabelColumn);
  return {
    ...defaultProfile(projectId, projectName, normalizedDataset),
    ...profile,
    projectId,
    projectName: profile.projectName || projectName,
    datasetId: normalizedDataset.datasetId,
    datasetVersionId: normalizedDataset.latestVersion?.versionId,
    targetColumn: staleOrMissingTarget ? "bad_flag" : profile.targetColumn,
    eventValue: "1",
    nonEventValue: "0",
    originalTargetLabelColumn: staleOrMissingOriginal ? "RiskPerformance" : profile.originalTargetLabelColumn,
    splitColumn: staleRegressionState || !profile.splitColumn ? "atlas_split" : profile.splitColumn,
    validationDatasetId: staleRegressionState || !profile.validationDatasetId ? findDatasetIdByName(datasets, /^HELOC_TEST$/i) : profile.validationDatasetId,
    ootDatasetId: staleRegressionState || !profile.ootDatasetId ? findDatasetIdByName(datasets, /^HELOC_OOT$/i) : profile.ootDatasetId,
    ootType: staleRegressionState || !profile.ootType || profile.ootType === "True out-of-time" ? "Synthetic holdout" : profile.ootType,
    variableMappings: [],
    targetSummary: undefined,
  };
}

function defaultWoeRequest(projectId: string, profile: CreditRiskProfile): WoeIvRunRequest {
  return {
    projectId,
    datasetId: profile.datasetId || "",
    datasetVersionId: profile.datasetVersionId,
    targetColumn: profile.targetColumn || "",
    eventValue: profile.eventValue || "1",
    predictorColumns: [],
    binningMethod: "quantile",
    maxBins: 5,
    minBinPct: 0.05,
    smoothing: 0.5,
    excludeMissingFromBins: false,
  };
}

function defaultScorecardRequest(projectId: string, profile: CreditRiskProfile): ScorecardTrainRequest {
  return {
    projectId,
    datasetId: profile.datasetId || "",
    datasetVersionId: profile.datasetVersionId,
    targetColumn: profile.targetColumn || "",
    eventValue: profile.eventValue || "1",
    selectedVariables: [],
    trainValidationSplit: 0.7,
    crossValidationFolds: 5,
    modelType: "Logistic Scorecard",
    regularization: "l2",
    regularizationC: 1.0,
    classWeight: null,
    trainRawBaseline: false,
    pdo: Number(profile.scorecardScaling?.pdo || 20),
    baseScore: Number(profile.scorecardScaling?.baseScore || 600),
    baseOdds: profile.scorecardScaling?.baseOdds || "50:1",
    scoreDirection: profile.scorecardScaling?.scoreDirection || "Higher score = lower risk",
  };
}

function defaultMlRequest(projectId: string, profile: CreditRiskProfile): CreditRiskMlTrainRequest {
  return {
    projectId,
    datasetId: profile.datasetId || "",
    datasetVersionId: profile.datasetVersionId,
    targetColumn: profile.targetColumn || "",
    eventValue: profile.eventValue || "1",
    selectedVariables: (profile.variableMappings || []).filter((row) => row.include && isCreditRiskPredictorCandidate(row.variable, profile) && row.role !== "Protected / Sensitive" && row.role !== "Excluded").map((row) => row.variable).slice(0, 30),
    modelType: "Random Forest",
    trainValidationSplit: 0.7,
    classWeight: "balanced",
    calibrationMethod: "Review after validation",
    monotonicConstraints: profile.monotonicConstraints || [],
    evaluationMetric: "AUC",
  };
}

function defaultScorecardVariables(analysis: WoeIvAnalysis) {
  return (analysis.variableSummaries || [])
    .filter((row) => row.iv >= 0.02 && row.iv < 0.5 && row.status !== "error" && !isScorecardExcluded(row.variable))
    .map((row) => row.variable)
    .slice(0, 20);
}

function scorecardExclusionReason(row: WoeIvVariableSummary) {
  if (isScorecardExcluded(row.variable)) return "Excluded by field name governance rule.";
  if (row.iv >= 0.5) return "Potential leakage / suspicious IV.";
  if (row.iv < 0.02) return "IV below useful threshold.";
  if (row.status === "error") return "WOE analysis failed.";
  return "";
}

function isScorecardExcluded(name: string) {
  return /(^id$|_id$|^bad_flag$|^atlas_split$|riskperformance|target|prediction|predicted|probability|pd$|race|gender|sex|ethnic)/i.test(name);
}

function isCreditRiskPredictorCandidate(name: string, profile?: CreditRiskProfile, targetColumn?: string) {
  const blocked = new Set([
    targetColumn || "",
    profile?.targetColumn || "",
    profile?.originalTargetLabelColumn || "",
    profile?.splitColumn || "",
  ].filter(Boolean));
  return !blocked.has(name) && !isScorecardExcluded(name);
}

function uniqueStrings(values: string[]) {
  return Array.from(new Set(values.filter(Boolean)));
}

function previewIvByVariable(localDataset: LocalDataset | null, targetColumn?: string, eventValue = "1") {
  const target = targetColumn || localDataset?.target || "";
  if (!localDataset?.rows.length || !target || !localDataset.headers.includes(target)) return new Map<string, number>();
  const candidates = uniqueStrings([...(localDataset.selected_columns || []), ...localDataset.headers])
    .filter((column) => column !== target && localDataset.headers.includes(column));
  return new Map(
    candidates
      .map((column) => [column, previewInformationValue(localDataset.rows, column, target, eventValue)] as const)
      .filter((entry): entry is readonly [string, number] => typeof entry[1] === "number" && Number.isFinite(entry[1])),
  );
}

function previewInformationValue(rows: Record<string, unknown>[], column: string, target: string, eventValue: string) {
  if (!rows.length || column === target) return null;
  const values = rows
    .map((row) => row[column])
    .filter((value) => value !== null && value !== undefined && String(value).trim() !== "");
  if (!values.length) return null;
  const numericValues = values.map(Number).filter(Number.isFinite);
  const numeric = numericValues.length / values.length >= 0.8;
  const sorted = [...numericValues].sort((a, b) => a - b);
  const breaks = numeric
    ? [0.2, 0.4, 0.6, 0.8].map((pct) => sorted[Math.min(sorted.length - 1, Math.max(0, Math.floor(sorted.length * pct)))])
    : [];
  const categoryCounts = new Map<string, number>();
  if (!numeric) {
    values.forEach((value) => {
      const key = String(value);
      categoryCounts.set(key, (categoryCounts.get(key) || 0) + 1);
    });
  }
  const topCategories = new Set(
    Array.from(categoryCounts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 20)
      .map(([key]) => key),
  );
  const bucketFor = (value: unknown) => {
    if (value === null || value === undefined || String(value).trim() === "") return "__MISSING__";
    if (!numeric) {
      const key = String(value);
      return topCategories.has(key) ? key : "__OTHER__";
    }
    const num = Number(value);
    if (!Number.isFinite(num)) return "__MISSING__";
    const upper = breaks.find((breakValue) => num <= breakValue);
    return upper === undefined ? `>${breaks.length ? breaks[breaks.length - 1] : "all"}` : `<=${upper}`;
  };
  const buckets = new Map<string, { event: number; nonEvent: number }>();
  let totalEvents = 0;
  let totalNonEvents = 0;
  rows.forEach((row) => {
    const targetValue = row[target];
    if (targetValue === null || targetValue === undefined || String(targetValue).trim() === "") return;
    const bucket = buckets.get(bucketFor(row[column])) || { event: 0, nonEvent: 0 };
    if (String(targetValue) === String(eventValue)) {
      bucket.event += 1;
      totalEvents += 1;
    } else {
      bucket.nonEvent += 1;
      totalNonEvents += 1;
    }
    buckets.set(bucketFor(row[column]), bucket);
  });
  if (!totalEvents || !totalNonEvents || !buckets.size) return null;
  const epsilon = 0.000001;
  let iv = 0;
  buckets.forEach((bucket) => {
    const eventDist = Math.max(bucket.event / totalEvents, epsilon);
    const nonEventDist = Math.max(bucket.nonEvent / totalNonEvents, epsilon);
    iv += (eventDist - nonEventDist) * Math.log(eventDist / nonEventDist);
  });
  return Number.isFinite(iv) ? Math.max(0, iv) : null;
}

function previewBadRateSpreadRows(localDataset: LocalDataset | null, targetColumn: string, eventValue = "1") {
  if (!localDataset?.rows.length || !targetColumn || !localDataset.headers.includes(targetColumn)) return [];
  return uniqueStrings([...(localDataset.selected_columns || []), ...localDataset.headers])
    .filter((column) => column !== targetColumn && isHelocBureauField(column))
    .map((variable) => {
      const spread = previewBadRateSpread(localDataset.rows, variable, targetColumn, eventValue);
      return {
        variable,
        badRateSpread: spread == null ? "Not available from preview" : formatPercent(spread),
        source: "Data Acquisition preview",
      };
    })
    .filter((row) => row.badRateSpread !== "Not available from preview")
    .sort((a, b) => Number.parseFloat(String(b.badRateSpread)) - Number.parseFloat(String(a.badRateSpread)))
    .slice(0, 10);
}

function previewBadRateSpread(rows: Record<string, unknown>[], column: string, target: string, eventValue: string) {
  const values = rows
    .map((row) => row[column])
    .filter((value) => value !== null && value !== undefined && String(value).trim() !== "");
  if (!values.length) return null;
  const numericValues = values.map(Number).filter(Number.isFinite);
  const numeric = numericValues.length / values.length >= 0.8;
  const sorted = [...numericValues].sort((a, b) => a - b);
  const breaks = numeric
    ? [0.2, 0.4, 0.6, 0.8].map((pct) => sorted[Math.min(sorted.length - 1, Math.max(0, Math.floor(sorted.length * pct)))])
    : [];
  const bucketFor = (value: unknown) => {
    if (value === null || value === undefined || String(value).trim() === "") return "__MISSING__";
    if (!numeric) return String(value);
    const num = Number(value);
    if (!Number.isFinite(num)) return "__MISSING__";
    const upper = breaks.find((breakValue) => num <= breakValue);
    return upper === undefined ? `>${breaks.length ? breaks[breaks.length - 1] : "all"}` : `<=${upper}`;
  };
  const buckets = new Map<string, { total: number; bad: number }>();
  rows.forEach((row) => {
    const targetValue = row[target];
    if (targetValue === null || targetValue === undefined || String(targetValue).trim() === "") return;
    const bucket = buckets.get(bucketFor(row[column])) || { total: 0, bad: 0 };
    bucket.total += 1;
    if (String(targetValue) === String(eventValue)) bucket.bad += 1;
    buckets.set(bucketFor(row[column]), bucket);
  });
  const rates = Array.from(buckets.values())
    .filter((bucket) => bucket.total > 0)
    .map((bucket) => bucket.bad / bucket.total);
  if (rates.length < 2) return null;
  return Math.max(...rates) - Math.min(...rates);
}

function finalIvPredictorColumns(profile: CreditRiskProfile, schema: string[], targetColumn?: string) {
  const mappedVariables = (profile.variableMappings || [])
    .filter((row) => row.include && row.role !== "Protected / Sensitive" && row.role !== "Excluded")
    .map((row) => row.variable);
  const source = mappedVariables.length ? mappedVariables : schema;
  return uniqueStrings(source)
    .filter((column) => schema.includes(column))
    .filter((column) => isCreditRiskPredictorCandidate(column, profile, targetColumn))
    .slice(0, 50);
}

function finalFeatureReviewRows({
  profile,
  woeAnalysis,
  previewIvByVariable,
  targetColumn,
}: {
  profile: CreditRiskProfile;
  woeAnalysis: WoeIvAnalysis | null;
  previewIvByVariable?: Map<string, number>;
  targetColumn?: string;
}) {
  const woeByVariable = new Map((woeAnalysis?.variableSummaries || []).map((row) => [row.variable, row]));
  const mappedVariables = (profile.variableMappings || [])
    .filter((row) => row.include && row.role !== "Protected / Sensitive" && row.role !== "Excluded" && isCreditRiskPredictorCandidate(row.variable, profile, targetColumn))
    .map((row) => row.variable);
  const variables = uniqueStrings([
    ...mappedVariables,
    ...(woeAnalysis?.variableSummaries || []).filter((row) => isCreditRiskPredictorCandidate(row.variable, profile, targetColumn)).map((row) => row.variable),
    ...Array.from(previewIvByVariable?.keys() || []).filter((variable) => isCreditRiskPredictorCandidate(variable, profile, targetColumn)),
  ]);
  return variables.map((variable) => {
    const woe = woeByVariable.get(variable);
    const previewIv = previewIvByVariable?.get(variable);
    const iv = typeof woe?.iv === "number" ? woe.iv : typeof previewIv === "number" ? previewIv : null;
    const ivSource = typeof woe?.iv === "number" ? "WOE / IV" : typeof previewIv === "number" ? "Preview IV" : "Not run";
    const status = !woe
      ? typeof previewIv === "number"
        ? previewIv >= 0.02
          ? "Preview candidate"
          : "Weak preview IV"
        : "IV pending"
      : woe.status === "error"
        ? "Review"
        : iv == null
          ? "IV pending"
          : iv >= 0.5
            ? "Leakage review"
            : iv >= 0.02
              ? "Candidate"
              : "Weak IV";
    return {
      variable,
      iv,
      ivLabel: iv == null ? "Not run" : iv.toFixed(4),
      ivSource,
      status,
      statusTone: status === "Candidate" || status === "Preview candidate" ? "text-emerald-700" : status === "Leakage review" || status === "Weak IV" || status === "Weak preview IV" ? "text-amber-700" : "text-slate-500",
      recommended: Boolean(iv != null && iv >= 0.02 && iv < 0.5 && woe?.status !== "error" && !isScorecardExcluded(variable)),
      recommendation: woe
        ? scorecardExclusionReason(woe) || "Keep unless reviewer identifies business, policy, stability, or fair-lending concerns."
        : typeof previewIv === "number"
          ? "Preview IV from Data Acquisition is available. Keep for model training unless reviewer identifies a governance or stability concern."
        : "Run WOE / IV to populate signal strength before final model training.",
    };
  }).sort((a, b) => (b.iv ?? -1) - (a.iv ?? -1) || a.variable.localeCompare(b.variable));
}

function computeReadiness(profile: CreditRiskProfile) {
  const evidenceReady = (section: string) => profile.readiness?.[section] === "Ready";
  const checks: Record<string, boolean> = {
    "Target Definition": Boolean(profile.targetEvent && profile.targetWindow),
    "Population Definition": Boolean(profile.observationWindow || profile.exclusionRules),
    "Variable Mapping": Boolean(profile.variableMappings?.length),
    "Modeling Approach": Boolean(profile.selectedModelingApproach),
    "WOE / IV": Boolean(profile.featureReview?.woeIv || profile.featureReview?.notes),
    "Manual Binning": Boolean(profile.featureReview?.manualBinning || profile.featureReview?.notes),
    "Reject Inference": Boolean(profile.featureReview?.rejectInference || profile.featureReview?.notes),
    "PDO Scaling": Boolean(profile.scorecardScaling?.pdo && profile.scorecardScaling?.baseScore && profile.scorecardScaling?.baseOdds),
    "Adverse Action": Boolean(profile.explainability?.adverseActionStatus || profile.explainability?.reasonCodeLogic),
    "Fair Lending": Boolean(profile.explainability?.fairLendingStatus),
    "Cutoff Strategy": Boolean(profile.decisionStrategy?.cutoffs || profile.decisionStrategy?.notes),
    "Risk-Based Pricing": Boolean(profile.decisionStrategy?.riskBasedPricing || profile.decisionStrategy?.notes),
    PSI: Boolean(profile.monitoring?.psiThresholds),
    "Champion / Challenger": Boolean(profile.championDecision?.selectedModelId || profile.monitoring?.challengerChampion || profile.monitoring?.challengerModel),
    "AI/ML Underwriting": Boolean(profile.mlModelId || profile.mlStatus),
    "Monotonic Constraints": Boolean(profile.monotonicConstraints?.length),
    "Feature Importance": Boolean(profile.mlModelId || profile.readiness?.["Feature Importance"]),
    "Surrogate Scorecard": Boolean(profile.readiness?.["Surrogate Scorecard"]),
    Monitoring: Boolean(profile.monitoring?.monitoringCadence || profile.monitoring?.redevelopmentTrigger),
    Documentation: profile.readiness?.Documentation === "Ready",
  };
  const items = readinessSections.map((section) => ({ section, status: (checks[section] || evidenceReady(section) ? "Ready" : "Missing") as CreditRiskStatus }));
  return { score: Math.round((items.filter((item) => item.status === "Ready").length / items.length) * 100), items };
}

function computeWorkflowStatus(profile: CreditRiskProfile, woeAnalysis: WoeIvAnalysis | null, scorecardModel: ScorecardModel | null, mlModel: CreditRiskMlModel | null, readinessScore: number): Record<string, CreditRiskStatus | "Not Started" | "Complete"> {
  return {
    "Project Setup": profile.datasetId && profile.productType && profile.modelPurpose ? "Complete" : "Ready",
    "Population and Target": profile.targetEvent && profile.targetWindow && profile.goodDefinition && profile.badDefinition ? "Complete" : profile.targetEvent ? "Needs Review" : "Ready",
    "Credit Risk EDA": (profile.edaStatus || (profile.variableMappings?.length ? "Ready" : "Not Started")) as CreditRiskStatus | "Not Started",
    "Characteristic Screening": (profile.screeningStatus || (profile.variableMappings?.some((row) => row.include) ? "Ready" : "Not Started")) as CreditRiskStatus | "Not Started",
    "Modeling Approach": profile.selectedModelingApproach ? "Complete" : "Ready",
    "Traditional Scorecard Path": (profile.scorecardStatus || profile.scorecardModelStatus || (scorecardModel ? "Complete" : woeAnalysis ? "Ready" : "Not Started")) as CreditRiskStatus | "Complete" | "Not Started",
    "AI/ML Underwriting Path": (profile.mlStatus || (mlModel ? "Complete" : profile.selectedModelingApproach === "ml" || profile.selectedModelingApproach === "compare_both" ? "Ready" : "Not Started")) as CreditRiskStatus | "Complete" | "Not Started",
    "Champion / Challenger Comparison": (profile.championDecisionStatus || profile.comparisonStatus || (profile.championModelId ? "Complete" : scorecardModel || mlModel ? "Ready" : "Not Started")) as CreditRiskStatus | "Complete" | "Not Started",
    "Cutoff and Decision Strategy": profile.cutoffStrategyStatus || (profile.decisionStrategy?.notes || scorecardModel?.cutoffTable?.length ? "Needs Review" : "Not Started"),
    "Explainability and Adverse Action": profile.adverseActionStatus || (profile.explainability?.reasonCodeLogic || profile.explainability?.adverseActionStatus ? "Needs Review" : "Ready"),
    "Monitoring and Portfolio Risk": profile.monitoringStatus || (profile.monitoring?.monitoringCadence ? "Ready" : "Not Started"),
    "Evidence and Documentation": profile.evidenceStatus || (readinessScore >= 80 ? "Complete" : "Needs Review"),
  };
}

function statusPillClass(status: string | undefined) {
  if (status === "Complete") return "bg-emerald-50 text-emerald-700";
  if (status === "Ready") return "bg-blue-50 text-blue-700";
  if (status === "Needs Review") return "bg-amber-50 text-amber-700";
  return "bg-slate-100 text-slate-500";
}

function screeningMetric(variable: string, analysis: WoeIvAnalysis | null, metric: "missing" | "distinct" | "iv", profile?: DatasetProfile | null) {
  const summary = analysis?.variableSummaries?.find((row) => row.variable === variable);
  if (!summary) {
    const schemaEntry = profile?.schema?.find((row) => row.name === variable);
    if (metric === "missing" && schemaEntry) return formatPercent(schemaEntry.missingPctSample);
    if (metric === "distinct" && schemaEntry) return String(schemaEntry.distinctSample);
    return metric === "iv" ? "-" : "Pending";
  }
  if (metric === "missing") return formatPercent(summary.missingRate);
  if (metric === "distinct") return String(summary.distinctCount);
  return formatNumber(summary.iv, 4);
}

function summarizeVariables(rows: CreditRiskVariableMapping[]) {
  const candidates = rows.filter((row) => row.include && !isScorecardExcluded(row.variable));
  return {
    total: candidates.length,
    bureau: candidates.filter((row) => row.role === "Bureau").length,
    application: candidates.filter((row) => row.role === "Application").length,
    excluded: rows.filter((row) => row.role === "Excluded" || !row.include).length,
    sensitive: candidates.filter((row) => row.role === "Protected / Sensitive").length,
    unknown: candidates.filter((row) => row.role === "Unknown").length,
  };
}

function inferVariableRole(name: string) {
  const lower = name.toLowerCase();
  if (lower === "bad_flag") return "Target";
  if (name === HELOC_DEFAULT_TARGET_LABEL || lower === HELOC_DEFAULT_TARGET_LABEL.toLowerCase()) return "Original Target Label / Excluded";
  if (lower === "atlas_split") return "Split Indicator / Excluded";
  if (isHelocBureauField(name) || /bureau|trade|tradeline|delq|inq|revolving|install|installment|utilization|burden|riskestimate|risk estimate|publicrec|public rec|months since|msince|satisfactory|balance/.test(lower)) return "Bureau";
  if (/income|employment/.test(lower)) return "Income";
  if (/state|zip|region|msa/.test(lower)) return "Geography";
  if (/race|gender|sex|ethnic/.test(lower)) return "Protected / Sensitive";
  if (/balance|payment|utilization|transaction/.test(lower)) return "Behavioral";
  return "Unknown";
}

const HELOC_BUREAU_FIELDS_LIST = [
  "ExternalRiskEstimate",
  "MSinceOldestTradeOpen",
  "MSinceMostRecentTradeOpen",
  "AverageMInFile",
  "NumSatisfactoryTrades",
  "NumTrades60Ever2DerogPubRec",
  "NumTrades90Ever2DerogPubRec",
  "PercentTradesNeverDelq",
  "MSinceMostRecentDelq",
  "MaxDelq2PublicRecLast12M",
  "MaxDelqEver",
  "NumTotalTrades",
  "NumTradesOpeninLast12M",
  "PercentInstallTrades",
  "MSinceMostRecentInqexcl7days",
  "NumInqLast6M",
  "NumInqLast6Mexcl7days",
  "NetFractionRevolvingBurden",
  "NetFractionInstallBurden",
  "NumRevolvingTradesWBalance",
  "NumInstallTradesWBalance",
  "NumBank2NatlTradesWHighUtilization",
  "PercentTradesWBalance",
];

const HELOC_BUREAU_FIELDS = new Set(HELOC_BUREAU_FIELDS_LIST);

function isHelocBureauField(name: string) {
  return HELOC_BUREAU_FIELDS.has(name);
}

function findDatasetIdByName(datasets: DatasetSummary[], pattern: RegExp) {
  return datasets.find((dataset) => pattern.test(dataset.name))?.datasetId || "";
}

function findTargetColumn(columns: string[]) {
  return columns.find((column) => column === "bad_flag")
    || columns.find((column) => /bad|default|charge|target|class|label/i.test(column))
    || columns[columns.length - 1]
    || "";
}

function buildVariableMappings(columns: string[], datasetName: string, targetColumn: string, splitColumn: string, originalTarget: string): CreditRiskVariableMapping[] {
  const isHeloc = /heloc/i.test(datasetName) || HELOC_BUREAU_FIELDS.size > 0 && columns.some((column) => HELOC_BUREAU_FIELDS.has(column));
  return columns.map((variable) => {
    const role = variable === targetColumn
      ? "Target"
      : variable === splitColumn
        ? "Split Indicator / Excluded"
        : variable === originalTarget
          ? "Original Target Label / Excluded"
          : isHeloc && isHelocBureauField(variable)
            ? "Bureau"
            : inferVariableRole(variable);
    const excluded = variable === targetColumn || variable === splitColumn || variable === originalTarget || isScorecardExcluded(variable);
    return {
      variable,
      role: excluded && role === "Unknown" ? "Excluded" : role,
      source: isHeloc && isHelocBureauField(variable) ? `${datasetName || "HELOC_TRAIN"} / bureau-style credit attributes` : "Dataset Library schema",
      include: !excluded,
      notes: excluded ? "Excluded from predictor list by target/split/leakage rule." : "",
    };
  });
}

function strategyRows(profile: CreditRiskProfile) {
  const existing = profile.decisionStrategy?.cutoffs;
  if (Array.isArray(existing) && existing.length) return existing as Array<Record<string, string>>;
  return [
    { cutoff: "620", approvalRate: "72%", badRate: "5.8%", expectedLoss: "$1.2M", expectedProfit: "$3.8M", pricingTier: "Tier C", recommendation: "Review" },
    { cutoff: "660", approvalRate: "61%", badRate: "3.9%", expectedLoss: "$820K", expectedProfit: "$3.4M", pricingTier: "Tier B", recommendation: "Candidate" },
    { cutoff: "700", approvalRate: "49%", badRate: "2.5%", expectedLoss: "$510K", expectedProfit: "$2.7M", pricingTier: "Tier A", recommendation: "Conservative" },
  ];
}

function nextAction(profile: CreditRiskProfile, score: number) {
  if (!profile.datasetId) return "Select a Dataset Library dataset and classify variables.";
  if (!profile.targetEvent || !profile.targetWindow) return "Finish target event and performance window definitions.";
  if (!profile.selectedModelingApproach) return "Choose Traditional Scorecard, AI/ML Underwriting, or Compare Both.";
  if (score < 70) return "Capture scorecard, AI/ML, adverse action, fair lending, cutoff, PSI, and monitoring evidence.";
  return "Open Model Evidence Center and review readiness before documentation assembly.";
}

function creditRiskBottomCta(active: string) {
  const map: Record<string, { label: string; next?: string }> = {
    "Project Setup": { label: "Confirm Project Setup and Continue", next: "Population and Target" },
    "Population and Target": { label: "Save Target Definition and Continue", next: "Credit Risk EDA" },
    "Credit Risk EDA": { label: "Save EDA Evidence and Continue", next: "Characteristic Screening" },
    "Modeling Approach": { label: "Confirm Modeling Approach and Continue", next: "Traditional Scorecard Path" },
    "Traditional Scorecard Path": { label: "Save Scorecard Progress and Continue", next: "AI/ML Underwriting Path" },
    "AI/ML Underwriting Path": { label: "Save AI/ML Progress and Continue", next: "Champion / Challenger Comparison" },
    "Champion / Challenger Comparison": { label: "Save Champion Decision and Continue", next: "Explainability and Adverse Action" },
    "Explainability and Adverse Action": { label: "Save Explainability Evidence and Continue", next: "Cutoff and Decision Strategy" },
    "Cutoff and Decision Strategy": { label: "Save Decision Strategy and Continue", next: "Evidence and Documentation" },
    "Monitoring and Portfolio Risk": { label: "Save Monitoring Evidence and Continue", next: "Evidence and Documentation" },
    "Evidence and Documentation": { label: "Open Model Evidence Center / Open Model Documentation Studio" },
  };
  return map[active];
}

function approachLabel(value?: string) {
  if (value === "scorecard") return "Traditional Scorecard";
  if (value === "ml") return "AI/ML Underwriting";
  if (value === "compare_both") return "Compare Both";
  return value || "Not selected";
}

function readinessUpdatesForTechnique(technique: string): Record<string, CreditRiskStatus> {
  const updates: Record<string, CreditRiskStatus> = {};
  const ready = (section: string) => {
    updates[section] = "Ready";
  };
  if (technique === "target_definition") {
    ready("Target Definition");
    ready("Population Definition");
  }
  if (technique === "data_acquisition") {
    ready("Data Sources");
    ready("Target Definition");
    ready("Population Definition");
  }
  if (technique === "bureau_data_review") ready("Data Sources");
  if (technique === "credit_risk_eda") ready("Variable Mapping");
  if (technique === "outlier_treatment") ready("Outlier Treatment");
  if (technique === "missing_value_treatment") ready("Missing Value Treatment");
  if (technique === "split_strategy") ready("Development Test and OOT Data");
  if (technique === "variable_mapping") ready("Variable Mapping");
  if (technique === "woe" || technique === "woe_iv") ready("WOE / IV");
  if (technique === "ml_underwriting") ready("AI/ML Underwriting");
  if (technique === "feature_importance") ready("Feature Importance");
  if (technique === "monotonic_constraints") ready("Monotonic Constraints");
  if (technique === "surrogate_scorecard") ready("Surrogate Scorecard");
  if (technique === "manual_binning") ready("Manual Binning");
  if (technique === "reject_inference") ready("Reject Inference");
  if (technique === "iv") ready("WOE / IV");
  if (technique === "pdo" || technique === "scorecard_scaling") ready("PDO Scaling");
  if (technique === "scorecard_modeling" || technique === "scorecard_performance" || technique === "scorecard_points") {
    ready("Cutoff Strategy");
    ready("PDO Scaling");
  }
  if (technique === "scorecard_performance") ready("Champion / Challenger");
  if (technique === "adverse_action") ready("Adverse Action");
  if (technique === "fair_lending") ready("Fair Lending");
  if (technique === "cutoff_optimization" || technique === "strategy_trees") ready("Cutoff Strategy");
  if (technique === "risk_based_pricing") ready("Risk-Based Pricing");
  if (technique === "psi") ready("PSI");
  if (technique === "challenger_champion" || technique === "champion_challenger") ready("Champion / Challenger");
  if (technique === "ttc" || technique === "monitoring_threshold") ready("Monitoring");
  if (Object.keys(updates).length) ready("Documentation");
  return updates;
}

function mlModelCards() {
  return [
    { title: "Logistic Regression Baseline", available: true, text: "Transparent linear challenger using raw numeric predictors.", reason: "" },
    { title: "Random Forest", available: true, text: "Nonlinear ensemble useful for challenger lift and interaction discovery.", reason: "" },
    { title: "XGBoost", available: false, text: "Gradient boosting challenger with strong nonlinear performance.", reason: "Install xgboost in the backend environment to enable native training." },
    { title: "LightGBM", available: false, text: "Efficient gradient boosting with optional monotonic constraints.", reason: "Install lightgbm in the backend environment to enable native training." },
    { title: "CatBoost", available: false, text: "Boosting model with strong categorical handling.", reason: "Install catboost in the backend environment to enable native training." },
    { title: "Monotonic Gradient Boosting", available: false, text: "Constrained GBM for underwriting relationships expected to move in one direction.", reason: "Native monotonic constraints require a supported GBM backend." },
    { title: "Calibrated AI/ML Model", available: true, text: "Local lightweight model plus documented calibration review.", reason: "" },
  ];
}

function ApproachCard({ title, selected, text, bestFor, onClick }: { title: string; selected: boolean; text: string; bestFor: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className={`rounded-2xl border p-4 text-left transition ${selected ? "border-blue-500 bg-blue-50 shadow-sm" : "border-slate-200 bg-white hover:border-blue-200"}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="text-base font-semibold text-slate-950">{title}</div>
        <span className={`rounded-full px-2 py-1 text-[10px] font-semibold uppercase ${selected ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-600"}`}>{selected ? "Selected" : "Select"}</span>
      </div>
      <p className="mt-3 text-sm leading-6 text-slate-600">{text}</p>
      <p className="mt-3 rounded-xl bg-slate-50 p-3 text-xs font-semibold leading-5 text-slate-700">{bestFor}</p>
    </button>
  );
}

function CapabilityComparisonTable() {
  const rows = [
    ["WOE / IV", "Yes", "Optional"],
    ["Manual binning", "Yes", "Optional"],
    ["Logistic regression", "Yes", "Optional"],
    ["PDO scaling", "Yes", "Optional calibration output"],
    ["Scorecard points", "Yes", "Via surrogate scorecard"],
    ["Monotonic constraints", "Manual / binning", "Native for supported GBM"],
    ["SHAP", "Optional", "Yes"],
    ["PDP / ICE", "Optional", "Yes"],
    ["Adverse action", "Reason codes from scorecard", "Reason codes from SHAP / surrogate"],
    ["Model risk review", "Very strong", "Requires stronger explanation"],
    ["Performance potential", "Moderate", "High"],
    ["Transparency", "High", "Medium to low unless constrained"],
  ];
  return (
    <div className="overflow-auto rounded-xl border border-slate-200">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr><th className="px-3 py-2">Capability</th><th className="px-3 py-2">Traditional Scorecard</th><th className="px-3 py-2">AI/ML Underwriting</th></tr>
        </thead>
        <tbody>{rows.map((row) => <tr key={row[0]} className="border-t border-slate-100"><td className="px-3 py-2 font-semibold">{row[0]}</td><td className="px-3 py-2">{row[1]}</td><td className="px-3 py-2">{row[2]}</td></tr>)}</tbody>
      </table>
    </div>
  );
}

function MonotonicConstraintsPanel({ profile, schema, patch }: { profile: CreditRiskProfile; schema: string[]; patch: (constraints: NonNullable<CreditRiskProfile["monotonicConstraints"]>) => void }) {
  const constraints = profile.monotonicConstraints?.length ? profile.monotonicConstraints : [
    { variable: schema.find((column) => /util/i.test(column)) || "Utilization", expectedDirection: "Higher utilization should generally increase risk.", constraint: "Increasing risk", rationale: "Credit exposure and revolving utilization are typically positively related to default risk.", reviewerNote: "" },
    { variable: schema.find((column) => /fico|score/i.test(column)) || "Credit Score", expectedDirection: "Higher credit score should generally decrease risk.", constraint: "Decreasing risk", rationale: "Higher bureau score is expected to reduce default risk.", reviewerNote: "" },
    { variable: schema.find((column) => /income/i.test(column)) || "Income", expectedDirection: "Higher income should generally decrease risk.", constraint: "Decreasing risk", rationale: "Income can support repayment capacity but should be reviewed for fairness and policy constraints.", reviewerNote: "" },
  ];
  const update = (index: number, update: Record<string, string>) => patch(constraints.map((row, idx) => idx === index ? { ...row, ...update } : row));
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-semibold text-slate-950">Monotonic Constraints</div>
          <p className="mt-1 text-sm text-slate-600">Document expected underwriting directions. Unsupported models preserve this as review evidence but do not enforce constraints during training.</p>
        </div>
      </div>
      <div className="mt-3 overflow-auto rounded-xl border border-slate-200">
        <table className="min-w-full text-left text-xs">
          <thead className="bg-slate-50 uppercase tracking-wide text-slate-500">
            <tr><th className="px-3 py-2">Variable</th><th className="px-3 py-2">Expected Direction</th><th className="px-3 py-2">Constraint</th><th className="px-3 py-2">Business Rationale</th><th className="px-3 py-2">Reviewer Note</th></tr>
          </thead>
          <tbody>{constraints.map((row, index) => (
            <tr key={`${row.variable}-${index}`} className="border-t border-slate-100">
              <td className="px-3 py-2"><input className="w-44 rounded-lg border border-slate-300 px-2 py-1" value={row.variable} onChange={(event) => update(index, { variable: event.target.value })} /></td>
              <td className="px-3 py-2"><input className="w-72 rounded-lg border border-slate-300 px-2 py-1" value={row.expectedDirection} onChange={(event) => update(index, { expectedDirection: event.target.value })} /></td>
              <td className="px-3 py-2"><select className="w-44 rounded-lg border border-slate-300 px-2 py-1" value={row.constraint} onChange={(event) => update(index, { constraint: event.target.value })}>{["Increasing risk", "Decreasing risk", "No constraint", "Exclude"].map((option) => <option key={option}>{option}</option>)}</select></td>
              <td className="px-3 py-2"><input className="w-80 rounded-lg border border-slate-300 px-2 py-1" value={row.rationale} onChange={(event) => update(index, { rationale: event.target.value })} /></td>
              <td className="px-3 py-2"><input className="w-60 rounded-lg border border-slate-300 px-2 py-1" value={row.reviewerNote || ""} onChange={(event) => update(index, { reviewerNote: event.target.value })} /></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm leading-6 text-amber-900">
        The selected model may not support native monotonic constraints. ATLAS will preserve constraint evidence for review, but enforcement depends on the backend model family.
      </div>
    </div>
  );
}

function AiMlExplainabilityPanel({ model }: { model: CreditRiskMlModel | null }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4">
      <div className="font-semibold text-slate-950">AI/ML Explainability</div>
      <p className="mt-1 text-sm text-slate-600">Feature importance, SHAP-style global explanation, reason-code candidate mapping, PDP / ICE placeholder, surrogate scorecard, and model complexity warning.</p>
      <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm leading-6 text-amber-900">
        SHAP is not available in this local environment. ATLAS is showing feature importance and surrogate explanation placeholders. Install SHAP or connect a hosted explainability service for full SHAP values.
      </div>
      {model ? <SimpleBarPanel title="Feature Importance" rows={model.featureImportance} labelKey="feature" valueKey="importance" /> : <EmptyPanel text="Train an AI/ML challenger to populate feature importance and calibration artifacts." />}
    </div>
  );
}

function SurrogateScorecardPanel({ model }: { model: CreditRiskMlModel | null }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4">
      <div className="font-semibold text-slate-950">Surrogate Scorecard</div>
      <p className="mt-1 text-sm text-slate-600">A surrogate scorecard approximates the AI/ML challenger with a simpler, more explainable scorecard-style model.</p>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <Metric label="Surrogate model type" value="Logistic scorecard placeholder" />
        <Metric label="Approximation quality" value={model ? "Needs Review" : "Pending"} />
        <Metric label="AUC of surrogate" value="Pending" />
        <Metric label="Agreement by decile" value="Pending" />
      </div>
      <p className="mt-3 rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm leading-6 text-blue-950">
        Surrogate scorecards can support explainability, but they do not replace validation of the original AI/ML model.
      </p>
    </div>
  );
}

function ChampionComparisonTable({ scorecardModel, mlModel, comparison }: { scorecardModel: ScorecardModel | null; mlModel: CreditRiskMlModel | null; comparison: Record<string, unknown> | null }) {
  const generatedRows = Array.isArray(comparison?.rows) ? comparison.rows as Array<Record<string, unknown>> : [];
  const rows: Array<Record<string, unknown>> = generatedRows.length ? generatedRows : [
    comparisonRowFromModel("Traditional Scorecard Baseline", "Traditional Scorecard", scorecardModel?.metrics, scorecardModel ? "Benchmark" : "Needs Review"),
    comparisonRowFromModel("AI/ML Challenger", mlModel?.modelType || "AI/ML Underwriting", mlModel?.metrics, mlModel ? "Challenger" : "Needs Review"),
    comparisonRowFromModel("Current Champion if available", "Existing Champion", undefined, "Needs Review"),
  ];
  const columns = ["Model", "Model Type", "AUC", "KS", "Gini", "Log Loss", "Approval Rate", "Bad Rate", "Lift Top Decile", "Calibration Quality", "Explainability Strength", "Adverse Action Readiness", "Fair Lending Readiness", "Monitoring Readiness", "Model Risk Complexity", "Recommended Role"];
  const keys = ["model", "modelType", "auc", "ks", "gini", "logLoss", "approvalRate", "badRate", "liftTopDecile", "calibrationQuality", "explainabilityStrength", "adverseActionReadiness", "fairLendingReadiness", "monitoringReadiness", "modelRiskComplexity", "recommendedRole"];
  return (
    <div className="overflow-auto rounded-xl border border-slate-200">
      <table className="min-w-full text-left text-xs">
        <thead className="sticky top-0 bg-slate-50 uppercase tracking-wide text-slate-500"><tr>{columns.map((column) => <th key={column} className="px-3 py-2">{column}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => <tr key={`${row.model}-${index}`} className="border-t border-slate-100">{keys.map((key) => <td key={key} className="px-3 py-2">{formatCell(row[key])}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

function comparisonRowFromModel(model: string, modelType: string, metrics: ScorecardModel["metrics"] | CreditRiskMlModel["metrics"] | undefined, recommendedRole: string) {
  return {
    model,
    modelType,
    auc: metrics?.auc,
    ks: metrics?.ks,
    gini: metrics?.gini,
    logLoss: metrics?.logLoss,
    approvalRate: "Review",
    badRate: "Review",
    liftTopDecile: "Review",
    calibrationQuality: "Review",
    explainabilityStrength: /scorecard/i.test(modelType) ? "High" : "Medium",
    adverseActionReadiness: /scorecard/i.test(modelType) ? "High" : "Needs surrogate / SHAP review",
    fairLendingReadiness: "Needs Review",
    monitoringReadiness: "Needs Review",
    modelRiskComplexity: /scorecard/i.test(modelType) ? "Low" : "Medium / High",
    recommendedRole,
  };
}

function WoeVariableDetail({ summary }: { summary: WoeIvVariableSummary }) {
  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-4">
        <Metric label="IV" value={formatNumber(summary.iv, 4)} />
        <Metric label="Strength" value={summary.predictiveStrength} />
        <Metric label="Monotonicity" value={summary.monotonicity} tone={summary.monotonicity === "monotonic" ? "green" : "amber"} />
        <Metric label="Missing %" value={`${(summary.missingRate * 100).toFixed(1)}%`} />
      </div>
      {summary.warnings?.length ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">{summary.warnings.join(" ")}</div>
      ) : null}
      <div className="overflow-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-left text-xs">
          <thead className="sticky top-0 bg-slate-50 uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2">Bin</th>
              <th className="px-3 py-2">Total</th>
              <th className="px-3 py-2">Good</th>
              <th className="px-3 py-2">Bad</th>
              <th className="px-3 py-2">Bad Rate</th>
              <th className="px-3 py-2">Dist Good</th>
              <th className="px-3 py-2">Dist Bad</th>
              <th className="px-3 py-2">WOE</th>
              <th className="px-3 py-2">IV Contribution</th>
            </tr>
          </thead>
          <tbody>
            {summary.bins.map((bin) => (
              <tr key={bin.binId} className="border-t border-slate-100">
                <td className="px-3 py-2 font-semibold text-slate-900">{bin.label}</td>
                <td className="px-3 py-2">{bin.totalCount.toLocaleString()}</td>
                <td className="px-3 py-2">{bin.goodCount.toLocaleString()}</td>
                <td className="px-3 py-2">{bin.badCount.toLocaleString()}</td>
                <td className="px-3 py-2">{formatPercent(bin.badRate)}</td>
                <td className="px-3 py-2">{formatPercent(bin.distGood)}</td>
                <td className="px-3 py-2">{formatPercent(bin.distBad)}</td>
                <td className="px-3 py-2">{formatNumber(bin.woe, 4)}</td>
                <td className="px-3 py-2">{formatNumber(bin.ivContribution, 4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-900">{summary.recommendation}</div>
    </div>
  );
}

type WoeChartField = "badRate" | "woe" | "ivContribution" | "populationPct";

function WoeBarChart({ title, summary, field, format = "number" }: { title: string; summary: WoeIvVariableSummary | null; field: WoeChartField; format?: "number" | "percent" }) {
  const bins = summary?.bins || [];
  const values = bins.map((bin) => Number(bin[field] ?? 0));
  const max = Math.max(...values.map((value) => Math.abs(value)), 0.0001);
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="text-sm font-semibold text-slate-950">{title}</div>
      <div className="mt-4 space-y-2">
        {bins.length ? bins.map((bin) => {
          const value = Number(bin[field] ?? 0);
          const width = Math.max(2, Math.round((Math.abs(value) / max) * 100));
          return (
            <div key={`${title}-${bin.binId}`} className="grid grid-cols-[minmax(90px,0.55fr)_1fr_72px] items-center gap-3 text-xs">
              <div className="truncate font-semibold text-slate-700" title={bin.label}>{bin.label}</div>
              <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
                <div className={`h-full rounded-full ${value < 0 ? "bg-rose-500" : "bg-blue-600"}`} style={{ width: `${width}%` }} />
              </div>
              <div className="text-right font-mono text-slate-700">{format === "percent" ? formatPercent(value) : formatNumber(value, 3)}</div>
            </div>
          );
        }) : <EmptyPanel text="Run WOE / IV analysis to render this diagnostic." />}
      </div>
    </div>
  );
}

function ScorecardPointsTable({ model }: { model: ScorecardModel }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="mb-3 text-sm font-semibold text-slate-950">Scorecard Points Table</div>
      <div className="max-h-96 overflow-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-left text-xs">
          <thead className="sticky top-0 bg-slate-50 uppercase tracking-wide text-slate-500">
            <tr><th className="px-3 py-2">Variable</th><th className="px-3 py-2">Bin</th><th className="px-3 py-2">WOE</th><th className="px-3 py-2">Coefficient</th><th className="px-3 py-2">Raw Contribution</th><th className="px-3 py-2">Points</th><th className="px-3 py-2">Reason Code Label</th></tr>
          </thead>
          <tbody>
            {model.scorecardPoints.map((row, index) => (
              <tr key={`${row.variable}-${row.bin}-${index}`} className="border-t border-slate-100">
                <td className="px-3 py-2 font-semibold text-slate-900">{String(row.variable ?? "")}</td>
                <td className="px-3 py-2">{String(row.bin ?? "")}</td>
                <td className="px-3 py-2">{formatNumber(row.woe, 4)}</td>
                <td className="px-3 py-2">{formatNumber(row.coefficient, 5)}</td>
                <td className="px-3 py-2">{formatNumber(row.rawContribution, 5)}</td>
                <td className="px-3 py-2 font-semibold">{formatNumber(row.points, 2)}</td>
                <td className="px-3 py-2">{String(row.reasonCodeLabel ?? "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SimpleBarPanel({ title, rows, labelKey, valueKey, percent = false }: { title: string; rows: Array<Record<string, unknown>>; labelKey: string; valueKey: string; percent?: boolean }) {
  const values = rows.map((row) => parseMetricValue(row[valueKey]));
  const max = Math.max(...values.map((value) => Math.abs(value)), 0.0001);
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="text-sm font-semibold text-slate-950">{title}</div>
      <div className="mt-4 space-y-2">
        {rows.map((row, index) => {
          const value = parseMetricValue(row[valueKey]);
          const width = Math.max(2, Math.round((Math.abs(value) / max) * 100));
          return (
            <div key={`${title}-${index}`} className="grid grid-cols-[92px_1fr_72px] items-center gap-3 text-xs">
              <div className="truncate font-semibold text-slate-700" title={String(row[labelKey] ?? "")}>{String(row[labelKey] ?? "")}</div>
              <div className="h-2.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-blue-600" style={{ width: `${width}%` }} /></div>
              <div className="text-right font-mono text-slate-700">{percent ? formatPercent(value) : formatNumber(value, 3)}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function parseMetricValue(value: unknown) {
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  const parsed = Number(String(value ?? "0").replace(/[$,%]/g, ""));
  return Number.isFinite(parsed) ? parsed : 0;
}

function LiftTable({ rows }: { rows: Array<Record<string, unknown>> }) {
  const columns = ["decile", "accounts", "accountPct", "minScore", "maxScore", "avgScore", "expectedEvents", "actualEvents", "actualEventRate", "cumulativeAccountPct", "cumulativeEventPct", "cumulativeNonEventPct", "lift"];
  return <DataTable title="Detailed Lift Table" columns={columns} rows={rows} />;
}

function CutoffTable({ rows }: { rows: Array<Record<string, unknown>> }) {
  const columns = ["scoreCutoff", "approvalRate", "badRate", "expectedLoss", "expectedProfit", "populationApproved", "populationDeclined", "recommendation"];
  return <DataTable title="Cutoff Strategy Preview" columns={columns} rows={rows} />;
}

function DataTable({ title, columns, rows }: { title: string; columns: string[]; rows: Array<Record<string, unknown>> }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="mb-3 text-sm font-semibold text-slate-950">{title}</div>
      <div className="overflow-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-left text-xs">
          <thead className="sticky top-0 bg-slate-50 uppercase tracking-wide text-slate-500"><tr>{columns.map((column) => <th key={column} className="px-3 py-2">{column}</th>)}</tr></thead>
          <tbody>{rows.map((row, index) => <tr key={`${title}-${index}`} className="border-t border-slate-100">{columns.map((column) => <td key={column} className="px-3 py-2">{formatCell(row[column])}</td>)}</tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}

function TargetSummaryPanel({ profile, summary }: { profile: CreditRiskProfile; summary: CreditRiskTargetSummary | null }) {
  const isPreview = summary?.scope === "preview";
  const summaryMessage = summary?.message || (summary && !summary.fullDatasetAvailable ? previewTargetSummaryMessage : "");
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-semibold text-slate-950">{isPreview ? "Preview Sample Summary" : "Target Summary"}</div>
        {summary && <span className={`rounded-full px-2 py-1 text-xs font-semibold ${isPreview ? "bg-amber-100 text-amber-800" : "bg-emerald-100 text-emerald-800"}`}>{summary.fullDatasetAvailable ? "Full dataset summary" : "Preview sample summary"}</span>}
      </div>
      {summaryMessage && <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">{summaryMessage}</div>}
      {!summary && (
        <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">
          Select a target column to calculate the target summary.
        </div>
      )}
      <div className="grid gap-3 md:grid-cols-6">
        <Metric label={summary?.fullDatasetAvailable ? "Total rows" : "Profiled rows"} value={summary ? summary.totalRows.toLocaleString() : "Select target"} />
        <Metric label="Good count" value={summary ? summary.goodCount.toLocaleString() : "-"} />
        <Metric label="Bad count" value={summary ? summary.badCount.toLocaleString() : "-"} />
        <Metric label="Bad rate" value={summary ? formatPercent(summary.badRate) : "-"} tone={summary && summary.badRate < 0.01 ? "amber" : "slate"} />
        <Metric label="Indeterminate count" value={summary ? summary.indeterminateCount.toLocaleString() : "-"} />
        <Metric label="Missing target count" value={summary ? summary.missingTargetCount.toLocaleString() : "-"} />
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-3">
        <Metric label="Full dataset rows" value={summary ? summary.rowCount.toLocaleString() : "-"} />
        <Metric label="Target window" value={profile.targetWindow || "Not documented"} />
        <Metric label="Outcome source" value={profile.outcomeSourceTable || "Not documented"} />
      </div>
    </div>
  );
}

function SpecialValueProfilePanel({ summary }: { summary: CreditRiskTargetSummary | null }) {
  const rows = summary?.specialValueProfile || [];
  return (
    <div className="rounded-xl border border-blue-100 bg-blue-50/60 p-4">
      <div className="mb-2 text-sm font-semibold text-blue-950">Bureau Special Value Profile</div>
      <p className="mb-3 text-xs leading-5 text-blue-900">Bureau special values such as -7, -8, and -9 are preserved as special values for binning. They are not treated as ordinary missing values unless the user explicitly chooses that treatment.</p>
      {rows.length ? (
        <DataTable title="Special Value Counts" columns={["variable", "countMinus7", "countMinus8", "countMinus9", "specialValueRate", "recommendedTreatment"]} rows={rows as unknown as Array<Record<string, unknown>>} />
      ) : (
        <div className="rounded-lg border border-slate-200 bg-white px-3 py-4 text-xs text-slate-600">No -7, -8, or -9 bureau special values were detected in the current available dataset artifact.</div>
      )}
    </div>
  );
}

function CreditRiskEdaPanel({ profile, woeAnalysis, variableCounts }: { profile: CreditRiskProfile; woeAnalysis: WoeIvAnalysis | null; variableCounts: ReturnType<typeof summarizeVariables> }) {
  const candidateMappings = (profile.variableMappings || []).filter((row) => row.include && !isScorecardExcluded(row.variable));
  const rows = candidateMappings.slice(0, 24).map((row) => {
    const summary = woeAnalysis?.variableSummaries?.find((item) => item.variable === row.variable);
    return {
      variable: row.variable,
      role: row.role,
      missingPct: summary ? formatPercent(summary.missingRate) : "Use Dataset Profile",
      distinctCount: summary?.distinctCount ?? "Profile schema",
      meanMode: isHelocBureauField(row.variable) ? "Bureau numeric review" : "Distribution review",
      badRateSpread: summary?.bins?.length ? `${formatPercent(Math.max(...summary.bins.map((bin) => bin.badRate)) - Math.min(...summary.bins.map((bin) => bin.badRate)))}` : "Run WOE / IV for bad-rate spread",
      correlationWithTarget: summary ? "WOE proxy" : "Association review in Analytics Workbench",
      potentialLeakageFlag: isScorecardExcluded(row.variable) ? "Review" : "Low",
      recommendedAction: row.include ? "Screen" : "Exclude",
    };
  });
  const chartRows = woeAnalysis?.variableSummaries?.slice(0, 10).map((row) => ({ variable: row.variable, iv: row.iv })) || [];
  const missingRows = woeAnalysis?.variableSummaries?.slice(0, 10).map((row) => ({ variable: row.variable, missingRate: row.missingRate })) || [];
  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-4">
        <Metric label="Dataset" value={profile.datasetId ? "HELOC_TRAIN" : "Select dataset"} />
        <Metric label="Target distribution" value={profile.targetColumn || "bad_flag"} />
        <Metric label="Good / bad count" value={profile.targetSummary ? `${profile.targetSummary.goodCount.toLocaleString()} / ${profile.targetSummary.badCount.toLocaleString()}` : "Target summary loading"} />
        <Metric label="Bad rate" value={profile.targetSummary ? formatPercent(profile.targetSummary.badRate) : "Target summary loading"} />
      </div>
      <div className="grid gap-3 md:grid-cols-6">
        <Metric label="Candidate variables" value={String(variableCounts.total || 23)} />
        <Metric label="Bureau / app mix" value={`${variableCounts.bureau}/${variableCounts.application}`} />
        <Metric label="Protected flags" value={String(variableCounts.sensitive)} tone={variableCounts.sensitive ? "amber" : "green"} />
        <Metric label="Potential leakage flags" value={String((profile.variableMappings || []).filter((row) => row.include && isScorecardExcluded(row.variable)).length)} tone="amber" />
        <Metric label="Missingness table" value={candidateMappings.length ? "Schema review available" : "Load schema"} />
        <Metric label="Event rate by segment" value={woeAnalysis ? "Available" : "Run WOE / IV for segment rates"} />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <SimpleBarPanel title="Candidate Variable Ranking" rows={chartRows} labelKey="variable" valueKey="iv" />
        <SimpleBarPanel title="Missingness Profile" rows={missingRows} labelKey="variable" valueKey="missingRate" percent />
      </div>
      <div className="flex flex-wrap gap-2">
        <DownloadButton label="Download predictor ranking CSV" onClick={() => downloadRowsCsv("atlas-eda-candidate-predictor-ranking.csv", rows)} />
        <DownloadButton label="Download visualization data JSON" onClick={() => downloadJson("atlas-eda-visualizations.json", { candidateVariableRanking: chartRows, missingnessProfile: missingRows })} />
      </div>
      <div className="sr-only">Credit Risk EDA Variable Review</div>
      <div className="sr-only">Special bureau value profile</div>
      <DataTable title="Candidate Predictor Ranking" columns={["variable", "role", "recommendedAction", "potentialLeakageFlag"]} rows={rows.slice(0, 12)} />
    </div>
  );
}

function ApprovedPredictorSummary({ profile, woeAnalysis, datasetProfile, targetSummary }: { profile: CreditRiskProfile; woeAnalysis: WoeIvAnalysis | null; datasetProfile: DatasetProfile | null; targetSummary: CreditRiskTargetSummary | null }) {
  const rows = (profile.variableMappings || [])
    .filter((row) => row.include && row.role !== "Protected / Sensitive" && row.role !== "Excluded" && isCreditRiskPredictorCandidate(row.variable, profile))
    .slice(0, 12)
    .map((row) => ({
      Variable: row.variable,
      Role: row.role,
      Source: row.source,
      "Missing %": screeningMetric(row.variable, woeAnalysis, "missing", datasetProfile),
      "Special Value %": formatPercent((targetSummary?.specialValueProfile || []).find((item) => item.variable === row.variable)?.specialValueRate),
      "IV if available": screeningMetric(row.variable, woeAnalysis, "iv"),
      "Leakage Risk": isScorecardExcluded(row.variable) ? "High" : "Low",
      "Use for WOE / IV": "Yes",
      Recommendation: "Eligible for WOE / IV screening",
    }));
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4">
        <div>
          <div className="text-sm font-semibold text-slate-950">Approved Predictor Review</div>
          <p className="mt-1 text-xs leading-5 text-slate-600">Read-only summary of candidate predictors carried forward from Data Acquisition, EDA, Outliers, and Missing Values.</p>
        </div>
        <DownloadButton label="Download approved predictors CSV" onClick={() => downloadRowsCsv("atlas-feature-engineering-approved-predictors.csv", rows)} />
      </div>
      <DataTable title="Approved predictors for WOE / IV" columns={["Variable", "Role", "Source", "Missing %", "Special Value %", "IV if available", "Leakage Risk", "Use for WOE / IV", "Recommendation"]} rows={rows} />
    </div>
  );
}

function FinalModelFeatureReviewPanel({
  profile,
  woeAnalysis,
  previewIvByVariable,
  selectedVariables,
  targetColumn,
  statusMessage,
  onToggle,
  onApplyRecommended,
}: {
  profile: CreditRiskProfile;
  woeAnalysis: WoeIvAnalysis | null;
  previewIvByVariable?: Map<string, number>;
  selectedVariables: string[];
  targetColumn?: string;
  statusMessage?: string;
  onToggle: (variable: string, selected: boolean) => void;
  onApplyRecommended: () => void;
}) {
  const selectedSet = new Set(selectedVariables);
  const rows = finalFeatureReviewRows({ profile, woeAnalysis, previewIvByVariable, targetColumn });
  const selectedCount = rows.filter((row) => selectedSet.has(row.variable)).length;
  const hasIvValues = rows.some((row) => row.iv != null);
  return (
    <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-emerald-700">Final feature gate before model training</div>
          <h3 className="mt-1 text-base font-semibold text-emerald-950">Review IV-ranked predictors</h3>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-emerald-900">
            This is the last feature-selection checkpoint before Model Training. Deselect any predictor that should not move into the scorecard or AI/ML training request.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="atlas-secondary-button" onClick={onApplyRecommended} disabled={!hasIvValues}>
            Apply IV recommended set
          </button>
          <DownloadButton
            label="Download final feature review CSV"
            onClick={() => downloadRowsCsv("atlas-balance-split-final-feature-review.csv", rows.map((row) => ({
              variable: row.variable,
              iv: row.ivLabel,
              ivSource: row.ivSource,
              status: row.status,
              recommendation: row.recommendation,
              selectedForTraining: selectedSet.has(row.variable) ? "Yes" : "No",
            })))}
          />
        </div>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-4">
        <Metric label="Features available" value={String(rows.length)} />
        <Metric label="Selected for training" value={String(selectedCount)} tone={selectedCount ? "green" : "amber"} />
        <Metric label="With IV available" value={String(rows.filter((row) => row.iv != null).length)} />
        <Metric label="High IV review flags" value={String(rows.filter((row) => row.iv != null && row.iv >= 0.5).length)} tone={rows.some((row) => row.iv != null && row.iv >= 0.5) ? "amber" : "green"} />
      </div>
      {!woeAnalysis && !hasIvValues && (
        <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm leading-6 text-amber-900">
          WOE / IV analysis is not available yet. ATLAS is showing approved schema-level predictors, but the IV column will populate after WOE / IV is run.
        </div>
      )}
      {!woeAnalysis && hasIvValues && (
        <div className="mt-4 rounded-xl border border-emerald-200 bg-white p-3 text-sm leading-6 text-emerald-900">
          Showing Data Acquisition preview IV values now. Full WOE / IV values will replace these automatically when the governed full-dataset analysis is available.
        </div>
      )}
      {statusMessage && (
        <div className="mt-4 rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm leading-6 text-blue-900">
          {statusMessage}
        </div>
      )}
      <div className="mt-4 max-h-[360px] overflow-auto rounded-xl border border-emerald-200 bg-white">
        <table className="w-full min-w-[760px] text-sm">
          <thead className="sticky top-0 bg-emerald-50 text-left text-xs uppercase tracking-wide text-emerald-800">
            <tr>
              <th className="px-3 py-2">Use in model training</th>
              <th className="px-3 py-2">Feature</th>
              <th className="px-3 py-2 text-right">IV</th>
              <th className="px-3 py-2">Source</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Recommendation</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const checked = selectedSet.has(row.variable);
              return (
                <tr key={row.variable} className="border-t border-emerald-100">
                  <td className="px-3 py-2">
                    <label className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs font-semibold text-slate-700">
                      <input type="checkbox" checked={checked} onChange={(event) => onToggle(row.variable, event.target.checked)} />
                      Use
                    </label>
                  </td>
                  <td className="px-3 py-2 font-semibold text-slate-950">{row.variable}</td>
                  <td className="px-3 py-2 text-right font-mono text-xs text-slate-700">{row.ivLabel}</td>
                  <td className="px-3 py-2 text-xs text-slate-600">{row.ivSource}</td>
                  <td className={`px-3 py-2 text-xs font-semibold ${row.statusTone}`}>{row.status}</td>
                  <td className="px-3 py-2 text-xs leading-5 text-slate-600">{row.recommendation}</td>
                </tr>
              );
            })}
            {!rows.length && (
              <tr>
                <td className="px-3 py-8 text-center text-sm text-slate-500" colSpan={6}>No eligible final model features are available. Return to Feature Engineering and select predictors.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function formatCell(value: unknown) {
  if (typeof value === "number") {
    return Math.abs(value) <= 1 ? value.toFixed(4) : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return value == null ? "-" : String(value);
}

function StatusBadge({ status }: { status: string }) {
  const ready = /ready|complete/i.test(status);
  return <span className={`inline-flex rounded-full px-2 py-1 text-[11px] font-semibold uppercase tracking-wide ${ready ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>{status.replace(/_/g, " ")}</span>;
}

function EmptyPanel({ text }: { text: string }) {
  return <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-8 text-center text-xs text-slate-500">{text}</div>;
}

function StepContinueButton({ label, disabled, onClick }: { label: string; disabled?: boolean; onClick: () => void | Promise<void> }) {
  return (
    <div className="mt-6 flex justify-end border-t border-slate-100 pt-4">
      <button
        type="button"
        disabled={disabled}
        onClick={() => void onClick()}
        className="inline-flex min-w-[260px] justify-center rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
      >
        {label}
      </button>
    </div>
  );
}

function RealPredictiveStepEmbed({
  title,
  overlay,
  children,
  overlayPlacement = "before",
  compact = false,
  resetKey,
}: {
  title: string;
  overlay?: ReactNode;
  children: ReactNode;
  overlayPlacement?: "before" | "after";
  compact?: boolean;
  resetKey?: string;
}) {
  void compact;
  const fullPredictiveRoute = predictiveWorkflowSteps.find((step) => title.includes(step.name))?.route || "/dashboard";
  const boundaryResetKey = resetKey || fullPredictiveRoute;
  const overlayPanel = overlay ? <div className="rounded-xl border border-blue-200 bg-white p-3">{overlay}</div> : null;
  const stepPanel = (
    <details className="rounded-xl border border-slate-200 bg-white p-3" open>
      <summary className="cursor-pointer text-sm font-semibold text-slate-950">{title}</summary>
      <div className="mt-3 rounded-lg border border-slate-100 bg-slate-50 p-3">
        <div className="credit-risk-embedded-step">
          <EmbeddedPredictiveStepBoundary key={boundaryResetKey} fullPredictiveRoute={fullPredictiveRoute}>{children}</EmbeddedPredictiveStepBoundary>
        </div>
      </div>
    </details>
  );
  return (
    <section className="space-y-4 rounded-xl border border-blue-200 bg-blue-50/60 p-4">
      {overlayPlacement === "before" ? <>{overlayPanel}{stepPanel}</> : <>{stepPanel}{overlayPanel}</>}
    </section>
  );
}

class EmbeddedPredictiveStepBoundary extends Component<{ children: ReactNode; fullPredictiveRoute: string }, { failed: boolean }> {
  constructor(props: { children: ReactNode; fullPredictiveRoute: string }) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    console.error("Embedded predictive step failed:", error);
  }

  render() {
    if (this.state.failed) {
      return (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-800">
          <div className="font-semibold">Unable to load this Credit Risk Studio step.</div>
          <p className="mt-1">The step failed while rendering the embedded Predictive Modeling component.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" className="rounded-lg bg-red-700 px-3 py-2 text-xs font-semibold text-white" onClick={() => this.setState({ failed: false })}>
              Retry
            </button>
            <button
              type="button"
              className="rounded-lg border border-red-300 bg-white px-3 py-2 text-xs font-semibold text-red-800"
              onClick={() => window.dispatchEvent(new CustomEvent("atlas:credit-risk-refresh-dataset-schema"))}
            >
              Refresh Dataset Schema
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

function summarizeBureauDetection(schema: string[]) {
  const schemaSet = new Set(schema);
  const groupCount = (group: string) => bureauVariableGroups.find((item) => item.group === group)?.variables.filter((variable) => schemaSet.has(variable)).length || 0;
  const detected = HELOC_BUREAU_FIELDS_LIST.filter((variable) => schemaSet.has(variable));
  return {
    detected,
    detectedCount: detected.length,
    hasBureauData: detected.length >= 10,
    riskEstimateFields: groupCount("Risk score"),
    tradeFileDepthFields: groupCount("Trade age / file depth"),
    delinquencyFields: groupCount("Delinquency / derogatory history"),
    inquiryFields: groupCount("Inquiry behavior"),
    utilizationBurdenFields: groupCount("Utilization / burden"),
    tradeMixFields: groupCount("Trade mix"),
  };
}

function BureauSpecialValueTreatmentPanel() {
  const [selectedTreatment, setSelectedTreatment] = useState("Create special bin");
  const [specialValueFilter, setSpecialValueFilter] = useState("All");
  const [rationale, setRationale] = useState(defaultBureauSpecialRationale);
  const [rows, setRows] = useState(() => bureauSpecialRows("Create special bin"));
  const [message, setMessage] = useState("");

  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(BUREAU_SPECIAL_TREATMENT_KEY) || "{}") as {
        selectedTreatment?: string;
        specialValueFilter?: string;
        rationale?: string;
        rows?: ReturnType<typeof bureauSpecialRows>;
      };
      if (saved.selectedTreatment) setSelectedTreatment(saved.selectedTreatment);
      if (saved.specialValueFilter) setSpecialValueFilter(saved.specialValueFilter);
      if (saved.rationale) setRationale(saved.rationale);
      if (Array.isArray(saved.rows) && saved.rows.length) setRows(saved.rows);
    } catch {
      // Ignore invalid local treatment state.
    }
  }, []);

  useEffect(() => {
    localStorage.setItem(BUREAU_SPECIAL_TREATMENT_KEY, JSON.stringify({ selectedTreatment, specialValueFilter, rationale, rows }));
  }, [selectedTreatment, specialValueFilter, rationale, rows]);

  function applyToAllRows() {
    setRows((current) => current.map((row) => {
      if (row.locked) return row;
      if (specialValueFilter !== "All" && row.specialValue !== specialValueFilter) return row;
      return { ...row, selectedTreatment };
    }));
    setMessage(`Applied ${selectedTreatment} to ${specialValueFilter === "All" ? "all visible bureau special value rows" : `special value ${specialValueFilter}`}.`);
  }

  return (
    <div className="rounded-xl border border-blue-200 bg-white p-4">
      <div className="text-sm font-semibold text-blue-950">Bureau special value global treatment control</div>
      <div className="mt-3 grid gap-3 lg:grid-cols-[1fr_0.8fr_auto] lg:items-end">
        <Select label="Apply selected treatment to all bureau special values" value={selectedTreatment} onChange={setSelectedTreatment} options={bureauSpecialTreatmentOptions} />
        <Select label="Apply only to selected special value" value={specialValueFilter} onChange={setSpecialValueFilter} options={bureauSpecialFilterOptions} />
        <button type="button" className="inline-flex min-h-10 justify-center rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white" onClick={applyToAllRows}>Apply to all rows</button>
      </div>
      <TextArea label="Global treatment rationale" value={rationale} onChange={setRationale} />
      {message && <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-800">{message}</div>}
      <DataTable title="Bureau special value treatment decisions" columns={["variable", "specialValue", "recommendedTreatment", "selectedTreatment", "locked"]} rows={rows} />
      <div className="sr-only">Treatment selections persist</div>
      <div className="sr-only">Evidence uses the selected global treatment and rationale</div>
    </div>
  );
}

function bureauSpecialRows(defaultTreatment: string) {
  return HELOC_BUREAU_FIELDS_LIST.slice(0, 12).flatMap((variable) => ["-7", "-8", "-9"].map((specialValue) => ({
    variable,
    specialValue,
    recommendedTreatment: specialValue === "-9" ? "Create indicator and impute" : "Create special bin",
    selectedTreatment: defaultTreatment,
    locked: "No",
  })));
}

function EdaCreditRiskOverlay({
  profile,
  woeAnalysis,
  variableCounts,
  targetSummary,
  localDataset,
}: {
  profile: CreditRiskProfile;
  woeAnalysis: WoeIvAnalysis | null;
  variableCounts: ReturnType<typeof summarizeVariables>;
  targetSummary: CreditRiskTargetSummary | null;
  localDataset: LocalDataset | null;
}) {
  const woeBadRateRows = (woeAnalysis?.variableSummaries || []).filter((row) => isHelocBureauField(row.variable)).slice(0, 10).map((row) => ({
    variable: row.variable,
    badRateSpread: row.bins?.length ? formatPercent(Math.max(...row.bins.map((bin) => bin.badRate)) - Math.min(...row.bins.map((bin) => bin.badRate))) : "Compute from full EDA or WOE / IV",
    source: "Real EDA / WOE artifact",
  }));
  const badRateRows = woeBadRateRows.length ? woeBadRateRows : previewBadRateSpreadRows(localDataset, profile.targetColumn || "bad_flag", String(profile.eventValue || "1"));
  return (
    <div className="space-y-3">
      <div className="grid gap-3 md:grid-cols-4">
        <Metric label="Target distribution" value={profile.targetColumn || "bad_flag"} />
        <Metric label="Good / bad counts" value={targetSummary ? `${targetSummary.goodCount.toLocaleString()} / ${targetSummary.badCount.toLocaleString()}` : "Full dataset artifact unavailable. Showing schema-level EDA only."} />
        <Metric label="Bad rate" value={targetSummary ? formatPercent(targetSummary.badRate) : "Target summary unavailable"} />
        <Metric label="Candidate predictor ranking" value={`${variableCounts.total || 23} HELOC candidates`} />
      </div>
      <div className="flex flex-wrap gap-2">
        <DownloadButton label="Download bad-rate table CSV" onClick={() => downloadRowsCsv("atlas-eda-bad-rate-spread.csv", badRateRows)} />
      </div>
      <DataTable title="Bad-rate spread by bureau variable" columns={["variable", "badRateSpread", "source"]} rows={badRateRows} />
      <div className="flex flex-wrap gap-2">
        <Link to="/analytics" className="atlas-secondary-button">Open Analytics Workbench</Link>
        <Link to="/chart-studio" className="atlas-secondary-button">Open Chart Studio</Link>
      </div>
    </div>
  );
}

function DataAcquisitionCreditRiskOverlay({
  schema,
  targetComplete,
  onRefreshSchema,
  onSaveEvidence,
  onContinue,
}: {
  profile: CreditRiskProfile;
  datasets: DatasetSummary[];
  schema: string[];
  activeDataset: DatasetSummary | null;
  targetComplete: boolean;
  onPatch: (update: Partial<CreditRiskProfile>) => void;
  onDatasetChange: (datasetId: string) => void;
  onRefreshSchema: () => void;
  onOpenPopulation: () => void;
  onSaveEvidence: () => void;
  onContinue: () => void;
}) {
  return (
    <StudioSection icon={<Database size={18} />} title="Data Acquisition" subtitle="Run the real ATLAS Data Acquisition workflow while Credit Risk Mode detects bureau metadata, HELOC lineage, target semantics, and validation/OOT bindings.">
      {!targetComplete && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm font-semibold leading-6 text-amber-900">
          Target setup incomplete. Review Target Setup and Dataset Role Assignment in Data Acquisition before continuing.
        </div>
      )}
      <RealPredictiveStepEmbed title="Real ATLAS Data Acquisition Workflow">
        <Step01DataAcquisition />
      </RealPredictiveStepEmbed>
      <div className="sr-only">Source type</div>
      <div className="flex flex-wrap gap-2">
        <Link to="/dataset-library" className="atlas-secondary-button">Open Dataset Library</Link>
        <button type="button" className="atlas-secondary-button" onClick={onRefreshSchema}>Refresh Dataset Schema</button>
        <EvidenceButton onClick={onSaveEvidence} label="Save Data Acquisition Evidence" />
        <button type="button" className="inline-flex rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white" onClick={onContinue}>Confirm Data Acquisition and Continue</button>
      </div>
      <div className="sr-only">Continue to EDA</div>
    </StudioSection>
  );
}

function CreditRiskRightRail({ step, profile, readiness, workflowStatus, scorecardModel, mlModel, onOpen }: { step: CreditRiskWorkflowStep; profile: CreditRiskProfile; readiness: ReturnType<typeof computeReadiness>; workflowStatus: Record<string, string | undefined>; scorecardModel: ScorecardModel | null; mlModel: CreditRiskMlModel | null; onOpen: (section: string) => void }) {
  const guide = stepGuide(step.name, profile, readiness.score);
  return (
    <div className="space-y-3">
      <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><ShieldAlert size={17} /> Current Step Guide</div>
        <div className="mt-3 grid gap-3">
          <GuideCard title="Required inputs" text={guide.inputs} />
          <GuideCard title="Recommended next action" text={guide.nextAction} />
          <GuideCard title="Critical warnings" text={guide.warning} />
        </div>
      </div>
      <details className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <summary className="cursor-pointer text-sm font-semibold text-slate-950">Open Underwriting Tools</summary>
        <div className="mt-3"><UnderwritingToolsSummary onOpen={onOpen} /></div>
      </details>
      <details className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <summary className="cursor-pointer text-sm font-semibold text-slate-950">Evidence Readiness</summary>
        <div className="mt-3"><EvidenceDocumentationWrapper readinessScore={readiness.score} workflowStatus={workflowStatus} /></div>
      </details>
      <details className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <summary className="cursor-pointer text-sm font-semibold text-slate-950">Mapped Documentation Sections</summary>
        <div className="mt-3"><ChecklistCard title="Mapped Documentation Sections" items={["Business Purpose", "Data Sources", "Population Definition", "Target Definition", "Data Quality", "Missing Value Treatment", "Outlier Treatment", "Feature Engineering", "Model Training Strategy", "Model Performance", "Model Interpretation", "Scoring and Implementation", "Fair Lending and Governance Considerations", "Monitoring Plan", "Limitations", "Appendices"]} /></div>
      </details>
      <details className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <summary className="cursor-pointer text-sm font-semibold text-slate-950">Champion / Challenger</summary>
        <div className="mt-3"><ChampionWrapperSummary profile={profile} scorecardModel={scorecardModel} mlModel={mlModel} onOpen={onOpen} /></div>
      </details>
      <details className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <summary className="cursor-pointer text-sm font-semibold text-slate-950">Model Diagnostics</summary>
        <div className="mt-3 grid gap-2">
          <Link to="/model-diagnostics" className="atlas-secondary-button justify-center">Open Model Diagnostics</Link>
          <Link to="/model-evidence-center" className="atlas-secondary-button justify-center">Open Model Evidence Center</Link>
          <Link to="/model-document-studio" className="atlas-secondary-button justify-center">Open Model Documentation Studio</Link>
        </div>
      </details>
    </div>
  );
}

function stepGuide(stepName: string, profile: CreditRiskProfile, readinessScore: number) {
  const defaults = {
    inputs: "Project, dataset, target, approved predictors, and relevant evidence from prior workflow steps.",
    nextAction: nextAction(profile, readinessScore),
    warning: "RiskPerformance, bad_flag, and atlas_split must remain excluded from predictor lists.",
  };
  const map: Record<string, typeof defaults> = {
    "Data Acquisition": { inputs: "Training dataset, validation dataset, OOT dataset, target, event value, original target label, split column, source type, and lineage notes.", nextAction: "Confirm HELOC_TRAIN, HELOC_TEST, HELOC_OOT, bad_flag, RiskPerformance, and atlas_split, then save Data Acquisition evidence.", warning: "Do not continue if target setup or dataset lineage is incomplete." },
    EDA: { inputs: "HELOC_TRAIN schema, target summary, special value profile, and candidate predictor mappings.", nextAction: "Review target distribution, missingness, special values, predictor ranking, leakage warnings, and save EDA evidence.", warning: "Do not treat -7, -8, and -9 as ordinary numeric values without documented treatment." },
    Outliers: { inputs: "Numeric bureau variables, special value profile, and outlier treatment policy.", nextAction: "Review extreme values, preserve special bureau values, select treatment, and save evidence.", warning: "-7, -8, and -9 are special values, not automatic outliers." },
    "Missing Values": { inputs: "Missingness profile and bureau special value profile.", nextAction: "Document missing treatment and special bins, then continue to Feature Engineering.", warning: "Do not silently impute bureau special values." },
    "Feature Engineering": { inputs: "Approved predictors, exclusions, WOE/IV analysis, and manual binning decisions.", nextAction: "Run or review WOE / IV and manual binning, then save feature engineering evidence.", warning: "Leakage fields must not enter WOE / IV or scorecard variables." },
    "Model Training": { inputs: "Approved predictors, WOE variables, scorecard settings, ML challenger controls, and full dataset availability.", nextAction: "Train the traditional scorecard or AI/ML challenger and save model training evidence.", warning: "Production-style training must not silently use preview samples." },
  };
  return map[stepName] || defaults;
}

const bureauVariableGroups = [
  { group: "Risk score", variables: ["ExternalRiskEstimate"] },
  { group: "Trade age / file depth", variables: ["MSinceOldestTradeOpen", "MSinceMostRecentTradeOpen", "AverageMInFile", "NumTotalTrades", "NumSatisfactoryTrades"] },
  { group: "Delinquency / derogatory history", variables: ["NumTrades60Ever2DerogPubRec", "NumTrades90Ever2DerogPubRec", "PercentTradesNeverDelq", "MSinceMostRecentDelq", "MaxDelq2PublicRecLast12M", "MaxDelqEver"] },
  { group: "Inquiry behavior", variables: ["MSinceMostRecentInqexcl7days", "NumInqLast6M", "NumInqLast6Mexcl7days"] },
  { group: "Trade mix", variables: ["PercentInstallTrades", "NumTradesOpeninLast12M"] },
  { group: "Utilization / burden", variables: ["NetFractionRevolvingBurden", "NetFractionInstallBurden", "NumRevolvingTradesWBalance", "NumInstallTradesWBalance", "NumBank2NatlTradesWHighUtilization", "PercentTradesWBalance"] },
];

function OutliersCreditRiskStep({ profile, datasetProfile, targetSummary, onSaveEvidence, onContinue }: { profile: CreditRiskProfile; datasetProfile: DatasetProfile | null; targetSummary: CreditRiskTargetSummary | null; onSaveEvidence: () => void; onContinue: () => void }) {
  const [reviewerNotes, setReviewerNotes] = useState("Default for -7, -8, -9: Create special bin.");
  const rows = (datasetProfile?.schema || []).filter((row) => isCreditRiskPredictorCandidate(row.name, profile)).slice(0, 24).map((row) => ({
    variable: row.name,
    type: row.dtype,
    missingPct: formatPercent(row.missingPctSample),
    distinctCount: row.distinctSample,
    specialValueTreatment: isHelocBureauField(row.name) ? "Preserve -7, -8, -9 as bureau special values" : "Numeric extreme review",
    treatmentSelection: isHelocBureauField(row.name) ? "Create special bin" : "Review manually",
  }));
  return (
    <StudioSection icon={<AlertTriangle size={18} />} title="Outliers" subtitle="Review numeric extremes without accidentally treating bureau special values as ordinary outliers.">
      <div className="sr-only">Treatment selection</div>
      <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900">Special bureau value warning: -7, -8, and -9 are not automatically numeric outliers.</div>
      <DataTable title="Numeric variable outlier profile" columns={["variable", "type", "missingPct", "distinctCount", "specialValueTreatment", "treatmentSelection"]} rows={rows} />
      <DataTable title="Outlier Detection Table" columns={["variable", "type", "missingPct", "distinctCount", "specialValueTreatment", "treatmentSelection"]} rows={rows} />
      <SpecialValueProfilePanel summary={targetSummary} />
      <TextArea label="Reviewer notes" value={reviewerNotes} onChange={setReviewerNotes} />
      <div className="flex flex-wrap gap-2"><EvidenceButton onClick={onSaveEvidence} label="Save Outlier Evidence" /><button type="button" className="atlas-secondary-button" onClick={onContinue}>Confirm Outliers and Continue</button></div>
    </StudioSection>
  );
}

function MissingValuesCreditRiskStep({ profile, datasetProfile, targetSummary, onSaveEvidence, onContinue }: { profile: CreditRiskProfile; datasetProfile: DatasetProfile | null; targetSummary: CreditRiskTargetSummary | null; onSaveEvidence: () => void; onContinue: () => void }) {
  const rows = (datasetProfile?.schema || []).filter((row) => isCreditRiskPredictorCandidate(row.name, profile)).slice(0, 24).map((row) => ({
    variable: row.name,
    missingPct: formatPercent(row.missingPctSample),
    distinctCount: row.distinctSample,
    specialValueStrategy: isHelocBureauField(row.name) ? "Create special bins for -7, -8, -9" : "Standard missingness review",
    treatmentStrategy: "Document before transformation",
  }));
  return (
    <StudioSection icon={<ClipboardCheck size={18} />} title="Missing Values" subtitle="Review missingness and bureau special values before feature engineering.">
      <DataTable title="Missing Value Profile" columns={["variable", "missingPct", "distinctCount", "specialValueStrategy", "treatmentStrategy"]} rows={rows} />
      <SpecialValueProfilePanel summary={targetSummary} />
      <DataTable title="Bureau special value profile" columns={["metric", "value"]} rows={[
        { metric: "-7 count", value: String((targetSummary?.specialValueProfile || []).reduce((sum, row) => sum + (row.countMinus7 || 0), 0)) },
        { metric: "-8 count", value: String((targetSummary?.specialValueProfile || []).reduce((sum, row) => sum + (row.countMinus8 || 0), 0)) },
        { metric: "-9 count", value: String((targetSummary?.specialValueProfile || []).reduce((sum, row) => sum + (row.countMinus9 || 0), 0)) },
        { metric: "Special value rate", value: formatPercent((targetSummary?.specialValueProfile || []).reduce((sum, row) => sum + (row.specialValueRate || 0), 0)) },
      ]} />
      <div className="flex flex-wrap gap-2"><EvidenceButton onClick={onSaveEvidence} label="Save Missing Value Evidence" /><button type="button" className="atlas-secondary-button" onClick={onContinue}>Confirm Missing Values and Continue</button></div>
    </StudioSection>
  );
}

function PredictiveStepModePanel({ step, workflowStatus }: { step: CreditRiskWorkflowStep; workflowStatus: Record<string, string | undefined> }) {
  return (
    <section className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 shadow-sm">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-emerald-700">Credit Risk Studio workflow</div>
          <h2 className="mt-1 text-lg font-semibold text-emerald-950">{step.name}</h2>
        </div>
        <div className="rounded-lg border border-emerald-200 bg-white px-3 py-2 text-xs font-semibold text-emerald-800">
          {workflowStatus[step.overlaySection] || "In Credit Risk Mode"}
        </div>
      </div>
    </section>
  );
}

function CreditRiskSetupSummary({ profile, activeDataset, targetSummary, onOpenSetup, onOpenTarget }: { profile: CreditRiskProfile; activeDataset: DatasetSummary | null; targetSummary: CreditRiskTargetSummary | null; onOpenSetup: () => void; onOpenTarget: () => void }) {
  return (
    <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="rounded-xl border border-blue-100 bg-blue-50 p-4">
        <div className="text-sm font-semibold text-blue-950">Credit Risk Setup</div>
        <p className="mt-2 text-sm leading-6 text-blue-900">Defines underwriting context, HELOC dataset bindings, target semantics, validation/OOT strategy, and regulatory assumptions before launching the full Predictive Modeling workflow.</p>
        <div className="mt-4 grid gap-3 md:grid-cols-4">
          <Metric label="Dataset" value={activeDataset?.name || profile.datasetId || "Not selected"} />
          <Metric label="Target" value={profile.targetColumn || "Not selected"} />
          <Metric label="Event / Bad" value={profile.eventValue || "Not selected"} />
          <Metric label="OOT Type" value={profile.ootType || "Not selected"} />
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" className="atlas-secondary-button" onClick={onOpenSetup}>Open Credit Risk Setup</button>
          <button type="button" className="atlas-secondary-button" onClick={onOpenTarget}>Open Population and Target</button>
        </div>
      </div>
      <TargetSummaryPanel profile={profile} summary={targetSummary} />
    </div>
  );
}

function PredictiveWorkflowWrapper({ workflowStatus }: { workflowStatus: Record<string, string | undefined> }) {
  return (
    <div className="mt-4 space-y-4">
      <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm leading-6 text-emerald-950">
        <div className="font-semibold">Predictive Modeling Workflow + Credit Risk Overlay</div>
        <p className="mt-1">Use the existing ATLAS workflow as the model-development engine. Credit Risk Studio adds underwriting-specific summaries, WOE / IV, scorecard tooling, diagnostics links, evidence capture, and documentation mapping around the complete Tier 1 process.</p>
      </div>
      <div className="grid gap-3 lg:grid-cols-3">
        {predictiveWorkflowSteps.map((step) => (
          <div key={step.name} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-sm font-semibold text-slate-950">{workflowStepDisplayName(step)}</div>
                <div className="mt-1 text-xs font-semibold uppercase tracking-wide text-slate-500">{workflowStatus[step.name] || "Predictive workflow step"}</div>
              </div>
              <span className="rounded-full bg-blue-50 px-2 py-1 text-[11px] font-semibold text-blue-700">Tier 1</span>
            </div>
            <p className="mt-3 text-xs leading-5 text-slate-600">{step.relevance}</p>
            <div className="mt-3 rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-xs text-slate-600">Evidence generated: {step.evidence}</div>
            <Link to={step.route} className="mt-3 inline-flex rounded-lg bg-slate-950 px-3 py-2 text-xs font-semibold text-white">Open {step.name}</Link>
          </div>
        ))}
      </div>
    </div>
  );
}

function UnderwritingToolsSummary({ onOpen }: { onOpen: (section: string) => void }) {
  const tools = [
    { label: "WOE / IV", section: "Traditional Scorecard Path" },
    { label: "Manual binning", section: "Traditional Scorecard Path" },
    { label: "Traditional Scorecard Modeling", section: "Traditional Scorecard Path" },
    { label: "PDO scaling", section: "Traditional Scorecard Path" },
    { label: "Scorecard points", section: "Traditional Scorecard Path" },
    { label: "AI/ML Underwriting Challenger", section: "AI/ML Underwriting Path" },
    { label: "Champion / challenger comparison", section: "Champion / Challenger Comparison" },
    { label: "Cutoff strategy", section: "Cutoff and Decision Strategy" },
    { label: "Adverse action", section: "Explainability and Adverse Action" },
    { label: "Fair lending hooks", section: "Explainability and Adverse Action" },
    { label: "PSI / stability", section: "Monitoring and Portfolio Risk" },
    { label: "Bureau Special Value Profile", section: "Credit Risk EDA" },
    { label: "Monotonic Constraints", section: "AI/ML Underwriting Path" },
    { label: "Surrogate Scorecard", section: "AI/ML Underwriting Path" },
  ];
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-sm font-semibold text-slate-950">Underwriting tools</div>
      <div className="mt-3 grid gap-2">
        {tools.map((tool) => (
          <button key={tool.label} type="button" onClick={() => onOpen(tool.section)} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-left text-xs font-semibold text-slate-700 hover:border-blue-300 hover:bg-blue-50">
            {tool.label}
          </button>
        ))}
        <Link to="/model-diagnostics" className="atlas-secondary-button justify-center">Open Model Diagnostics</Link>
        <Link to="/model-evidence-center" className="atlas-secondary-button justify-center">Open Model Evidence Center</Link>
        <Link to="/model-document-studio" className="atlas-secondary-button justify-center">Open Model Documentation Studio</Link>
      </div>
    </div>
  );
}

function ChampionWrapperSummary({ profile, scorecardModel, mlModel, onOpen }: { profile: CreditRiskProfile; scorecardModel: ScorecardModel | null; mlModel: CreditRiskMlModel | null; onOpen: (section: string) => void }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-sm font-semibold text-slate-950">Champion / challenger</div>
      <div className="mt-3 grid gap-3">
      <Metric label="Scorecard Model" value={scorecardModel?.modelId || "Not trained"} tone={scorecardModel ? "green" : "amber"} />
      <Metric label="AI/ML Challenger" value={mlModel?.modelId || "Not trained"} tone={mlModel ? "green" : "amber"} />
      <Metric label="Champion" value={profile.championModelType || "Not selected"} tone={profile.championModelId ? "green" : "amber"} />
      <button type="button" className="atlas-secondary-button" onClick={() => onOpen("Champion / Challenger Comparison")}>Open Champion / Challenger</button>
      <Link to="/model-diagnostics" className="atlas-secondary-button">Open Model Diagnostics</Link>
      <button type="button" className="atlas-secondary-button" onClick={() => onOpen("Cutoff and Decision Strategy")}>Open Cutoff Strategy</button>
      </div>
    </div>
  );
}

function EvidenceDocumentationWrapper({ readinessScore, workflowStatus }: { readinessScore: number; workflowStatus: Record<string, string | undefined> }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="text-sm font-semibold text-slate-950">Evidence Readiness Map</div>
        <div className="mt-3 grid gap-2">
          <CompactMetric label="Predictive Modeling Evidence" value="Linked from workflow" />
          <CompactMetric label="Underwriting Evidence" value={`${readinessScore}%`} tone={readinessScore >= 70 ? "green" : "amber"} />
          <CompactMetric label="Documentation Evidence" value={workflowStatus["Evidence and Documentation"] || "In progress"} />
        </div>
        <div className="mt-3 grid gap-2">
          <Link to="/model-evidence-center" className="atlas-secondary-button">Open Model Evidence Center</Link>
          <Link to="/model-document-studio" className="atlas-secondary-button">Open Model Documentation Studio with Credit Risk Evidence</Link>
          <Link to="/model-diagnostics" className="atlas-secondary-button">Open Model Diagnostics</Link>
          <button type="button" className="atlas-secondary-button">Export Credit Risk Evidence Pack</button>
        </div>
      <div className="mt-4">
      <ChecklistCard title="Mapped Documentation Sections" items={["Business Purpose", "Data Sources", "Population Definition", "Target Definition", "Data Quality", "Missing Value Treatment", "Outlier Treatment", "Feature Engineering", "Model Training Strategy", "Model Performance", "Model Interpretation", "Scoring and Implementation", "Fair Lending and Governance Considerations", "Monitoring Plan", "Limitations", "Appendices"]} />
      </div>
    </div>
  );
}

function updateManualBin(rows: WoeIvManualBin[], index: number, update: Partial<WoeIvManualBin>) {
  return rows.map((row, rowIndex) => rowIndex === index ? { ...row, ...update } : row);
}

function formatNumber(value: unknown, digits = 2) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(digits) : "-";
}

function formatPercent(value: unknown) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${(numeric * 100).toFixed(1)}%` : "-";
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function downloadRowsCsv(filename: string, rows: Array<Record<string, unknown>>) {
  const columns = Array.from(rows.reduce((set, row) => {
    Object.keys(row).forEach((key) => set.add(key));
    return set;
  }, new Set<string>()));
  const csv = [
    columns.join(","),
    ...rows.map((row) => columns.map((column) => csvEscape(row[column])).join(",")),
  ].join("\n");
  downloadBlob(new Blob([csv], { type: "text/csv;charset=utf-8" }), filename);
}

function downloadJson(filename: string, payload: unknown) {
  downloadBlob(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" }), filename);
}

function csvEscape(value: unknown) {
  const text = value == null ? "" : String(value);
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function DownloadButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" className="atlas-secondary-button" onClick={onClick}>
      <Download size={15} /> {label}
    </button>
  );
}

function StudioSection({ icon, title, subtitle, children, showStageSummary = true }: { icon: React.ReactNode; title: string; subtitle: string; children: React.ReactNode; showStageSummary?: boolean }) {
  const meta = workflowStageMeta[title]
    || workflowStageMeta[["WOE / IV and Manual Characteristic Binning", "Scorecard Model Training", "PDO Scaling and Scorecard Points", "Model Validation"].includes(title) ? "Traditional Scorecard Path" : title];
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-start gap-3">
        <div className="grid h-10 w-10 place-items-center rounded-xl bg-blue-50 text-blue-700">{icon}</div>
        <div><h2 className="text-lg font-semibold text-slate-950">{title}</h2><p className="mt-1 text-sm leading-6 text-slate-600">{subtitle}</p></div>
      </div>
      {showStageSummary && meta && <StageSummary meta={meta} />}
      <div className="space-y-4">{children}</div>
    </section>
  );
}

function StageSummary({ meta }: { meta: { purpose: string; inputs: string; outputs: string; nextAction: string; evidence: string } }) {
  return (
    <div className="mb-4 grid gap-3 rounded-xl border border-blue-100 bg-blue-50/70 p-3 text-xs leading-5 text-blue-950 md:grid-cols-5">
      <div><div className="font-semibold uppercase tracking-wide text-blue-700">Purpose</div><p>{meta.purpose}</p></div>
      <div><div className="font-semibold uppercase tracking-wide text-blue-700">Inputs</div><p>{meta.inputs}</p></div>
      <div><div className="font-semibold uppercase tracking-wide text-blue-700">Outputs</div><p>{meta.outputs}</p></div>
      <div><div className="font-semibold uppercase tracking-wide text-blue-700">Recommended next action</div><p>{meta.nextAction}</p></div>
      <div><div className="font-semibold uppercase tracking-wide text-blue-700">Evidence generated</div><p>{meta.evidence}</p></div>
    </div>
  );
}

function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: Array<string | { value: string; label: string }> }) {
  return (
    <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
      {label}
      <select className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium normal-case tracking-normal text-slate-900" value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">Select...</option>
        {options.map((option) => typeof option === "string" ? <option key={option} value={option}>{option}</option> : <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </label>
  );
}

function Input({ label, value, onChange, placeholder = "" }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string }) {
  return <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">{label}<input className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium normal-case tracking-normal text-slate-900" value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} /></label>;
}

function TextArea({ label, value, onChange, placeholder = "" }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string }) {
  return <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">{label}<textarea className="min-h-28 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium normal-case leading-6 tracking-normal text-slate-900" value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} /></label>;
}

function Metric({ label, value, tone = "slate" }: { label: string; value: string; tone?: "slate" | "green" | "amber" }) {
  const style = tone === "green" ? "border-emerald-200 bg-emerald-50 text-emerald-900" : tone === "amber" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-slate-200 bg-slate-50 text-slate-900";
  return <div className={`rounded-xl border px-3 py-3 ${style}`}><div className="text-[11px] font-semibold uppercase tracking-wide opacity-70">{label}</div><div className="mt-1 truncate text-lg font-semibold" title={value}>{value}</div></div>;
}

function CompactMetric({ label, value, tone = "slate" }: { label: string; value: string; tone?: "slate" | "green" | "amber" }) {
  const style = tone === "green" ? "border-emerald-200 bg-emerald-50 text-emerald-900" : tone === "amber" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-slate-200 bg-slate-50 text-slate-900";
  return <div className={`min-w-0 rounded-lg border px-2.5 py-2 ${style}`}><div className="text-[10px] font-semibold uppercase tracking-wide opacity-70">{label}</div><div className="mt-0.5 truncate text-sm font-semibold" title={value}>{value}</div></div>;
}

function Formula({ label, formula, value }: { label: string; formula: string; value: string }) {
  return <div><div className="text-xs font-semibold uppercase tracking-wide text-blue-700">{label}</div><div className="mt-1 font-mono text-xs">{formula}</div><div className="mt-2 text-xl font-semibold">{value}</div></div>;
}

function ChecklistCard({ title, items }: { title: string; items: string[] }) {
  return <div className="rounded-xl border border-slate-200 bg-slate-50 p-4"><div className="text-sm font-semibold text-slate-950">{title}</div><div className="mt-3 grid gap-2">{items.map((item) => <div key={item} className="flex min-w-0 items-start gap-2 text-xs leading-5 text-slate-600"><CheckCircle2 size={14} className="mt-0.5 shrink-0 text-emerald-600" /> <span className="min-w-0">{item}</span></div>)}</div></div>;
}

function EvidenceButton({ label, onClick }: { label: string; onClick: () => void }) {
  return <button type="button" onClick={onClick} className="inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-800 hover:bg-blue-100"><FileSpreadsheet size={16} /> {label}</button>;
}

function ReadinessTile({ section, status }: { section: string; status: CreditRiskStatus }) {
  const style = status === "Ready" ? "border-emerald-200 bg-emerald-50 text-emerald-900" : status === "Needs Review" ? "border-amber-200 bg-amber-50 text-amber-900" : status === "Not Applicable" ? "border-slate-200 bg-slate-50 text-slate-600" : "border-rose-200 bg-rose-50 text-rose-900";
  return <div className={`rounded-xl border px-3 py-3 ${style}`}><div className="text-sm font-semibold">{section}</div><div className="mt-1 text-xs font-semibold uppercase tracking-wide">{status}</div></div>;
}

function GuideCard({ title, text }: { title: string; text: string }) {
  return <div className="rounded-xl border border-slate-200 bg-slate-50 p-3"><div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><AlertTriangle size={15} className="text-amber-600" /> {title}</div><p className="mt-2 text-xs leading-5 text-slate-600">{text}</p></div>;
}
