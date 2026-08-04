import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

const [
  predictorDistributionExplorer,
  correlationExplorer,
  vifExplorer,
  findingsDecisionWorkspace,
] = await Promise.all([
  read("src/components/eda/visual/PredictorDistributionExplorer.tsx"),
  read("src/components/eda/visual/CorrelationExplorer.tsx"),
  read("src/components/eda/visual/VifExplorer.tsx"),
  read("src/components/eda/FindingsDecisionWorkspace.tsx"),
]);

const [
  acquisition,
  enterprise,
  codePanel,
  languageTabs,
  eda,
  split,
  training,
  metadataRouter,
  qualityService,
  featureService,
  jobService,
  outliers,
  missingValues,
  outlierRouter,
  missingRouter,
  modelingApp,
  workflows,
  featureEngineering,
  workflowStore,
  evaluation,
  interpretation,
  trainer,
  evaluationService,
  scoring,
  edaWorkspaceTypes,
] = await Promise.all([
  read("src/steps/Step01_DataAcquisition.tsx"),
  read("src/lib/enterpriseDataAccess.ts"),
  read("src/components/StepPythonPanel.tsx"),
  read("src/components/code/CodeLanguageTabs.tsx"),
  read("src/steps/Step02_EDA.tsx"),
  read("src/steps/Step06_BalancingSplit.tsx"),
  read("src/steps/Step06_Train.tsx"),
  read("server/core/metadata_router.py"),
  read("server/preprocessing/quality_profile_service.py"),
  read("server/preprocessing/feature_profile_service.py"),
  read("server/training/training_job_service.py"),
  read("src/steps/Step04_Outliers.tsx"),
  read("src/steps/Step04_MissingValues.tsx"),
  read("server/preprocessing/outlier_router.py"),
  read("server/preprocessing/missing_router.py"),
  read("src/apps/ModelingApp.tsx"),
  read("src/config/workflows.ts"),
  read("src/steps/Step05_EncodingScaling.tsx"),
  read("src/state/useWorkflowStore.ts"),
  read("src/steps/Step08_Evaluation.tsx"),
  read("src/steps/Step09_Interpretation.tsx"),
  read("server/training/trainer.py"),
  read("server/evaluation/eval_service.py"),
  read("src/steps/Step10_Scoring.tsx"),
  read("server/eda/workspace_types.py"),
]);

assert.match(acquisition, /fullSourceRows/);
assert.match(acquisition, /previewSamplingMethod/);
assert.match(acquisition, /previewRowLimit/);
assert.match(acquisition, /profileRowLimit/);
assert.match(acquisition, /Preview & Profiling Settings/);
assert.match(acquisition, /Preview and profiling settings do not change the registered modeling dataset/);
assert.doesNotMatch(acquisition, /HELOC_DATA_ACQUISITION_SUMMARY|RiskPerformance|HELOC_TRAIN|bad_flag/);
assert.match(acquisition, /Full-population structural review/);
assert.match(acquisition, />Data Quality</);
assert.match(acquisition, /Full Dataset|Complete Browser Dataset|Preview Profile/);
assert.doesNotMatch(acquisition, /Full Data Quality Report|Python Synchronization|Sampling and Profiling Controls/);
assert.match(enterprise, /typeof value === "number"/);
assert.match(enterprise, /date\|datetime\|timestamp/);

assert.match(codePanel, /Data Access & Reproducibility Code/);
assert.match(codePanel, /Code & Reproducibility/);
assert.match(codePanel, /language: "python"/);
assert.match(codePanel, /language: "sas"/);
assert.match(codePanel, /runUserSasCompatible/);
assert.match(codePanel, /runUserSas/);
assert.match(codePanel, /fetchDataAcquisitionReproducibilityContext/);
assert.match(codePanel, /buildDataAcquisitionPythonContext/);
assert.match(codePanel, /language: "metadata"/);
assert.match(codePanel, /SELECTED_FEATURES/);
assert.match(codePanel, /dataset_library/);
assert.match(languageTabs, /languages\.map/);
assert.doesNotMatch(languageTabs, /Object\.keys\(LABELS\).*map/s);

assert.match(eda, /<StepShell/);
assert.match(eda, /getNextStepPath\("step02"\)/);
assert.match(eda, /onNext=\{completeEDA\}/);
assert.doesNotMatch(eda, /markCompleteAndNext\("step02"\)/);
assert.doesNotMatch(eda, /import StepPythonPanel/);
assert.match(eda, /completionBlockers[\s\S]*id: "overview"[\s\S]*"Load the governed EDA overview\."/);
assert.match(eda, /const nextDisabledReason = nextDisabled[\s\S]*completionSummary\.text/);
assert.match(eda, /nextDisabledReason=\{nextDisabledReason\}/);
assert.match(
  eda,
  /const nextDisabled =[\s\S]{0,700}!overview[\s\S]*confirmationPending[\s\S]*!reviewerConclusionComplete[\s\S]*!reviewerCommentaryComplete[\s\S]*!overallStatusEligible[\s\S]*!duplicateDecisionComplete;/,
  "EDA navigation must preserve overview/loading gates and require governed reviewer, status, and duplicate decisions."
);
assert.match(eda, /EDAUnavailablePanel/);
assert.match(eda, /Return to Data Acquisition/);
assert.match(eda, /EDA service route is unavailable/);
assert.match(eda, /safeArray/);
assert.match(eda, /safeObject/);
assert.match(eda, /ClassDistributionChart/);
assert.match(eda, /HistogramChart/);
assert.match(eda, /atlas-tab-button-active/);
assert.match(eda, /chartBins/);
assert.match(eda, /histogram_bins/);
assert.match(eda, /histogramBins/);
assert.match(eda, /loadLocalDataset/);
assert.match(eda, /target: overview\?\.target \|\| confirmedDataset\?\.target \|\| undefined/);
assert.match(eda, /selected_features: confirmedDataset\?\.selected_columns \?\? \[\]/);
assert.match(eda, /requestSequence/);
assert.doesNotMatch(eda, /Showing a quantile-based distribution view/);
assert.match(eda, /<PredictorDistributionExplorer/);
assert.doesNotMatch(eda, /eda\/histogram\/\$\{/);
assert.match(predictorDistributionExplorer, /eda\/workspace\/distribution/);
assert.match(predictorDistributionExplorer, /method: "POST"/);
assert.match(predictorDistributionExplorer, /Predictor Distribution Explorer/);
assert.match(predictorDistributionExplorer, /Linked quantile view/);
assert.match(predictorDistributionExplorer, /Mean \$\{formatNumber\(displayData\?\.markers\.mean/);
assert.match(predictorDistributionExplorer, /Median \$\{formatNumber\(displayData\?\.markers\.median/);
assert.match(eda, /dataTableDescriptions/);
assert.match(eda, /safeRows\.length === 1 \? "record" : "records"/);
assert.match(eda, /sticky left-0/);
assert.match(eda, /scaleByKey/);
assert.match(eda, /PairwiseMatrix/);
assert.match(eda, /Pairwise Plot Builder/);
assert.match(eda, /Generate pairwise plot/);
assert.match(eda, /Target association ranking/);
assert.match(eda, /<CorrelationExplorer/);
assert.match(eda, /<VifExplorer/);
assert.doesNotMatch(eda, /<CorrelationGrid/);
assert.doesNotMatch(eda, /<VifBarChart/);
assert.match(correlationExplorer, /Correlation explorer/);
assert.match(vifExplorer, /review thresholds, not automatic removal/);
assert.match(eda, /No governed time or segment field has been selected/);
assert.match(eda, /No governed time or segment fields were detected/);
assert.match(findingsDecisionWorkspace, /Duplicate Row Decision/);
assert.match(findingsDecisionWorkspace, /Exclude duplicate rows before downstream modeling/);
assert.match(eda, /Full Governed Population[\s\S]*Development Population/);

assert.match(split, /Final Predictor Review/);
assert.match(split, /fetchFullFeatureProfile/);
assert.match(split, /selected_features: selected/);
assert.match(split, /Select at least one eligible predictor before model training/);
assert.match(split, /Restore manifest selection/);
assert.match(split, /threshold were deselected/);
assert.match(split, /Included in training contract/);
assert.match(split, /Signal evidence/);
assert.match(split, /Training readiness/);
assert.match(split, /balancing_split\/config/);
assert.match(split, /readinessItems/);
assert.match(split, /nextReady/);
assert.match(split, /previewDistributions/);
assert.match(split, /Ready\. One action will validate, persist, create evidence, update MDD, and continue/);
assert.match(split, /title="Training and Validation Design"/);
assert.match(split, /data-testid="advanced-balancing-settings"/);
assert.match(split, /data-testid="advanced-external-validation"/);
assert.match(split, /data-testid="compact-final-predictor-review"/);
assert.doesNotMatch(split, />Holdout size</);
assert.match(split, /Training population only/);
assert.match(split, /Holdout remains untouched/);
assert.doesNotMatch(split, /Planned future validation designs/);
assert.doesNotMatch(split, /PlannedValidation/);
assert.match(split, /credentials: "include"/);

assert.match(metadataRouter, /Preserve the complete source frame/);
assert.doesNotMatch(metadataRouter, /df = df\.loc\[:, keep\]/);
assert.match(qualityService, /profileScope.*full_dataset/s);
assert.match(qualityService, /pd\.api\.types\.is_numeric_dtype/);
assert.match(featureService, /information_value/);
assert.match(featureService, /event_value/);

assert.match(training, /\/model\/train\/jobs/);
assert.match(training, /\/model\/train\/preflight/);
assert.match(training, /trainingActionLabel\(/);
assert.doesNotMatch(training, /disabled=\{jobActive \|\| !selectedModels\.length \|\| !readiness\}/);
assert.match(training, /\/model\/train\/jobs\/active/);
assert.match(training, /dataset_id: datasetIdentity\?\.dataset_id/);
assert.match(
  training,
  /dataset_version_id: datasetIdentity\?\.dataset_version_id/,
);
assert.doesNotMatch(training, /data_access\?\.(?:datasetId|version)/);
assert.match(training, /non_event_value: dataset\?\.non_event_value/);
assert.match(training, /user: requestUser/);
assert.match(training, /Kill unfinished/);
assert.match(training, /Queued|Training|Complete|Failed|Cancelled/);
assert.match(training, /model approval remains downstream/);
assert.match(training, /This is a selection lock, not model approval/);
assert.match(training, /function CandidateLeaderboard/);
assert.match(training, /Ranked candidate/);
assert.match(training, /Targetless diagnostic runs/);
assert.match(training, /Supplemental anomaly evidence is reported separately/);
assert.match(training, /Gaussian Naive Bayes/);
assert.match(training, /Local Outlier Factor/);
assert.match(training, /One-Class SVM/);
assert.match(training, /Robust Covariance/);
assert.match(training, /Unsupervised anomaly models fit without a target/);
assert.match(training, /never eligible for champion selection/);
assert.match(training, /model\/train\/jobs/);
assert.match(training, /credentials: "include"/);
assert.match(jobService, /ThreadPoolExecutor/);
assert.match(jobService, /max_parallel_honored/);
assert.match(jobService, /trained_feature_names/);
assert.match(jobService, /partial_ranked_results/);
assert.match(jobService, /"dataset_id": preflight\["dataset_id"\]/);
assert.match(jobService, /"non_event_value": preflight\["non_event_value"\]/);
assert.match(jobService, /creation_duration_ms/);
assert.match(jobService, /result_persistence_ms/);

assert.match(outliers, /Full-data flagged/);
assert.match(outliers, /scope="full_dataset"/);
assert.match(outliers, /scope="rendered_sample"/);
assert.match(outliers, /onNext=\{completeStep\}/);
assert.match(outliers, /createEvidence/);
assert.match(outliers, /safeArray/);
assert.match(outliers, /Go to Data Acquisition/);
assert.match(outliers, /Go to EDA/);
assert.doesNotMatch(outliers, /synthSeries|browser sample from Step 1/);
assert.match(outlierRouter, /DATASTORE\.get_raw_active_df/);
assert.match(outlierRouter, /scoped_store\.set_processed\(work\)/);
assert.match(outlierRouter, /with scoped_store\.state_lock/);
assert.match(outlierRouter, /outlier_application/);
assert.match(outlierRouter, /json_safe\(result\)/);

assert.match(missingValues, /Full-data missingness/);
assert.match(missingValues, /Selected treatment only/);
assert.match(missingValues, /updateGlobalStrategy/);
assert.match(missingValues, /Changing the global strategy immediately updates compatible feature-level selections/);
assert.doesNotMatch(missingValues, /Set compatible defaults/);
assert.match(missingValues, /onNext=\{completeStep\}/);
assert.match(missingValues, /createEvidence/);
assert.doesNotMatch(missingValues, /localDataset\.rows|browser sample from Step 1/);
assert.match(missingRouter, /resolve_development_analysis_scope/);
assert.match(missingRouter, /\*\*scope\.metadata\(\)/);
assert.match(missingRouter, /development_rows/);
assert.doesNotMatch(missingRouter, /scope.*full_dataset/s);
assert.match(missingRouter, /source_stage/);
assert.match(missingRouter, /missing_application/);
assert.match(missingRouter, /informative/);
assert.match(missingRouter, /return json_safe\(/);

assert.match(modelingApp, /path="\/step01b"[\s\S]*LegacyPredictiveRouteRedirect targetPath="\/step01\?section=credit-bureau-review"/);
assert.match(modelingApp, /if \(workflowId\) \{[\s\S]*normalizeWorkflowOrder\(workflowId\)/);
assert.doesNotMatch(workflows, /label:\s*"Credit Bureau Data Review"/);
assert.match(workflowStore, /version:\s*8/);
assert.match(featureEngineering, /Partial<FeatureManifestRow>/);
assert.match(featureEngineering, /source_features:\s*Array\.isArray\(row\.source_features\)/);
assert.match(evaluation, /useNavigate/);
assert.match(evaluation, /Continue to Interpretation Review/);
assert.match(evaluation, /navigate\(projectWorkflowRoute\(projectId, `\/step09\?candidate_id=/);

assert.match(interpretation, /requireLocalDatasetCanonicalIdentity/);
assert.match(interpretation, /Promise\.allSettled/);
assert.match(interpretation, /AnalysisScopeBadge/);
assert.match(interpretation, /Computing partial dependence on the governed holdout/);
assert.match(interpretation, /interpretation\/importance\?\$\{interpretationContextQuery\}/s);
assert.match(interpretation, /interpretation\/pdp\?feature=.*interpretationContextQuery/s);
assert.match(interpretation, /interpretation\/rfe\?keep=.*interpretationContextQuery/s);
assert.match(interpretation, /train\/last\?\$\{trainingContext\.toString\(\)\}/);
assert.match(interpretation, /isArtifactContextError/);
assert.match(interpretation, /rfeCacheScope/);
assert.match(interpretation, /decision_boundary\?\$\{params\.toString\(\)\}/);
assert.match(interpretation, /restoreExactFinalModel/);
assert.match(interpretation, /Confirm Final Model and Continue to Scoring/);
assert.match(interpretation, /diagnostic analysis only; it cannot select, refit, or alter the candidate promoted as final/);
assert.doesNotMatch(interpretation, /refits the selected estimator family/);
assert.doesNotMatch(interpretation, /importance\.length >= 2/);
assert.doesNotMatch(interpretation, /Mark Complete & Next Step/);

assert.match(trainer, /"gnb"/);
assert.match(trainer, /"oneclass_svm"/);
assert.match(trainer, /"elliptic"/);
assert.match(trainer, /"champion_eligible": False/);
assert.match(evaluationService, /permutation_importance/);
assert.match(evaluationService, /def final_model_status/);
assert.match(evaluationService, /full_train_rows/);
assert.match(scoring, /model\/final\/status/);
assert.match(scoring, /data-testid="final-model-scoring-contract"/);
assert.match(scoring, /Verified artifact/);
assert.match(scoring, /Confirm Scoring and Continue to Documentation/);
// Stage B.6: context matching moved into the pure, unit-tested helper (symmetric skip
// semantics mirroring the backend's _artifact_context_mismatch), and the status effect
// must guard against out-of-order responses overwriting the current project's view.
assert.match(scoring, /resolveFinalModelReadiness/);
assert.match(scoring, /let stale = false/);
assert.match(scoring, /stale = true/);
const finalModelReadiness = await read("src/lib/finalModelReadiness.ts");
assert.match(finalModelReadiness, /durabilityComplete/);
assert.match(finalModelReadiness, /verified model version and complete candidate lineage/);
assert.match(scoring, /nextDisabled=\{!scoredOutputCount\}/);
assert.match(scoring, /import StepPythonPanel/);
assert.match(scoring, /<StepPythonPanel \/>/);
assert.doesNotMatch(scoring, /Mark Complete & Next Step/);

const trainerRouter = await read("server/training/trainer_router.py");
assert.match(trainerRouter, /def get_last_train\([\s\S]*project_id: str = Query\(\.\.\.\)/);
assert.match(trainerRouter, /authorize_modeling_scope\(user, project_id, "view"\)/);
assert.match(trainerRouter, /The last training run does not match the current/);

const edaRouter = await read("server/eda/eda_router.py");
assert.match(edaRouter, /@router\.post\("\/workspace\/\{section\}"\)/);
assert.match(edaRouter, /@router\.post\("\/profile"\)/);
assert.match(edaRouter, /@router\.post\("\/analyze"\)/);
assert.match(edaRouter, /@router\.post\("\/vif-simulation"\)/);
assert.match(edaRouter, /backend_dataset_missing/);
assert.match(edaRouter, /status_code=status/);
assert.match(edaRouter, /EDA request received/);

const edaWorkspaceService = await read("server/eda/workspace_service.py");
assert.match(edaWorkspaceService, /def _histogram_bins/);
assert.match(edaWorkspaceService, /"histogram": _histogram_bins/);
assert.match(edaWorkspaceService, /request\.histogram_bins/);
assert.match(edaWorkspaceService, /pairwise_event_rows/);
assert.match(edaWorkspaceService, /def _predictor_authorization/);
assert.match(edaWorkspaceService, /"distribution": self\._distribution/);
assert.match(edaWorkspaceService, /def vif_simulation/);
assert.match(edaWorkspaceService, /"non_mutating": True/);
assert.match(edaWorkspaceTypes, /histogram_bins/);
assert.match(edaWorkspaceTypes, /feature: Optional\[str\]/);
assert.match(edaWorkspaceTypes, /selection_min: Optional\[float\]/);
assert.match(edaWorkspaceTypes, /class EDAVifSimulationRequest/);

const splitRouter = await read("server/splitting/split_router.py");
assert.match(splitRouter, /"has_split": has_split/);
assert.match(splitRouter, /"readiness_reason": reason/);
assert.match(splitRouter, /"selected_feature_hash"/);
assert.match(splitRouter, /"split_config_hash"/);

console.log("Predictive Modeling repair contract tests passed.");
